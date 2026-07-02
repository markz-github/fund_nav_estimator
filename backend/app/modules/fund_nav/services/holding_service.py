from __future__ import annotations

from decimal import Decimal
import re

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare.akshare_source import AkshareSource
from app.modules.fund_nav.data_sources.web.eastmoney_source import EastmoneySource
from app.modules.fund_nav.data_sources.web.etf88_source import Etf88Source
from app.modules.fund_nav.data_sources.web.fund_company_source import FundCompanySource
from app.modules.fund_nav.data_sources.web.public_fund_source import PublicWebFundSource
from app.modules.fund_nav.data_sources.web.sina_fund_source import SinaFundSource
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.report_period import latest_completed_quarter_period
from app.modules.fund_nav.services.fund_classifier import FundClassifier
from app.modules.fund_nav.services.fund_profile_service import FundProfileService
from app.modules.fund_nav.services.manual_index_mapping_service import ManualIndexMappingService
from app.utils.performance import timed


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

    @timed()
    def list_holdings(self, fund_code: str) -> list[FundHolding]:
        normalized_code = self.source._normalize_fund_code(fund_code)
        return self.db.scalars(
            select(FundHolding)
            .where(FundHolding.fund_code == normalized_code)
            .order_by(FundHolding.report_period.desc(), FundHolding.holding_ratio.desc())
        ).all()

    @timed()
    def refresh_holdings(self, fund_code: str) -> list[FundHolding]:
        normalized_code = self.source._normalize_fund_code(fund_code)
        snapshots = self._collect_holdings(normalized_code)
        replace_all_periods = False
        use_target_fund_holdings = self._should_use_target_fund_holdings(normalized_code, snapshots)
        if use_target_fund_holdings:
            target_fund_snapshots = self._collect_target_fund_holdings(normalized_code)
            if target_fund_snapshots:
                snapshots = target_fund_snapshots
                replace_all_periods = True
            else:
                inferred_target = ManualIndexMappingService(self.db).get_target_etf_holding(normalized_code)
                if inferred_target is None:
                    inferred_target = self._infer_target_fund_holding(normalized_code)
                if inferred_target is not None:
                    snapshots = [inferred_target]
                    replace_all_periods = True
        else:
            self._delete_target_hint_holdings(normalized_code)
        snapshots = self._deduplicate_snapshots(snapshots)
        refreshed: list[FundHolding] = []
        self._delete_stale_holdings(normalized_code, snapshots, replace_all_periods)

        for snapshot in snapshots:
            holding = self.db.scalar(
                select(FundHolding)
                .where(
                    FundHolding.fund_code == snapshot["fund_code"],
                    FundHolding.report_period == snapshot["report_period"],
                    FundHolding.asset_code == snapshot["asset_code"],
                )
                .execution_options(include_deleted=True)
            )
            if holding is None:
                holding = FundHolding(**snapshot)
                self.db.add(holding)
            else:
                holding.is_deleted = 0
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

    def _delete_stale_holdings(self, fund_code: str, snapshots: list[dict], replace_all_periods: bool = False) -> None:
        if replace_all_periods:
            snapshot_keys = {
                (snapshot["report_period"], snapshot["asset_code"])
                for snapshot in snapshots
            }
            stale_rows = self.db.scalars(
                select(FundHolding)
                .where(FundHolding.fund_code == fund_code)
                .execution_options(include_deleted=True)
            ).all()
            for holding in stale_rows:
                holding.is_deleted = 0 if (holding.report_period, holding.asset_code) in snapshot_keys else 1
            return

        by_period: dict[str, set[str]] = {}
        for snapshot in snapshots:
            by_period.setdefault(snapshot["report_period"], set()).add(snapshot["asset_code"])

        for report_period, asset_codes in by_period.items():
            if not asset_codes:
                continue
            self.db.execute(
                update(FundHolding)
                .where(
                    FundHolding.fund_code == fund_code,
                    FundHolding.report_period == report_period,
                    FundHolding.asset_code.not_in(asset_codes),
                )
                .values(is_deleted=1)
            )

    def _delete_target_hint_holdings(self, fund_code: str) -> None:
        self.db.execute(
            update(FundHolding)
            .where(
                FundHolding.fund_code == fund_code,
                FundHolding.source.like("%:target_hint"),
            )
            .values(is_deleted=1)
        )

    @timed()
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

    @timed()
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

    @staticmethod
    def _deduplicate_snapshots(snapshots: list[dict]) -> list[dict]:
        deduped: dict[tuple[str, str, str], dict] = {}
        for snapshot in snapshots:
            key = (snapshot["fund_code"], snapshot["report_period"], snapshot["asset_code"])
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = dict(snapshot)
                continue

            existing["holding_ratio"] += snapshot["holding_ratio"]
            existing_value = existing.get("holding_value")
            next_value = snapshot.get("holding_value")
            if existing_value is None:
                existing["holding_value"] = next_value
            elif next_value is not None:
                existing["holding_value"] = existing_value + next_value
            if not existing.get("asset_name"):
                existing["asset_name"] = snapshot["asset_name"]
            if not existing.get("market"):
                existing["market"] = snapshot.get("market")
        return list(deduped.values())

    def _should_use_target_fund_holdings(
        self, fund_code: str, snapshots: list[dict]
    ) -> bool:
        local_fund = self.db.scalar(select(Fund).where(Fund.fund_code == fund_code))
        fund_name = local_fund.fund_name if local_fund is not None else ""

        try:
            profile = FundProfileService(self.db, self.source).get_or_sync_profile(fund_code)
        except Exception:
            profile = None
        if not fund_name and profile is not None:
            fund_name = profile.fund_name or ""
        if local_fund is not None:
            return FundClassifier.is_etf_feeder_fund(local_fund)
        if profile is not None:
            return FundClassifier.is_etf_feeder_fund(profile)
        return "ETF联接" in fund_name or "联接" in fund_name

    def _infer_target_fund_holding(self, fund_code: str) -> dict | None:
        profile = self.db.scalar(select(Fund).where(Fund.fund_code == fund_code))
        if profile is None or not profile.fund_name:
            return None
        fund_name = profile.fund_name
        if not FundClassifier.is_etf_feeder_fund(profile):
            return None

        candidates = self.db.scalars(
            select(Fund)
            .where(
                Fund.enabled == 1,
                Fund.fund_code != fund_code,
                Fund.fund_code.regexp_match(r"^[15][0-9]{5}$"),
                Fund.fund_name.like("%ETF%"),
            )
            .order_by(Fund.fund_code.asc())
        ).all()
        for candidate in candidates:
            candidate_name = candidate.fund_name or ""
            if self._is_target_fund_name_match(fund_name, candidate_name):
                return {
                    "fund_code": fund_code,
                    "report_period": self._current_report_period(),
                    "asset_code": candidate.fund_code,
                    "asset_name": candidate_name,
                    "asset_type": "etf",
                    "market": "CN",
                    "holding_ratio": Decimal("1"),
                    "holding_value": None,
                    "source": "local:fund_name_match",
                }
        return None

    @staticmethod
    def _is_target_fund_name_match(fund_name: str, candidate_name: str) -> bool:
        chunks = [
            chunk
            for chunk in re.split(r"ETF|交易型开放式|指数|基金|联接|发起式|[（）()A-Za-z0-9\-]+", candidate_name)
            if len(chunk) >= 2
        ]
        if not chunks:
            return False
        return all(chunk in fund_name for chunk in chunks)

    @staticmethod
    def _current_report_period() -> str:
        return latest_completed_quarter_period()
