from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.models.market_quote import MarketQuote
from app.utils.performance import timed


class EstimateService:
    def __init__(self, db: Session) -> None:
        self.db = db

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
        statement = select(Fund).where(Fund.enabled == 1)
        if fund_codes:
            statement = statement.where(Fund.fund_code.in_(fund_codes))
        funds = self.db.scalars(statement).all()
        estimates: list[FundEstimate] = []
        skipped: list[dict] = []
        estimate_time = datetime.now().replace(microsecond=0)

        for fund in funds:
            result = self._estimate_one(fund.fund_code, estimate_time)
            if isinstance(result, FundEstimate):
                estimates.append(result)
            else:
                skipped.append({"fund_code": fund.fund_code, "reason": result})

        self.db.commit()
        for estimate in estimates:
            self.db.refresh(estimate)

        return {
            "estimated_count": len(estimates),
            "skipped_count": len(skipped),
            "skipped": skipped,
        }

    @staticmethod
    def calculate_estimated_nav(base_nav: Decimal, weighted_growth: Decimal) -> Decimal:
        return base_nav * (Decimal("1") + weighted_growth)

    def _estimate_one(self, fund_code: str, estimate_time: datetime) -> FundEstimate | str:
        latest_nav = self._latest_nav(fund_code)
        if latest_nav is None:
            return "missing_nav"

        holdings = self._latest_holdings(fund_code)
        if not holdings:
            return "missing_holdings"

        latest_quotes = self._latest_quotes([holding.asset_code for holding in holdings])
        weighted_growth = Decimal("0")
        covered_ratio = Decimal("0")
        total_ratio = Decimal("0")

        for holding in holdings:
            total_ratio += holding.holding_ratio
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
        estimated_nav = self.calculate_estimated_nav(latest_nav.unit_nav, weighted_growth)
        estimate = FundEstimate(
            fund_code=fund_code,
            estimate_date=estimate_time.date(),
            estimate_time=estimate_time,
            base_nav_date=latest_nav.nav_date,
            base_unit_nav=latest_nav.unit_nav,
            estimated_growth_rate=weighted_growth,
            estimated_nav=estimated_nav,
            coverage_ratio=coverage_ratio,
            source_snapshot=f"holdings={holdings[0].report_period};quotes={estimate_time.isoformat()}",
        )
        self.db.add(estimate)
        return estimate

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
