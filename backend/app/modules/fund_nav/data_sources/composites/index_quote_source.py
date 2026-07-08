from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare.akshare_source import MarketQuoteSnapshot
from app.modules.fund_nav.data_sources.akshare.eastmoney_index_source import EastmoneyIndexSource
from app.modules.fund_nav.data_sources.akshare.sina_index_source import SinaIndexSource
from app.modules.fund_nav.data_sources.web.eastmoney_index_source import EastmoneyHttpIndexSource
from app.modules.fund_nav.data_sources.web.sina_index_source import SinaHttpIndexSource
from app.modules.fund_nav.data_sources.web.tencent_index_source import TencentIndexSource
from app.modules.fund_nav.data_sources.web.xueqiu_index_source import XueqiuIndexSource
from app.modules.fund_nav.services.index_quote_source_status_service import IndexQuoteSourceStatusService


class CompositeIndexQuoteSource:
    """Fetch index quotes from realtime sources only."""

    def __init__(self, helper, db: Session | None = None) -> None:
        self.helper = helper
        self.status_service = IndexQuoteSourceStatusService(db)
        self.eastmoney_http = EastmoneyHttpIndexSource(helper)
        self.eastmoney = EastmoneyIndexSource(helper)
        self.sina = SinaIndexSource(helper)
        self.sina_http = SinaHttpIndexSource(helper)
        self.tencent = TencentIndexSource(helper)
        self.xueqiu = XueqiuIndexSource(helper)

    def get_quotes(self, index_codes: list[str]) -> list[MarketQuoteSnapshot]:
        quote_time = datetime.now()
        target_codes = {
            self.helper._normalize_index_code(raw_code)
            for raw_code in index_codes
            if self.helper._normalize_index_code(raw_code)
        }
        snapshots: dict[str, MarketQuoteSnapshot] = {}

        realtime_sources = {
            "eastmoney_http_spot": self.eastmoney_http.get_spot_quotes,
            "eastmoney_spot": self.eastmoney.get_spot_quotes,
            "sina_spot": self.sina.get_spot_quotes,
            "sina_http_spot": self.sina_http.get_spot_quotes,
            "tencent_spot": self.tencent.get_spot_quotes,
            "xueqiu_spot": self.xueqiu.get_spot_quotes,
        }

        for source_status in self.status_service.ordered_sources("index"):
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

        return list(snapshots.values())
