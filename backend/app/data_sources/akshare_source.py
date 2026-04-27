from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import re

import akshare as ak
import requests


@dataclass(frozen=True)
class FundProfile:
    fund_code: str
    fund_name: str
    fund_type: str | None


@dataclass(frozen=True)
class FundNavSnapshot:
    fund_code: str
    nav_date: date
    unit_nav: Decimal
    accumulated_nav: Decimal | None
    daily_growth_rate: Decimal | None


@dataclass(frozen=True)
class MarketQuoteSnapshot:
    asset_code: str
    asset_name: str | None
    asset_type: str
    market: str | None
    trade_date: date
    quote_time: datetime
    latest_price: Decimal | None
    prev_close: Decimal | None
    change_rate: Decimal | None


class AkshareSource:
    """Thin adapter for akshare calls.

    Real akshare function names occasionally change, so all external calls
    should stay behind this adapter instead of leaking into services.
    """

    source_name = "akshare"

    def get_fund_profile(self, fund_code: str) -> FundProfile:
        normalized_code = self._normalize_fund_code(fund_code)
        fund_df = ak.fund_name_em()
        matched = fund_df[fund_df["基金代码"].astype(str).str.zfill(6) == normalized_code]
        if matched.empty:
            raise LookupError(f"Fund not found: {normalized_code}")

        row = matched.iloc[0]
        return FundProfile(
            fund_code=normalized_code,
            fund_name=str(row["基金简称"]),
            fund_type=self._none_if_nan(row.get("基金类型")),
        )

    def get_latest_fund_nav(self, fund_code: str) -> FundNavSnapshot | None:
        normalized_code = self._normalize_fund_code(fund_code)
        daily_df = ak.fund_open_fund_daily_em()
        matched = daily_df[daily_df["基金代码"].astype(str).str.zfill(6) == normalized_code]
        if matched.empty:
            return None

        row = matched.iloc[0]
        nav_date = self._extract_latest_nav_date(list(daily_df.columns))
        unit_nav_column = f"{nav_date.isoformat()}-单位净值"
        accumulated_nav_column = f"{nav_date.isoformat()}-累计净值"

        return FundNavSnapshot(
            fund_code=normalized_code,
            nav_date=nav_date,
            unit_nav=self._decimal(row[unit_nav_column]),
            accumulated_nav=self._optional_decimal(row.get(accumulated_nav_column)),
            daily_growth_rate=self._percent(row.get("日增长率")),
        )

    def get_fund_holdings(self, fund_code: str) -> list[dict]:
        normalized_code = self._normalize_fund_code(fund_code)
        current_year = date.today().year
        for year in range(current_year, current_year - 4, -1):
            holding_df = ak.fund_portfolio_hold_em(symbol=normalized_code, date=str(year))
            if holding_df.empty:
                continue

            holdings = []
            for _, row in holding_df.iterrows():
                asset_code = str(row["股票代码"]).strip().zfill(5 if len(str(row["股票代码"]).strip()) == 5 else 6)
                holdings.append(
                    {
                        "fund_code": normalized_code,
                        "report_period": self._parse_report_period(str(row["季度"])),
                        "asset_code": asset_code,
                        "asset_name": str(row["股票名称"]).strip(),
                        "asset_type": "stock",
                        "market": self._infer_stock_market(asset_code),
                        "holding_ratio": self._percent(row["占净值比例"]),
                        "holding_value": self._optional_decimal(row.get("持仓市值")),
                        "source": self.source_name,
                    }
                )
            return holdings
        return []

    def get_market_quotes(self, asset_codes: list[str]) -> list[MarketQuoteSnapshot]:
        target_codes = {str(code).strip() for code in asset_codes if str(code).strip()}
        if not target_codes:
            return []

        quote_time = datetime.now()
        trade_date = quote_time.date()
        snapshots: dict[str, MarketQuoteSnapshot] = {}
        has_hk = any(len(code) == 5 for code in target_codes)
        has_etf = any(len(code) == 6 and code.startswith(("5", "1")) for code in target_codes)
        has_cn_stock = any(len(code) == 6 and not code.startswith(("5", "1")) for code in target_codes)

        fetch_tasks = []
        if has_cn_stock:
            fetch_tasks.extend(
                [
                    ("CN", "stock", ak.stock_zh_a_spot),
                    ("CN", "stock", ak.stock_zh_a_spot_em),
                ]
            )
        if has_hk:
            fetch_tasks.extend(
                [
                    ("HK", "stock", ak.stock_hk_spot),
                    ("HK", "stock", ak.stock_hk_spot_em),
                ]
            )
        if has_etf:
            fetch_tasks.append(("CN", "etf", ak.fund_etf_spot_em))

        for market_name, asset_type, fetcher in fetch_tasks:
            try:
                market_df = fetcher()
            except Exception:
                continue

            if market_df.empty:
                continue

            for _, row in market_df.iterrows():
                raw_code = str(row["代码"]).strip()
                normalized_code = self._normalize_asset_code(raw_code, market_name)
                if normalized_code not in target_codes:
                    continue
                snapshots[normalized_code] = MarketQuoteSnapshot(
                    asset_code=normalized_code,
                    asset_name=self._none_if_nan(row.get("名称") or row.get("中文名称")),
                    asset_type=asset_type,
                    market=self._infer_stock_market(normalized_code)
                    if asset_type == "stock"
                    else market_name,
                    trade_date=self._quote_trade_date(row, quote_time),
                    quote_time=quote_time,
                    latest_price=self._optional_decimal(row.get("最新价")),
                    prev_close=self._optional_decimal(row.get("昨收")),
                    change_rate=self._percent(row.get("涨跌幅")),
                )

        missing_codes = target_codes - set(snapshots.keys())
        for asset_code in missing_codes:
            fallback = self._get_sina_quote(asset_code, quote_time)
            if fallback is None:
                fallback = self._get_latest_history_quote(asset_code, quote_time)
            if fallback is not None:
                snapshots[asset_code] = fallback

        return list(snapshots.values())

    @staticmethod
    def _normalize_fund_code(fund_code: str) -> str:
        return str(fund_code).strip().zfill(6)

    @staticmethod
    def _extract_latest_nav_date(columns: list[str]) -> date:
        candidates: list[date] = []
        for column in columns:
            match = re.match(r"^(\d{4}-\d{2}-\d{2})-单位净值$", column)
            if match:
                candidates.append(date.fromisoformat(match.group(1)))
        if not candidates:
            raise ValueError("No unit nav date column found in akshare daily fund data.")
        return max(candidates)

    @staticmethod
    def _none_if_nan(value) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "" or text.lower() == "nan":
            return None
        return text

    @classmethod
    def _optional_decimal(cls, value) -> Decimal | None:
        text = cls._none_if_nan(value)
        if text is None:
            return None
        return cls._decimal(text)

    @staticmethod
    def _decimal(value) -> Decimal:
        text = str(value).strip().replace(",", "")
        if text.endswith("%"):
            text = text[:-1]
        if text == "" or text == "--" or text.lower() == "nan":
            raise ValueError(f"Invalid decimal value: {value}")
        return Decimal(text)

    @classmethod
    def _percent(cls, value) -> Decimal | None:
        decimal_value = cls._optional_decimal(value)
        if decimal_value is None:
            return None
        return decimal_value / Decimal("100")

    @staticmethod
    def _parse_report_period(value: str) -> str:
        match = re.search(r"(\d{4})年(\d)季度", value)
        if not match:
            return value.strip()
        return f"{match.group(1)}Q{match.group(2)}"

    @staticmethod
    def _infer_stock_market(asset_code: str) -> str | None:
        if len(asset_code) == 5:
            return "HK"
        if asset_code.startswith(("6", "9")):
            return "SH"
        if asset_code.startswith(("0", "2", "3")):
            return "SZ"
        if asset_code.startswith(("4", "8")):
            return "BJ"
        return None

    @staticmethod
    def _normalize_asset_code(asset_code: str, market: str | None = None) -> str:
        code = str(asset_code).strip()
        code = re.sub(r"^(sh|sz|bj|hk)", "", code, flags=re.IGNORECASE)
        if market == "HK" or (code.isdigit() and len(code) == 5):
            return code.zfill(5)
        if code.isdigit() and len(code) < 6:
            return code.zfill(6)
        return code

    def _get_latest_history_quote(
        self, asset_code: str, quote_time: datetime
    ) -> MarketQuoteSnapshot | None:
        end_date = quote_time.strftime("%Y%m%d")
        start_date = (quote_time - timedelta(days=45)).strftime("%Y%m%d")
        market = self._infer_stock_market(asset_code)
        asset_type = "stock"

        try:
            if len(asset_code) == 5:
                market = "HK"
                history_df = ak.stock_hk_hist(
                    symbol=asset_code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="",
                )
            elif asset_code.startswith(("5", "1")):
                asset_type = "etf"
                history_df = ak.fund_etf_hist_em(
                    symbol=asset_code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="",
                )
            else:
                history_df = ak.stock_zh_a_hist(
                    symbol=asset_code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="",
                )
        except Exception:
            return None

        if history_df.empty:
            return None

        row = history_df.iloc[-1]
        trade_date_value = row["日期"]
        if hasattr(trade_date_value, "date"):
            trade_date = trade_date_value.date()
        else:
            trade_date = date.fromisoformat(str(trade_date_value))

        latest_price = self._optional_decimal(row.get("收盘"))
        change_rate = self._percent(row.get("涨跌幅"))
        prev_close = self._previous_close(latest_price, change_rate)

        return MarketQuoteSnapshot(
            asset_code=asset_code,
            asset_name=None,
            asset_type=asset_type,
            market=market,
            trade_date=trade_date,
            quote_time=quote_time,
            latest_price=latest_price,
            prev_close=prev_close,
            change_rate=change_rate,
        )

    def _get_sina_quote(
        self, asset_code: str, quote_time: datetime
    ) -> MarketQuoteSnapshot | None:
        sina_code = self._sina_asset_code(asset_code)
        if sina_code is None:
            return None

        try:
            response = requests.get(
                f"https://hq.sinajs.cn/list={sina_code}",
                headers={
                    "Referer": "https://finance.sina.com.cn",
                    "User-Agent": "Mozilla/5.0",
                },
                timeout=15,
            )
            response.encoding = "gbk"
        except requests.RequestException:
            return None

        match = re.search(r'="(?P<payload>[^"]*)"', response.text)
        if not match:
            return None
        fields = match.group("payload").split(",")
        if len(fields) < 32 or not fields[0]:
            return None

        latest_price = self._optional_decimal(fields[3])
        prev_close = self._optional_decimal(fields[2])
        change_rate = None
        if latest_price is not None and prev_close not in (None, Decimal("0")):
            change_rate = (latest_price - prev_close) / prev_close

        trade_date = quote_time.date()
        try:
            trade_date = date.fromisoformat(fields[30])
        except (ValueError, IndexError):
            pass

        quote_datetime = quote_time
        try:
            quote_datetime = datetime.fromisoformat(f"{fields[30]} {fields[31]}")
        except (ValueError, IndexError):
            pass

        asset_type = "etf" if asset_code.startswith(("5", "1")) else "stock"
        return MarketQuoteSnapshot(
            asset_code=asset_code,
            asset_name=fields[0],
            asset_type=asset_type,
            market=self._infer_stock_market(asset_code) if asset_type == "stock" else "CN",
            trade_date=trade_date,
            quote_time=quote_datetime,
            latest_price=latest_price,
            prev_close=prev_close,
            change_rate=change_rate,
        )

    @staticmethod
    def _sina_asset_code(asset_code: str) -> str | None:
        if len(asset_code) == 5:
            return f"hk{asset_code}"
        if not asset_code.isdigit() or len(asset_code) != 6:
            return None
        if asset_code.startswith(("5", "6", "9")):
            return f"sh{asset_code}"
        if asset_code.startswith(("0", "1", "2", "3")):
            return f"sz{asset_code}"
        return None

    @staticmethod
    def _previous_close(
        latest_price: Decimal | None, change_rate: Decimal | None
    ) -> Decimal | None:
        if latest_price is None or change_rate is None:
            return None
        denominator = Decimal("1") + change_rate
        if denominator == 0:
            return None
        return latest_price / denominator

    @staticmethod
    def _quote_trade_date(row, quote_time: datetime) -> date:
        raw_datetime = row.get("日期时间")
        if raw_datetime is not None:
            try:
                return datetime.strptime(str(raw_datetime).split(" ")[0], "%Y/%m/%d").date()
            except ValueError:
                pass

        current_date = quote_time.date()
        if current_date.weekday() == 5:
            return current_date - timedelta(days=1)
        if current_date.weekday() == 6:
            return current_date - timedelta(days=2)
        return current_date
