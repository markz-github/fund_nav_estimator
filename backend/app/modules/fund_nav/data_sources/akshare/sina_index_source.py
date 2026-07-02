from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import akshare as ak

from app.modules.fund_nav.data_sources.akshare.akshare_source import MarketQuoteSnapshot


class SinaIndexSource:
    source_name = "sina"

    def __init__(self, helper) -> None:
        self.helper = helper

    def get_spot_quotes(
        self,
        index_codes: set[str],
        quote_time: datetime,
    ) -> dict[str, MarketQuoteSnapshot]:
        snapshots: dict[str, MarketQuoteSnapshot] = {}
        if not index_codes:
            return snapshots
        try:
            market_df = self._get_spot_dataframe()
        except Exception:
            return snapshots

        matched_rows = self.helper._rows_by_normalized_codes(
            market_df,
            index_codes,
            code_column="代码",
            normalizer=self.helper._normalize_index_code,
        )
        for normalized_code, row in matched_rows:
            snapshot = self._spot_snapshot(normalized_code, row, quote_time)
            if snapshot is not None:
                snapshots[normalized_code] = snapshot
        return snapshots

    def get_daily_quote(
        self,
        index_code: str,
        quote_time: datetime,
    ) -> MarketQuoteSnapshot | None:
        symbol = self._prefixed_symbol(index_code)
        if symbol is None:
            return None
        try:
            history_df = ak.stock_zh_index_daily(symbol=symbol)
        except Exception as exc:
            self.helper._record_fetch_diagnostic(
                "error",
                "akshare",
                "stock_zh_index_daily",
                f"fetch failed: {index_code};{exc!r}",
            )
            return None
        return self._daily_snapshot(index_code, history_df, quote_time)

    def get_tencent_daily_quote(
        self,
        index_code: str,
        quote_time: datetime,
    ) -> MarketQuoteSnapshot | None:
        symbol = self._prefixed_symbol(index_code)
        if symbol is None:
            return None
        try:
            history_df = ak.stock_zh_index_daily_tx(symbol=symbol)
        except Exception as exc:
            self.helper._record_fetch_diagnostic(
                "error",
                "akshare",
                "stock_zh_index_daily_tx",
                f"fetch failed: {index_code};{exc!r}",
            )
            return None
        return self._daily_snapshot(index_code, history_df, quote_time)

    def _get_spot_dataframe(self):
        return self.helper._load_dataframe(
            "stock_zh_index_spot_sina",
            ak.stock_zh_index_spot_sina,
            self.helper._realtime_cache_ttl_seconds,
            code_column="代码",
            normalizer=self.helper._normalize_index_code,
            max_stale_age_seconds=self.helper._realtime_stale_cache_max_age_seconds,
        )

    def _spot_snapshot(
        self,
        index_code: str,
        row,
        quote_time: datetime,
    ) -> MarketQuoteSnapshot | None:
        latest_price = self.helper._optional_decimal(row.get("最新价"))
        change_rate = self.helper._percent(row.get("涨跌幅"))
        prev_close = self.helper._optional_decimal(row.get("昨收"))
        if latest_price is None or change_rate is None:
            return None
        if prev_close is None:
            prev_close = self.helper._previous_close(latest_price, change_rate)

        return MarketQuoteSnapshot(
            asset_code=index_code,
            asset_name=self.helper._none_if_nan(row.get("名称")),
            asset_type="index",
            market="CN",
            trade_date=quote_time.date(),
            quote_time=quote_time,
            latest_price=latest_price,
            prev_close=prev_close,
            change_rate=change_rate,
        )

    def _daily_snapshot(
        self,
        index_code: str,
        history_df,
        quote_time: datetime,
    ) -> MarketQuoteSnapshot | None:
        if history_df.empty:
            return None
        row = history_df.iloc[-1]
        previous_row = history_df.iloc[-2] if len(history_df) >= 2 else None
        trade_date = self._date_from_daily_row(row)
        latest_price = self._daily_close(row)
        prev_close = self._daily_close(previous_row) if previous_row is not None else None
        change_rate = None
        if latest_price is not None and prev_close not in (None, Decimal("0")):
            change_rate = (latest_price - prev_close) / prev_close
        return MarketQuoteSnapshot(
            asset_code=index_code,
            asset_name=None,
            asset_type="index",
            market="CN",
            trade_date=trade_date,
            quote_time=quote_time,
            latest_price=latest_price,
            prev_close=prev_close,
            change_rate=change_rate,
        )

    def _date_from_daily_row(self, row) -> date:
        for column in ("date", "日期"):
            value = row.get(column)
            if value is not None:
                return self.helper._date_from_value(value)
        return self.helper._date_from_value(row.iloc[0])

    def _daily_close(self, row) -> Decimal | None:
        if row is None:
            return None
        for column in ("close", "收盘", "收盘价"):
            if column in row:
                return self.helper._optional_decimal(row.get(column))
        return None

    @staticmethod
    def _prefixed_symbol(index_code: str) -> str | None:
        code = str(index_code or "").strip()
        if not code.isdigit():
            return None
        if code.startswith(("0", "3")):
            return f"sz{code}"
        if code.startswith(("8", "9")):
            return None
        return f"sh{code}"
