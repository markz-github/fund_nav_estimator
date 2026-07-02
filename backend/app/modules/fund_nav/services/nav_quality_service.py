from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.models.fund_index_mapping import FundIndexMapping
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.services.fund_classifier import FundClassifier
from app.modules.operations.models.data_fetch_error import DataFetchError
from app.modules.operations.services.operation_log_service import log_fetch_error


class FundNavQualityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def check_latest_nav_freshness(self, reference_time: datetime | None = None) -> dict:
        default_expected_nav_date = self.expected_nav_date(reference_time)
        rows = self._latest_nav_rows()
        stale: list[dict] = []
        mapping_issues = self.check_mapping_completeness()

        for fund, latest_nav in rows:
            expected_nav_date = self.expected_nav_date_for_fund(fund, reference_time)
            nav_rule = self.nav_freshness_rule(fund)
            if latest_nav is not None and latest_nav.nav_date >= expected_nav_date:
                continue
            item = {
                "fund_code": fund.fund_code,
                "fund_name": fund.fund_name,
                "latest_nav_date": latest_nav.nav_date.isoformat() if latest_nav else None,
                "expected_nav_date": expected_nav_date.isoformat(),
                "nav_rule": nav_rule,
                "reason": "missing_nav" if latest_nav is None else "stale_nav",
            }
            stale.append(item)
            self._log_stale_nav(item)

        return {
            "checked_count": len(rows),
            "stale_count": len(stale),
            "mapping_issue_count": len(mapping_issues),
            "expected_nav_date": default_expected_nav_date,
            "stale": stale,
            "mapping_issues": mapping_issues,
        }

    def check_mapping_completeness(self) -> list[dict]:
        issues: list[dict] = []
        funds = list(self.db.scalars(select(Fund).where(Fund.enabled == 1).order_by(Fund.fund_code.asc())).all())
        index_mapping_codes = set(
            self.db.scalars(
                select(FundIndexMapping.fund_code).where(FundIndexMapping.index_code.is_not(None))
            ).all()
        )
        target_etf_codes = set(
            self.db.scalars(
                select(FundHolding.fund_code).where(
                    FundHolding.asset_type == "etf",
                    FundHolding.source.in_(
                        (
                            "etf88",
                            "eastmoney",
                            "fund_company",
                            "sina",
                            "public_web",
                            "local:fund_name_match",
                            "manual:target_etf",
                        )
                    ),
                )
            ).all()
        )

        for fund in funds:
            if self.is_index_tracking_fund(fund) and fund.fund_code not in index_mapping_codes:
                item = {
                    "fund_code": fund.fund_code,
                    "fund_name": fund.fund_name,
                    "mapping_type": "index",
                    "reason": "missing_index_mapping",
                    "action": "manual_index_mapping_required",
                }
                issues.append(item)
                self._log_mapping_issue(item)

            if self.is_etf_feeder_fund(fund) and fund.fund_code not in target_etf_codes:
                item = {
                    "fund_code": fund.fund_code,
                    "fund_name": fund.fund_name,
                    "mapping_type": "target_etf",
                    "reason": "missing_target_etf_mapping",
                    "action": "manual_target_etf_mapping_required",
                }
                issues.append(item)
                self._log_mapping_issue(item)

        return issues

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
            f"nav_rule={item['nav_rule']};"
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

    def _log_mapping_issue(self, item: dict) -> None:
        message = (
            f"mapping_type={item['mapping_type']};"
            f"reason={item['reason']};"
            f"action={item['action']}"
        )
        exists = self.db.scalar(
            select(DataFetchError.id)
            .where(
                DataFetchError.source == "quality_check",
                DataFetchError.data_type == "fund_mapping",
                DataFetchError.target_code == item["fund_code"],
                DataFetchError.error_message == message,
                DataFetchError.resolved == 0,
            )
            .limit(1)
        )
        if exists is None:
            log_fetch_error(self.db, "quality_check", "fund_mapping", item["fund_code"], message)

    @classmethod
    def expected_nav_date(cls, reference_time: datetime | None = None) -> date:
        now = reference_time or datetime.now()
        today = now.date()
        if today.weekday() >= 5:
            return cls.previous_business_day(today)
        if now.hour < 20:
            return cls.previous_business_day(today)
        return today

    @classmethod
    def expected_nav_date_for_fund(cls, fund: Fund, reference_time: datetime | None = None) -> date:
        expected_date = cls.expected_nav_date(reference_time)
        if cls.nav_freshness_rule(fund) == "qdii_delayed":
            return cls.previous_business_day(expected_date)
        return expected_date

    @classmethod
    def nav_freshness_rule(cls, fund: Fund) -> str:
        return "qdii_delayed" if cls.is_delayed_nav_fund(fund) else "standard"

    @staticmethod
    def is_delayed_nav_fund(fund: Fund) -> bool:
        return FundClassifier.is_delayed_nav_fund(fund)

    @staticmethod
    def is_index_fund(fund: Fund) -> bool:
        return FundClassifier.is_index_tracking_fund(fund)

    @staticmethod
    def is_index_tracking_fund(fund: Fund) -> bool:
        return FundClassifier.is_index_tracking_fund(fund)

    @staticmethod
    def is_etf_feeder_fund(fund: Fund) -> bool:
        return FundClassifier.is_etf_feeder_fund(fund)

    @staticmethod
    def previous_business_day(value: date) -> date:
        previous = value - timedelta(days=1)
        while previous.weekday() >= 5:
            previous -= timedelta(days=1)
        return previous
