from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import re
import logging
from threading import Lock
from time import monotonic

import akshare as ak
import requests

from app.utils.performance import timed


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
    source: str = "akshare"


@dataclass(frozen=True)
class EtfIopvSnapshot:
    fund_code: str
    asset_name: str | None
    estimate_time: datetime
    estimated_nav: Decimal
    latest_price: Decimal | None
    change_rate: Decimal | None
    source: str = "akshare:etf_iopv"


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
    _fund_daily_cache_ttl_seconds = 600
    _realtime_cache_ttl_seconds = 300
    _realtime_stale_cache_max_age_seconds = 900
    _cache_wait_timeout_seconds = 60
    _normalized_code_column = "_normalized_code"
    _dataframe_cache: dict[str, tuple[object, float]] = {}
    _cache_locks: dict[str, Lock] = {}
    _cache_locks_guard = Lock()

    @timed()
    def get_fund_profile(self, fund_code: str) -> FundProfile:
        normalized_code = self._normalize_fund_code(fund_code)
        fund_df = self.get_fund_profiles_dataframe()
        matched = fund_df[fund_df["基金代码"].astype(str).str.zfill(6) == normalized_code]
        if matched.empty:
            raise LookupError(f"Fund not found: {normalized_code}")

        row = matched.iloc[0]
        return FundProfile(
            fund_code=normalized_code,
            fund_name=str(row["基金简称"]),
            fund_type=self._none_if_nan(row.get("基金类型")),
        )

    @timed()
    def get_fund_profiles(self) -> list[FundProfile]:
        fund_df = self.get_fund_profiles_dataframe()
        profiles: list[FundProfile] = []
        for _, row in fund_df.iterrows():
            fund_code = str(row["基金代码"]).strip().zfill(6)
            fund_name = self._none_if_nan(row.get("基金简称"))
            if not fund_code or fund_name is None:
                continue
            profiles.append(
                FundProfile(
                    fund_code=fund_code,
                    fund_name=fund_name,
                    fund_type=self._none_if_nan(row.get("基金类型")),
                )
            )
        return profiles

    @staticmethod
    def get_fund_profiles_dataframe():
        started = monotonic()
        try:
            dataframe = ak.fund_name_em()
        except Exception:
            logging.getLogger("app.performance").exception(
                "akshare_fetch endpoint=fund_name_em status=failed duration_ms=%.2f",
                (monotonic() - started) * 1000,
            )
            raise
        logging.getLogger("app.performance").info(
            "akshare_fetch endpoint=fund_name_em status=success rows=%s duration_ms=%.2f",
            len(dataframe),
            (monotonic() - started) * 1000,
        )
        return dataframe

    @timed()
    def get_latest_fund_nav(self, fund_code: str) -> FundNavSnapshot | None:
        normalized_code = self._normalize_fund_code(fund_code)
        if self._should_try_etf_first(normalized_code):
            etf_snapshot = self._get_latest_etf_nav_snapshot(normalized_code)
            if etf_snapshot is not None:
                return etf_snapshot

        daily_df = self.get_fund_daily_dataframe()
        row = self._first_row_by_normalized_code(
            daily_df,
            normalized_code,
            code_column="基金代码",
            normalizer=self._normalize_fund_code,
        )
        if row is None:
            return self._get_latest_eastmoney_fund_nav_snapshot(normalized_code) or self._get_latest_etf_nav_snapshot(normalized_code)

        nav_date = self._extract_latest_nav_date_for_row(row, list(daily_df.columns))
        if nav_date is None:
            return self._get_latest_eastmoney_fund_nav_snapshot(normalized_code)

        latest_table_date = self._extract_latest_nav_date(list(daily_df.columns))
        fallback_snapshot: FundNavSnapshot | None = None
        if latest_table_date > nav_date:
            fallback_snapshot = self._get_latest_eastmoney_fund_nav_snapshot(normalized_code)
            if fallback_snapshot is not None and fallback_snapshot.nav_date > nav_date:
                return fallback_snapshot

        unit_nav_column = f"{nav_date.isoformat()}-单位净值"
        accumulated_nav_column = f"{nav_date.isoformat()}-累计净值"

        try:
            snapshot = FundNavSnapshot(
                fund_code=normalized_code,
                nav_date=nav_date,
                unit_nav=self._decimal(row[unit_nav_column]),
                accumulated_nav=self._optional_decimal(row.get(accumulated_nav_column)),
                daily_growth_rate=self._percent(row.get("日增长率")),
                source=self.source_name,
            )
            if snapshot.daily_growth_rate is None:
                fallback_snapshot = fallback_snapshot or self._get_latest_eastmoney_fund_nav_snapshot(normalized_code)
                if fallback_snapshot is not None and fallback_snapshot.nav_date == snapshot.nav_date:
                    return fallback_snapshot
            return snapshot
        except Exception:
            return fallback_snapshot or self._get_latest_eastmoney_fund_nav_snapshot(normalized_code)

    @timed()
    def get_fund_nav_history(self, fund_code: str) -> list[FundNavSnapshot]:
        normalized_code = self._normalize_fund_code(fund_code)
        dataframe = ak.fund_open_fund_info_em(symbol=normalized_code, indicator="单位净值走势", period="成立来")
        snapshots: list[FundNavSnapshot] = []
        for _, row in dataframe.iterrows():
            raw_nav_date = row.get("净值日期")
            if raw_nav_date is None:
                continue
            if hasattr(raw_nav_date, "date"):
                nav_date = raw_nav_date.date()
            else:
                nav_date = date.fromisoformat(str(raw_nav_date).split(" ")[0])
            unit_nav = self._optional_decimal(row.get("单位净值"))
            if unit_nav is None:
                continue
            snapshots.append(
                FundNavSnapshot(
                    fund_code=normalized_code,
                    nav_date=nav_date,
                    unit_nav=unit_nav,
                    accumulated_nav=self._optional_decimal(row.get("累计净值")),
                    daily_growth_rate=self._percent(row.get("日增长率")),
                    source=f"{self.source_name}:fund_open_fund_info_em",
                )
            )
        return sorted(snapshots, key=lambda item: item.nav_date)

    @classmethod
    def get_fund_daily_dataframe(cls):
        return cls._load_dataframe(
            "fund_open_fund_daily_em",
            ak.fund_open_fund_daily_em,
            cls._fund_daily_cache_ttl_seconds,
            code_column="基金代码",
            normalizer=cls._normalize_fund_code,
        )

    @staticmethod
    def _should_try_etf_first(fund_code: str) -> bool:
        return fund_code.startswith("5")

    def _get_latest_etf_nav_snapshot(self, fund_code: str) -> FundNavSnapshot | None:
        if not fund_code.startswith(("5", "1")):
            return None

        try:
            etf_df = self._get_etf_spot_dataframe()
        except Exception:
            return None

        row = self._first_row_by_normalized_code(
            etf_df,
            fund_code,
            code_column="代码",
            normalizer=lambda value: self._normalize_asset_code(value, "CN"),
        )
        if row is None:
            return None

        prev_close = self._optional_decimal(row.get("昨收"))
        unit_nav = prev_close
        source = f"{self.source_name}:etf_spot_prev_close"

        if unit_nav is None:
            unit_nav = self._optional_decimal(row.get("IOPV实时估值"))
            source = f"{self.source_name}:etf_spot"
        if unit_nav is None:
            unit_nav = self._optional_decimal(row.get("最新价"))
            source = f"{self.source_name}:etf_spot"
        if unit_nav is None:
            return None

        quote_date = date.today()
        raw_date = row.get("数据日期")
        if raw_date is not None:
            try:
                if hasattr(raw_date, "date"):
                    quote_date = raw_date.date()
                else:
                    quote_date = date.fromisoformat(str(raw_date).split(" ")[0])
            except ValueError:
                pass
        nav_date = self._previous_business_day(quote_date) if prev_close is not None else quote_date

        return FundNavSnapshot(
            fund_code=fund_code,
            nav_date=nav_date,
            unit_nav=unit_nav,
            accumulated_nav=None,
            daily_growth_rate=self._percent(row.get("涨跌幅")),
            source=source,
        )

    def get_etf_iopv_snapshot(self, fund_code: str) -> EtfIopvSnapshot | None:
        normalized_code = self._normalize_asset_code(fund_code, "CN")
        if not normalized_code.startswith(("5", "1")):
            return None
        try:
            etf_df = self._get_etf_spot_dataframe()
        except Exception:
            quote = self._get_eastmoney_etf_quote(normalized_code, datetime.now().replace(microsecond=0))
            if quote is None or quote.latest_price is None:
                return None
            return EtfIopvSnapshot(
                fund_code=normalized_code,
                asset_name=quote.asset_name,
                estimate_time=quote.quote_time,
                estimated_nav=quote.latest_price,
                latest_price=quote.latest_price,
                change_rate=quote.change_rate,
                source="eastmoney:etf_price_fallback",
            )

        row = self._first_row_by_normalized_code(
            etf_df,
            normalized_code,
            code_column="代码",
            normalizer=lambda value: self._normalize_asset_code(value, "CN"),
        )
        if row is None:
            return None

        iopv = self._optional_decimal(row.get("IOPV实时估值"))
        source = "akshare:etf_iopv"
        if iopv is None:
            iopv = self._optional_decimal(row.get("最新价"))
            source = "akshare:etf_price_fallback"
        if iopv is None:
            quote = self._get_eastmoney_etf_quote(normalized_code, datetime.now().replace(microsecond=0))
            if quote is None or quote.latest_price is None:
                return None
            return EtfIopvSnapshot(
                fund_code=normalized_code,
                asset_name=quote.asset_name,
                estimate_time=quote.quote_time,
                estimated_nav=quote.latest_price,
                latest_price=quote.latest_price,
                change_rate=quote.change_rate,
                source="eastmoney:etf_price_fallback",
            )

        return EtfIopvSnapshot(
            fund_code=normalized_code,
            asset_name=self._none_if_nan(row.get("名称")),
            estimate_time=datetime.now().replace(microsecond=0),
            estimated_nav=iopv,
            latest_price=self._optional_decimal(row.get("最新价")),
            change_rate=self._percent(row.get("涨跌幅")),
            source=source,
        )

    def _get_latest_eastmoney_fund_nav_snapshot(self, fund_code: str) -> FundNavSnapshot | None:
        try:
            response = requests.get(
                f"https://fund.eastmoney.com/{fund_code}.html",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            if response.status_code >= 400:
                return None
            response.encoding = response.apparent_encoding or "utf-8"
        except requests.RequestException:
            return None

        text = re.sub(r"<[^>]+>", " ", response.text)
        text = re.sub(r"\s+", " ", text)
        today = date.today()
        full_date_match = re.search(
            r"单位净值\s*\((?P<date>\d{4}-\d{2}-\d{2})\)\s+"
            r"(?P<unit>\d+(?:\.\d+)?)(?P<growth>[-+]?\d+(?:\.\d+)?)%"
            r".{0,200}?累计净值\s+(?P<accumulated>\d+(?:\.\d+)?)",
            text,
        )
        short_date_match = re.search(
            r"(?P<month>\d{2})-(?P<day>\d{2})\s+"
            r"(?P<unit>\d+(?:\.\d+)?)\s+"
            r"(?P<accumulated>\d+(?:\.\d+)?)\s+"
            r"(?P<growth>[-+]?\d+(?:\.\d+)?)%",
            text,
        )
        if full_date_match:
            nav_date = date.fromisoformat(full_date_match.group("date"))
            match = full_date_match
        elif short_date_match:
            nav_date = date(today.year, int(short_date_match.group("month")), int(short_date_match.group("day")))
            if nav_date > today:
                nav_date = date(today.year - 1, nav_date.month, nav_date.day)
            match = short_date_match
        else:
            return None

        return FundNavSnapshot(
            fund_code=fund_code,
            nav_date=nav_date,
            unit_nav=Decimal(match.group("unit")),
            accumulated_nav=Decimal(match.group("accumulated")),
            daily_growth_rate=Decimal(match.group("growth")) / Decimal("100"),
            source=f"{self.source_name}:eastmoney_fund_page",
        )

    @timed()
    def get_fund_holdings(self, fund_code: str) -> list[dict]:
        normalized_code = self._normalize_fund_code(fund_code)
        current_year = date.today().year
        for year in range(current_year, current_year - 4, -1):
            holdings = []
            holdings.extend(self._stock_holdings(normalized_code, year))
            holdings.extend(self._bond_holdings(normalized_code, year))
            if holdings:
                return holdings
        return []

    def _stock_holdings(self, fund_code: str, year: int) -> list[dict]:
        try:
            holding_df = ak.fund_portfolio_hold_em(symbol=fund_code, date=str(year))
        except Exception:
            return []
        if holding_df.empty:
            return []

        holdings = []
        for _, row in holding_df.iterrows():
            asset_code = self._normalize_holding_asset_code(row["股票代码"])
            asset_type = self._infer_holding_asset_type(asset_code)
            holdings.append(
                {
                    "fund_code": fund_code,
                    "report_period": self._parse_report_period(str(row["季度"])),
                    "asset_code": asset_code,
                    "asset_name": str(row["股票名称"]).strip(),
                    "asset_type": asset_type,
                    "market": self._infer_holding_market(asset_code, asset_type),
                    "holding_ratio": self._percent(row["占净值比例"]),
                    "holding_value": self._optional_decimal(row.get("持仓市值")),
                    "source": self.source_name,
                }
            )
        return holdings

    def _bond_holdings(self, fund_code: str, year: int) -> list[dict]:
        try:
            holding_df = ak.fund_portfolio_bond_hold_em(symbol=fund_code, date=str(year))
        except Exception:
            return []
        if holding_df.empty:
            return []

        holdings = []
        for _, row in holding_df.iterrows():
            asset_code = self._normalize_holding_asset_code(row["债券代码"])
            holdings.append(
                {
                    "fund_code": fund_code,
                    "report_period": self._parse_report_period(str(row["季度"])),
                    "asset_code": asset_code,
                    "asset_name": str(row["债券名称"]).strip(),
                    "asset_type": "bond",
                    "market": "CN",
                    "holding_ratio": self._percent(row["占净值比例"]),
                    "holding_value": self._optional_decimal(row.get("持仓市值")),
                    "source": self.source_name,
                }
            )
        return holdings

    @timed()
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
        us_codes = {code for code in target_codes if self._is_us_stock_code(code)}

        fetch_groups = []
        if has_cn_stock:
            fetch_groups.append(
                ("CN", "stock", [self._get_cn_stock_spot_dataframe, self._get_cn_stock_spot_em_dataframe])
            )
        if has_hk:
            fetch_groups.append(
                ("HK", "stock", [self._get_hk_stock_spot_dataframe, self._get_hk_stock_spot_em_dataframe])
            )
        if has_etf:
            fetch_groups.append(("CN", "etf", [self._get_etf_spot_dataframe]))

        for market_name, asset_type, fetchers in fetch_groups:
            group_targets = {
                code
                for code in target_codes
                if (market_name == "HK" and len(code) == 5)
                or (asset_type == "etf" and len(code) == 6 and code.startswith(("5", "1")))
                or (market_name == "CN" and asset_type == "stock" and len(code) == 6 and not code.startswith(("5", "1")))
            }
            for source_index, fetcher in enumerate(fetchers):
                missing_targets = group_targets - set(snapshots)
                if not missing_targets:
                    break
                logging.getLogger("app.performance").info(
                    "akshare_source endpoint=%s market=%s fallback=%s missing=%s",
                    fetcher.__name__,
                    market_name,
                    source_index > 0,
                    len(missing_targets),
                )
                try:
                    market_df = fetcher()
                except Exception:
                    continue
                if market_df.empty:
                    continue
                parse_started = monotonic()
                matched_rows = self._rows_by_normalized_codes(
                    market_df,
                    missing_targets,
                    code_column="代码",
                    normalizer=lambda value: self._normalize_asset_code(value, market_name),
                )
                for normalized_code, row in matched_rows:
                    snapshots[normalized_code] = MarketQuoteSnapshot(
                        asset_code=normalized_code,
                        asset_name=self._none_if_nan(row.get("名称") or row.get("中文名称")),
                        asset_type=asset_type,
                        market=self._infer_stock_market(normalized_code) if asset_type == "stock" else market_name,
                        trade_date=self._quote_trade_date(row, quote_time),
                        quote_time=quote_time,
                        latest_price=self._optional_decimal(row.get("最新价")),
                        prev_close=self._optional_decimal(row.get("昨收")),
                        change_rate=self._percent(row.get("涨跌幅")),
                    )
                logging.getLogger("app.performance").info(
                    "akshare_parse endpoint=%s rows=%s target=%s matched=%s duration_ms=%.2f",
                    fetcher.__name__,
                    len(market_df),
                    len(missing_targets),
                    len(missing_targets & set(snapshots)),
                    (monotonic() - parse_started) * 1000,
                )

        for asset_code in us_codes:
            snapshot = self._get_us_daily_quote(asset_code, quote_time)
            if snapshot is not None:
                snapshots[asset_code] = snapshot

        missing_codes = target_codes - set(snapshots.keys())
        for asset_code in missing_codes:
            fallback = self._get_eastmoney_etf_quote(asset_code, quote_time)
            if fallback is None:
                fallback = self._get_sina_quote(asset_code, quote_time)
            if fallback is None:
                fallback = self._get_latest_history_quote(asset_code, quote_time)
            if fallback is not None:
                snapshots[asset_code] = fallback

        return list(snapshots.values())

    @classmethod
    def _get_etf_spot_dataframe(cls):
        return cls._load_dataframe(
            "fund_etf_spot_em",
            ak.fund_etf_spot_em,
            cls._realtime_cache_ttl_seconds,
            code_column="代码",
            normalizer=lambda value: cls._normalize_asset_code(value, "CN"),
            max_stale_age_seconds=cls._realtime_stale_cache_max_age_seconds,
        )

    @classmethod
    def _get_cn_stock_spot_dataframe(cls):
        return cls._load_dataframe(
            "stock_zh_a_spot",
            ak.stock_zh_a_spot,
            cls._realtime_cache_ttl_seconds,
            code_column="代码",
            normalizer=lambda value: cls._normalize_asset_code(value, "CN"),
            max_stale_age_seconds=cls._realtime_stale_cache_max_age_seconds,
        )

    @classmethod
    def _get_cn_stock_spot_em_dataframe(cls):
        return cls._load_dataframe(
            "stock_zh_a_spot_em",
            ak.stock_zh_a_spot_em,
            cls._realtime_cache_ttl_seconds,
            code_column="代码",
            normalizer=lambda value: cls._normalize_asset_code(value, "CN"),
            max_stale_age_seconds=cls._realtime_stale_cache_max_age_seconds,
        )

    @classmethod
    def _get_hk_stock_spot_dataframe(cls):
        return cls._load_dataframe(
            "stock_hk_spot",
            ak.stock_hk_spot,
            cls._realtime_cache_ttl_seconds,
            code_column="代码",
            normalizer=lambda value: cls._normalize_asset_code(value, "HK"),
            max_stale_age_seconds=cls._realtime_stale_cache_max_age_seconds,
        )

    @classmethod
    def _get_hk_stock_spot_em_dataframe(cls):
        return cls._load_dataframe(
            "stock_hk_spot_em",
            ak.stock_hk_spot_em,
            cls._realtime_cache_ttl_seconds,
            code_column="代码",
            normalizer=lambda value: cls._normalize_asset_code(value, "HK"),
            max_stale_age_seconds=cls._realtime_stale_cache_max_age_seconds,
        )

    @classmethod
    def _load_dataframe(
        cls,
        endpoint: str,
        fetcher,
        ttl_seconds: int,
        *,
        code_column: str | None = None,
        normalizer=None,
        max_stale_age_seconds: int | None = None,
    ):
        cached = cls._fresh_cache(endpoint, ttl_seconds)
        if cached is not None:
            return cached
        lock = cls._cache_lock(endpoint)
        wait_started = monotonic()
        if not lock.acquire(timeout=cls._cache_wait_timeout_seconds):
            logging.getLogger("app.performance").error(
                "akshare_lock endpoint=%s status=timeout wait_ms=%.2f",
                endpoint,
                (monotonic() - wait_started) * 1000,
            )
            raise TimeoutError(f"Timed out waiting for AkShare endpoint lock: {endpoint}")
        try:
            logging.getLogger("app.performance").info(
                "akshare_lock endpoint=%s status=acquired wait_ms=%.2f",
                endpoint,
                (monotonic() - wait_started) * 1000,
            )
            cached = cls._fresh_cache(endpoint, ttl_seconds)
            if cached is not None:
                return cached
            started = monotonic()
            try:
                dataframe = fetcher()
            except Exception:
                logging.getLogger("app.performance").exception(
                    "akshare_fetch endpoint=%s status=failed duration_ms=%.2f",
                    endpoint,
                    (monotonic() - started) * 1000,
                )
                stale = cls._stale_cache(endpoint)
                if stale is not None:
                    value, loaded_at = stale
                    age = monotonic() - loaded_at
                    if max_stale_age_seconds is not None and age > max_stale_age_seconds:
                        logging.getLogger("app.performance").warning(
                            "akshare_cache endpoint=%s status=stale_rejected age_seconds=%.2f max_age_seconds=%s",
                            endpoint,
                            age,
                            max_stale_age_seconds,
                        )
                        raise
                    logging.getLogger("app.performance").warning(
                        "akshare_cache endpoint=%s status=stale_fallback age_seconds=%.2f",
                        endpoint,
                        age,
                    )
                    return value
                raise
            dataframe = cls._indexed_dataframe(dataframe, code_column=code_column, normalizer=normalizer)
            cls._dataframe_cache[endpoint] = (dataframe, monotonic())
            logging.getLogger("app.performance").info(
                "akshare_fetch endpoint=%s status=success rows=%s duration_ms=%.2f",
                endpoint,
                len(dataframe),
                (monotonic() - started) * 1000,
            )
            return dataframe
        finally:
            lock.release()

    @classmethod
    def _fresh_cache(cls, endpoint: str, ttl_seconds: int):
        cached = cls._stale_cache(endpoint)
        if cached is None:
            logging.getLogger("app.performance").info("akshare_cache endpoint=%s status=miss", endpoint)
            return None
        dataframe, loaded_at = cached
        age = monotonic() - loaded_at
        if age >= ttl_seconds:
            logging.getLogger("app.performance").info(
                "akshare_cache endpoint=%s status=expired age_seconds=%.2f", endpoint, age
            )
            return None
        logging.getLogger("app.performance").info(
            "akshare_cache endpoint=%s status=hit age_seconds=%.2f", endpoint, age
        )
        return dataframe

    @classmethod
    def _stale_cache(cls, endpoint: str):
        return cls._dataframe_cache.get(endpoint)

    @classmethod
    def _cache_lock(cls, endpoint: str) -> Lock:
        with cls._cache_locks_guard:
            return cls._cache_locks.setdefault(endpoint, Lock())

    @classmethod
    def _indexed_dataframe(cls, dataframe, *, code_column: str | None, normalizer):
        if code_column is None or normalizer is None or code_column not in dataframe.columns:
            return dataframe
        indexed = dataframe.copy()
        indexed[cls._normalized_code_column] = indexed[code_column].map(normalizer)
        return indexed.set_index(cls._normalized_code_column, drop=False)

    @classmethod
    def _first_row_by_normalized_code(cls, dataframe, normalized_code: str, *, code_column: str, normalizer):
        rows = cls._rows_by_normalized_codes(
            dataframe,
            {normalized_code},
            code_column=code_column,
            normalizer=normalizer,
        )
        return rows[0][1] if rows else None

    @classmethod
    def _rows_by_normalized_codes(cls, dataframe, normalized_codes: set[str], *, code_column: str, normalizer):
        if not normalized_codes or dataframe.empty:
            return []
        if cls._normalized_code_column in dataframe.columns:
            if dataframe.index.name == cls._normalized_code_column:
                rows = []
                for normalized_code in normalized_codes:
                    try:
                        selected = dataframe.loc[normalized_code]
                    except KeyError:
                        continue
                    if hasattr(selected, "to_frame"):
                        rows.append((normalized_code, selected))
                    else:
                        for _, row in selected.iterrows():
                            rows.append((normalized_code, row))
                return rows
            matched = dataframe[dataframe[cls._normalized_code_column].isin(normalized_codes)]
            return [(row[cls._normalized_code_column], row) for _, row in matched.iterrows()]

        if code_column not in dataframe.columns:
            return []
        matched_rows = []
        for _, row in dataframe.iterrows():
            normalized_code = normalizer(row[code_column])
            if normalized_code in normalized_codes:
                matched_rows.append((normalized_code, row))
        return matched_rows

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
    def _previous_business_day(value: date) -> date:
        previous = value - timedelta(days=1)
        while previous.weekday() >= 5:
            previous -= timedelta(days=1)
        return previous

    @classmethod
    def _extract_latest_nav_date_for_row(cls, row, columns: list[str]) -> date | None:
        candidates: list[date] = []
        for column in columns:
            match = re.match(r"^(\d{4}-\d{2}-\d{2})-单位净值$", column)
            if not match:
                continue
            if cls._none_if_nan(row.get(column)) is not None:
                candidates.append(date.fromisoformat(match.group(1)))
        if not candidates:
            return None
        return max(candidates)

    @staticmethod
    def _none_if_nan(value) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if text == "" or text in {"-", "--", "—"} or text.lower() == "nan":
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
        if AkshareSource._is_us_stock_code(asset_code):
            return "US"
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
    def _infer_holding_asset_type(asset_code: str) -> str:
        if len(asset_code) == 6 and asset_code.startswith(("5", "1")):
            return "etf"
        return "stock"

    @staticmethod
    def _infer_holding_market(asset_code: str, asset_type: str) -> str | None:
        if asset_type == "etf":
            return "CN"
        return AkshareSource._infer_stock_market(asset_code)

    @staticmethod
    def _normalize_asset_code(asset_code: str, market: str | None = None) -> str:
        code = str(asset_code).strip()
        code = re.sub(r"^(sh|sz|bj|hk)", "", code, flags=re.IGNORECASE)
        if market == "HK" or (code.isdigit() and len(code) == 5):
            return code.zfill(5)
        if code.isdigit() and len(code) < 6:
            return code.zfill(6)
        return code

    @staticmethod
    def _normalize_holding_asset_code(asset_code) -> str:
        code = str(asset_code).strip().upper()
        if re.search(r"[A-Z]", code):
            return re.sub(r"^0+", "", code)
        return code.zfill(5 if len(code) == 5 else 6)

    @staticmethod
    def _is_us_stock_code(asset_code: str) -> bool:
        return bool(re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", asset_code.upper()))

    def _get_us_daily_quote(
        self, asset_code: str, quote_time: datetime
    ) -> MarketQuoteSnapshot | None:
        try:
            history_df = ak.stock_us_daily(symbol=asset_code, adjust="")
        except Exception:
            return None

        if history_df.empty or len(history_df) < 1:
            return None

        row = history_df.iloc[-1]
        previous_row = history_df.iloc[-2] if len(history_df) >= 2 else None

        latest_price = self._optional_decimal(row.get("close"))
        prev_close = self._optional_decimal(previous_row.get("close")) if previous_row is not None else None
        change_rate = None
        if latest_price is not None and prev_close not in (None, Decimal("0")):
            change_rate = (latest_price - prev_close) / prev_close

        trade_date_value = row.get("date")
        if hasattr(trade_date_value, "date"):
            trade_date = trade_date_value.date()
        else:
            trade_date = date.fromisoformat(str(trade_date_value).split(" ")[0])

        return MarketQuoteSnapshot(
            asset_code=asset_code,
            asset_name=None,
            asset_type="stock",
            market="US",
            trade_date=trade_date,
            quote_time=datetime.combine(trade_date, datetime.min.time()),
            latest_price=latest_price,
            prev_close=prev_close,
            change_rate=change_rate,
        )

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
                timeout=60,
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

    def _get_eastmoney_etf_quote(
        self, asset_code: str, quote_time: datetime
    ) -> MarketQuoteSnapshot | None:
        if not (asset_code.isdigit() and len(asset_code) == 6 and asset_code.startswith(("5", "1"))):
            return None
        market_id = "1" if asset_code.startswith("5") else "0"
        try:
            response = requests.get(
                "https://push2.eastmoney.com/api/qt/stock/get",
                params={
                    "secid": f"{market_id}.{asset_code}",
                    "fields": "f43,f58,f60,f86,f170",
                },
                headers={
                    "Referer": "https://quote.eastmoney.com/",
                    "User-Agent": "Mozilla/5.0",
                },
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            logging.getLogger("app.performance").exception(
                "fallback_quote source=eastmoney_etf asset_code=%s status=failed",
                asset_code,
            )
            return None

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return None

        latest_price = self._eastmoney_price(data.get("f43"))
        prev_close = self._eastmoney_price(data.get("f60"))
        change_rate = self._eastmoney_change_rate(data.get("f170"))
        if latest_price is None and change_rate is None:
            return None

        quote_datetime = quote_time
        raw_time = data.get("f86")
        try:
            if raw_time not in (None, "-", ""):
                quote_datetime = datetime.fromtimestamp(int(raw_time))
        except (ValueError, OSError, OverflowError):
            pass

        logging.getLogger("app.performance").info(
            "fallback_quote source=eastmoney_etf asset_code=%s status=success",
            asset_code,
        )
        return MarketQuoteSnapshot(
            asset_code=asset_code,
            asset_name=self._none_if_nan(data.get("f58")),
            asset_type="etf",
            market="CN",
            trade_date=quote_datetime.date(),
            quote_time=quote_datetime,
            latest_price=latest_price,
            prev_close=prev_close,
            change_rate=change_rate,
        )

    @classmethod
    def _eastmoney_price(cls, value) -> Decimal | None:
        try:
            decimal_value = cls._optional_decimal(value)
        except ValueError:
            return None
        if decimal_value is None:
            return None
        return decimal_value / Decimal("1000")

    @classmethod
    def _eastmoney_change_rate(cls, value) -> Decimal | None:
        try:
            decimal_value = cls._optional_decimal(value)
        except ValueError:
            return None
        if decimal_value is None:
            return None
        return decimal_value / Decimal("10000")

    @staticmethod
    def _sina_asset_code(asset_code: str) -> str | None:
        if len(asset_code) == 5:
            return f"hk{asset_code}"
        if AkshareSource._is_us_stock_code(asset_code):
            return None
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
        raw_date = row.get("数据日期")
        if raw_date is not None:
            try:
                if hasattr(raw_date, "date"):
                    return raw_date.date()
                return date.fromisoformat(str(raw_date).split(" ")[0])
            except ValueError:
                pass

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
