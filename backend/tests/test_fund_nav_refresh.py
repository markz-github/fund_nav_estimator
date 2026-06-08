from __future__ import annotations

from datetime import date, datetime
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

from app.modules.fund_nav.data_sources.akshare_source import AkshareSource, EtfIopvSnapshot, FundNavSnapshot
from app.modules.fund_nav.data_sources.eastmoney_source import EastmoneySource
from app.database import Base
from app.modules.fund_nav.models.asset_valuation_config import AssetValuationConfig
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.models.market_quote import MarketQuote
from app.modules.fund_nav.report_period import latest_completed_quarter_period
from app.modules.fund_nav.schemas.fund import FundCreate
from app.modules.fund_nav.services.fund_service import FundService
from app.modules.fund_nav.services.holding_service import HoldingService
from app.modules.fund_nav.services.estimate_service import EstimateService
from app.modules.fund_nav.services.market_service import MarketService
from app.modules.fund_nav.services.asset_valuation_config_service import load_asset_valuation_config_map


class FundNavRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        AkshareSource._dataframe_cache.clear()
        AkshareSource._cache_locks.clear()

    def test_latest_completed_quarter_period_does_not_use_unfinished_quarter(self) -> None:
        self.assertEqual(latest_completed_quarter_period(date(2026, 6, 5)), "2026Q1")
        self.assertEqual(latest_completed_quarter_period(date(2026, 1, 5)), "2025Q4")

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

    def test_list_funds_includes_latest_estimate_date(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        db.add(Fund(id=1, fund_code="000001", fund_name="测试基金"))
        db.add(
            FundNav(
                id=1,
                fund_code="000001",
                nav_date=date(2026, 6, 5),
                unit_nav=Decimal("1.0000"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0.0100"),
                source="test",
            )
        )
        db.add(
            FundEstimate(
                id=1,
                fund_code="000001",
                estimate_date=date(2026, 6, 8),
                estimate_time=datetime(2026, 6, 8, 14, 30),
                base_nav_date=date(2026, 6, 5),
                base_unit_nav=Decimal("1.0000"),
                estimated_growth_rate=Decimal("0.0123"),
                estimated_nav=Decimal("1.0123"),
                coverage_ratio=Decimal("0.9000"),
                source_snapshot="test",
            )
        )
        db.commit()

        try:
            funds = FundService(db).list_funds()
        finally:
            db.close()

        self.assertEqual(funds[0]["latest_estimate_date"], date(2026, 6, 8))

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

    def test_refresh_nav_replaces_etf_prev_close_with_official_page_nav(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)
        source.get_latest_fund_nav.return_value = FundNavSnapshot(
            fund_code="561560",
            nav_date=date(2026, 6, 4),
            unit_nav=Decimal("1.4908"),
            accumulated_nav=Decimal("1.4908"),
            daily_growth_rate=Decimal("-0.0144"),
            source="akshare:eastmoney_fund_page",
        )
        db.add(
            FundNav(
                id=1,
                fund_code="561560",
                nav_date=date(2026, 6, 4),
                unit_nav=Decimal("1.5130"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("-0.0152"),
                source="akshare:etf_spot_prev_close",
            )
        )
        db.commit()

        try:
            nav = FundService(db, source).refresh_nav("561560")
        finally:
            db.close()

        self.assertIsNotNone(nav)
        self.assertEqual(nav.unit_nav, Decimal("1.4908"))
        self.assertEqual(nav.source, "akshare:eastmoney_fund_page")

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

    def test_refresh_nav_calculates_growth_rate_when_source_missing_growth(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)
        source.get_latest_fund_nav.return_value = FundNavSnapshot(
            fund_code="017436",
            nav_date=date(2026, 6, 4),
            unit_nav=Decimal("2.5059"),
            accumulated_nav=Decimal("2.5059"),
            daily_growth_rate=None,
            source="akshare",
        )

        db.add_all(
            [
                FundNav(
                    id=1,
                    fund_code="017436",
                    nav_date=date(2026, 6, 3),
                    unit_nav=Decimal("2.5043"),
                    accumulated_nav=Decimal("2.5043"),
                    daily_growth_rate=Decimal("-0.0086"),
                    source="akshare:eastmoney_fund_page",
                ),
                FundNav(
                    id=2,
                    fund_code="017436",
                    nav_date=date(2026, 6, 4),
                    unit_nav=Decimal("2.5059"),
                    accumulated_nav=Decimal("2.5059"),
                    daily_growth_rate=None,
                    source="akshare",
                ),
            ]
        )
        db.commit()

        try:
            nav = FundService(db, source).refresh_nav("017436")
        finally:
            db.close()

        self.assertIsNotNone(nav)
        self.assertEqual(nav.nav_date, date(2026, 6, 4))
        self.assertEqual(nav.daily_growth_rate, Decimal("0.000639"))

    def test_get_fund_nav_history_parses_open_fund_info_rows(self) -> None:
        dataframe = pd.DataFrame(
            [
                {"净值日期": "2026-06-04", "单位净值": "1.2345", "累计净值": "1.4567", "日增长率": "1.23"},
                {"净值日期": "2026-06-03", "单位净值": "1.2195", "累计净值": "1.4417", "日增长率": "-0.10"},
            ]
        )

        with patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_open_fund_info_em", return_value=dataframe) as fetcher:
            snapshots = AkshareSource().get_fund_nav_history("18125")

        fetcher.assert_called_once_with(symbol="018125", indicator="单位净值走势", period="成立来")
        self.assertEqual([snapshot.nav_date for snapshot in snapshots], [date(2026, 6, 3), date(2026, 6, 4)])
        self.assertEqual(snapshots[-1].unit_nav, Decimal("1.2345"))
        self.assertEqual(snapshots[-1].daily_growth_rate, Decimal("0.0123"))
        self.assertEqual(snapshots[-1].source, "akshare:fund_open_fund_info_em")

    def test_refresh_nav_history_upserts_rows_into_fund_navs(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)
        source.get_fund_nav_history.return_value = [
            FundNavSnapshot(
                fund_code="018125",
                nav_date=date(2026, 6, 3),
                unit_nav=Decimal("1.0000"),
                accumulated_nav=Decimal("1.1000"),
                daily_growth_rate=Decimal("0.0010"),
                source="akshare:fund_open_fund_info_em",
            ),
            FundNavSnapshot(
                fund_code="018125",
                nav_date=date(2026, 6, 4),
                unit_nav=Decimal("1.0100"),
                accumulated_nav=Decimal("1.1100"),
                daily_growth_rate=Decimal("0.0100"),
                source="akshare:fund_open_fund_info_em",
            ),
        ]

        try:
            navs = FundService(db, source).refresh_nav_history("18125")
            history = FundService(db, source).list_nav_history("018125")
        finally:
            db.close()

        self.assertEqual(len(navs), 2)
        self.assertEqual([item.nav_date for item in history], [date(2026, 6, 3), date(2026, 6, 4)])
        self.assertEqual(history[-1].unit_nav, Decimal("1.010000"))

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

    def test_etf_estimate_uses_iopv_strategy_without_holdings(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source.get_etf_iopv_snapshot.return_value = EtfIopvSnapshot(
            fund_code="561560",
            asset_name="电力ETF华泰柏瑞",
            estimate_time=datetime(2026, 6, 5, 10, 30),
            estimated_nav=Decimal("1.4638"),
            latest_price=Decimal("1.4600"),
            change_rate=Decimal("-0.0181"),
        )
        db.add(Fund(id=1, fund_code="561560", fund_name="电力ETF华泰柏瑞", fund_type="指数型-股票"))
        db.add(
            FundNav(
                id=1,
                fund_code="561560",
                nav_date=date(2026, 6, 4),
                unit_nav=Decimal("1.4908"),
                accumulated_nav=Decimal("1.4908"),
                daily_growth_rate=Decimal("-0.0144"),
                source="akshare:eastmoney_fund_page",
            )
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "561560"))
            service = EstimateService(db, source)
            result = service._estimate_one(fund, datetime(2026, 6, 5, 10, 30))
        finally:
            db.close()

        self.assertTrue(EstimateService.is_exchange_traded_fund(fund))
        self.assertEqual(result.estimated_nav, Decimal("1.4638"))
        self.assertEqual(result.base_unit_nav, Decimal("1.4908"))
        self.assertEqual(result.estimated_growth_rate.quantize(Decimal("0.0001")), Decimal("-0.0181"))
        self.assertEqual(result.coverage_ratio, Decimal("1"))
        self.assertIn("strategy=etf_iopv", result.source_snapshot)

    def test_etf_estimate_uses_local_quote_before_iopv(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source.get_etf_iopv_snapshot.return_value = EtfIopvSnapshot(
            fund_code="561560",
            asset_name="电力ETF华泰柏瑞",
            estimate_time=datetime(2026, 6, 5, 12, 56),
            estimated_nav=Decimal("1.4700"),
            latest_price=Decimal("1.4690"),
            change_rate=Decimal("-0.0140"),
        )
        db.add(Fund(id=1, fund_code="561560", fund_name="电力ETF华泰柏瑞", fund_type="指数型-股票"))
        db.add(
            FundNav(
                id=1,
                fund_code="561560",
                nav_date=date(2026, 6, 4),
                unit_nav=Decimal("1.4908"),
                accumulated_nav=Decimal("1.4908"),
                daily_growth_rate=Decimal("-0.0144"),
                source="akshare:eastmoney_fund_page",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="561560",
                asset_name="电力ETF华泰柏瑞",
                asset_type="etf",
                market="CN",
                trade_date=date(2026, 6, 5),
                quote_time=datetime(2026, 6, 5, 11, 30),
                latest_price=Decimal("1.4630"),
                prev_close=Decimal("1.4900"),
                change_rate=Decimal("-0.018121"),
                source="akshare",
            )
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "561560"))
            result = EstimateService(db, source)._estimate_one(fund, datetime(2026, 6, 5, 12, 56))
        finally:
            db.close()

        self.assertEqual(result.estimated_nav, Decimal("1.4630"))
        self.assertEqual(result.estimated_growth_rate, Decimal("-0.018121"))
        self.assertIn("strategy=etf_quote", result.source_snapshot)
        source.get_etf_iopv_snapshot.assert_not_called()

    def test_asset_valuation_config_map_uses_exact_and_default_rules(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add_all(
            [
                AssetValuationConfig(
                    id=1,
                    asset_type="stock",
                    market="SZ",
                    realtime_valuable=1,
                    valuation_mode="quote",
                    enabled=1,
                ),
                AssetValuationConfig(
                    id=2,
                    asset_type="bond",
                    market="*",
                    realtime_valuable=0,
                    valuation_mode="none",
                    enabled=1,
                ),
            ]
        )
        db.commit()

        try:
            config_map = load_asset_valuation_config_map(db)
        finally:
            db.close()

        self.assertTrue(config_map.resolve("stock", "SZ").realtime_valuable)
        self.assertEqual(config_map.resolve("stock", "SZ").valuation_mode, "quote")
        self.assertFalse(config_map.resolve("bond", "CN").realtime_valuable)
        self.assertEqual(config_map.resolve("bond", "CN").valuation_mode, "none")
        self.assertFalse(config_map.resolve("cash", "CN").realtime_valuable)

    def test_refresh_quotes_for_holdings_skips_non_realtime_bonds(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add_all(
            [
                FundHolding(
                    id=1,
                    fund_code="018125",
                    report_period="2026Q1",
                    asset_code="000001",
                    asset_name="平安银行",
                    asset_type="stock",
                    market="SZ",
                    holding_ratio=Decimal("0.500000"),
                    holding_value=None,
                    source="test",
                ),
                FundHolding(
                    id=2,
                    fund_code="018125",
                    report_period="2026Q1",
                    asset_code="019785",
                    asset_name="25国债13",
                    asset_type="bond",
                    market="CN",
                    holding_ratio=Decimal("0.500000"),
                    holding_value=None,
                    source="test",
                ),
            ]
        )
        db.commit()
        source = Mock()
        source.get_market_quotes.return_value = []

        try:
            MarketService(db, source).refresh_quotes_for_holdings(["018125"])
        finally:
            db.close()

        source.get_market_quotes.assert_called_once_with(["000001"])

    def test_bond_holdings_do_not_participate_in_estimate_but_reduce_coverage(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(Fund(id=1, fund_code="018125", fund_name="永赢先进制造智选混合发起C"))
        db.add(
            FundNav(
                id=1,
                fund_code="018125",
                nav_date=date(2026, 6, 5),
                unit_nav=Decimal("1.0000"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0"),
                source="test",
            )
        )
        db.add_all(
            [
                FundHolding(
                    id=1,
                    fund_code="018125",
                    report_period="2026Q1",
                    asset_code="000001",
                    asset_name="平安银行",
                    asset_type="stock",
                    market="SZ",
                    holding_ratio=Decimal("0.500000"),
                    holding_value=None,
                    source="test",
                ),
                FundHolding(
                    id=2,
                    fund_code="018125",
                    report_period="2026Q1",
                    asset_code="019785",
                    asset_name="25国债13",
                    asset_type="bond",
                    market="CN",
                    holding_ratio=Decimal("0.500000"),
                    holding_value=None,
                    source="test",
                ),
            ]
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="000001",
                asset_name="平安银行",
                asset_type="stock",
                market="SZ",
                trade_date=date(2026, 6, 8),
                quote_time=datetime(2026, 6, 8, 10, 30),
                latest_price=Decimal("10"),
                prev_close=Decimal("9.8"),
                change_rate=Decimal("0.020000"),
                source="test",
            )
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "018125"))
            result = EstimateService(db, Mock())._estimate_one(fund, datetime(2026, 6, 8, 10, 35))
        finally:
            db.close()

        self.assertEqual(result.estimated_growth_rate, Decimal("0.010000000000"))
        self.assertEqual(result.estimated_nav, Decimal("1.0100000000000000"))
        self.assertEqual(result.coverage_ratio, Decimal("0.5"))

    def test_target_fund_holdings_replace_stale_stock_holdings_from_newer_period(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)
        source.get_fund_holdings.return_value = [
            {
                "fund_code": "012805",
                "report_period": "2025Q1",
                "asset_code": "00772",
                "asset_name": "阅文集团",
                "asset_type": "stock",
                "market": "HK",
                "holding_ratio": Decimal("0.050000"),
                "holding_value": None,
                "source": "akshare",
            }
        ]
        target_source = Mock()
        target_source.get_target_fund_holdings.return_value = [
            {
                "fund_code": "012805",
                "report_period": "2024Q4",
                "asset_code": "513380",
                "asset_name": "广发恒生科技(QDII-ETF)",
                "asset_type": "etf",
                "market": "CN",
                "holding_ratio": Decimal("0.930800"),
                "holding_value": Decimal("211284.48"),
                "source": "etf88",
            }
        ]
        db.add(
            Fund(
                id=1,
                fund_code="012805",
                fund_name="广发恒生科技ETF联接(QDII)A",
                fund_type="QDII",
            )
        )
        db.add(
            FundHolding(
                id=1,
                fund_code="012805",
                report_period="2025Q1",
                asset_code="00772",
                asset_name="阅文集团",
                asset_type="stock",
                market="HK",
                holding_ratio=Decimal("0.050000"),
                holding_value=None,
                source="akshare",
            )
        )
        db.add(
            FundHolding(
                id=2,
                fund_code="012805",
                report_period="2024Q4",
                asset_code="513380",
                asset_name="广发恒生科技(QDII-ETF)",
                asset_type="etf",
                market="CN",
                holding_ratio=Decimal("0.930800"),
                holding_value=Decimal("211284.48"),
                source="etf88",
                is_deleted=1,
            )
        )
        db.commit()

        try:
            refreshed = HoldingService(
                db,
                source=source,
                holding_sources=[source],
                target_fund_sources=[target_source],
            ).refresh_holdings("012805")
            visible_holdings = db.scalars(
                select(FundHolding)
                .where(FundHolding.fund_code == "012805")
                .order_by(FundHolding.report_period.desc(), FundHolding.holding_ratio.desc())
            ).all()
        finally:
            db.close()

        self.assertEqual([holding.asset_code for holding in refreshed], ["513380"])
        self.assertEqual([holding.asset_code for holding in visible_holdings], ["513380"])

    def test_plain_qdii_does_not_use_target_fund_hint(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)
        source.get_fund_holdings.return_value = []
        target_source = Mock()
        target_source.get_target_fund_holdings.return_value = [
            {
                "fund_code": "017436",
                "report_period": "2026Q2",
                "asset_code": "159981",
                "asset_name": "工ETF建信1",
                "asset_type": "etf",
                "market": "CN",
                "holding_ratio": Decimal("1"),
                "holding_value": None,
                "source": "public_web:target_hint",
            }
        ]
        db.add(
            Fund(
                id=1,
                fund_code="017436",
                fund_name="华宝纳斯达克精选股票发起式(QDII)A",
                fund_type="QDII",
            )
        )
        db.add(
            FundHolding(
                id=1,
                fund_code="017436",
                report_period="2026Q2",
                asset_code="159981",
                asset_name="工ETF建信1",
                asset_type="etf",
                market="CN",
                holding_ratio=Decimal("1"),
                holding_value=None,
                source="public_web:target_hint",
            )
        )
        db.commit()

        try:
            with patch(
                "app.modules.fund_nav.services.holding_service.FundProfileService.get_or_sync_profile",
                return_value=None,
            ):
                refreshed = HoldingService(
                    db,
                    source=source,
                    holding_sources=[source],
                    target_fund_sources=[target_source],
                ).refresh_holdings("017436")
                visible_holdings = db.scalars(
                    select(FundHolding)
                    .where(FundHolding.fund_code == "017436")
                    .order_by(FundHolding.report_period.desc(), FundHolding.holding_ratio.desc())
                ).all()
        finally:
            db.close()

        self.assertEqual(refreshed, [])
        self.assertEqual(visible_holdings, [])
        target_source.get_target_fund_holdings.assert_not_called()

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

    def test_qdii_nav_falls_back_to_eastmoney_page_when_daily_table_has_dash(self) -> None:
        daily_df = pd.DataFrame(
            [
                {
                    "基金代码": "017436",
                    "2026-06-03-单位净值": "-",
                    "2026-06-03-累计净值": "-",
                    "2026-06-02-单位净值": "2.5259",
                    "2026-06-02-累计净值": "2.5259",
                    "日增长率": "2.15",
                }
            ]
        )
        response = Mock()
        response.status_code = 200
        response.apparent_encoding = "utf-8"
        response.text = "单位净值 (2026-06-03) 2.5043-0.86% 累计净值 2.5043"

        with (
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_open_fund_daily_em", return_value=daily_df),
            patch("app.modules.fund_nav.data_sources.akshare_source.requests.get", return_value=response),
            patch("app.modules.fund_nav.data_sources.akshare_source.date") as mocked_date,
        ):
            mocked_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            mocked_date.today.return_value = date(2026, 6, 5)
            mocked_date.fromisoformat.side_effect = date.fromisoformat
            snapshot = AkshareSource().get_latest_fund_nav("017436")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.nav_date, date(2026, 6, 3))
        self.assertEqual(snapshot.unit_nav, Decimal("2.5043"))
        self.assertEqual(snapshot.source, "akshare:eastmoney_fund_page")

    def test_qdii_nav_fills_missing_growth_rate_from_eastmoney_page(self) -> None:
        daily_df = pd.DataFrame(
            [
                {
                    "基金代码": "017436",
                    "2026-06-04-单位净值": "2.5059",
                    "2026-06-04-累计净值": "2.5059",
                    "日增长率": "-",
                }
            ]
        )
        response = Mock()
        response.status_code = 200
        response.apparent_encoding = "utf-8"
        response.text = "单位净值 (2026-06-04) 2.5059+0.06% 累计净值 2.5059"

        with (
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_open_fund_daily_em", return_value=daily_df),
            patch("app.modules.fund_nav.data_sources.akshare_source.requests.get", return_value=response),
            patch("app.modules.fund_nav.data_sources.akshare_source.date") as mocked_date,
        ):
            mocked_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            mocked_date.today.return_value = date(2026, 6, 7)
            mocked_date.fromisoformat.side_effect = date.fromisoformat
            snapshot = AkshareSource().get_latest_fund_nav("017436")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.nav_date, date(2026, 6, 4))
        self.assertEqual(snapshot.unit_nav, Decimal("2.5059"))
        self.assertEqual(snapshot.daily_growth_rate, Decimal("0.0006"))
        self.assertEqual(snapshot.source, "akshare:eastmoney_fund_page")

    def test_five_prefix_etf_nav_falls_back_to_eastmoney_page_when_tables_miss(self) -> None:
        etf_df = pd.DataFrame([{"代码": "515450", "昨收": "1.098"}])
        daily_df = pd.DataFrame([{"基金代码": "000001", "2026-06-04-单位净值": "1.001"}])
        response = Mock()
        response.status_code = 200
        response.apparent_encoding = "utf-8"
        response.text = "<table><tr><td>06-04</td><td>1.3721</td><td>1.3721</td><td>2.14%</td></tr></table>"

        with (
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_etf_spot_em", return_value=etf_df),
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_open_fund_daily_em", return_value=daily_df),
            patch("app.modules.fund_nav.data_sources.akshare_source.requests.get", return_value=response),
            patch("app.modules.fund_nav.data_sources.akshare_source.date") as mocked_date,
        ):
            mocked_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            mocked_date.today.return_value = date(2026, 6, 5)
            mocked_date.fromisoformat.side_effect = date.fromisoformat
            snapshot = AkshareSource().get_latest_fund_nav("561560")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.nav_date, date(2026, 6, 4))
        self.assertEqual(snapshot.unit_nav, Decimal("1.3721"))
        self.assertEqual(snapshot.source, "akshare:eastmoney_fund_page")

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

    def test_etf_iopv_snapshot_falls_back_to_latest_price_when_iopv_missing(self) -> None:
        etf_df = pd.DataFrame(
            [{"代码": "561560", "名称": "电力ETF华泰柏瑞", "最新价": "1.464", "涨跌幅": "-1.81"}]
        )

        with patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_etf_spot_em", return_value=etf_df):
            snapshot = AkshareSource().get_etf_iopv_snapshot("561560")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.estimated_nav, Decimal("1.464"))
        self.assertEqual(snapshot.change_rate, Decimal("-0.0181"))
        self.assertEqual(snapshot.source, "akshare:etf_price_fallback")

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

        with (
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_portfolio_hold_em", return_value=holding_df),
            patch(
                "app.modules.fund_nav.data_sources.akshare_source.ak.fund_portfolio_bond_hold_em",
                return_value=pd.DataFrame(),
            ),
        ):
            holdings = AkshareSource().get_fund_holdings("018172")

        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0]["asset_code"], "159915")
        self.assertEqual(holdings[0]["asset_type"], "etf")
        self.assertEqual(holdings[0]["market"], "CN")
        self.assertEqual(holdings[0]["holding_ratio"], Decimal("0.85"))

    def test_akshare_holdings_include_bonds(self) -> None:
        stock_df = pd.DataFrame(
            [
                {
                    "股票代码": "603179",
                    "股票名称": "新泉股份",
                    "占净值比例": "9.37",
                    "持仓市值": "147056.42",
                    "季度": "2026年1季度股票投资明细",
                }
            ]
        )
        bond_df = pd.DataFrame(
            [
                {
                    "债券代码": "019785",
                    "债券名称": "25国债13",
                    "占净值比例": "0.45",
                    "持仓市值": "7096.85",
                    "季度": "2026年1季度债券投资明细",
                }
            ]
        )

        with (
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_portfolio_hold_em", return_value=stock_df),
            patch("app.modules.fund_nav.data_sources.akshare_source.ak.fund_portfolio_bond_hold_em", return_value=bond_df),
        ):
            holdings = AkshareSource().get_fund_holdings("018125")

        self.assertEqual([holding["asset_type"] for holding in holdings], ["stock", "bond"])
        bond = holdings[1]
        self.assertEqual(bond["asset_code"], "019785")
        self.assertEqual(bond["asset_name"], "25国债13")
        self.assertEqual(bond["market"], "CN")
        self.assertEqual(bond["holding_ratio"], Decimal("0.0045"))

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
