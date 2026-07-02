from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
import re
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare.akshare_source import AkshareSource
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.models.fund_index_mapping import FundIndexMapping
from app.modules.fund_nav.models.fund_task_detail_log import FundTaskDetailLog
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.models.market_quote import MarketQuote
from app.modules.fund_nav.services.asset_valuation_config_service import (
    AssetValuationConfigMap,
    load_asset_valuation_config_map,
)
from app.modules.fund_nav.services.fund_classifier import FundClassifier
from app.modules.fund_nav.services.nav_quality_service import FundNavQualityService
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
        if self.service._is_stale_official_nav(fund, latest_nav, estimate_time):
            return "stale_nav"

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
            if self.service._is_stale_realtime_quote(holding, quote, estimate_time):
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


class IndexTrackingEstimateStrategy(EstimateStrategy):
    def __init__(self, service: "EstimateService") -> None:
        self.service = service

    def estimate(self, fund: Fund, estimate_time: datetime) -> FundEstimate | str:
        latest_nav = self.service._latest_nav(fund.fund_code)
        if latest_nav is None:
            return "missing_nav"
        if self.service._is_stale_official_nav(fund, latest_nav, estimate_time):
            return "stale_nav"

        mapping = self.service._index_mapping(fund.fund_code)
        index_code = self.service._normalize_index_code(mapping.index_code if mapping else None)
        if not index_code:
            return "missing_index_mapping"

        quote = self.service._latest_quotes([index_code]).get(index_code)
        if quote is None or quote.change_rate is None:
            return "missing_index_quote"
        if self.service._is_stale_index_quote(quote, estimate_time):
            return "stale_index_quote"

        estimated_nav = self.service.calculate_estimated_nav(latest_nav.unit_nav, quote.change_rate)
        return FundEstimate(
            fund_code=fund.fund_code,
            estimate_date=estimate_time.date(),
            estimate_time=estimate_time,
            base_nav_date=latest_nav.nav_date,
            base_unit_nav=latest_nav.unit_nav,
            estimated_growth_rate=quote.change_rate,
            estimated_nav=estimated_nav,
            coverage_ratio=Decimal("1"),
            source_snapshot=f"strategy=index_tracking;index={index_code};quote={quote.quote_time.isoformat()}",
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
        self._last_attempts: list[dict[str, str]] = []

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
    def run_estimates(
        self,
        fund_codes: list[str] | None = None,
        *,
        task_log_id: int | None = None,
        task_type: str = "estimate_nav",
    ) -> dict:
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
            self._add_fund_task_detail_log(
                fund,
                result,
                task_log_id=task_log_id,
                task_type=task_type,
                estimate_time=estimate_time,
            )

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
        result = self._estimate_with_preferred_strategy(fund, estimate_time)
        if isinstance(result, FundEstimate):
            self.db.add(result)
        return result

    def _estimate_with_preferred_strategy(self, fund: Fund, estimate_time: datetime) -> FundEstimate | str:
        attempts: list[dict[str, str]] = []
        self._last_attempts = attempts
        if self.is_exchange_traded_fund(fund) or self._has_etf_nav_source(fund.fund_code):
            result = EtfIopvEstimateStrategy(self).estimate(fund, estimate_time)
            attempts.append({"strategy": "etf_iopv", "result": "success" if isinstance(result, FundEstimate) else result})
            return result

        if self.is_index_tracking_fund(fund):
            result = IndexTrackingEstimateStrategy(self).estimate(fund, estimate_time)
            attempts.append({"strategy": "index_tracking", "result": "success" if isinstance(result, FundEstimate) else result})
            if isinstance(result, FundEstimate) or result in {"missing_nav", "stale_nav"}:
                return result

        result = HoldingWeightedEstimateStrategy(self).estimate(fund, estimate_time)
        attempts.append({"strategy": "holding_weighted", "result": "success" if isinstance(result, FundEstimate) else result})
        return result

    def _add_fund_task_detail_log(
        self,
        fund: Fund,
        result: FundEstimate | str,
        *,
        task_log_id: int | None,
        task_type: str,
        estimate_time: datetime,
    ) -> None:
        attempts = list(self._last_attempts)
        message = ";".join(f"{item['strategy']}={item['result']}" for item in attempts) or None
        if isinstance(result, FundEstimate):
            strategy = self._strategy_from_snapshot(result.source_snapshot)
            self._upsert_fund_task_detail_log(
                fund_code=fund.fund_code,
                task_type=task_type,
                estimate_date=result.estimate_date,
                values={
                    "task_log_id": task_log_id,
                    "fund_name": fund.fund_name,
                    "status": "success",
                    "strategy": strategy,
                    "reason": None,
                    "estimate_time": result.estimate_time,
                    "estimated_nav": result.estimated_nav,
                    "estimated_growth_rate": result.estimated_growth_rate,
                    "coverage_ratio": result.coverage_ratio,
                    "source_snapshot": result.source_snapshot,
                    "message": message,
                },
            )
            return

        self._upsert_fund_task_detail_log(
            fund_code=fund.fund_code,
            task_type=task_type,
            estimate_date=estimate_time.date(),
            values={
                "task_log_id": task_log_id,
                "fund_name": fund.fund_name,
                "status": "skipped",
                "strategy": attempts[-1]["strategy"] if attempts else None,
                "reason": result,
                "estimate_time": estimate_time,
                "estimated_nav": None,
                "estimated_growth_rate": None,
                "coverage_ratio": None,
                "source_snapshot": None,
                "message": message,
            },
        )

    def _upsert_fund_task_detail_log(
        self,
        *,
        fund_code: str,
        task_type: str,
        estimate_date,
        values: dict,
    ) -> None:
        detail_log = self.db.scalar(
            select(FundTaskDetailLog)
            .where(
                FundTaskDetailLog.fund_code == fund_code,
                FundTaskDetailLog.estimate_date == estimate_date,
            )
            .order_by(FundTaskDetailLog.estimate_time.desc(), FundTaskDetailLog.id.desc())
        )
        if detail_log is None:
            self.db.add(
                FundTaskDetailLog(
                    fund_code=fund_code,
                    task_type=task_type,
                    estimate_date=estimate_date,
                    **values,
                )
            )
            return

        detail_log.task_type = task_type
        for key, value in values.items():
            setattr(detail_log, key, value)
        detail_log.created_at = datetime.now().replace(microsecond=0)

    @staticmethod
    def _strategy_from_snapshot(source_snapshot: str | None) -> str | None:
        if not source_snapshot:
            return None
        match = re.search(r"(?:^|;)strategy=([^;]+)", source_snapshot)
        return match.group(1) if match else None

    def _strategy_for_fund(self, fund: Fund) -> EstimateStrategy:
        if self.is_exchange_traded_fund(fund) or self._has_etf_nav_source(fund.fund_code):
            return EtfIopvEstimateStrategy(self)
        if self.is_index_tracking_fund(fund):
            return IndexTrackingEstimateStrategy(self)
        return HoldingWeightedEstimateStrategy(self)

    def _asset_valuation_configs(self) -> AssetValuationConfigMap:
        if self._valuation_configs is None:
            self._valuation_configs = load_asset_valuation_config_map(self.db)
        return self._valuation_configs

    @staticmethod
    def is_exchange_traded_fund(fund: Fund) -> bool:
        return FundClassifier.is_exchange_traded_fund(fund)

    @staticmethod
    def is_index_tracking_fund(fund: Fund) -> bool:
        return FundClassifier.is_index_tracking_fund(fund)

    def _has_etf_nav_source(self, fund_code: str) -> bool:
        fund_code = str(fund_code or "").strip()
        if not fund_code.startswith(("5", "1")):
            return False
        latest_nav = self._latest_nav(fund_code)
        return latest_nav is not None and latest_nav.source in {"akshare:etf_spot", "akshare:etf_spot_prev_close"}

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

    def _index_mapping(self, fund_code: str) -> FundIndexMapping | None:
        normalized_code = str(fund_code or "").strip().zfill(6)
        return self.db.scalar(
            select(FundIndexMapping).where(
                FundIndexMapping.fund_code == normalized_code,
                FundIndexMapping.index_code.is_not(None),
            )
        )

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

    @staticmethod
    def _is_stale_realtime_quote(
        holding: FundHolding,
        quote: MarketQuote,
        estimate_time: datetime,
    ) -> bool:
        realtime_markets = {"SH", "SZ", "BJ", "HK", "CN"}
        return (
            holding.market in realtime_markets
            and quote.trade_date < estimate_time.date()
        )

    @staticmethod
    def _is_stale_index_quote(quote: MarketQuote, estimate_time: datetime) -> bool:
        return quote.trade_date < estimate_time.date()

    @staticmethod
    def _normalize_index_code(index_code: str | None) -> str | None:
        code = str(index_code or "").strip().upper()
        if not code:
            return None
        for suffix in (".CSI", ".CSINDEX", ".CNI", ".SH", ".SZ"):
            if code.endswith(suffix):
                return code[: -len(suffix)]
        return code

    @staticmethod
    def _is_stale_official_nav(fund: Fund, nav: FundNav, estimate_time: datetime) -> bool:
        return nav.nav_date < FundNavQualityService.expected_nav_date_for_fund(fund, estimate_time)
