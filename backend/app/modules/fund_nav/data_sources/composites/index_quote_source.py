from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare.akshare_source import MarketQuoteSnapshot
from app.modules.fund_nav.data_sources.akshare.csindex_index_source import CsindexIndexSource
from app.modules.fund_nav.data_sources.akshare.cni_index_source import CniIndexSource
from app.modules.fund_nav.data_sources.akshare.eastmoney_index_source import EastmoneyIndexSource
from app.modules.fund_nav.data_sources.akshare.sina_index_source import SinaIndexSource
from app.modules.fund_nav.services.index_quote_source_status_service import IndexQuoteSourceStatusService


class CompositeIndexQuoteSource:
    """Fetch index quotes from realtime sources first, then daily fallbacks."""

    def __init__(self, helper, db: Session | None = None) -> None:
        self.helper = helper
        self.status_service = IndexQuoteSourceStatusService(db)
        self.eastmoney = EastmoneyIndexSource(helper)
        self.sina = SinaIndexSource(helper)
        self.csindex = CsindexIndexSource(helper)
        self.cni = CniIndexSource(helper)

    def get_quotes(self, index_codes: list[str]) -> list[MarketQuoteSnapshot]:
        quote_time = datetime.now()
        target_codes = {
            self.helper._normalize_index_code(raw_code)
            for raw_code in index_codes
            if self.helper._normalize_index_code(raw_code)
        }
        snapshots: dict[str, MarketQuoteSnapshot] = {}

        realtime_sources = {
            "eastmoney_spot": self.eastmoney.get_spot_quotes,
            "sina_spot": self.sina.get_spot_quotes,
        }
        daily_sources = {
            "eastmoney_daily": self.eastmoney.get_daily_quote,
            "sina_daily": self.sina.get_daily_quote,
            "tencent_daily": self.sina.get_tencent_daily_quote,
            "csindex_daily": self.csindex.get_daily_quote,
            "cni_daily": self.cni.get_daily_quote,
        }

        for source_status in self.status_service.ordered_sources("realtime"):
            missing_codes = target_codes - set(snapshots)
            if not missing_codes:
                return list(snapshots.values())
            realtime_source = realtime_sources.get(source_status.source_key)
            if realtime_source is None:
                continue
            try:
                source_snapshots = realtime_source(missing_codes, quote_time)
            except Exception as exc:
                self.status_service.record_failure(source_status.source_key, repr(exc))
                continue
            if source_snapshots:
                snapshots.update(source_snapshots)
                self.status_service.record_success(source_status.source_key)
            else:
                self.status_service.record_failure(source_status.source_key)

        for index_code in sorted(target_codes - set(snapshots)):
            for source_status in self.status_service.ordered_sources("daily"):
                daily_source = daily_sources.get(source_status.source_key)
                if daily_source is None:
                    continue
                try:
                    snapshot = daily_source(index_code, quote_time)
                except Exception as exc:
                    self.status_service.record_failure(source_status.source_key, repr(exc))
                    continue
                if snapshot is None:
                    self.status_service.record_failure(source_status.source_key)
                    continue
                snapshots[index_code] = snapshot
                self.status_service.record_success(source_status.source_key)
                break

        return list(snapshots.values())
