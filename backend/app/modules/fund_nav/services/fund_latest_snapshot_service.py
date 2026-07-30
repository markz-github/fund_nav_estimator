from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.models.fund_latest_snapshot import FundLatestSnapshot


TARGET_ETF_SOURCES = ("fund_company", "local:fund_name_match", "manual:target_etf")


class FundLatestSnapshotService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def set_latest_nav(self, fund_code: str, nav_id: int) -> None:
        self._snapshot(fund_code).latest_nav_id = nav_id

    def set_latest_estimate(self, fund_code: str, estimate_id: int) -> None:
        self._snapshot(fund_code).latest_estimate_id = estimate_id

    def refresh_target_etf(self, fund_code: str) -> None:
        holding = self.db.scalar(
            select(FundHolding)
            .where(
                FundHolding.fund_code == fund_code,
                FundHolding.asset_type == "etf",
                FundHolding.source.in_(TARGET_ETF_SOURCES),
            )
            .order_by(
                FundHolding.report_period.desc(),
                FundHolding.holding_ratio.desc(),
                FundHolding.id.desc(),
            )
            .limit(1)
        )
        self._snapshot(fund_code).target_etf_holding_id = holding.id if holding else None

    def _snapshot(self, fund_code: str) -> FundLatestSnapshot:
        snapshot = self.db.get(FundLatestSnapshot, fund_code)
        if snapshot is None:
            snapshot = FundLatestSnapshot(fund_code=fund_code)
            self.db.add(snapshot)
        snapshot.is_deleted = 0
        return snapshot
