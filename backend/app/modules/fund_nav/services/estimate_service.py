from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare_source import AkshareSource
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.models.market_quote import MarketQuote
from app.modules.fund_nav.services.asset_valuation_config_service import (
    AssetValuationConfigMap,
    load_asset_valuation_config_map,
)
from app.utils.performance import timed


class EstimateStrategy:
    def estimate(self, fund: Fund, estimate_time: datetime) -> FundEstimate | str:
        raise NotImplementedError


class HoldingWeightedEstimateStrategy(EstimateStrategy):
    def __init__(self, service: "EstimateService") -> None:
        self.service = service

    def estimate(self, fund: Fund, estimate_time: datetime) -> FundEstimate | str:
        fund_code = fund.fund_code
        latest_nav = self.service._latest_nav(fund_code)
        if latest_nav is None:
            return "missing_nav"

        holdings = self.service._latest_holdings(fund_code)
        if not holdings:
            return "missing_holdings"

        valuation_configs = self.service._asset_valuation_configs()
        valuable_holdings = [
            holding
            for holding in holdings
            if valuation_configs.resolve(holding.asset_type, holding.market).realtime_valuable
        ]
        latest_quotes = self.service._latest_quotes([holding.asset_code for holding in valuable_holdings])
        weighted_growth = Decimal("0")
        covered_ratio = Decimal("0")
        total_ratio = Decimal("0")

        for holding in holdings:
            total_ratio += holding.holding_ratio
            if not valuation_configs.resolve(holding.asset_type, holding.market).realtime_valuable:
                continue
            quote = latest_quotes.get(holding.asset_code)
            if quote is None or quote.change_rate is None:
                continue
            weighted_growth += holding.holding_ratio * quote.change_rate
            covered_ratio += holding.holding_ratio

        if total_ratio == 0:
            return "zero_holding_ratio"
        if covered_ratio == 0:
            return "missing_quotes"

        coverage_ratio = covered_ratio / total_ratio
        estimated_nav = self.service.calculate_estimated_nav(latest_nav.unit_nav, weighted_growth)
        return FundEstimate(
            fund_code=fund_code,
            estimate_date=estimate_time.date(),
            estimate_time=estimate_time,
            base_nav_date=latest_nav.nav_date,
            base_unit_nav=latest_nav.unit_nav,
            estimated_growth_rate=weighted_growth,
            estimated_nav=estimated_nav,
            coverage_ratio=coverage_ratio,
            source_snapshot=f"strategy=holding_weighted;holdings={holdings[0].report_period};quotes={estimate_time.isoformat()}",
        )


class EtfIopvEstimateStrategy(EstimateStrategy):
    def __init__(self, service: "EstimateService") -> None:
        self.service = service

    def estimate(self, fund: Fund, estimate_time: datetime) -> FundEstimate | str:
        latest_nav = self.service._latest_nav(fund.fund_code)
        quote = self.service._latest_quotes([fund.fund_code]).get(fund.fund_code)
        if quote is not None and quote.latest_price is not None:
            base_nav_date = latest_nav.nav_date if latest_nav is not None else quote.trade_date
            base_unit_nav = latest_nav.unit_nav if latest_nav is not None else quote.latest_price
            return FundEstimate(
                fund_code=fund.fund_code,
                estimate_date=estimate_time.date(),
                estimate_time=estimate_time,
                base_nav_date=base_nav_date,
                base_unit_nav=base_unit_nav,
                estimated_growth_rate=quote.change_rate,
                estimated_nav=quote.latest_price,
                coverage_ratio=Decimal("1"),
                source_snapshot=f"strategy=etf_quote;quote={quote.quote_time.isoformat()}",
            )

        snapshot = self.service.source.get_etf_iopv_snapshot(fund.fund_code)
        if snapshot is None:
            return "missing_etf_quote"

        base_nav_date = latest_nav.nav_date if latest_nav is not None else estimate_time.date()
        base_unit_nav = latest_nav.unit_nav if latest_nav is not None else snapshot.estimated_nav
        growth_rate = snapshot.change_rate
        if latest_nav is not None and base_unit_nav != 0:
            growth_rate = (snapshot.estimated_nav - base_unit_nav) / base_unit_nav

        return FundEstimate(
            fund_code=fund.fund_code,
            estimate_date=estimate_time.date(),
            estimate_time=estimate_time,
            base_nav_date=base_nav_date,
            base_unit_nav=base_unit_nav,
            estimated_growth_rate=growth_rate,
            estimated_nav=snapshot.estimated_nav,
            coverage_ratio=Decimal("1"),
            source_snapshot=f"strategy=etf_iopv;source={snapshot.source};quotes={snapshot.estimate_time.isoformat()}",
        )


