from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_nav import FundNav


DEFAULT_DRIFT_DAYS = 60


class EstimateDriftService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_fund_drift_summaries(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        threshold: Decimal | None = None,
    ) -> list[dict]:
        start_date, end_date = self._date_range(start_date, end_date)
        points_by_fund: dict[str, list[dict]] = {}
        for point in self._comparison_points(start_date=start_date, end_date=end_date):
            points_by_fund.setdefault(point["fund_code"], []).append(point)

        funds = self.db.scalars(
            select(Fund).where(Fund.enabled == 1).order_by(Fund.fund_code.asc())
        ).all()
        summaries: list[dict] = []
        for fund in funds:
            points = points_by_fund.get(fund.fund_code, [])
            comparable_count = len(points)
            difference_rates = [point["difference_rate"] for point in points]
            recent_7_difference_rates = difference_rates[-7:]
            exceeded_count = (
                sum(1 for value in difference_rates if threshold is not None and value >= threshold)
                if threshold is not None
                else 0
            )
            latest_point = points[-1] if points else None
            summaries.append(
                {
                    "fund_code": fund.fund_code,
                    "fund_name": fund.fund_name,
                    "comparable_count": comparable_count,
                    "max_difference_rate": max(difference_rates) if difference_rates else None,
                    "avg_difference_rate": (
                        sum(difference_rates, Decimal("0")) / Decimal(comparable_count)
                        if comparable_count
                        else None
                    ),
                    "recent_7_trading_day_difference_rate": (
                        sum(recent_7_difference_rates, Decimal("0")) / Decimal(len(recent_7_difference_rates))
                        if recent_7_difference_rates
                        else None
                    ),
                    "latest_date": latest_point["estimate_date"] if latest_point else None,
                    "latest_difference_rate": latest_point["difference_rate"] if latest_point else None,
                    "threshold_exceeded_count": exceeded_count,
                }
            )
        return summaries

    def get_fund_drift_points(
        self,
        fund_code: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        threshold: Decimal | None = None,
    ) -> dict:
        normalized_code = str(fund_code).strip().zfill(6)
        start_date, end_date = self._date_range(start_date, end_date)
        fund = self.db.scalar(select(Fund).where(Fund.fund_code == normalized_code))
        points = [
            self._with_threshold(point, threshold)
            for point in self._comparison_points(
                start_date=start_date,
                end_date=end_date,
                fund_code=normalized_code,
            )
        ]
        rates = [point["difference_rate"] for point in points]
        return {
            "fund_code": normalized_code,
            "fund_name": fund.fund_name if fund else None,
            "start_date": start_date,
            "end_date": end_date,
            "threshold": threshold,
            "comparable_count": len(points),
            "max_difference_rate": max(rates) if rates else None,
            "avg_difference_rate": (
                sum(rates, Decimal("0")) / Decimal(len(rates)) if rates else None
            ),
            "threshold_exceeded_count": sum(1 for point in points if point["threshold_exceeded"]),
            "points": points,
        }

    def _comparison_points(
        self,
        *,
        start_date: date,
        end_date: date,
        fund_code: str | None = None,
    ) -> list[dict]:
        latest_estimate_times = (
            select(
                FundEstimate.fund_code,
                FundEstimate.estimate_date,
                func.max(FundEstimate.estimate_time).label("latest_estimate_time"),
            )
            .where(
                FundEstimate.estimate_date >= start_date,
                FundEstimate.estimate_date <= end_date,
                FundEstimate.estimated_nav.is_not(None),
            )
            .group_by(FundEstimate.fund_code, FundEstimate.estimate_date)
            .subquery()
        )
        statement = (
            select(FundEstimate, FundNav)
            .join(
                latest_estimate_times,
                (FundEstimate.fund_code == latest_estimate_times.c.fund_code)
                & (FundEstimate.estimate_date == latest_estimate_times.c.estimate_date)
                & (FundEstimate.estimate_time == latest_estimate_times.c.latest_estimate_time),
            )
            .join(
                FundNav,
                (FundNav.fund_code == FundEstimate.fund_code)
                & (FundNav.nav_date == FundEstimate.estimate_date),
            )
            .join(Fund, Fund.fund_code == FundEstimate.fund_code)
            .where(
                Fund.enabled == 1,
                FundNav.unit_nav > 0,
            )
            .order_by(FundEstimate.fund_code.asc(), FundEstimate.estimate_date.asc())
        )
        if fund_code:
            statement = statement.where(FundEstimate.fund_code == fund_code)

        points = []
        for estimate, nav in self.db.execute(statement).all():
            estimated_nav = estimate.estimated_nav
            official_nav = nav.unit_nav
            absolute_difference = estimated_nav - official_nav
            difference_rate = abs(absolute_difference) / official_nav
            points.append(
                {
                    "fund_code": estimate.fund_code,
                    "estimate_date": estimate.estimate_date,
                    "estimate_time": estimate.estimate_time,
                    "estimated_nav": estimated_nav,
                    "official_nav": official_nav,
                    "absolute_difference": absolute_difference,
                    "difference_rate": difference_rate,
                    "coverage_ratio": estimate.coverage_ratio,
                    "base_nav_date": estimate.base_nav_date,
                    "threshold_exceeded": False,
                }
            )
        return points

    @staticmethod
    def _with_threshold(point: dict, threshold: Decimal | None) -> dict:
        next_point = dict(point)
        next_point["threshold_exceeded"] = (
            threshold is not None and next_point["difference_rate"] >= threshold
        )
        return next_point

    @staticmethod
    def _date_range(start_date: date | None, end_date: date | None) -> tuple[date, date]:
        resolved_end = end_date or date.today()
        resolved_start = start_date or (resolved_end - timedelta(days=DEFAULT_DRIFT_DAYS - 1))
        if resolved_start > resolved_end:
            return resolved_end, resolved_start
        return resolved_start, resolved_end
