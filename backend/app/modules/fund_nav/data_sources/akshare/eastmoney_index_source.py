from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import akshare as ak

from app.modules.fund_nav.data_sources.akshare.akshare_source import MarketQuoteSnapshot


class EastmoneyIndexSource:
    source_name = "eastmoney"
    spot_groups = ("深证系列指数", "中证系列指数", "沪深重要指数", "上证系列指数")

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

        for group in self.spot_groups:
            missing_codes = index_codes - set(snapshots)
            if not missing_codes:
                break
            try:
                market_df = self._get_spot_dataframe(group)
            except Exception:
                continue
            matched_rows = self.helper._rows_by_normalized_codes(
                market_df,
                missing_codes,
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
        end_date = quote_time.strftime("%Y%m%d")
        start_date = (quote_time - timedelta(days=45)).strftime("%Y%m%d")
        try:
            history_df = ak.index_zh_a_hist(
                symbol=index_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            self.helper._record_fetch_diagnostic(
                "error",
                "akshare",
                "index_zh_a_hist",
                f"fetch failed: {index_code};{exc!r}",
            )
            return None
        if history_df.empty:
            return None

        row = history_df.iloc[-1]
        trade_date = self.helper._date_from_value(row.get("日期"))
        latest_price = self.helper._optional_decimal(row.get("收盘"))
        change_rate = self.helper._percent(row.get("涨跌幅"))
        prev_close = self.helper._previous_close(latest_price, change_rate)
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

    def _get_spot_dataframe(self, symbol: str):
        return self.helper._load_dataframe(
            f"stock_zh_index_spot_em:{symbol}",
            lambda: ak.stock_zh_index_spot_em(symbol=symbol),
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