class EstimateService:
    def __init__(self, db: Session, source: AkshareSource | None = None) -> None:
        self.db = db
        self.source = source or AkshareSource()
        self._valuation_configs: AssetValuationConfigMap | None = None

    @timed()
    def latest_all(self) -> list[FundEstimate]:
        subquery = (
            select(
                FundEstimate.fund_code,
                func.max(FundEstimate.estimate_time).label("latest_time"),
            )
            .group_by(FundEstimate.fund_code)
            .subquery()
        )
        return self.db.scalars(
            select(FundEstimate).join(
                subquery,
                (FundEstimate.fund_code == subquery.c.fund_code)
                & (FundEstimate.estimate_time == subquery.c.latest_time),
            )
        ).all()

    @timed()
    def history(self, fund_code: str, limit: int = 100) -> list[FundEstimate]:
        return self.db.scalars(
            select(FundEstimate)
            .where(FundEstimate.fund_code == fund_code)
            .order_by(FundEstimate.estimate_time.desc())
            .limit(limit)
        ).all()

    @timed()
    def run_estimates(self, fund_codes: list[str] | None = None) -> dict:
        started = perf_counter()
        statement = select(Fund).where(Fund.enabled == 1)
        if fund_codes:
            statement = statement.where(Fund.fund_code.in_(fund_codes))
        funds = self.db.scalars(statement).all()
        estimates: list[FundEstimate] = []
        skipped: list[dict] = []
        estimate_time = datetime.now().replace(microsecond=0)

        for fund in funds:
            result = self._estimate_one(fund, estimate_time)
            if isinstance(result, FundEstimate):
                estimates.append(result)
            else:
                skipped.append({"fund_code": fund.fund_code, "reason": result})

        commit_started = perf_counter()
        self.db.commit()
        for estimate in estimates:
            self.db.refresh(estimate)

        result = {
            "estimated_count": len(estimates),
            "skipped_count": len(skipped),
            "skipped": skipped,
        }
        logging.getLogger("app.performance").info(
            "estimate target=%s success=%s skipped=%s commit_ms=%.2f total_ms=%.2f",
            len(funds),
            len(estimates),
            len(skipped),
            (perf_counter() - commit_started) * 1000,
            (perf_counter() - started) * 1000,
        )
        return result

    @staticmethod
    def calculate_estimated_nav(base_nav: Decimal, weighted_growth: Decimal) -> Decimal:
        return base_nav * (Decimal("1") + weighted_growth)

    def _estimate_one(self, fund: Fund, estimate_time: datetime) -> FundEstimate | str:
        result = self._strategy_for_fund(fund).estimate(fund, estimate_time)
        if isinstance(result, FundEstimate):
            self.db.add(result)
        return result

    def _strategy_for_fund(self, fund: Fund) -> EstimateStrategy:
        if self.is_exchange_traded_fund(fund):
            return EtfIopvEstimateStrategy(self)
        return HoldingWeightedEstimateStrategy(self)

    def _asset_valuation_configs(self) -> AssetValuationConfigMap:
        if self._valuation_configs is None:
            self._valuation_configs = load_asset_valuation_config_map(self.db)
        return self._valuation_configs

    @staticmethod
    def is_exchange_traded_fund(fund: Fund) -> bool:
        fund_code = str(fund.fund_code or "").strip()
        fund_name = fund.fund_name or ""
        fund_type = fund.fund_type or ""
        return fund_code.startswith(("5", "1")) and ("ETF" in fund_name.upper() or "ETF" in fund_type.upper())

    def _latest_nav(self, fund_code: str) -> FundNav | None:
        return self.db.scalar(
            select(FundNav)
            .where(FundNav.fund_code == fund_code)
            .order_by(FundNav.nav_date.desc())
            .limit(1)
        )

    def _latest_holdings(self, fund_code: str) -> list[FundHolding]:
        latest_period = self.db.scalar(
            select(func.max(FundHolding.report_period)).where(
                FundHolding.fund_code == fund_code,
                FundHolding.holding_ratio > 0,
            )
        )
        if latest_period is None:
            latest_period = self.db.scalar(
                select(func.max(FundHolding.report_period)).where(FundHolding.fund_code == fund_code)
            )
            if latest_period is None:
                return []
        return self.db.scalars(
            select(FundHolding)
            .where(
                FundHolding.fund_code == fund_code,
                FundHolding.report_period == latest_period,
            )
            .order_by(FundHolding.holding_ratio.desc())
        ).all()

    def _latest_quotes(self, asset_codes: list[str]) -> dict[str, MarketQuote]:
        if not asset_codes:
            return {}
        subquery = (
            select(MarketQuote.asset_code, func.max(MarketQuote.quote_time).label("latest_time"))
            .where(MarketQuote.asset_code.in_(asset_codes))
            .group_by(MarketQuote.asset_code)
            .subquery()
        )
        quotes = self.db.scalars(
            select(MarketQuote).join(
                subquery,
                (MarketQuote.asset_code == subquery.c.asset_code)
                & (MarketQuote.quote_time == subquery.c.latest_time),
            )
        ).all()
        return {quote.asset_code: quote for quote in quotes}
