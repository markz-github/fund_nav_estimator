from __future__ import annotations

from datetime import datetime
import re

from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare.akshare_source import MarketQuoteSnapshot
from app.modules.fund_nav.data_sources.akshare.eastmoney_index_source import EastmoneyIndexSource
from app.modules.fund_nav.data_sources.akshare.sina_index_source import SinaIndexSource
from app.modules.fund_nav.data_sources.web.eastmoney_index_source import EastmoneyHttpIndexSource
from app.modules.fund_nav.data_sources.web.sina_index_source import SinaHttpIndexSource
from app.modules.fund_nav.data_sources.web.tencent_index_source import TencentIndexSource
from app.modules.fund_nav.data_sources.web.xueqiu_index_source import XueqiuIndexSource
from app.modules.fund_nav.services.index_quote_source_status_service import IndexQuoteSourceStatusService
from app.modules.fund_nav.services.index_quote_symbol_service import IndexQuoteSymbolService


class CompositeIndexQuoteSource:
    """Fetch index quotes from realtime sources only."""

    def __init__(self, helper, db: Session | None = None) -> None:
        self.helper = helper
        self.status_service = IndexQuoteSourceStatusService(db)
        self.symbol_service = IndexQuoteSymbolService(db)
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
            request_codes = self._supported_codes(source_status, missing_codes)
            if not request_codes:
                continue
            realtime_source = realtime_sources.get(source_status.source_key)
            if realtime_source is None:
                continue
            request_symbols = self.symbol_service.request_symbols(source_status.source_key, request_codes)
            try:
                source_snapshots = realtime_source(request_codes, quote_time, request_symbols)
            except Exception as exc:
                self.status_service.record_failure(source_status.source_key, repr(exc))
                continue
            if source_snapshots:
                snapshots.update(source_snapshots)
                self.status_service.record_success(source_status.source_key)
            else:
                self.status_service.record_failure(
                    source_status.source_key,
                    self._no_quote_error(source_status.source_key, request_codes),
                )

        return list(snapshots.values())

    def _no_quote_error(self, source_key: str, missing_codes: set[str]) -> str:
        requested = self.symbol_service.request_symbols(source_key, missing_codes)
        supported = self.symbol_service.supported_codes(source_key, missing_codes)
        unsupported = sorted(code for code in missing_codes if code not in supported)
        parts = [
            "no quote matched",
            f"missing={self._join_codes(missing_codes)}",
        ]
        if requested:
            examples = [f"{code}->{symbol}" for code, symbol in sorted(requested.items())[:20]]
            parts.append(f"requested={','.join(examples)}")
        if unsupported:
            parts.append(f"unsupported={self._join_codes(unsupported)}")
        return ";".join(parts)

    def _supported_codes(self, source_status, missing_codes: set[str]) -> set[str]:
        symbol_supported_codes = self.symbol_service.supported_codes(source_status.source_key, missing_codes)
        rule_type = (source_status.exclude_rule_type or "none").strip().lower()
        rule_value = (source_status.exclude_rule_value or "").strip()
        if rule_type == "regex" and rule_value:
            try:
                pattern = re.compile(rule_value)
            except re.error:
                return set(symbol_supported_codes)
            return {code for code in symbol_supported_codes if pattern.search(str(code)) is None}
        if rule_type == "enum" and rule_value:
            excluded = {
                item.strip()
                for raw_part in rule_value.replace("\n", ",").split(",")
                for item in [raw_part.strip()]
                if item
            }
            return {code for code in symbol_supported_codes if str(code) not in excluded}
        return set(symbol_supported_codes)

    @staticmethod
    def _join_codes(codes) -> str:
        values = sorted(str(code) for code in codes)
        if len(values) <= 20:
            return ",".join(values)
        return ",".join(values[:20]) + f",...(+{len(values) - 20})"
