from __future__ import annotations

from datetime import date, timedelta
import logging

from sqlalchemy import Select, asc, desc, func, select
from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare_source import AkshareSource
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_index_mapping import FundIndexMapping
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.schemas.fund import FundCreate
from app.modules.fund_nav.services.fund_profile_service import FundProfileService
from app.utils.performance import timed


logger = logging.getLogger("app.fund_nav")


class FundService:
    def __init__(self, db: Session, source: AkshareSource | None = None) -> None:
        self.db = db
        self.source = source or AkshareSource()

    @timed()
    def list_funds(self, sort_by: str | None = None, sort_order: str = "desc") -> list[dict]:
        query = select(Fund)
        if sort_by == "latest_estimated_growth_rate":
            latest_estimate_times = (
                select(
                    FundEstimate.fund_code,
                    func.max(FundEstimate.estimate_time).label("latest_estimate_time"),
                )
                .group_by(FundEstimate.fund_code)
                .subquery()
            )
            latest_estimates = (
                select(
                    FundEstimate.fund_code,
                    FundEstimate.estimated_growth_rate,
                )
                .join(
                    latest_estimate_times,
                    (FundEstimate.fund_code == latest_estimate_times.c.fund_code)
                    & (FundEstimate.estimate_time == latest_estimate_times.c.latest_estimate_time),
                )
                .subquery()
            )
            direction = asc if sort_order == "asc" else desc
            query = (
                query.outerjoin(latest_estimates, Fund.fund_code == latest_estimates.c.fund_code)
                .order_by(
                    latest_estimates.c.estimated_growth_rate.is_(None),
                    direction(latest_estimates.c.estimated_growth_rate),
                    Fund.created_at.desc(),
                )
            )
        else:
            query = query.order_by(Fund.created_at.desc())

        funds = self.db.scalars(query).all()
        return [self._fund_with_latest_data(fund) for fund in funds]

    @timed()
    def get_fund_detail(self, fund_code: str) -> dict | None:
        normalized_code = self.source._normalize_fund_code(fund_code)
        fund = self.db.scalar(select(Fund).where(Fund.fund_code == normalized_code))
        if fund is None:
            return None
        return self._fund_with_latest_data(fund)

    @timed()
    def create_fund(self, payload: FundCreate) -> Fund:
        fund_code = self.source._normalize_fund_code(payload.fund_code)
        existing = self.db.scalar(
            select(Fund)
            .where(Fund.fund_code == fund_code)
            .execution_options(include_deleted=True)
        )
        if existing and existing.is_deleted == 0:
            raise ValueError("基金已在自选基金池中")
        profile = FundProfileService(self.db, self.source).get_profile(fund_code)
        if existing:
            fund = existing
            fund.is_deleted = 0
            fund.enabled = 1
            fund.fund_name = profile.fund_name if profile else fund_code
            fund.fund_type = profile.fund_type if profile else None
            fund.remark = payload.remark
        else:
            fund = Fund(
                fund_code=fund_code,
                fund_name=profile.fund_name if profile else fund_code,
                fund_type=profile.fund_type if profile else None,
                remark=payload.remark,
            )
            self.db.add(fund)
        self.db.commit()
        self.db.refresh(fund)
        return fund

    @timed()
    def refresh_profile(self, fund_code: str) -> Fund | None:
        normalized_code = self.source._normalize_fund_code(fund_code)
        fund = self.db.scalar(select(Fund).where(Fund.fund_code == normalized_code))
        if fund is None:
            return None

        profile = FundProfileService(self.db, self.source).get_or_sync_profile(normalized_code)
        if profile is None:
            return fund
        fund.fund_name = profile.fund_name
        fund.fund_type = profile.fund_type
        self.db.commit()
        self.db.refresh(fund)
        return fund

    def delete_fund(self, fund_code: str) -> bool:
        fund = self.db.scalar(select(Fund).where(Fund.fund_code == fund_code))
        if not fund:
            return False
        self.db.delete(fund)
        self.db.commit()
        return True

    @timed()
    def refresh_nav(self, fund_code: str) -> FundNav | None:
        normalized_code = self.source._normalize_fund_code(fund_code)
        latest_nav = self.db.scalar(self._latest_nav_query(normalized_code))
        if latest_nav is not None and self._is_fresh_local_nav(latest_nav):
            logger.info(
                "refresh_nav skipped_fresh fund_code=%s local_date=%s local_source=%s local_growth=%s",
                normalized_code,
                latest_nav.nav_date,
                latest_nav.source,
                latest_nav.daily_growth_rate,
            )
            return latest_nav

        snapshot = self.source.get_latest_fund_nav(normalized_code)
        if snapshot is None:
            logger.info(
                "refresh_nav source_empty fund_code=%s local_date=%s local_source=%s",
                normalized_code,
                latest_nav.nav_date if latest_nav else None,
                latest_nav.source if latest_nav else None,
            )
            return latest_nav
        logger.info(
            "refresh_nav source_snapshot fund_code=%s snapshot_date=%s snapshot_source=%s snapshot_growth=%s local_date=%s local_source=%s",
            normalized_code,
            snapshot.nav_date,
            snapshot.source,
            snapshot.daily_growth_rate,
            latest_nav.nav_date if latest_nav else None,
            latest_nav.source if latest_nav else None,
        )
        daily_growth_rate = snapshot.daily_growth_rate
        if daily_growth_rate is None:
            previous_nav = self.db.scalar(self._previous_nav_query(normalized_code, snapshot.nav_date))
            if previous_nav is not None and previous_nav.unit_nav:
                daily_growth_rate = (snapshot.unit_nav - previous_nav.unit_nav) / previous_nav.unit_nav
                logger.info(
                    "refresh_nav calculated_growth fund_code=%s snapshot_date=%s previous_date=%s growth=%s",
                    normalized_code,
                    snapshot.nav_date,
                    previous_nav.nav_date,
                    daily_growth_rate,
                )

        nav = self.db.scalar(
            select(FundNav)
            .where(
                FundNav.fund_code == normalized_code,
                FundNav.nav_date == snapshot.nav_date,
            )
            .execution_options(include_deleted=True)
        )
        if nav is None:
            if self._should_replace_legacy_etf_nav(latest_nav, snapshot.source):
                nav = latest_nav
                nav.nav_date = snapshot.nav_date
            else:
                nav = FundNav(
                    fund_code=normalized_code,
                    nav_date=snapshot.nav_date,
                    unit_nav=snapshot.unit_nav,
                    accumulated_nav=snapshot.accumulated_nav,
                    daily_growth_rate=snapshot.daily_growth_rate,
                    source=snapshot.source,
                )
                self.db.add(nav)
        else:
            if (
                self._should_replace_legacy_etf_nav(latest_nav, snapshot.source)
                and latest_nav is not None
                and latest_nav.id != nav.id
            ):
                self.db.delete(latest_nav)

        nav.is_deleted = 0
        nav.unit_nav = snapshot.unit_nav
        nav.accumulated_nav = snapshot.accumulated_nav
        nav.daily_growth_rate = daily_growth_rate
        nav.source = snapshot.source

        self.db.commit()
        self.db.refresh(nav)
        logger.info(
            "refresh_nav saved fund_code=%s nav_date=%s source=%s growth=%s",
            normalized_code,
            nav.nav_date,
            nav.source,
            nav.daily_growth_rate,
        )
        return nav

    def _fund_with_latest_data(self, fund: Fund) -> dict:
        latest_nav = self.db.scalar(self._latest_nav_query(fund.fund_code))
        latest_estimate = self.db.scalar(self._latest_estimate_query(fund.fund_code))
        index_mapping = self.db.scalar(self._index_mapping_query(fund.fund_code))
        return {
            "id": fund.id,
            "fund_code": fund.fund_code,
            "fund_name": fund.fund_name,
            "fund_type": fund.fund_type,
            "enabled": fund.enabled,
            "remark": fund.remark,
            "tracked_index_code": index_mapping.index_code if index_mapping else None,
            "tracked_index_name": index_mapping.index_name if index_mapping else None,
            "tracked_index_source": index_mapping.source if index_mapping else None,
            "tracked_index_confidence": index_mapping.confidence if index_mapping else None,
            "latest_unit_nav": latest_nav.unit_nav if latest_nav else None,
            "latest_nav_date": latest_nav.nav_date if latest_nav else None,
            "latest_daily_growth_rate": latest_nav.daily_growth_rate if latest_nav else None,
            "latest_estimated_nav": latest_estimate.estimated_nav if latest_estimate else None,
            "latest_estimated_growth_rate": (
                latest_estimate.estimated_growth_rate if latest_estimate else None
            ),
            "latest_estimate_time": latest_estimate.estimate_time if latest_estimate else None,
            "latest_coverage_ratio": latest_estimate.coverage_ratio if latest_estimate else None,
        }

    @staticmethod
    def _latest_nav_query(fund_code: str) -> Select[tuple[FundNav]]:
        return (
            select(FundNav)
            .where(FundNav.fund_code == fund_code)
            .order_by(FundNav.nav_date.desc())
            .limit(1)
        )

    @staticmethod
    def _previous_nav_query(fund_code: str, nav_date: date) -> Select[tuple[FundNav]]:
        return (
            select(FundNav)
            .where(FundNav.fund_code == fund_code, FundNav.nav_date < nav_date)
            .order_by(FundNav.nav_date.desc())
            .limit(1)
        )

    @staticmethod
    def _latest_estimate_query(fund_code: str) -> Select[tuple[FundEstimate]]:
        return (
            select(FundEstimate)
            .where(FundEstimate.fund_code == fund_code)
            .order_by(FundEstimate.estimate_time.desc())
            .limit(1)
        )

    @staticmethod
    def _index_mapping_query(fund_code: str) -> Select[tuple[FundIndexMapping]]:
        return (
            select(FundIndexMapping)
            .where(FundIndexMapping.fund_code == fund_code)
            .limit(1)
        )

    @staticmethod
    def _is_fresh_local_nav(nav: FundNav) -> bool:
        if nav.daily_growth_rate is None:
            return False
        today = date.today()
        if nav.source == "akshare:etf_spot_prev_close":
            return False
        if nav.source == "akshare:etf_spot":
            return False
        return nav.nav_date >= today

    @staticmethod
    def _previous_business_day(value: date) -> date:
        previous = value - timedelta(days=1)
        while previous.weekday() >= 5:
            previous -= timedelta(days=1)
        return previous

    @staticmethod
    def _should_replace_legacy_etf_nav(nav: FundNav | None, next_source: str) -> bool:
        if nav is None:
            return False
        if next_source == "akshare:eastmoney_fund_page":
            return nav.source in {"akshare:etf_spot", "akshare:etf_spot_prev_close"}
        return nav.source == "akshare:etf_spot" and next_source == "akshare:etf_spot_prev_close"
