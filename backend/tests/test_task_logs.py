from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: F401
from app.database import Base
from app.modules.information.api.tasks import get_task_log_options, list_task_logs
from app.modules.information.models.task_log import TaskLog
from app.modules.information.services.operation_log_service import normalize_task_status, task_status_from_counts


class TaskLogTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self) -> None:
        self.db.close()

    def test_status_definitions_match_private_contract(self) -> None:
        options = get_task_log_options()

        self.assertEqual(
            [option["value"] for option in options["task_statuses"]],
            ["pending", "running", "success", "partial", "failed", "skipped"],
        )
        self.assertEqual(task_status_from_counts(success=1, failed=1), "partial")
        self.assertEqual(task_status_from_counts(), "skipped")
        self.assertEqual(normalize_task_status("unknown"), "failed")

    def test_list_task_logs_filters_and_paginates(self) -> None:
        now = datetime.now()
        self.db.add_all(
            [
                TaskLog(task_name="old", task_type="refresh_nav", status="success", started_at=now - timedelta(minutes=2)),
                TaskLog(task_name="pending", task_type="refresh_nav", status="pending", started_at=now - timedelta(minutes=1)),
                TaskLog(task_name="other", task_type="estimate_nav", status="pending", started_at=now),
            ]
        )
        self.db.commit()

        result = list_task_logs(module="fund_nav", task_type="refresh_nav", status="pending", page=1, page_size=1, db=self.db)

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["page_size"], 1)
        self.assertEqual(result["items"][0]["task_name"], "pending")

    def test_single_fund_queue_task_records_linkable_target(self) -> None:
        from app.modules.fund_nav.services.fund_task_queue_service import FundTaskQueueService

        result = FundTaskQueueService(self.db).submit(
            "refresh_nav",
            "手动刷新基金官方净值",
            origin="manual",
            fund_codes=["1"],
        )

        log = self.db.get(TaskLog, result.task_log_id)
        self.assertEqual(log.target_type, "fund")
        self.assertEqual(log.target_id, "000001")


if __name__ == "__main__":
    unittest.main()
