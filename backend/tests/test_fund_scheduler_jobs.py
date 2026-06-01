from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.scheduler.fund_jobs import refresh_fund_navs_job


class FundSchedulerJobTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
