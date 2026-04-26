from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data_sources.akshare_source import AkshareSource
from app.models.fund_holding import FundHolding


class HoldingService:
    def __init__(self, db: Session, source: AkshareSource | None = None) -> None:
        self.db = db
        self.source = source or AkshareSource()

    def list_holdings(self, fund_code: str) -> list[FundHolding]:
        normalized_code = self.source._normalize_fund_code(fund_code)
        return self.db.scalars(
            select(FundHolding)
            .where(FundHolding.fund_code == normalized_code)
            .order_by(FundHolding.report_period.desc(), FundHolding.holding_ratio.desc())
        ).all()

    def refresh_holdings(self, fund_code: str) -> list[FundHolding]:
        normalized_code = self.source._normalize_fund_code(fund_code)
        snapshots = self.source.get_fund_holdings(normalized_code)
        refreshed: list[FundHolding] = []

        for snapshot in snapshots:
            holding = self.db.scalar(
                select(FundHolding).where(
                    FundHolding.fund_code == snapshot["fund_code"],
                    FundHolding.report_period == snapshot["report_period"],
                    FundHolding.asset_code == snapshot["asset_code"],
                )
            )
            if holding is None:
                holding = FundHolding(**snapshot)
                self.db.add(holding)
            else:
                holding.asset_name = snapshot["asset_name"]
                holding.asset_type = snapshot["asset_type"]
                holding.market = snapshot["market"]
                holding.holding_ratio = snapshot["holding_ratio"]
                holding.holding_value = snapshot["holding_value"]
                holding.source = snapshot["source"]
            refreshed.append(holding)

        self.db.commit()
        for holding in refreshed:
            self.db.refresh(holding)
        return refreshed
