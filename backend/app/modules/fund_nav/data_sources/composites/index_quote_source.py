from __future__ import annotations

from datetime import datetime

from app.modules.fund_nav.data_sources.akshare.akshare_source import MarketQuoteSnapshot
from app.modules.fund_nav.data_sources.akshare.csindex_index_source import CsindexIndexSource
from app.modules.fund_nav.data_sources.akshare.cni_index_source import CniIndexSource
from app.modules.fund_nav.data_sources.akshare.eastmoney_index_source import EastmoneyIndexSource
from app.modules.fund_nav.data_sources.akshare.sina_index_source import SinaIndexSource


class CompositeIndexQuoteSource:
    """Fetch index quotes from realtime sources first, then daily fallbacks."""

    def __init__(self, helper) -> None:
        self.helper = helper
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

        for realtime_source in (self.eastmoney.get_spot_quotes, self.sina.get_spot_quotes):
            missing_codes = target_codes - set(snapshots)
            if not missing_codes:
                return list(snapshots.values())
            snapshots.update(realtime_source(missing_codes, quote_time))

        for index_code in sorted(target_codes - set(snapshots)):
            snapshot = (
                self.eastmoney.get_daily_quote(index_code, quote_time)
                or self.sina.get_daily_quote(index_code, quote_time)
                or self.sina.get_tencent_daily_quote(index_code, quote_time)
                or self.csindex.get_daily_quote(index_code, quote_time)
                or self.cni.get_daily_quote(index_code, quote_time)
            )
            if snapshot is not None:
                snapshots[index_code] = snapshot

        return list(snapshots.values())
