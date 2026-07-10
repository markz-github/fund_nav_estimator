from __future__ import annotations

from datetime import datetime

import requests

from app.modules.fund_nav.data_sources.akshare.akshare_source import MarketQuoteSnapshot


class XueqiuIndexSource:
    source_name = "xueqiu"
    home_url = "https://xueqiu.com/"
    quote_url = "https://stock.xueqiu.com/v5/stock/realtime/quotec.json"

    def __init__(self, helper) -> None:
        self.helper = helper

    def get_spot_quotes(
        self,
        index_codes: set[str],
        quote_time: datetime,
        quote_symbols: dict[str, str] | None = None,
    ) -> dict[str, MarketQuoteSnapshot]:
        symbols = quote_symbols or {
            index_code: self._symbol(index_code)
            for index_code in index_codes
            if self._symbol(index_code) is not None
        }
        if not symbols:
            return {}

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://xueqiu.com/",
        }
        try:
            session = requests.Session()
            try:
                session.get(self.home_url, headers=headers, timeout=10)
            except Exception:
                pass
            response = session.get(
                self.quote_url,
                params={"symbol": ",".join(symbols.values())},
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            self.helper._record_fetch_diagnostic(
                "error",
                "xueqiu",
                "stock.xueqiu.com",
                f"fetch failed: {exc!r}",
            )
            raise

        code_by_symbol = {symbol.upper(): code for code, symbol in symbols.items()}
        snapshots: dict[str, MarketQuoteSnapshot] = {}
        for row in payload.get("data") or []:
            symbol = str(row.get("symbol") or "").upper()
            index_code = code_by_symbol.get(symbol)
            if not index_code:
                continue
            snapshot = self._snapshot(index_code, row, quote_time)
            if snapshot is not None:
                snapshots[index_code] = snapshot
        return snapshots

    def _snapshot(
        self,
        index_code: str,
        row: dict,
        quote_time: datetime,
    ) -> MarketQuoteSnapshot | None:
        latest_price = self.helper._optional_decimal(row.get("current"))
        change_rate = self.helper._percent(row.get("percent"))
        if latest_price is None or change_rate is None:
            return None
        prev_close = self.helper._optional_decimal(row.get("last_close"))
        if prev_close is None:
            prev_close = self.helper._previous_close(latest_price, change_rate)
        provider_time = self._provider_time(row.get("timestamp") or row.get("time")) or quote_time
        return MarketQuoteSnapshot(
            asset_code=index_code,
            asset_name=self.helper._none_if_nan(row.get("name")),
            asset_type="index",
            market="CN",
            trade_date=provider_time.date(),
            quote_time=provider_time.replace(microsecond=0),
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
            return f"SZ{code}"
        if code.startswith("9"):
            return f"CSI{code}"
        if code.startswith(("0", "5", "8", "9")):
            return f"SH{code}"
        return None

    @staticmethod
    def _provider_time(value) -> datetime | None:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        if timestamp <= 0:
            return None
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp)
