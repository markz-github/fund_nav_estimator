from __future__ import annotations

from datetime import datetime

import requests

from app.modules.fund_nav.data_sources.akshare.akshare_source import MarketQuoteSnapshot


class EastmoneyHttpIndexSource:
    source_name = "eastmoney_http"
    quote_url = "https://push2.eastmoney.com/api/qt/ulist.np/get"

    def __init__(self, helper) -> None:
        self.helper = helper

    def get_spot_quotes(
        self,
        index_codes: set[str],
        quote_time: datetime,
        quote_symbols: dict[str, str] | None = None,
    ) -> dict[str, MarketQuoteSnapshot]:
        secids = quote_symbols or {
            index_code: self._secid(index_code)
            for index_code in index_codes
            if self._secid(index_code) is not None
        }
        if not secids:
            return {}

        try:
            response = requests.get(
                self.quote_url,
                params={
                    "fltt": "2",
                    "secids": ",".join(secids.values()),
                    "fields": "f12,f13,f14,f2,f3,f18,f124",
                },
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://quote.eastmoney.com/",
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            self.helper._record_fetch_diagnostic(
                "error",
                "eastmoney_http",
                "push2.eastmoney.com",
                f"fetch failed: {exc!r}",
            )
            raise

        code_by_secid = {secid: code for code, secid in secids.items()}
        snapshots: dict[str, MarketQuoteSnapshot] = {}
        for row in (payload.get("data") or {}).get("diff") or []:
            index_code = code_by_secid.get(f"{row.get('f13')}.{row.get('f12')}")
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
        latest_price = self.helper._optional_decimal(row.get("f2"))
        change_rate = self.helper._percent(row.get("f3"))
        if latest_price is None or change_rate is None:
            return None
        prev_close = self.helper._optional_decimal(row.get("f18"))
        if prev_close is None:
            prev_close = self.helper._previous_close(latest_price, change_rate)
        provider_time = self._provider_time(row.get("f124")) or quote_time
        return MarketQuoteSnapshot(
            asset_code=index_code,
            asset_name=self.helper._none_if_nan(row.get("f14")),
            asset_type="index",
            market="CN",
            trade_date=provider_time.date(),
            quote_time=provider_time.replace(microsecond=0),
            latest_price=latest_price,
            prev_close=prev_close,
            change_rate=change_rate,
        )

    @staticmethod
    def _secid(index_code: str) -> str | None:
        code = str(index_code or "").strip()
        if not code.isdigit():
            return None
        if code.startswith("9"):
            return f"2.{code}"
        if code.startswith("3"):
            return f"0.{code}"
        if code.startswith(("0", "5", "8")):
            return f"1.{code}"
        return None

    @staticmethod
    def _provider_time(value) -> datetime | None:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        if timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp)
