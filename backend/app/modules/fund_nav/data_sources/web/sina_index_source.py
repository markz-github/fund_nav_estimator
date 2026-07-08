from __future__ import annotations

from datetime import datetime

import requests

from app.modules.fund_nav.data_sources.akshare.akshare_source import MarketQuoteSnapshot


class SinaHttpIndexSource:
    source_name = "sina_http"
    quote_url = "https://hq.sinajs.cn/list={symbols}"

    def __init__(self, helper) -> None:
        self.helper = helper

    def get_spot_quotes(
        self,
        index_codes: set[str],
        quote_time: datetime,
    ) -> dict[str, MarketQuoteSnapshot]:
        symbols = {
            index_code: self._symbol(index_code)
            for index_code in index_codes
            if self._symbol(index_code) is not None
        }
        if not symbols:
            return {}

        try:
            response = requests.get(
                self.quote_url.format(symbols=",".join(symbols.values())),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://finance.sina.com.cn/",
                },
                timeout=10,
            )
            response.raise_for_status()
            text = response.content.decode("gbk", errors="ignore")
        except Exception as exc:
            self.helper._record_fetch_diagnostic(
                "error",
                "sina_http",
                "hq.sinajs.cn",
                f"fetch failed: {exc!r}",
            )
            return {}

        snapshots: dict[str, MarketQuoteSnapshot] = {}
        symbol_to_code = {symbol: code for code, symbol in symbols.items()}
        for quote_part in text.split(";"):
            if "=" not in quote_part:
                continue
            raw_key, raw_value = quote_part.split("=", 1)
            symbol = raw_key.strip().removeprefix("var hq_str_")
            index_code = symbol_to_code.get(symbol)
            if not index_code:
                continue
            snapshot = self._snapshot(index_code, raw_value.strip().strip('"'), quote_time)
            if snapshot is not None:
                snapshots[index_code] = snapshot
        return snapshots

    def _snapshot(
        self,
        index_code: str,
        raw_value: str,
        quote_time: datetime,
    ) -> MarketQuoteSnapshot | None:
        fields = raw_value.split(",")
        if len(fields) < 4:
            return None
        asset_name = fields[0] or None
        latest_price = self.helper._optional_decimal(fields[1])
        change_rate = self.helper._percent(fields[3])
        if latest_price is None or change_rate is None:
            return None
        prev_close = self.helper._previous_close(latest_price, change_rate)
        return MarketQuoteSnapshot(
            asset_code=index_code,
            asset_name=asset_name,
            asset_type="index",
            market="CN",
            trade_date=quote_time.date(),
            quote_time=quote_time,
            latest_price=latest_price,
            prev_close=prev_close,
            change_rate=change_rate,
        )

    @staticmethod
    def _symbol(index_code: str) -> str | None:
        code = str(index_code or "").strip()
        if not code.isdigit():
            return None
        if code.startswith("3"):
            return f"s_sz{code}"
        if code.startswith(("0", "5", "8", "9")):
            return f"s_sh{code}"
        return None
