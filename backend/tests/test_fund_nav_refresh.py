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

from app.modules.fund_nav.data_sources.akshare.akshare_source import AkshareSource, EtfIopvSnapshot, FundNavSnapshot, MarketQuoteSnapshot
from app.modules.fund_nav.data_sources.akshare.eastmoney_index_source import EastmoneyIndexSource
from app.modules.fund_nav.data_sources.web.eastmoney_source import EastmoneySource
from app.modules.fund_nav.data_sources.web.eastmoney_index_source import EastmoneyHttpIndexSource
from app.modules.fund_nav.data_sources.akshare.index_catalog_source import MarketIndexSnapshot
from app.modules.fund_nav.data_sources.akshare.sina_index_source import SinaIndexSource
from app.modules.fund_nav.data_sources.web.sina_index_source import SinaHttpIndexSource
from app.modules.fund_nav.data_sources.web.tencent_index_source import TencentIndexSource
from app.modules.fund_nav.data_sources.web.xueqiu_index_source import XueqiuIndexSource
from app.modules.fund_nav.data_sources.index_mapping_source import FundIndexMappingSnapshot
from app.database import Base
from app.modules.fund_nav.models.asset_valuation_config import AssetValuationConfig
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_estimate import FundEstimate
from app.modules.fund_nav.models.fund_holding import FundHolding
from app.modules.fund_nav.models.fund_index_mapping import FundIndexMapping
from app.modules.fund_nav.models.fund_nav import FundNav
from app.modules.fund_nav.models.fund_profile import FundProfile
from app.modules.fund_nav.models.fund_task_detail_log import FundTaskDetailLog
from app.modules.fund_nav.models.index_quote_source_status import IndexQuoteSourceStatus
from app.modules.fund_nav.models.manual_fund_index_mapping import ManualFundIndexMapping
from app.modules.fund_nav.models.market_index import MarketIndex
from app.modules.fund_nav.models.market_quote import MarketQuote
from app.modules.fund_nav.report_period import latest_completed_quarter_period
from app.modules.fund_nav.schemas.fund import FundCreate
from app.modules.fund_nav.schemas.manual_index_mapping import ManualFundIndexMappingIn
from app.modules.fund_nav.schemas.task_detail import FundTaskDetailLogOut
from app.modules.fund_nav.api.funds import list_task_detail_logs
from app.modules.fund_nav.api.market import index_quote_sources
from app.modules.fund_nav.services.fund_service import FundService
from app.modules.fund_nav.services.fund_classifier import FundClassifier
from app.modules.fund_nav.services.fund_index_mapping_service import FundIndexMappingService
from app.modules.fund_nav.services.fund_profile_service import FundProfileService
from app.modules.fund_nav.services.holding_service import HoldingService
from app.modules.fund_nav.services.index_catalog_service import IndexCatalogService
from app.modules.fund_nav.services.index_quote_source_status_service import (
    DISABLE_FAILURES,
    IndexQuoteSourceStatusService,
    seed_default_index_quote_source_statuses,
)
from app.modules.fund_nav.services.manual_index_mapping_service import ManualIndexMappingService
from app.modules.fund_nav.services.estimate_service import EstimateService, IndexTrackingEstimateStrategy
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

    def test_fund_category_is_saved_from_profile_and_returned_in_list(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)
        db.add_all(
            [
                FundProfile(
                    id=1,
                    fund_code="501009",
                    fund_name="汇添富中证生物科技指数(LOF)A",
                    fund_type="指数型-股票",
                    fund_category="index_tracking",
                    fund_category_source="auto",
                    fund_category_updated_at=datetime(2026, 6, 8, 21, 0),
                    source="test",
                    synced_at=datetime(2026, 6, 8, 21, 0),
                ),
                Fund(
                    id=100,
                    fund_code="501009",
                    fund_name="501009",
                    is_deleted=1,
                ),
            ]
        )
        db.commit()

        try:
            fund = FundService(db, source).create_fund(FundCreate(fund_code="501009"))
            rows = FundService(db, source).list_funds()
        finally:
            db.close()

        self.assertEqual(fund.fund_category, "index_tracking")
        self.assertEqual(rows[0]["fund_category"], "index_tracking")
        self.assertEqual(rows[0]["fund_category_label"], "指数跟踪基金")

    def test_fund_classifier_prefers_saved_category(self) -> None:
        fund = Fund(
            id=1,
            fund_code="501009",
            fund_name="普通基金",
            fund_type="混合型",
            fund_category="index_tracking",
            fund_category_source="auto",
        )

        self.assertTrue(FundClassifier.is_index_tracking_fund(fund))

    def test_initialize_fund_categories_backfills_profiles_and_funds(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add_all(
            [
                FundProfile(
                    id=1,
                    fund_code="501009",
                    fund_name="汇添富中证生物科技指数(LOF)A",
                    fund_type="指数型-股票",
                    source="test",
                    synced_at=datetime(2026, 6, 8, 21, 0),
                ),
                Fund(id=1, fund_code="012805", fund_name="广发恒生科技ETF联接(QDII)A"),
            ]
        )
        db.commit()

        try:
            result = FundProfileService(db).initialize_fund_categories()
            profile = db.scalar(select(FundProfile).where(FundProfile.fund_code == "501009"))
            fund = db.scalar(select(Fund).where(Fund.fund_code == "012805"))
        finally:
            db.close()

        self.assertEqual(result, {"profiles": 1, "funds": 1})
        self.assertEqual(profile.fund_category, "index_tracking")
        self.assertEqual(fund.fund_category, "etf_feeder")

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

        with patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_open_fund_info_em", return_value=dataframe) as fetcher:
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
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_etf_spot_em", return_value=etf_df),
            patch(
                "app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_open_fund_daily_em",
                side_effect=AssertionError("open fund daily table should not be loaded for 5-prefix ETFs"),
            ),
        ):
            snapshot = AkshareSource().get_latest_fund_nav("515450")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.source, "akshare:etf_spot_prev_close")
        self.assertEqual(snapshot.unit_nav, Decimal("1.098"))
        self.assertEqual(snapshot.nav_date, date(2026, 4, 27))

    def test_etf_estimate_requires_persisted_quote_without_holdings(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
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
        self.assertEqual(result, "missing_etf_quote")
        source.get_etf_iopv_snapshot.assert_not_called()

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

    def test_etf_estimate_with_etf_spot_nav_source_requires_persisted_quote(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        fund = Fund(id=1, fund_code="515450", fund_name="515450", fund_type=None)
        db.add(fund)
        db.add(
            FundNav(
                id=1,
                fund_code="515450",
                nav_date=date(2026, 6, 4),
                unit_nav=Decimal("1.4908"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("-0.0144"),
                source="akshare:etf_spot_prev_close",
            )
        )
        db.commit()

        try:
            result = EstimateService(db, source)._estimate_one(fund, datetime(2026, 6, 5, 10, 30))
        finally:
            db.close()

        self.assertEqual(result, "missing_etf_quote")
        source.get_etf_iopv_snapshot.assert_not_called()

    def test_index_fund_estimate_uses_tracking_index_quote(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(
            Fund(
                id=1,
                fund_code="501009",
                fund_name="汇添富中证生物科技指数(LOF)A",
                fund_type="指数型-股票",
            )
        )
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="501009",
                index_code="930743.CSI",
                index_name="中证生物科技主题指数",
                source="test",
                confidence="high",
            )
        )
        db.add(
            FundNav(
                id=1,
                fund_code="501009",
                nav_date=date(2026, 6, 23),
                unit_nav=Decimal("1.0992"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0.0058"),
                source="test",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="930743",
                asset_name="中证生科",
                asset_type="index",
                market="CN",
                trade_date=date(2026, 6, 24),
                quote_time=datetime(2026, 6, 24, 15, 30),
                latest_price=Decimal("2901.69"),
                prev_close=Decimal("2853.55"),
                change_rate=Decimal("0.0169"),
                source="test",
            )
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "501009"))
            result = EstimateService(db, Mock())._estimate_one(fund, datetime(2026, 6, 24, 15, 35))
        finally:
            db.close()

        self.assertIsInstance(result, FundEstimate)
        self.assertEqual(result.estimated_nav, Decimal("1.117776480000"))
        self.assertEqual(result.estimated_growth_rate, Decimal("0.0169"))
        self.assertEqual(result.coverage_ratio, Decimal("1"))
        self.assertIn("strategy=index_tracking", result.source_snapshot)

    def test_index_fund_estimate_prefers_current_trade_date_quote_over_later_stale_quote(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(
            Fund(
                id=1,
                fund_code="006786",
                fund_name="泰康港股通大消费指数A",
                fund_type="指数型-股票",
            )
        )
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="006786",
                index_code="931027.CSI",
                index_name="中证港股通大消费主题指数",
                source="test",
                confidence="high",
            )
        )
        db.add(
            FundNav(
                id=1,
                fund_code="006786",
                nav_date=date(2026, 7, 7),
                unit_nav=Decimal("0.8940"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("-0.0073"),
                source="test",
            )
        )
        db.add_all(
            [
                MarketQuote(
                    id=1,
                    asset_code="931027",
                    asset_name="港股通大消费",
                    asset_type="index",
                    market="CN",
                    trade_date=date(2026, 7, 8),
                    quote_time=datetime(2026, 7, 8, 14, 36, 11),
                    latest_price=Decimal("4021.34"),
                    prev_close=Decimal("3937.83"),
                    change_rate=Decimal("0.0212"),
                    source="test",
                ),
                MarketQuote(
                    id=2,
                    asset_code="931027",
                    asset_name="港股通大消费",
                    asset_type="index",
                    market="CN",
                    trade_date=date(2026, 7, 7),
                    quote_time=datetime(2026, 7, 8, 15, 33, 56),
                    latest_price=Decimal("3937.83"),
                    prev_close=Decimal("3968.39"),
                    change_rate=Decimal("-0.0077"),
                    source="test",
                ),
            ]
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "006786"))
            result = EstimateService(db, Mock())._estimate_one(fund, datetime(2026, 7, 8, 17, 22, 15))
        finally:
            db.close()

        self.assertIsInstance(result, FundEstimate)
        self.assertEqual(result.estimated_growth_rate, Decimal("0.0212"))
        self.assertIn("strategy=index_tracking", result.source_snapshot)
        self.assertIn("quote=2026-07-08T14:36:11", result.source_snapshot)

    def test_index_fund_estimate_does_not_fetch_missing_index_quote_on_demand(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(
            Fund(
                id=1,
                fund_code="501009",
                fund_name="汇添富中证生物科技指数(LOF)A",
                fund_type="指数型-股票",
            )
        )
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="501009",
                index_code="930743.CSI",
                index_name="中证生物科技主题指数",
                source="test",
                confidence="high",
            )
        )
        db.add(
            FundNav(
                id=1,
                fund_code="501009",
                nav_date=date(2026, 6, 23),
                unit_nav=Decimal("1.0992"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0.0058"),
                source="test",
            )
        )
        db.commit()
        source = Mock()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "501009"))
            result = IndexTrackingEstimateStrategy(EstimateService(db, source)).estimate(
                fund,
                datetime(2026, 6, 24, 10, 35),
            )
            quote = db.scalar(select(MarketQuote).where(MarketQuote.asset_code == "930743"))
        finally:
            db.close()

        self.assertEqual(result, "missing_index_quote")
        self.assertIsNone(quote)
        source.get_index_quotes.assert_not_called()

    def test_index_fund_estimate_requires_current_trade_date_quote(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(
            Fund(
                id=1,
                fund_code="501009",
                fund_name="汇添富中证生物科技指数(LOF)A",
                fund_type="指数型-股票",
            )
        )
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="501009",
                index_code="930743.CSI",
                index_name="中证生物科技主题指数",
                source="test",
                confidence="high",
            )
        )
        db.add(
            FundNav(
                id=1,
                fund_code="501009",
                nav_date=date(2026, 6, 23),
                unit_nav=Decimal("1.0992"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0.0058"),
                source="test",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="930743",
                asset_name="中证生科",
                asset_type="index",
                market="CN",
                trade_date=date(2026, 6, 23),
                quote_time=datetime(2026, 6, 23, 15, 30),
                latest_price=Decimal("2853.55"),
                prev_close=Decimal("2840.00"),
                change_rate=Decimal("0.0047"),
                source="test",
            )
        )
        db.commit()
        source = Mock()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "501009"))
            result = IndexTrackingEstimateStrategy(EstimateService(db, source)).estimate(
                fund,
                datetime(2026, 6, 24, 10, 35),
            )
        finally:
            db.close()

        self.assertEqual(result, "missing_index_quote")
        source.get_index_quotes.assert_not_called()

    def test_run_estimates_records_fund_detail_log(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        today = date.today()
        db.add(
            Fund(
                id=1,
                fund_code="501009",
                fund_name="汇添富中证生物科技指数(LOF)A",
                fund_type="指数型-股票",
            )
        )
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="501009",
                index_code="930743.CSI",
                index_name="中证生物科技主题指数",
                source="test",
                confidence="high",
            )
        )
        db.add(
            FundNav(
                id=1,
                fund_code="501009",
                nav_date=today,
                unit_nav=Decimal("1.0000"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0"),
                source="test",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="930743",
                asset_name="中证生科",
                asset_type="index",
                market="CN",
                trade_date=today,
                quote_time=datetime.combine(today, datetime.min.time()).replace(hour=15, minute=30),
                latest_price=Decimal("2901.69"),
                prev_close=Decimal("2853.55"),
                change_rate=Decimal("0.0169"),
                source="test",
            )
        )
        db.commit()

        try:
            result = EstimateService(db, Mock()).run_estimates(["501009"], task_log_id=123, task_type="estimate_nav")
            detail_log = db.scalar(select(FundTaskDetailLog).where(FundTaskDetailLog.fund_code == "501009"))
            first_detail_log_id = detail_log.id if detail_log else None

            quote = db.scalar(select(MarketQuote).where(MarketQuote.asset_code == "930743"))
            quote.change_rate = Decimal("0.0200")
            db.commit()
            sleep(1.1)
            second_result = EstimateService(db, Mock()).run_estimates(
                ["501009"],
                task_log_id=456,
                task_type="estimate_nav",
            )
            detail_logs = db.scalars(select(FundTaskDetailLog).where(FundTaskDetailLog.fund_code == "501009")).all()
            detail_log = detail_logs[0]
        finally:
            db.close()

        self.assertEqual(result["estimated_count"], 1)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(second_result["estimated_count"], 1)
        self.assertEqual(len(detail_logs), 1)
        self.assertIsNotNone(detail_log)
        self.assertEqual(detail_log.id, first_detail_log_id)
        self.assertEqual(detail_log.task_log_id, 456)
        self.assertEqual(detail_log.status, "success")
        self.assertEqual(detail_log.strategy, "index_tracking")
        self.assertEqual(detail_log.estimated_growth_rate, Decimal("0.020000"))
        self.assertEqual(detail_log.estimate_date, today)
        self.assertIn("index_tracking=success", detail_log.message)
        detail_log_out = FundTaskDetailLogOut.model_validate(detail_log)
        self.assertEqual(detail_log_out.strategy_label, "指数法")
        self.assertEqual(detail_log_out.attempts[0].strategy_label, "指数法")
        self.assertEqual(detail_log_out.attempts[0].result_label, "成功")

    def test_manual_quote_estimate_updates_daily_fund_detail_log(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        today = date.today()
        db.add(
            Fund(
                id=1,
                fund_code="501009",
                fund_name="汇添富中证生物科技指数(LOF)A",
                fund_type="指数型-股票",
            )
        )
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="501009",
                index_code="930743.CSI",
                index_name="中证生物科技主题指数",
                source="test",
                confidence="high",
            )
        )
        db.add(
            FundNav(
                id=1,
                fund_code="501009",
                nav_date=today,
                unit_nav=Decimal("1.0000"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0"),
                source="test",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="930743",
                asset_name="中证生科",
                asset_type="index",
                market="CN",
                trade_date=today,
                quote_time=datetime.combine(today, datetime.min.time()).replace(hour=15, minute=30),
                latest_price=Decimal("2901.69"),
                prev_close=Decimal("2853.55"),
                change_rate=Decimal("0.0169"),
                source="test",
            )
        )
        db.commit()

        try:
            EstimateService(db, Mock()).run_estimates(["501009"], task_log_id=123, task_type="estimate_nav")
            detail_log = db.scalar(select(FundTaskDetailLog).where(FundTaskDetailLog.fund_code == "501009"))
            first_detail_log_id = detail_log.id if detail_log else None

            quote = db.scalar(select(MarketQuote).where(MarketQuote.asset_code == "930743"))
            quote.change_rate = Decimal("0.0310")
            db.commit()
            sleep(1.1)
            EstimateService(db, Mock()).run_estimates(
                ["501009"],
                task_log_id=456,
                task_type="refresh_quote_estimate",
            )
            detail_logs = db.scalars(select(FundTaskDetailLog).where(FundTaskDetailLog.fund_code == "501009")).all()
            detail_log = detail_logs[0]
        finally:
            db.close()

        self.assertEqual(len(detail_logs), 1)
        self.assertEqual(detail_log.id, first_detail_log_id)
        self.assertEqual(detail_log.task_log_id, 456)
        self.assertEqual(detail_log.task_type, "refresh_quote_estimate")
        self.assertEqual(detail_log.strategy, "index_tracking")
        self.assertEqual(detail_log.estimated_growth_rate, Decimal("0.031000"))

    def test_list_task_detail_logs_filters_by_fund_and_date(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        target_date = date(2026, 7, 2)
        db.add_all(
            [
                FundTaskDetailLog(
                    task_type="estimate_nav",
                    fund_code="161036",
                    fund_name="富国中证娱乐主题指数增强(LOF)A",
                    status="success",
                    strategy="holding_weighted",
                    estimate_date=target_date,
                    estimate_time=datetime(2026, 7, 2, 15, 30),
                    estimated_nav=Decimal("0.650000"),
                    estimated_growth_rate=Decimal("0.006000"),
                    coverage_ratio=Decimal("0.900000"),
                    message="holding_weighted=success",
                ),
                FundTaskDetailLog(
                    task_type="estimate_nav",
                    fund_code="501009",
                    fund_name="汇添富中证生物科技指数(LOF)A",
                    status="success",
                    strategy="index_tracking",
                    estimate_date=target_date,
                    estimate_time=datetime(2026, 7, 2, 15, 35),
                    estimated_nav=Decimal("1.120000"),
                    estimated_growth_rate=Decimal("0.020000"),
                    coverage_ratio=Decimal("1"),
                    message="index_tracking=success",
                ),
                FundTaskDetailLog(
                    task_type="estimate_nav",
                    fund_code="161036",
                    fund_name="富国中证娱乐主题指数增强(LOF)A",
                    status="success",
                    strategy="index_tracking",
                    estimate_date=date(2026, 7, 1),
                    estimate_time=datetime(2026, 7, 1, 15, 35),
                    estimated_nav=Decimal("0.648000"),
                    estimated_growth_rate=Decimal("0.003000"),
                    coverage_ratio=Decimal("1"),
                    message="index_tracking=success",
                ),
            ]
        )
        db.commit()

        try:
            logs = list_task_detail_logs(fund_code="161036", estimate_date=target_date, limit=100, db=db)
        finally:
            db.close()

        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].fund_code, "161036")
        self.assertEqual(logs[0].estimate_date, target_date)

    def test_run_estimates_updates_daily_skipped_fund_detail_log(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        today = date.today()
        db.add(
            Fund(
                id=1,
                fund_code="000001",
                fund_name="测试混合基金",
                fund_type="混合型",
            )
        )
        db.commit()

        try:
            result = EstimateService(db, Mock()).run_estimates(["000001"], task_log_id=123, task_type="estimate_nav")
            second_result = EstimateService(db, Mock()).run_estimates(
                ["000001"],
                task_log_id=456,
                task_type="estimate_nav",
            )
            detail_logs = db.scalars(select(FundTaskDetailLog).where(FundTaskDetailLog.fund_code == "000001")).all()
            detail_log = detail_logs[0]
        finally:
            db.close()

        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(second_result["skipped_count"], 1)
        self.assertEqual(len(detail_logs), 1)
        self.assertEqual(detail_log.task_log_id, 456)
        self.assertEqual(detail_log.status, "skipped")
        self.assertEqual(detail_log.reason, "missing_nav")
        self.assertEqual(detail_log.estimate_date, today)
        self.assertIsNotNone(detail_log.estimate_time)
        self.assertIn("holding_weighted=missing_nav", detail_log.message)

    def test_index_fund_estimate_falls_back_to_holdings_without_index_quote(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(
            Fund(
                id=1,
                fund_code="501009",
                fund_name="汇添富中证生物科技指数(LOF)A",
                fund_type="指数型-股票",
            )
        )
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="501009",
                index_code="930743.CSI",
                index_name="中证生物科技主题指数",
                source="test",
                confidence="high",
            )
        )
        db.add(
            FundNav(
                id=1,
                fund_code="501009",
                nav_date=date(2026, 6, 23),
                unit_nav=Decimal("1.0992"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0.0058"),
                source="test",
            )
        )
        db.add(
            FundHolding(
                id=1,
                fund_code="501009",
                report_period="2026Q1",
                asset_code="600276",
                asset_name="恒瑞医药",
                asset_type="stock",
                market="SH",
                holding_ratio=Decimal("1.000000"),
                holding_value=None,
                source="test",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="600276",
                asset_name="恒瑞医药",
                asset_type="stock",
                market="SH",
                trade_date=date(2026, 6, 24),
                quote_time=datetime(2026, 6, 24, 15, 0),
                latest_price=Decimal("50"),
                prev_close=Decimal("49"),
                change_rate=Decimal("0.020000"),
                source="test",
            )
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "501009"))
            result = EstimateService(db, Mock())._estimate_one(fund, datetime(2026, 6, 24, 15, 35))
        finally:
            db.close()

        self.assertIsInstance(result, FundEstimate)
        self.assertEqual(result.estimated_nav, Decimal("1.1211840000000000"))
        self.assertIn("strategy=holding_weighted", result.source_snapshot)

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
        self.assertTrue(config_map.resolve("index", "CN").realtime_valuable)
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

    def test_refresh_quotes_for_holdings_includes_etf_fund_itself(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(Fund(id=1, fund_code="515450", fund_name="红利低波ETF", fund_type="指数型-股票"))
        db.add(
            AssetValuationConfig(
                id=1,
                asset_type="etf",
                market="CN",
                realtime_valuable=1,
                valuation_mode="quote",
                enabled=1,
            )
        )
        db.commit()
        source = Mock()
        source.source_name = "akshare"
        source.get_market_quotes.return_value = [
            MarketQuoteSnapshot(
                asset_code="515450",
                asset_name="红利低波ETF",
                asset_type="etf",
                market="CN",
                trade_date=date(2026, 6, 5),
                quote_time=datetime(2026, 6, 5, 10, 30),
                latest_price=Decimal("1.4638"),
                prev_close=Decimal("1.4908"),
                change_rate=Decimal("-0.0181"),
            )
        ]

        try:
            quotes = MarketService(db, source).refresh_quotes_for_holdings(["515450"])
        finally:
            db.close()

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].asset_code, "515450")
        source.get_market_quotes.assert_called_once_with(["515450"])
        source.get_index_quotes.assert_not_called()

    def test_refresh_quotes_for_holdings_includes_index_mapping_for_index_fund(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(
            Fund(
                id=1,
                fund_code="501009",
                fund_name="汇添富中证生物科技指数(LOF)A",
                fund_type="指数型-股票",
            )
        )
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="501009",
                index_code="930743.CSI",
                index_name="中证生物科技主题指数",
                source="test",
                confidence="high",
            )
        )
        db.commit()
        source = Mock()
        source.source_name = "akshare"
        source.get_market_quotes.return_value = []
        source.get_index_quotes.return_value = [
            MarketQuoteSnapshot(
                asset_code="930743",
                asset_name="中证生科",
                asset_type="index",
                market="CN",
                trade_date=date(2026, 6, 24),
                quote_time=datetime(2026, 6, 24, 15, 30),
                latest_price=Decimal("2901.69"),
                prev_close=Decimal("2853.55"),
                change_rate=Decimal("0.0169"),
            )
        ]

        try:
            quotes = MarketService(db, source).refresh_quotes_for_holdings(["501009"])
        finally:
            db.close()

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].asset_code, "930743")
        self.assertEqual(quotes[0].asset_type, "index")
        source.get_market_quotes.assert_not_called()
        source.get_index_quotes.assert_called_once_with(["930743"])

    def test_refresh_quotes_for_holdings_refreshes_stock_etf_index_in_order(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(
            Fund(
                id=1,
                fund_code="501009",
                fund_name="汇添富中证生物科技指数(LOF)A",
                fund_type="指数型-股票",
            )
        )
        db.add(
            Fund(
                id=2,
                fund_code="515450",
                fund_name="红利低波ETF",
                fund_type="指数型-股票",
            )
        )
        db.add(
            FundHolding(
                id=1,
                fund_code="501009",
                report_period="2026Q1",
                asset_code="600276",
                asset_name="恒瑞医药",
                asset_type="stock",
                market="SH",
                holding_ratio=Decimal("1.000000"),
                holding_value=None,
                source="test",
            )
        )
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="501009",
                index_code="930743.CSI",
                index_name="中证生物科技主题指数",
                source="test",
                confidence="high",
            )
        )
        db.commit()
        source = Mock()
        source.source_name = "akshare"
        calls = []

        def fake_market_quotes(asset_codes):
            calls.append(("market", list(asset_codes)))
            return []

        def fake_index_quotes(index_codes):
            calls.append(("index", list(index_codes)))
            return []

        source.get_market_quotes.side_effect = fake_market_quotes
        source.get_index_quotes.side_effect = fake_index_quotes

        try:
            MarketService(db, source).refresh_quotes_for_holdings()
        finally:
            db.close()

        self.assertEqual(
            calls,
            [
                ("market", ["600276"]),
                ("market", ["515450"]),
                ("index", ["930743"]),
            ],
        )

    def test_index_quotes_prefer_eastmoney_http_realtime_spot_for_csi_theme_index(self) -> None:
        provider_time = datetime(2026, 7, 8, 16, 29, 55)
        response = Mock()
        response.json.return_value = {
            "data": {
                "diff": [
                    {
                        "f12": "930875",
                        "f13": 2,
                        "f14": "空天军工",
                        "f2": 2158.4,
                        "f3": -2.53,
                        "f18": 2214.35,
                        "f124": int(provider_time.timestamp()),
                    }
                ]
            }
        }
        response.raise_for_status.return_value = None

        with (
            patch(
                "app.modules.fund_nav.data_sources.web.eastmoney_index_source.requests.get",
                return_value=response,
            ) as request_get,
            patch.object(EastmoneyIndexSource, "get_spot_quotes") as eastmoney_spot,
        ):
            quotes = AkshareSource().get_index_quotes(["930875.CSI"])

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].asset_code, "930875")
        self.assertEqual(quotes[0].asset_name, "空天军工")
        self.assertEqual(quotes[0].trade_date, date(2026, 7, 8))
        self.assertEqual(quotes[0].quote_time, provider_time)
        self.assertEqual(quotes[0].latest_price, Decimal("2158.4"))
        self.assertEqual(quotes[0].prev_close, Decimal("2214.35"))
        self.assertEqual(quotes[0].change_rate, Decimal("-0.0253"))
        request_get.assert_called_once()
        self.assertIn("2.930875", request_get.call_args.kwargs["params"]["secids"])
        eastmoney_spot.assert_not_called()

    def test_index_quotes_fall_back_to_akshare_eastmoney_realtime_spot_when_http_missing(self) -> None:
        columns = ["代码", "名称", "最新价", "涨跌幅", "昨收"]

        def fake_spot(symbol: str):
            if symbol == "深证系列指数":
                return pd.DataFrame(
                    [
                        {
                            "代码": "399395",
                            "名称": "国证有色",
                            "最新价": 9352.43,
                            "涨跌幅": 0.10,
                            "昨收": 9343.06,
                        }
                    ],
                    columns=columns,
                )
            return pd.DataFrame(columns=columns)

        with (
            patch.object(EastmoneyHttpIndexSource, "get_spot_quotes", return_value={}),
            patch(
                "app.modules.fund_nav.data_sources.akshare.eastmoney_index_source.ak.stock_zh_index_spot_em",
                side_effect=fake_spot,
            ),
        ):
            quotes = AkshareSource().get_index_quotes(["399395"])

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].asset_code, "399395")
        self.assertEqual(quotes[0].asset_name, "国证有色")
        self.assertEqual(quotes[0].trade_date, quotes[0].quote_time.date())
        self.assertEqual(quotes[0].latest_price, Decimal("9352.43"))
        self.assertEqual(quotes[0].change_rate, Decimal("0.001"))

    def test_index_quotes_fall_back_to_sina_realtime_when_eastmoney_spot_missing(self) -> None:
        empty_spot = pd.DataFrame(columns=["代码", "名称", "最新价", "涨跌幅", "昨收"])
        sina_spot = pd.DataFrame(
            [
                {
                    "代码": "sz399395",
                    "名称": "国证有色",
                    "最新价": 9409.938,
                    "涨跌幅": 0.615,
                    "昨收": 9352.435,
                }
            ]
        )

        with (
            patch.object(EastmoneyHttpIndexSource, "get_spot_quotes", return_value={}),
            patch(
                "app.modules.fund_nav.data_sources.akshare.eastmoney_index_source.ak.stock_zh_index_spot_em",
                return_value=empty_spot,
            ),
            patch(
                "app.modules.fund_nav.data_sources.akshare.sina_index_source.ak.stock_zh_index_spot_sina",
                return_value=sina_spot,
            ),
        ):
            quotes = AkshareSource().get_index_quotes(["399395"])

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].asset_code, "399395")
        self.assertEqual(quotes[0].asset_name, "国证有色")
        self.assertEqual(quotes[0].trade_date, quotes[0].quote_time.date())
        self.assertEqual(quotes[0].latest_price, Decimal("9409.938"))
        self.assertEqual(quotes[0].prev_close, Decimal("9352.435"))
        self.assertEqual(quotes[0].change_rate, Decimal("0.00615"))

    def test_index_quotes_fall_back_to_sina_http_realtime_when_akshare_sina_missing(self) -> None:
        quote_time = datetime(2026, 7, 8, 10, 30)
        snapshot = MarketQuoteSnapshot(
            asset_code="399395",
            asset_name="国证有色",
            asset_type="index",
            market="CN",
            trade_date=quote_time.date(),
            quote_time=quote_time,
            latest_price=Decimal("9409.938"),
            prev_close=Decimal("9352.435"),
            change_rate=Decimal("0.00615"),
        )

        with (
            patch.object(EastmoneyHttpIndexSource, "get_spot_quotes", return_value={}),
            patch.object(EastmoneyIndexSource, "get_spot_quotes", return_value={}),
            patch.object(SinaIndexSource, "get_spot_quotes", return_value={}),
            patch.object(SinaHttpIndexSource, "get_spot_quotes", return_value={"399395": snapshot}) as sina_http_spot,
            patch.object(TencentIndexSource, "get_spot_quotes") as tencent_spot,
        ):
            quotes = AkshareSource().get_index_quotes(["399395"])

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].asset_code, "399395")
        sina_http_spot.assert_called_once()
        tencent_spot.assert_not_called()

    def test_sina_http_index_source_parses_simplified_quote(self) -> None:
        response = Mock()
        response.content = 'var hq_str_s_sz399395="国证有色,9409.938,57.503,0.615,0,0";'.encode("gbk")
        response.raise_for_status.return_value = None
        quote_time = datetime(2026, 7, 8, 10, 30)

        with patch(
            "app.modules.fund_nav.data_sources.web.sina_index_source.requests.get",
            return_value=response,
        ) as request_get:
            quotes = SinaHttpIndexSource(AkshareSource()).get_spot_quotes({"399395"}, quote_time)

        quote = quotes["399395"]
        self.assertEqual(quote.asset_name, "国证有色")
        self.assertEqual(quote.trade_date, date(2026, 7, 8))
        self.assertEqual(quote.latest_price, Decimal("9409.938"))
        self.assertEqual(quote.change_rate, Decimal("0.00615"))
        self.assertIn("s_sz399395", request_get.call_args.args[0])

    def test_index_quotes_fall_back_to_tencent_realtime_when_eastmoney_and_sina_missing(self) -> None:
        snapshot = MarketQuoteSnapshot(
            asset_code="399395",
            asset_name="国证有色",
            asset_type="index",
            market="CN",
            trade_date=date(2026, 7, 8),
            quote_time=datetime(2026, 7, 8, 10, 30),
            latest_price=Decimal("9409.938"),
            prev_close=Decimal("9352.435"),
            change_rate=Decimal("0.00615"),
        )

        with (
            patch.object(EastmoneyHttpIndexSource, "get_spot_quotes", return_value={}),
            patch.object(EastmoneyIndexSource, "get_spot_quotes", return_value={}),
            patch.object(SinaIndexSource, "get_spot_quotes", return_value={}),
            patch.object(SinaHttpIndexSource, "get_spot_quotes", return_value={}),
            patch.object(TencentIndexSource, "get_spot_quotes", return_value={"399395": snapshot}) as tencent_spot,
        ):
            quotes = AkshareSource().get_index_quotes(["399395"])

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].asset_code, "399395")
        tencent_spot.assert_called_once()

    def test_index_quotes_fall_back_to_xueqiu_realtime_when_previous_sources_missing(self) -> None:
        snapshot = MarketQuoteSnapshot(
            asset_code="399395",
            asset_name="国证有色",
            asset_type="index",
            market="CN",
            trade_date=date(2026, 7, 8),
            quote_time=datetime(2026, 7, 8, 10, 30),
            latest_price=Decimal("9409.938"),
            prev_close=Decimal("9352.435"),
            change_rate=Decimal("0.00615"),
        )

        with (
            patch.object(EastmoneyHttpIndexSource, "get_spot_quotes", return_value={}),
            patch.object(EastmoneyIndexSource, "get_spot_quotes", return_value={}),
            patch.object(SinaIndexSource, "get_spot_quotes", return_value={}),
            patch.object(SinaHttpIndexSource, "get_spot_quotes", return_value={}),
            patch.object(TencentIndexSource, "get_spot_quotes", return_value={}),
            patch.object(XueqiuIndexSource, "get_spot_quotes", return_value={"399395": snapshot}) as xueqiu_spot,
        ):
            quotes = AkshareSource().get_index_quotes(["399395"])

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0].asset_code, "399395")
        xueqiu_spot.assert_called_once()

    def test_xueqiu_index_source_parses_realtime_quote(self) -> None:
        provider_time = datetime(2026, 7, 8, 10, 30)
        home_response = Mock()
        home_response.raise_for_status.return_value = None
        quote_response = Mock()
        quote_response.raise_for_status.return_value = None
        quote_response.json.return_value = {
            "data": [
                {
                    "symbol": "SZ399395",
                    "name": "国证有色",
                    "current": 9409.938,
                    "percent": 0.615,
                    "last_close": 9352.435,
                    "timestamp": int(provider_time.timestamp() * 1000),
                }
            ]
        }
        session = Mock()
        session.get.side_effect = [home_response, quote_response]

        with patch(
            "app.modules.fund_nav.data_sources.web.xueqiu_index_source.requests.Session",
            return_value=session,
        ):
            quotes = XueqiuIndexSource(AkshareSource()).get_spot_quotes({"399395"}, provider_time)

        quote = quotes["399395"]
        self.assertEqual(quote.asset_name, "国证有色")
        self.assertEqual(quote.trade_date, date(2026, 7, 8))
        self.assertEqual(quote.quote_time, provider_time)
        self.assertEqual(quote.latest_price, Decimal("9409.938"))
        self.assertEqual(quote.prev_close, Decimal("9352.435"))
        self.assertEqual(quote.change_rate, Decimal("0.00615"))
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["symbol"], "SZ399395")

    def test_index_quotes_do_not_fall_back_to_daily_when_spot_missing(self) -> None:
        empty_spot = pd.DataFrame(columns=["代码", "名称", "最新价", "涨跌幅", "昨收"])

        with (
            patch.object(EastmoneyHttpIndexSource, "get_spot_quotes", return_value={}),
            patch(
                "app.modules.fund_nav.data_sources.akshare.eastmoney_index_source.ak.stock_zh_index_spot_em",
                return_value=empty_spot,
            ),
            patch(
                "app.modules.fund_nav.data_sources.akshare.sina_index_source.ak.stock_zh_index_spot_sina",
                return_value=empty_spot,
            ),
            patch.object(SinaHttpIndexSource, "get_spot_quotes", return_value={}),
            patch.object(TencentIndexSource, "get_spot_quotes", return_value={}),
            patch.object(XueqiuIndexSource, "get_spot_quotes", return_value={}),
            patch(
                "app.modules.fund_nav.data_sources.akshare.eastmoney_index_source.ak.index_zh_a_hist",
                side_effect=AssertionError("index daily fallback should not be used for NAV estimate quotes"),
            ),
        ):
            quotes = AkshareSource().get_index_quotes(["930997.CSI"])

        self.assertEqual(quotes, [])

    def test_index_quote_sources_record_success_and_failure_stats(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        seed_default_index_quote_source_statuses(db)
        db.commit()
        snapshot = MarketQuoteSnapshot(
            asset_code="399395",
            asset_name="国证有色",
            asset_type="index",
            market="CN",
            trade_date=date(2026, 7, 8),
            quote_time=datetime(2026, 7, 8, 10, 30),
            latest_price=Decimal("9409.938"),
            prev_close=Decimal("9352.435"),
            change_rate=Decimal("0.00615"),
        )

        try:
            with (
                patch.object(EastmoneyHttpIndexSource, "get_spot_quotes", return_value={}),
                patch.object(EastmoneyIndexSource, "get_spot_quotes", return_value={}),
                patch.object(SinaIndexSource, "get_spot_quotes", return_value={"399395": snapshot}),
            ):
                quotes = AkshareSource(db).get_index_quotes(["399395"])
            eastmoney_status = db.scalar(
                select(IndexQuoteSourceStatus).where(IndexQuoteSourceStatus.source_key == "eastmoney_spot")
            )
            sina_status = db.scalar(
                select(IndexQuoteSourceStatus).where(IndexQuoteSourceStatus.source_key == "sina_spot")
            )
        finally:
            db.close()

        self.assertEqual(len(quotes), 1)
        self.assertEqual(eastmoney_status.failure_count, 1)
        self.assertEqual(eastmoney_status.consecutive_failures, 1)
        self.assertEqual(sina_status.success_count, 1)
        self.assertEqual(sina_status.consecutive_failures, 0)

    def test_index_quote_source_records_exception_message_when_source_raises(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        seed_default_index_quote_source_statuses(db)
        db.commit()
        snapshot = MarketQuoteSnapshot(
            asset_code="399395",
            asset_name="国证有色",
            asset_type="index",
            market="CN",
            trade_date=date(2026, 7, 8),
            quote_time=datetime(2026, 7, 8, 10, 30),
            latest_price=Decimal("9409.938"),
            prev_close=Decimal("9352.435"),
            change_rate=Decimal("0.00615"),
        )

        try:
            with (
                patch.object(EastmoneyHttpIndexSource, "get_spot_quotes", side_effect=ConnectionError("proxy refused")),
                patch.object(EastmoneyIndexSource, "get_spot_quotes", return_value={"399395": snapshot}),
            ):
                quotes = AkshareSource(db).get_index_quotes(["399395"])
            eastmoney_http_status = db.scalar(
                select(IndexQuoteSourceStatus).where(IndexQuoteSourceStatus.source_key == "eastmoney_http_spot")
            )
        finally:
            db.close()

        self.assertEqual(len(quotes), 1)
        self.assertEqual(eastmoney_http_status.failure_count, 1)
        self.assertIn("proxy refused", eastmoney_http_status.last_error)
        self.assertNotEqual(eastmoney_http_status.last_error, "no quote matched")

    def test_index_quote_sources_use_success_rate_to_adjust_realtime_order(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        seed_default_index_quote_source_statuses(db)
        eastmoney_status = db.scalar(
            select(IndexQuoteSourceStatus).where(IndexQuoteSourceStatus.source_key == "eastmoney_spot")
        )
        sina_status = db.scalar(
            select(IndexQuoteSourceStatus).where(IndexQuoteSourceStatus.source_key == "sina_spot")
        )
        eastmoney_status.failure_count = 10
        eastmoney_status.consecutive_failures = 4
        sina_status.success_count = 10
        db.commit()
        snapshot = MarketQuoteSnapshot(
            asset_code="399395",
            asset_name="国证有色",
            asset_type="index",
            market="CN",
            trade_date=date(2026, 7, 8),
            quote_time=datetime(2026, 7, 8, 10, 30),
            latest_price=Decimal("9409.938"),
            prev_close=Decimal("9352.435"),
            change_rate=Decimal("0.00615"),
        )

        try:
            with (
                patch.object(EastmoneyHttpIndexSource, "get_spot_quotes", return_value={}),
                patch.object(EastmoneyIndexSource, "get_spot_quotes", return_value={}) as eastmoney_spot,
                patch.object(SinaIndexSource, "get_spot_quotes", return_value={"399395": snapshot}) as sina_spot,
            ):
                quotes = AkshareSource(db).get_index_quotes(["399395"])
        finally:
            db.close()

        self.assertEqual(len(quotes), 1)
        sina_spot.assert_called_once()
        eastmoney_spot.assert_not_called()

    def test_index_quote_source_is_disabled_after_long_consecutive_failures(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        service = IndexQuoteSourceStatusService(db)
        service.seed_defaults()

        try:
            for _ in range(DISABLE_FAILURES):
                service.record_failure("eastmoney_spot")
            status = db.scalar(
                select(IndexQuoteSourceStatus).where(IndexQuoteSourceStatus.source_key == "eastmoney_spot")
            )
            ordered_sources = service.ordered_sources("realtime")
        finally:
            db.close()

        self.assertEqual(status.enabled, 0)
        self.assertNotIn("eastmoney_spot", [item.source_key for item in ordered_sources])

    def test_index_quote_source_status_api_returns_default_sources(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            rows = index_quote_sources(db)
        finally:
            db.close()

        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["source_key"], "eastmoney_http_spot")
        self.assertEqual(rows[0]["source_type_label"], "实时")
        self.assertEqual(rows[0]["status_label"], "启用")
        self.assertIn("effective_priority", rows[0])

    def test_refresh_index_related_mappings_includes_index_and_etf_funds(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add_all(
            [
                Fund(
                    id=1,
                    fund_code="501009",
                    fund_name="汇添富中证生物科技指数(LOF)A",
                    fund_type="指数型-股票",
                ),
                Fund(id=2, fund_code="515450", fund_name="红利低波ETF", fund_type="指数型-股票"),
                Fund(id=3, fund_code="018125", fund_name="永赢先进制造智选混合发起C", fund_type="混合型"),
            ]
        )
        db.add_all(
            [
                FundIndexMapping(
                    id=1,
                    fund_code="501009",
                    index_code="OLD1",
                    index_name="旧指数1",
                    source="old",
                    confidence="low",
                ),
                FundIndexMapping(
                    id=2,
                    fund_code="515450",
                    index_code="OLD2",
                    index_name="旧指数2",
                    source="old",
                    confidence="low",
                ),
            ]
        )
        db.commit()
        source = Mock()
        source.get_mapping.side_effect = lambda code: FundIndexMappingSnapshot(
            fund_code=code,
            index_code=f"{code}.IDX",
            index_name=f"测试指数{code}",
            benchmark_text=None,
            source="test",
            confidence="high",
        )

        try:
            mappings = FundIndexMappingService(db, source).refresh_mappings_for_index_related_funds()
            saved_codes = sorted(
                row.fund_code
                for row in db.scalars(select(FundIndexMapping).order_by(FundIndexMapping.fund_code)).all()
            )
        finally:
            db.close()

        self.assertEqual(len(mappings), 2)
        self.assertEqual(saved_codes, ["501009", "515450"])
        self.assertEqual([call.args[0] for call in source.get_mapping.call_args_list], ["501009", "515450"])

    def test_refresh_index_catalog_upserts_indexes(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        source = Mock()
        source.get_indexes.return_value = [
            MarketIndexSnapshot(
                index_code="931027",
                index_name="中证港股通大消费主题指数",
                index_short_name="港股通大消费",
                provider="csindex",
                currency="港元",
                asset_class="股票",
                source="test",
            )
        ]

        try:
            indexes = IndexCatalogService(db, source).refresh_indexes()
            saved = db.scalar(select(MarketIndex).where(MarketIndex.index_code == "931027"))
        finally:
            db.close()

        self.assertEqual(len(indexes), 1)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.index_name, "中证港股通大消费主题指数")
        self.assertEqual(saved.provider, "csindex")

    def test_refresh_mapping_resolves_index_code_from_local_catalog(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(
            MarketIndex(
                index_code="931027",
                index_name="中证港股通大消费主题指数",
                index_short_name="港股通大消费",
                provider="csindex",
                currency="港元",
                asset_class="股票",
                source="test",
            )
        )
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="006786",
                index_code=None,
                index_name="旧指数",
                source="old",
                confidence="low",
            )
        )
        db.commit()
        source = Mock()
        source.get_mapping.return_value = FundIndexMappingSnapshot(
            fund_code="006786",
            index_code=None,
            index_name="中证港股通大消费主题港元指数",
            benchmark_text="中证港股通大消费主题指数收益率*95%+金融机构人民币活期存款利率(税后)*5%",
            source="eastmoney",
            confidence="medium",
        )

        try:
            mapping = FundIndexMappingService(db, source).refresh_mapping("006786")
        finally:
            db.close()

        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.index_code, "931027")
        self.assertEqual(mapping.index_name, "中证港股通大消费主题指数")
        self.assertEqual(mapping.source, "eastmoney+index_catalog:csindex")
        self.assertEqual(mapping.confidence, "high")

    def test_index_catalog_does_not_cross_provider_match_exact_name(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add_all(
            [
                MarketIndex(
                    index_code="932112",
                    index_name="国证有色金属行业指数",
                    index_short_name="国证有色金属",
                    provider="csindex",
                    currency="人民币",
                    asset_class="股票",
                    source="test",
                ),
                MarketIndex(
                    index_code="399395",
                    index_name="国证有色",
                    index_short_name="国证有色",
                    provider="cni",
                    currency=None,
                    asset_class=None,
                    source="test",
                ),
            ]
        )
        db.commit()

        try:
            resolved = IndexCatalogService(db).resolve_index("国证有色金属行业指数")
        finally:
            db.close()

        self.assertIsNone(resolved)

    def test_manual_index_mapping_crud_and_refresh_priority(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(Fund(id=1, fund_code="160218", fund_name="国泰国证房地产行业指数A", fund_type="指数型-股票"))
        db.add(
            FundIndexMapping(
                id=1,
                fund_code="160218",
                index_code=None,
                index_name="旧指数",
                source="old",
                confidence="low",
            )
        )
        db.commit()
        manual_service = ManualIndexMappingService(db)
        manual_service.save_mapping(
            ManualFundIndexMappingIn(
                fund_code="160218",
                mapping_type="index",
                target_code="399393",
                target_name="国证地产",
                remark="国证目录只有简称，人工维护",
            )
        )
        source = Mock()
        source.get_mapping.return_value = FundIndexMappingSnapshot(
            fund_code="160218",
            index_code=None,
            index_name="国证房地产行业指数",
            benchmark_text=None,
            source="eastmoney",
            confidence="medium",
        )

        try:
            refreshed = FundIndexMappingService(db, source).refresh_mapping("160218")
            manual = db.scalar(select(ManualFundIndexMapping).where(ManualFundIndexMapping.fund_code == "160218"))
        finally:
            db.close()

        self.assertIsNotNone(manual)
        self.assertEqual(manual.fund_name, "国泰国证房地产行业指数A")
        self.assertEqual(refreshed.index_code, "399393")
        self.assertEqual(refreshed.index_name, "国证地产")
        self.assertEqual(refreshed.source, "manual")
        source.get_mapping.assert_not_called()

    def test_manual_target_etf_mapping_used_when_web_sources_empty(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(Fund(id=1, fund_code="012805", fund_name="广发恒生科技ETF联接(QDII)A"))
        db.commit()
        ManualIndexMappingService(db).save_mapping(
            ManualFundIndexMappingIn(
                fund_code="012805",
                fund_name="广发恒生科技ETF联接(QDII)A",
                mapping_type="target_etf",
                target_code="513380",
                target_name="广发恒生科技(QDII-ETF)",
                target_market="CN",
                holding_ratio=Decimal("0.9308"),
                report_period="2024Q4",
            )
        )
        holding_source = Mock()
        holding_source.get_fund_holdings.return_value = []
        target_source = Mock()
        target_source.get_target_fund_holdings.return_value = []
        normalize_source = Mock()
        normalize_source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)

        try:
            refreshed = HoldingService(
                db,
                source=normalize_source,
                holding_sources=[holding_source],
                target_fund_sources=[target_source],
            ).refresh_holdings("12805")
            detail = FundService(db, normalize_source).get_fund_detail("012805")
        finally:
            db.close()

        self.assertEqual(len(refreshed), 1)
        self.assertEqual(refreshed[0].asset_code, "513380")
        self.assertEqual(refreshed[0].asset_name, "广发恒生科技(QDII-ETF)")
        self.assertEqual(refreshed[0].source, "manual:target_etf")
        self.assertEqual(detail["target_etf_code"], "513380")
        self.assertEqual(detail["target_etf_source"], "manual:target_etf")

    def test_fund_detail_includes_target_etf_from_target_holding(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(Fund(id=1, fund_code="018172", fund_name="华泰柏瑞中证电力全指ETF发起式联接A"))
        db.add_all(
            [
                FundHolding(
                    id=1,
                    fund_code="018172",
                    report_period="2026Q1",
                    asset_code="561560",
                    asset_name="电力ETF华泰柏瑞",
                    asset_type="etf",
                    market="CN",
                    holding_ratio=Decimal("1"),
                    holding_value=None,
                    source="local:fund_name_match",
                ),
                FundHolding(
                    id=2,
                    fund_code="018172",
                    report_period="2026Q1",
                    asset_code="510300",
                    asset_name="沪深300ETF",
                    asset_type="etf",
                    market="CN",
                    holding_ratio=Decimal("0.1"),
                    holding_value=None,
                    source="akshare:portfolio",
                ),
            ]
        )
        db.commit()
        source = Mock()
        source._normalize_fund_code.side_effect = lambda code: str(code).strip().zfill(6)

        try:
            detail = FundService(db, source).get_fund_detail("18172")
        finally:
            db.close()

        self.assertEqual(detail["target_etf_code"], "561560")
        self.assertEqual(detail["target_etf_name"], "电力ETF华泰柏瑞")
        self.assertEqual(detail["target_etf_source"], "local:fund_name_match")

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

    def test_etf_feeder_estimate_skips_stale_target_etf_quote(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(Fund(id=1, fund_code="018172", fund_name="华泰柏瑞中证电力全指ETF发起式联接A"))
        db.add(
            FundNav(
                id=1,
                fund_code="018172",
                nav_date=date(2026, 6, 23),
                unit_nav=Decimal("1.1906"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("-0.0103"),
                source="test",
            )
        )
        db.add(
            FundNav(
                id=2,
                fund_code="561560",
                nav_date=date(2026, 6, 23),
                unit_nav=Decimal("1.3119"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("-0.0109"),
                source="test",
            )
        )
        db.add(
            FundHolding(
                id=1,
                fund_code="018172",
                report_period="2026Q1",
                asset_code="561560",
                asset_name="电力ETF华泰柏瑞",
                asset_type="etf",
                market="CN",
                holding_ratio=Decimal("1.000000"),
                holding_value=None,
                source="local:fund_name_match",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="561560",
                asset_name="电力ETF华泰柏瑞",
                asset_type="etf",
                market="CN",
                trade_date=date(2026, 6, 23),
                quote_time=datetime(2026, 6, 24, 15, 0),
                latest_price=Decimal("1.3840"),
                prev_close=Decimal("1.3710"),
                change_rate=Decimal("0.0095"),
                source="test",
            )
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "018172"))
            result = EstimateService(db, Mock())._estimate_one(fund, datetime(2026, 6, 24, 15, 5))
        finally:
            db.close()

        self.assertEqual(result, "missing_quotes")

    def test_estimate_skips_stale_stock_quote(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(Fund(id=1, fund_code="018125", fund_name="永赢先进制造智选混合发起C"))
        db.add(
            FundNav(
                id=1,
                fund_code="018125",
                nav_date=date(2026, 6, 23),
                unit_nav=Decimal("1.0000"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0"),
                source="test",
            )
        )
        db.add(
            FundHolding(
                id=1,
                fund_code="018125",
                report_period="2026Q1",
                asset_code="689009",
                asset_name="九号公司-WD",
                asset_type="stock",
                market="SH",
                holding_ratio=Decimal("1.000000"),
                holding_value=None,
                source="test",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="689009",
                asset_name="九号公司-WD",
                asset_type="stock",
                market="SH",
                trade_date=date(2026, 6, 23),
                quote_time=datetime(2026, 6, 24, 15, 0),
                latest_price=Decimal("35.8"),
                prev_close=Decimal("34.67"),
                change_rate=Decimal("0.0326"),
                source="test",
            )
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "018125"))
            result = EstimateService(db, Mock())._estimate_one(fund, datetime(2026, 6, 24, 15, 5))
        finally:
            db.close()

        self.assertEqual(result, "missing_quotes")

    def test_estimate_skips_stale_official_nav(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(Fund(id=1, fund_code="018125", fund_name="永赢先进制造智选混合发起C"))
        db.add(
            FundNav(
                id=1,
                fund_code="018125",
                nav_date=date(2026, 6, 19),
                unit_nav=Decimal("1.0000"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0"),
                source="test",
            )
        )
        db.add(
            FundHolding(
                id=1,
                fund_code="018125",
                report_period="2026Q1",
                asset_code="689009",
                asset_name="九号公司-WD",
                asset_type="stock",
                market="SH",
                holding_ratio=Decimal("1.000000"),
                holding_value=None,
                source="test",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="689009",
                asset_name="九号公司-WD",
                asset_type="stock",
                market="SH",
                trade_date=date(2026, 6, 24),
                quote_time=datetime(2026, 6, 24, 15, 0),
                latest_price=Decimal("35.8"),
                prev_close=Decimal("34.67"),
                change_rate=Decimal("0.0326"),
                source="test",
            )
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "018125"))
            result = EstimateService(db, Mock())._estimate_one(fund, datetime(2026, 6, 24, 15, 5))
        finally:
            db.close()

        self.assertEqual(result, "stale_nav")

    def test_qdii_estimate_allows_previous_business_day_official_nav(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(
            Fund(
                id=1,
                fund_code="017436",
                fund_name="华宝纳斯达克精选股票发起式(QDII)A",
                fund_type="QDII",
            )
        )
        db.add(
            FundNav(
                id=1,
                fund_code="017436",
                nav_date=date(2026, 6, 26),
                unit_nav=Decimal("2.5000"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("0"),
                source="test",
            )
        )
        db.add(
            AssetValuationConfig(
                id=1,
                asset_type="stock",
                market="US",
                realtime_valuable=1,
                valuation_mode="quote",
                enabled=1,
            )
        )
        db.add(
            FundHolding(
                id=1,
                fund_code="017436",
                report_period="2026Q1",
                asset_code="AAPL",
                asset_name="苹果",
                asset_type="stock",
                market="US",
                holding_ratio=Decimal("1.000000"),
                holding_value=None,
                source="test",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="AAPL",
                asset_name="苹果",
                asset_type="stock",
                market="US",
                trade_date=date(2026, 6, 29),
                quote_time=datetime(2026, 6, 29, 15, 0),
                latest_price=Decimal("200"),
                prev_close=Decimal("198"),
                change_rate=Decimal("0.0100"),
                source="test",
            )
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "017436"))
            result = EstimateService(db, Mock())._estimate_one(fund, datetime(2026, 6, 29, 22, 30))
        finally:
            db.close()

        self.assertIsInstance(result, FundEstimate)
        self.assertEqual(result.base_nav_date, date(2026, 6, 26))

    def test_etf_quote_trade_date_uses_etf_spot_data_date(self) -> None:
        trade_date = AkshareSource._quote_trade_date({"数据日期": "2026-06-23"}, datetime(2026, 6, 24, 15, 0))

        self.assertEqual(trade_date, date(2026, 6, 23))

    def test_etf_feeder_estimate_uses_fresh_target_etf_quote(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        db.add(Fund(id=1, fund_code="018172", fund_name="华泰柏瑞中证电力全指ETF发起式联接A"))
        db.add(
            FundNav(
                id=1,
                fund_code="018172",
                nav_date=date(2026, 6, 23),
                unit_nav=Decimal("1.1906"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("-0.0103"),
                source="test",
            )
        )
        db.add(
            FundNav(
                id=2,
                fund_code="561560",
                nav_date=date(2026, 6, 24),
                unit_nav=Decimal("1.2880"),
                accumulated_nav=None,
                daily_growth_rate=Decimal("-0.0182"),
                source="test",
            )
        )
        db.add(
            FundHolding(
                id=1,
                fund_code="018172",
                report_period="2026Q1",
                asset_code="561560",
                asset_name="电力ETF华泰柏瑞",
                asset_type="etf",
                market="CN",
                holding_ratio=Decimal("1.000000"),
                holding_value=None,
                source="local:fund_name_match",
            )
        )
        db.add(
            MarketQuote(
                id=1,
                asset_code="561560",
                asset_name="电力ETF华泰柏瑞",
                asset_type="etf",
                market="CN",
                trade_date=date(2026, 6, 24),
                quote_time=datetime(2026, 6, 24, 14, 30),
                latest_price=Decimal("1.3840"),
                prev_close=Decimal("1.3710"),
                change_rate=Decimal("0.0095"),
                source="test",
            )
        )
        db.commit()

        try:
            fund = db.scalar(select(Fund).where(Fund.fund_code == "018172"))
            result = EstimateService(db, Mock())._estimate_one(fund, datetime(2026, 6, 24, 14, 35))
        finally:
            db.close()

        self.assertEqual(result.estimated_growth_rate, Decimal("0.009500000000"))
        self.assertEqual(result.estimated_nav, Decimal("1.2019107000000000"))

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

        with patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_open_fund_daily_em", return_value=daily_df) as daily:
            source = AkshareSource()
            first = source.get_latest_fund_nav("000001")
            second = source.get_latest_fund_nav("000002")

        self.assertIsInstance(first, FundNavSnapshot)
        self.assertIsInstance(second, FundNavSnapshot)
        self.assertEqual(daily.call_count, 1)

    def test_etf_spot_table_is_cached_for_repeated_refreshes(self) -> None:
        etf_df = pd.DataFrame([{"代码": "515450", "昨收": "1.098", "涨跌幅": "0.25"}])

        with patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_etf_spot_em", return_value=etf_df) as etf:
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
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_open_fund_daily_em", return_value=daily_df),
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.requests.get", return_value=response),
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.date") as mocked_date,
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
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_open_fund_daily_em", return_value=daily_df),
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.requests.get", return_value=response),
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.date") as mocked_date,
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
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_etf_spot_em", return_value=etf_df),
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_open_fund_daily_em", return_value=daily_df),
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.requests.get", return_value=response),
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.date") as mocked_date,
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

        with patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_etf_spot_em", side_effect=slow_fetch) as etf:
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
            "app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_etf_spot_em",
            side_effect=RuntimeError("network down"),
        ):
            result = AkshareSource._get_etf_spot_dataframe()

        self.assertIs(result, etf_df)

    def test_realtime_cache_rejects_too_old_stale_dataframe_when_refresh_fails(self) -> None:
        etf_df = pd.DataFrame([{"代码": "561560", "最新价": "1.384", "涨跌幅": "0.95"}])
        AkshareSource._dataframe_cache["fund_etf_spot_em"] = (
            etf_df,
            monotonic() - AkshareSource._realtime_stale_cache_max_age_seconds - 1,
        )

        with patch(
            "app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_etf_spot_em",
            side_effect=RuntimeError("network down"),
        ):
            with self.assertRaises(RuntimeError):
                AkshareSource._get_etf_spot_dataframe()

    def test_cn_primary_spot_source_skips_backup_when_target_is_covered(self) -> None:
        primary_df = pd.DataFrame(
            [{"代码": "600000", "名称": "浦发银行", "最新价": "10", "昨收": "9", "涨跌幅": "1"}]
        )

        with (
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.stock_zh_a_spot", return_value=primary_df),
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.stock_zh_a_spot_em") as backup,
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
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_etf_spot_em", return_value=etf_df) as etf,
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

        with patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_etf_spot_em", return_value=etf_df):
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
                "app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_etf_spot_em",
                side_effect=RuntimeError("remote disconnected"),
            ),
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.requests.get", return_value=response),
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
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_portfolio_hold_em", return_value=holding_df),
            patch(
                "app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_portfolio_bond_hold_em",
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
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_portfolio_hold_em", return_value=stock_df),
            patch("app.modules.fund_nav.data_sources.akshare.akshare_source.ak.fund_portfolio_bond_hold_em", return_value=bond_df),
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
