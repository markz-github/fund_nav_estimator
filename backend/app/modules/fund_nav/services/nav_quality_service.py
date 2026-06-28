from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.operations.models.data_fetch_error import DataFetchError
from app.modules.operations.services.operation_log_service import log_fetch_error


class FundNavQualityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def check_latest_nav_freshness(self, reference_time: datetime | None = None) -> dict:
        expected_nav_date = self.expected_nav_date(reference_time)
        rows = self._latest_nav_rows()
        stale: list[dict] = []

        for fund, latest_nav in rows:
            if latest_nav is not None and latest_nav.nav_date >= expected_nav_date:
                continue
            item = {
                "fund_code": fund.fund_code,
                "fund_name": fund.fund_name,
                "latest_nav_date": latest_nav.nav_date.isoformat() if latest_nav else None,
                "expected_nav_date": expected_nav_date.isoformat(),
                "reason": "missing_nav" if latest_nav is None else "stale_nav",
            }
            stale.append(item)
            self._log_stale_nav(item)

        return {
            "checked_count": len(rows),
            "stale_count": len(stale),
            "expected_nav_date": expected_nav_date,
            "stale": stale,
        }

    def _latest_nav_rows(self) -> list[tuple[Fund, FundNav | None]]:
        latest_nav_dates = (
            select(FundNav.fund_code, func.max(FundNav.nav_date).label("latest_nav_date"))
            .group_by(FundNav.fund_code)
            .subquery()
        )
        return list(
            self.db.execute(
                select(Fund, FundNav)
                .outerjoin(latest_nav_dates, Fund.fund_code == latest_nav_dates.c.fund_code)
                .outerjoin(
                    FundNav,
                    (FundNav.fund_code == Fund.fund_code)
                    & (FundNav.nav_date == latest_nav_dates.c.latest_nav_date),
                )
                .where(Fund.enabled == 1)
                .order_by(Fund.fund_code.asc())
            ).all()
        )

    def _log_stale_nav(self, item: dict) -> None:
        message = (
            f"latest_nav_date={item['latest_nav_date']};"
            f"expected_nav_date={item['expected_nav_date']};"
            f"reason={item['reason']}"
        )
        exists = self.db.scalar(
            select(DataFetchError.id)
            .where(
                DataFetchError.source == "quality_check",
                DataFetchError.data_type == "fund_nav",
                DataFetchError.target_code == item["fund_code"],
                DataFetchError.error_message == message,
                DataFetchError.resolved == 0,
            )
            .limit(1)
        )
        if exists is None:
            log_fetch_error(self.db, "quality_check", "fund_nav", item["fund_code"], message)

    @classmethod
    def expected_nav_date(cls, reference_time: datetime | None = None) -> date:
        now = reference_time or datetime.now()
        today = now.date()
        if today.weekday() >= 5:
            return cls.previous_business_day(today)
        if now.hour < 20:
            return cls.previous_business_day(today)
        return today

    @staticmethod
    def previous_business_day(value: date) -> date:
        previous = value - timedelta(days=1)
        while previous.weekday() >= 5:
            previous -= timedelta(days=1)
        return previous
