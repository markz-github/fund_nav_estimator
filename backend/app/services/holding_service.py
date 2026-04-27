from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data_sources.akshare_source import AkshareSource
from app.data_sources.eastmoney_source import EastmoneySource
from app.data_sources.etf88_source import Etf88Source
from app.data_sources.fund_company_source import FundCompanySource
from app.data_sources.public_web_source import PublicWebFundSource
from app.data_sources.sina_source import SinaFundSource
from app.models.fund_holding import FundHolding


class HoldingService:
    def __init__(
        self,
        db: Session,
        source: AkshareSource | None = None,
        etf88_source: Etf88Source | None = None,
        holding_sources: list | None = None,
        target_fund_sources: list | None = None,
    ) -> None:
        self.db = db
        self.source = source or AkshareSource()
        self.holding_sources = holding_sources or [
            self.source,
            EastmoneySource(),
            SinaFundSource(),
        ]
        self.target_fund_sources = target_fund_sources or [
            etf88_source or Etf88Source(),
            EastmoneySource(),
            FundCompanySource(),
            SinaFundSource(),
            PublicWebFundSource(),
        ]

    def list_holdings(self, fund_code: str) -> list[FundHolding]:
        normalized_code = self.source._normalize_fund_code(fund_code)
        return self.db.scalars(
            select(FundHolding)
            .where(FundHolding.fund_code == normalized_code)
            .order_by(FundHolding.report_period.desc(), FundHolding.holding_ratio.desc())
        ).all()

    def refresh_holdings(self, fund_code: str) -> list[FundHolding]:
        normalized_code = self.source._normalize_fund_code(fund_code)
        snapshots = self._collect_holdings(normalized_code)
        if self._should_use_target_fund_holdings(normalized_code, snapshots):
            target_fund_snapshots = self._collect_target_fund_holdings(normalized_code)
            if target_fund_snapshots:
                snapshots = target_fund_snapshots
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

    def _collect_holdings(self, fund_code: str) -> list[dict]:
        for source in self.holding_sources:
            try:
                snapshots = source.get_fund_holdings(fund_code)
            except Exception:
                continue
            snapshots = self._valid_snapshots(snapshots)
            if snapshots:
                return snapshots
        return []

    def _collect_target_fund_holdings(self, fund_code: str) -> list[dict]:
        for source in self.target_fund_sources:
            try:
                snapshots = source.get_target_fund_holdings(fund_code)
            except Exception:
                continue
            snapshots = self._valid_snapshots(snapshots)
            if snapshots:
                return snapshots
        return []

    @staticmethod
    def _valid_snapshots(snapshots: list[dict]) -> list[dict]:
        required_keys = {
            "fund_code",
            "report_period",
            "asset_code",
            "asset_name",
            "asset_type",
            "holding_ratio",
            "source",
        }
        return [
            snapshot
            for snapshot in snapshots
            if required_keys.issubset(snapshot)
            and snapshot["asset_code"]
            and snapshot["asset_name"]
            and snapshot["holding_ratio"] is not None
        ]

    def _should_use_target_fund_holdings(
        self, fund_code: str, snapshots: list[dict]
    ) -> bool:
        if not snapshots:
            return True
        total_ratio = sum(snapshot["holding_ratio"] for snapshot in snapshots)
        if total_ratio == 0:
            return True

        try:
            profile = self.source.get_fund_profile(fund_code)
        except Exception:
            return False
        fund_name = profile.fund_name or ""
        fund_type = profile.fund_type or ""
        return "ETF联接" in fund_name or "联接" in fund_name or "QDII" in fund_type
