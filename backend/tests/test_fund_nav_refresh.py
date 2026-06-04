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
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.modules.fund_nav.data_sources.akshare_source import AkshareSource, FundNavSnapshot
from app.modules.fund_nav.data_sources.eastmoney_source import EastmoneySource
from app.database import Base
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.schemas.fund import FundCreate
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

    def test_delete_fund_soft_deletes_and_create_restores_existing_row(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)
        service = FundService(db, source)

        try:
            created = Fund(id=1, fund_code="000001", fund_name="000001", remark="first")
            db.add(created)
            db.commit()
            self.assertTrue(service.delete_fund("000001"))
            self.assertIsNone(db.scalar(select(Fund).where(Fund.fund_code == "000001")))

            restored = service.create_fund(FundCreate(fund_code="000001", remark="restored"))
        finally:
            db.close()

        self.assertEqual(restored.id, created.id)
        self.assertEqual(restored.is_deleted, 0)
        self.assertEqual(restored.remark, "restored")

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

    def test_etf_holding_quote_uses_etf_realtime_source(self) -> None:
        etf_df = pd.DataFrame(
            [{"代码": "159915", "名称": "创业板ETF", "最新价": "1.234", "昨收": "1.200", "涨跌幅": "2.83"}]
        )

        with (
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_etf_spot_em", return_value=etf_df) as etf,
            patch.object(AkshareSource, "_get_sina_quote", return_value=None),
            patch.object(AkshareSource, "_get_latest_history_quote", return_value=None),
        ):
            snapshots = AkshareSource().get_market_quotes(["159915"])

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].asset_code, "159915")
        self.assertEqual(snapshots[0].asset_type, "etf")
        self.assertEqual(snapshots[0].market, "CN")
        self.assertEqual(snapshots[0].change_rate, Decimal("0.0283"))
        etf.assert_called_once()

    def test_etf_quote_falls_back_to_eastmoney_single_quote_when_spot_table_fails(self) -> None:
        response = Mock()
        response.json.return_value = {
            "data": {
                "f43": 1490,
                "f58": "电力ETF华泰柏瑞",
                "f60": 1513,
                "f86": 1780560711,
                "f170": -152,
            }
        }
        response.raise_for_status.return_value = None

        with (
            patch(
                "app.modules.fund_nav.data_sources.akshare_source.ak.fund_etf_spot_em",
                side_effect=RuntimeError("remote disconnected"),
            ),
            patch("app.modules.fund_nav.data_sources.akshare_source.requests.get", return_value=response),
            patch.object(AkshareSource, "_get_sina_quote", return_value=None),
            patch.object(AkshareSource, "_get_latest_history_quote", return_value=None),
        ):
            snapshots = AkshareSource().get_market_quotes(["561560"])

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].asset_code, "561560")
        self.assertEqual(snapshots[0].asset_name, "电力ETF华泰柏瑞")
        self.assertEqual(snapshots[0].asset_type, "etf")
        self.assertEqual(snapshots[0].latest_price, Decimal("1.49"))
        self.assertEqual(snapshots[0].prev_close, Decimal("1.513"))
        self.assertEqual(snapshots[0].change_rate, Decimal("-0.0152"))

    def test_akshare_holdings_mark_etf_assets(self) -> None:
        holding_df = pd.DataFrame(
            [
                {
                    "股票代码": "159915",
                    "股票名称": "创业板ETF",
                    "占净值比例": "85.00",
                    "持仓市值": "1000",
                    "季度": "2026年2季度股票投资明细",
                }
            ]
        )

        with patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_portfolio_hold_em", return_value=holding_df):
            holdings = AkshareSource().get_fund_holdings("018172")

        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0]["asset_code"], "159915")
        self.assertEqual(holdings[0]["asset_type"], "etf")
        self.assertEqual(holdings[0]["market"], "CN")
        self.assertEqual(holdings[0]["holding_ratio"], Decimal("0.85"))

    def test_eastmoney_target_hint_ignores_footer_code_and_page_title(self) -> None:
        html_text = (
            "沪ICP备11042629号-1 沪B2-20130026 网站备案号 "
            "华泰柏瑞中证电力全指ETF发起式联接A(018172)基金资产配置"
        )

        with patch.object(EastmoneySource, "_fetch_pages_text", return_value=html_text):
            holdings = EastmoneySource().get_target_fund_holdings("018172")

        self.assertEqual(holdings, [])

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
