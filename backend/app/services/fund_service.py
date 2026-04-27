from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.data_sources.akshare_source import AkshareSource
from app.models.fund import Fund
from app.models.fund_estimate import FundEstimate
from app.models.fund_nav import FundNav
from app.schemas.fund import FundCreate


class FundService:
    def __init__(self, db: Session, source: AkshareSource | None = None) -> None:
        self.db = db
        self.source = source or AkshareSource()

    def list_funds(self) -> list[dict]:
        funds = self.db.scalars(select(Fund).order_by(Fund.created_at.desc())).all()
        return [self._fund_with_latest_data(fund) for fund in funds]

    def get_fund_detail(self, fund_code: str) -> dict | None:
        normalized_code = self.source._normalize_fund_code(fund_code)
        fund = self.db.scalar(select(Fund).where(Fund.fund_code == normalized_code))
        if fund is None:
            return None
        return self._fund_with_latest_data(fund)

    def create_fund(self, payload: FundCreate) -> Fund:
        fund_code = self.source._normalize_fund_code(payload.fund_code)
        existing = self.db.scalar(select(Fund).where(Fund.fund_code == fund_code))
        if existing:
            self.refresh_nav(existing.fund_code)
            return existing

        profile = self.source.get_fund_profile(fund_code)
        fund = Fund(
            fund_code=profile.fund_code,
            fund_name=profile.fund_name,
            fund_type=profile.fund_type,
            remark=payload.remark,
        )
        self.db.add(fund)
        self.db.commit()
        self.db.refresh(fund)
        self.refresh_nav(fund.fund_code)
        return fund

    def delete_fund(self, fund_code: str) -> bool:
        fund = self.db.scalar(select(Fund).where(Fund.fund_code == fund_code))
        if not fund:
            return False
        self.db.delete(fund)
        self.db.commit()
        return True

    def refresh_nav(self, fund_code: str) -> FundNav | None:
        normalized_code = self.source._normalize_fund_code(fund_code)
        snapshot = self.source.get_latest_fund_nav(normalized_code)
        if snapshot is None:
            return None

        nav = self.db.scalar(
            select(FundNav).where(
                FundNav.fund_code == normalized_code,
                FundNav.nav_date == snapshot.nav_date,
            )
        )
        if nav is None:
            nav = FundNav(
                fund_code=normalized_code,
                nav_date=snapshot.nav_date,
                unit_nav=snapshot.unit_nav,
                accumulated_nav=snapshot.accumulated_nav,
                daily_growth_rate=snapshot.daily_growth_rate,
                source=self.source.source_name,
            )
            self.db.add(nav)
        else:
            nav.unit_nav = snapshot.unit_nav
            nav.accumulated_nav = snapshot.accumulated_nav
            nav.daily_growth_rate = snapshot.daily_growth_rate
            nav.source = self.source.source_name

        fund = self.db.scalar(select(Fund).where(Fund.fund_code == normalized_code))
        if fund is not None:
            profile = self.source.get_fund_profile(normalized_code)
            fund.fund_name = profile.fund_name
            fund.fund_type = profile.fund_type

        self.db.commit()
        self.db.refresh(nav)
        return nav

    def _fund_with_latest_data(self, fund: Fund) -> dict:
        latest_nav = self.db.scalar(self._latest_nav_query(fund.fund_code))
        latest_estimate = self.db.scalar(self._latest_estimate_query(fund.fund_code))
        return {
            "id": fund.id,
            "fund_code": fund.fund_code,
            "fund_name": fund.fund_name,
            "fund_type": fund.fund_type,
            "enabled": fund.enabled,
            "remark": fund.remark,
            "latest_unit_nav": latest_nav.unit_nav if latest_nav else None,
            "latest_nav_date": latest_nav.nav_date if latest_nav else None,
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
    def _latest_estimate_query(fund_code: str) -> Select[tuple[FundEstimate]]:
        return (
            select(FundEstimate)
            .where(FundEstimate.fund_code == fund_code)
            .order_by(FundEstimate.estimate_time.desc())
            .limit(1)
        )
