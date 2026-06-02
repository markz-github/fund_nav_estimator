from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.modules.fund_nav.data_sources.akshare_source import AkshareSource, FundNavSnapshot
from app.database import Base
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.services.fund_service import FundService
from app.modules.fund_nav.services.holding_service import HoldingService


class FundNavRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        AkshareSource._dataframe_cache.clear()
        AkshareSource._cache_locks.clear()

    def test_refresh_nav_returns_today_open_fund_local_nav_without_external_fetch(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)

        db.add(
            FundNav(
                id=1,
                fund_code="515450",
                nav_date=date.today(),
                unit_nav=Decimal("1.2345"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0.0123"),
                source="akshare",
            )
        )
        db.commit()

        try:
            nav = FundService(db, source).refresh_nav("515450")
        finally:
            db.close()

        self.assertIsNotNone(nav)
        self.assertEqual(nav.fund_code, "515450")
        source.get_latest_fund_nav.assert_not_called()

    def test_refresh_nav_replaces_legacy_today_etf_spot_cache(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)
        source.get_latest_fund_nav.return_value = FundNavSnapshot(
            fund_code="515450",
            nav_date=FundService._previous_business_day(date.today()),
            unit_nav=Decimal("1.111"),
            accumulated_nav=None,
            daily_growth_rate=Decimal("0.0123"),
            source="akshare:etf_spot_prev_close",
        )

        db.add(
            FundNav(
                id=1,
                fund_code="515450",
                nav_date=date.today(),
                unit_nav=Decimal("1.2345"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0.0123"),
                source="akshare:etf_spot",
            )
        )
        db.commit()

        try:
            nav = FundService(db, source).refresh_nav("515450")
        finally:
            db.close()

        self.assertIsNotNone(nav)
        self.assertEqual(nav.source, "akshare:etf_spot_prev_close")
        self.assertEqual(nav.unit_nav, Decimal("1.111"))
        source.get_latest_fund_nav.assert_called_once_with("515450")

    def test_refresh_nav_falls_back_to_local_nav_when_source_returns_none(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)
        source.get_latest_fund_nav.return_value = None

        db.add(
            FundNav(
                id=1,
                fund_code="515450",
                nav_date=date.today(),
                unit_nav=Decimal("1.2345"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0.0123"),
                source="akshare:etf_spot",
            )
        )
        db.commit()

        try:
            nav = FundService(db, source).refresh_nav("515450")
        finally:
            db.close()

        self.assertIsNotNone(nav)
        self.assertEqual(nav.source, "akshare:etf_spot")
        self.assertEqual(nav.unit_nav, Decimal("1.2345"))
        source.get_latest_fund_nav.assert_called_once_with("515450")

    def test_refresh_nav_refetches_fresh_local_nav_without_growth_rate(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)
        source.get_latest_fund_nav.return_value = FundNavSnapshot(
            fund_code="000001",
            nav_date=date.today(),
            unit_nav=Decimal("1.2000"),
            accumulated_nav=Decimal("3.0000"),
            daily_growth_rate=Decimal("-0.0095"),
            source="akshare",
        )

        db.add(
            FundNav(
                id=1,
                fund_code="000001",
                nav_date=date.today(),
                unit_nav=Decimal("1.2000"),
                accumulated_nav=Decimal("3.0000"),
                daily_growth_rate=None,
                source="akshare",
            )
        )
        db.commit()

        try:
            nav = FundService(db, source).refresh_nav("000001")
        finally:
            db.close()

        self.assertIsNotNone(nav)
        self.assertEqual(nav.daily_growth_rate, Decimal("-0.0095"))
        source.get_latest_fund_nav.assert_called_once_with("000001")

    def test_five_prefix_etf_uses_etf_source_before_open_fund_daily_table(self) -> None:
        etf_df = pd.DataFrame(
            [
                {
                    "代码": "515450",
                    "昨收": "1.098",
                    "IOPV实时估值": "1.111",
                    "最新价": "1.110",
                    "数据日期": "2026-04-28",
                    "涨跌幅": "0.25",
                }
            ]
        )

        with (
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_etf_spot_em", return_value=etf_df),
            patch(
                "app.modules.fund_nav.data_sources.akshare_source.ak.fund_open_fund_daily_em",
                side_effect=AssertionError("open fund daily table should not be loaded for 5-prefix ETFs"),
            ),
        ):
            snapshot = AkshareSource().get_latest_fund_nav("515450")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.source, "akshare:etf_spot_prev_close")
        self.assertEqual(snapshot.unit_nav, Decimal("1.098"))
        self.assertEqual(snapshot.nav_date, date(2026, 4, 27))

    def test_open_fund_daily_table_is_cached_for_repeated_refreshes(self) -> None:
        daily_df = pd.DataFrame(
            [
                {
                    "基金代码": "000001",
                    "2026-04-27-单位净值": "1.001",
                    "2026-04-27-累计净值": "2.001",
                    "日增长率": "0.10",
                },
                {
                    "基金代码": "000002",
                    "2026-04-27-单位净值": "1.002",
                    "2026-04-27-累计净值": "2.002",
                    "日增长率": "0.20",
                },
            ]
        )

        with patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_open_fund_daily_em", return_value=daily_df) as daily:
            source = AkshareSource()
            first = source.get_latest_fund_nav("000001")
            second = source.get_latest_fund_nav("000002")

        self.assertIsInstance(first, FundNavSnapshot)
        self.assertIsInstance(second, FundNavSnapshot)
        self.assertEqual(daily.call_count, 1)

    def test_etf_spot_table_is_cached_for_repeated_refreshes(self) -> None:
        etf_df = pd.DataFrame([{"代码": "515450", "昨收": "1.098", "涨跌幅": "0.25"}])

        with patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_etf_spot_em", return_value=etf_df) as etf:
            source = AkshareSource()
            source.get_latest_fund_nav("515450")
            source.get_latest_fund_nav("515450")

        self.assertEqual(etf.call_count, 1)

    def test_two_cache_misses_only_fetch_akshare_once(self) -> None:
        etf_df = pd.DataFrame([{"代码": "515450", "昨收": "1.098", "涨跌幅": "0.25"}])

        def slow_fetch():
            sleep(0.05)
            return etf_df

        with patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_etf_spot_em", side_effect=slow_fetch) as etf:
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: AkshareSource._get_etf_spot_dataframe(), range(2)))

        self.assertEqual(etf.call_count, 1)
        self.assertIs(results[0], results[1])

    def test_expired_cache_falls_back_to_stale_dataframe_when_refresh_fails(self) -> None:
        etf_df = pd.DataFrame([{"代码": "515450", "昨收": "1.098", "涨跌幅": "0.25"}])
        AkshareSource._dataframe_cache["fund_etf_spot_em"] = (
            etf_df,
            monotonic() - AkshareSource._realtime_cache_ttl_seconds - 1,
        )

        with patch(
            "app.modules.fund_nav.data_sources.akshare_source.ak.fund_etf_spot_em",
            side_effect=RuntimeError("network down"),
        ):
            result = AkshareSource._get_etf_spot_dataframe()

        self.assertIs(result, etf_df)

    def test_cn_primary_spot_source_skips_backup_when_target_is_covered(self) -> None:
        primary_df = pd.DataFrame(
            [{"代码": "600000", "名称": "浦发银行", "最新价": "10", "昨收": "9", "涨跌幅": "1"}]
        )

        with (
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.stock_zh_a_spot", return_value=primary_df),
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.stock_zh_a_spot_em") as backup,
            patch.object(AkshareSource, "_get_sina_quote", return_value=None),
            patch.object(AkshareSource, "_get_latest_history_quote", return_value=None),
        ):
            snapshots = AkshareSource().get_market_quotes(["600000"])

        self.assertEqual([snapshot.asset_code for snapshot in snapshots], ["600000"])
        cached, _ = AkshareSource._dataframe_cache["stock_zh_a_spot"]
        self.assertIn("_normalized_code", cached.columns)
        self.assertEqual(cached.index.name, "_normalized_code")
        backup.assert_not_called()

    def test_holdings_are_deduplicated_by_unique_key_before_insert(self) -> None:
        snapshots = [
            {
                "fund_code": "018172",
                "report_period": "2026Q2",
                "asset_code": "130026",
                "asset_name": "资产A",
                "asset_type": "stock",
                "market": "SZ",
                "holding_ratio": Decimal("0.10"),
                "holding_value": Decimal("100"),
                "source": "akshare",
            },
            {
                "fund_code": "018172",
                "report_period": "2026Q2",
                "asset_code": "130026",
                "asset_name": "资产A",
                "asset_type": "stock",
                "market": "SZ",
                "holding_ratio": Decimal("0.20"),
                "holding_value": Decimal("200"),
                "source": "akshare",
            },
        ]

        deduplicated = HoldingService._deduplicate_snapshots(snapshots)

        self.assertEqual(len(deduplicated), 1)
        self.assertEqual(deduplicated[0]["holding_ratio"], Decimal("0.30"))
        self.assertEqual(deduplicated[0]["holding_value"], Decimal("300"))


if __name__ == "__main__":
    unittest.main()
