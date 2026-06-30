from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.scheduler.fund_jobs import check_fund_nav_quality_job, refresh_fund_navs_job, refresh_index_catalog_job
from app.config import AppConfig


class FundSchedulerJobTests(unittest.TestCase):
    def test_default_fund_scheduler_crons_run_nav_refresh_twice_before_quality_check(self) -> None:
        config = AppConfig()

        self.assertEqual(config.scheduler_refresh_nav_cron, "0 21,22 * * *")
        self.assertEqual(config.scheduler_check_nav_quality_cron, "30 22 * * mon-fri")
        self.assertEqual(config.scheduler_refresh_index_catalog_cron, "20 3 * * *")

    def test_scheduled_fund_job_only_submits_queue_task(self) -> None:
        db = Mock()
        session_context = Mock()
        session_context.__enter__ = Mock(return_value=db)
        session_context.__exit__ = Mock(return_value=False)
        service = Mock()

        with (
            patch("app.scheduler.fund_jobs.SessionLocal", return_value=session_context),
            patch("app.scheduler.fund_jobs.FundTaskQueueService", return_value=service),
        ):
            refresh_fund_navs_job()

        service.submit.assert_called_once_with(
            "refresh_nav",
            "刷新基金官方净值",
            origin="scheduled",
        )

    def test_scheduled_nav_quality_job_only_submits_queue_task(self) -> None:
        db = Mock()
        session_context = Mock()
        session_context.__enter__ = Mock(return_value=db)
        session_context.__exit__ = Mock(return_value=False)
        service = Mock()

        with (
            patch("app.scheduler.fund_jobs.SessionLocal", return_value=session_context),
            patch("app.scheduler.fund_jobs.FundTaskQueueService", return_value=service),
        ):
            check_fund_nav_quality_job()

        service.submit.assert_called_once_with(
            "check_nav_quality",
            "检查基金官方净值新鲜度",
            origin="scheduled",
        )

    def test_scheduled_index_catalog_job_only_submits_queue_task(self) -> None:
        db = Mock()
        session_context = Mock()
        session_context.__enter__ = Mock(return_value=db)
        session_context.__exit__ = Mock(return_value=False)
        service = Mock()

        with (
            patch("app.scheduler.fund_jobs.SessionLocal", return_value=session_context),
            patch("app.scheduler.fund_jobs.FundTaskQueueService", return_value=service),
        ):
            refresh_index_catalog_job()

        service.submit.assert_called_once_with(
            "refresh_index_catalog",
            "刷新指数目录",
            origin="scheduled",
        )


if __name__ == "__main__":
    unittest.main()
