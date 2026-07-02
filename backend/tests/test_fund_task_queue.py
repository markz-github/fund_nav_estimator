from __future__ import annotations

from datetime import date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: F401
from app.database import Base
from app.modules.fund_nav.data_sources.akshare.akshare_source import FetchDiagnostic
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_task_queue import FundTaskQueue
from app.modules.fund_nav.services.fund_task_queue_service import FundTaskQueueService
from app.modules.operations.models.task_log import TaskLog
from app.modules.operations.models.data_fetch_error import DataFetchError


class FundTaskQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(bind=engine)
        self.db = self.SessionLocal()
        self.service = FundTaskQueueService(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def test_reuses_same_pending_task_after_code_normalization(self) -> None:
        first = self.service.submit(
            "refresh_nav",
            "刷新基金官方净值",
            origin="manual",
            fund_codes=["2", "000001", "2"],
        )
        second = self.service.submit(
            "refresh_nav",
            "刷新基金官方净值",
            origin="manual",
            fund_codes=["000002", "1"],
        )

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(second.task_id, first.task_id)
        self.assertEqual(self.db.query(FundTaskQueue).count(), 1)

    def test_running_task_does_not_block_new_pending_task(self) -> None:
        first = self.service.submit("refresh_quote", "刷新持仓资产行情", origin="scheduled")
        running = self.db.get(FundTaskQueue, first.task_id)
        running.status = "running"
        self.db.commit()

        second = self.service.submit("refresh_quote", "刷新持仓资产行情", origin="manual")

        self.assertFalse(second.reused)
        self.assertNotEqual(second.task_id, first.task_id)

    def test_claims_pending_tasks_fifo(self) -> None:
        first = self.service.submit("refresh_nav", "刷新基金官方净值", origin="manual", fund_codes=["1"])
        self.service.submit("refresh_nav", "刷新基金官方净值", origin="manual", fund_codes=["2"])

        claimed = self.service.claim_next()

        self.assertEqual(claimed.id, first.task_id)
        self.assertEqual(claimed.status, "running")

    def test_recovers_running_tasks_as_failed(self) -> None:
        submitted = self.service.submit("refresh_quote", "刷新持仓资产行情", origin="scheduled")
        task = self.db.get(FundTaskQueue, submitted.task_id)
        task.status = "running"
        task_log = self.db.get(TaskLog, submitted.task_log_id)
        task_log.status = "running"
        self.db.commit()

        recovered = self.service.recover_interrupted()

        self.assertEqual(recovered, 1)
        self.assertEqual(self.db.get(FundTaskQueue, submitted.task_id).status, "failed")
        self.assertEqual(self.db.get(TaskLog, submitted.task_log_id).status, "failed")

    def test_pending_task_log_is_created_with_queue_task(self) -> None:
        submitted = self.service.submit("estimate_nav", "估算基金当日净值", origin="manual")

        task = self.db.scalar(select(FundTaskQueue).where(FundTaskQueue.id == submitted.task_id))
        task_log = self.db.get(TaskLog, submitted.task_log_id)

        self.assertEqual(task.status, "pending")
        self.assertEqual(task_log.status, "pending")

    def test_refresh_quote_records_upstream_failure_in_task_log(self) -> None:
        submitted = self.service.submit("refresh_quote", "刷新持仓资产行情", origin="manual")
        task = self.db.get(FundTaskQueue, submitted.task_id)
        task.status = "running"
        self.db.commit()

        class FakeMarketService:
            def __init__(self, db):
                self.last_refresh_diagnostics = [
                    FetchDiagnostic("error", "akshare", "fund_etf_spot_em", "fetch failed: RemoteDisconnected")
                ]

            def refresh_quotes_for_holdings(self, fund_codes=None):
                return [object()]

        with patch("app.modules.fund_nav.services.fund_task_queue_service.MarketService", FakeMarketService):
            self.service.execute(submitted.task_id)

        task_log = self.db.get(TaskLog, submitted.task_log_id)
        self.assertEqual(task_log.status, "partial")
        self.assertIn("upstream_errors=1", task_log.message)
        self.assertIn("fund_etf_spot_em", task_log.message)
        fetch_error = self.db.scalar(select(DataFetchError))
        self.assertEqual(fetch_error.source, "akshare")

    def test_check_nav_quality_task_records_partial_when_stale_nav_exists(self) -> None:
        self.db.add(Fund(id=1, fund_code="000001", fund_name="测试基金"))
        self.db.commit()
        submitted = self.service.submit("check_nav_quality", "检查基金官方净值新鲜度", origin="scheduled")
        task = self.db.get(FundTaskQueue, submitted.task_id)
        task.status = "running"
        self.db.commit()

        with patch(
            "app.modules.fund_nav.services.fund_task_queue_service.FundNavQualityService.expected_nav_date",
            return_value=date(2026, 6, 8),
        ):
            self.service.execute(submitted.task_id)

        task_log = self.db.get(TaskLog, submitted.task_log_id)
        fetch_error = self.db.scalar(select(DataFetchError))
        self.assertEqual(task_log.status, "partial")
        self.assertIn("stale=1", task_log.message)
        self.assertEqual(fetch_error.source, "quality_check")

    def test_refresh_holding_task_also_refreshes_index_mappings(self) -> None:
        submitted = self.service.submit(
            "refresh_holding",
            "刷新基金持仓",
            origin="manual",
            fund_codes=["501009"],
        )
        task = self.db.get(FundTaskQueue, submitted.task_id)
        task.status = "running"
        self.db.commit()

        calls: dict[str, list] = {"holdings": [], "mappings": []}

        class FakeHoldingService:
            def __init__(self, db):
                pass

            def refresh_holdings(self, fund_code):
                calls["holdings"].append(fund_code)
                return [object()]

        class FakeFundIndexMappingService:
            def __init__(self, db):
                pass

            def refresh_mappings_for_index_related_funds(self, fund_codes=None):
                calls["mappings"].append(fund_codes)
                return [object(), object()]

        with (
            patch("app.modules.fund_nav.services.fund_task_queue_service.HoldingService", FakeHoldingService),
            patch(
                "app.modules.fund_nav.services.fund_task_queue_service.FundIndexMappingService",
                FakeFundIndexMappingService,
            ),
        ):
            self.service.execute(submitted.task_id)

        task_log = self.db.get(TaskLog, submitted.task_log_id)
        self.assertEqual(task_log.status, "success")
        self.assertIn("holdings=1", task_log.message)
        self.assertIn("index_mappings=2", task_log.message)
        self.assertEqual(calls["holdings"], ["501009"])
        self.assertEqual(calls["mappings"], [["501009"]])

    def test_refresh_index_catalog_task_records_count(self) -> None:
        submitted = self.service.submit("refresh_index_catalog", "刷新指数目录", origin="manual")
        task = self.db.get(FundTaskQueue, submitted.task_id)
        task.status = "running"
        self.db.commit()

        class FakeIndexCatalogService:
            def __init__(self, db):
                pass

            def refresh_indexes(self):
                return [object(), object(), object()]

        with patch("app.modules.fund_nav.services.fund_task_queue_service.IndexCatalogService", FakeIndexCatalogService):
            self.service.execute(submitted.task_id)

        task_log = self.db.get(TaskLog, submitted.task_log_id)
        self.assertEqual(task_log.status, "success")
        self.assertIn("indexes=3", task_log.message)

    def test_concurrent_identical_submissions_reuse_one_pending_task(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine)

        def submit_task(_):
            with SessionLocal() as db:
                return FundTaskQueueService(db).submit(
                    "refresh_nav",
                    "刷新基金官方净值",
                    origin="manual",
                    fund_codes=["000001"],
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(submit_task, range(2)))

        with SessionLocal() as db:
            self.assertEqual(db.query(FundTaskQueue).count(), 1)
        self.assertEqual({result.task_id for result in results}, {results[0].task_id})
        self.assertEqual(sum(result.reused for result in results), 1)


if __name__ == "__main__":
    unittest.main()
