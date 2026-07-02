from __future__ import annotations

from datetime import datetime, timedelta

import akshare as ak

from app.modules.fund_nav.data_sources.akshare.akshare_source import MarketQuoteSnapshot


class CsindexIndexSource:
    source_name = "csindex"

    def __init__(self, helper) -> None:
        self.helper = helper

    def get_daily_quote(
        self,
        index_code: str,
        quote_time: datetime,
    ) -> MarketQuoteSnapshot | None:
        end_date = quote_time.strftime("%Y%m%d")
        start_date = (quote_time - timedelta(days=45)).strftime("%Y%m%d")
        try:
            history_df = ak.stock_zh_index_hist_csindex(
                symbol=index_code,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
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
            asset_name=self.helper._none_if_nan(row.get("指数中文简称") or row.get("指数中文全称")),
            asset_type="index",
            market="CN",
            trade_date=trade_date,
            quote_time=quote_time,
            latest_price=latest_price,
            prev_close=prev_close,
            change_rate=change_rate,
        )
