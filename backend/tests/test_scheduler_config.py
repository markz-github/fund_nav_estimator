from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: F401
from app.database import Base
from app.modules.information.models.task_log import TaskLog
from app.scheduler.jobs import (
    create_scheduler,
    generate_information_summary_documents_job,
    generate_information_video_notes_job,
    poll_information_summary_documents_job,
    push_information_summary_documents_job,
    scan_information_videos_job,
)


def settings(fund_enabled: bool, information_enabled: bool):
    return SimpleNamespace(
        scheduler_fund_enabled=fund_enabled,
        scheduler_information_enabled=information_enabled,
        scheduler_refresh_nav_cron="0 20 * * *",
        scheduler_refresh_profiles_cron="10 19 * * *",
        scheduler_refresh_holdings_cron="30 20 * * mon-fri",
        scheduler_refresh_quotes_cron="0,30 9-15 * * mon-fri",
        scheduler_estimate_nav_cron="5,35 9-15 * * mon-fri",
        scheduler_scan_videos_cron="*/3 * * * *",
        scheduler_generate_video_notes_interval_seconds=30,
        scheduler_generate_summary_documents_cron="0 7 * * *",
        scheduler_poll_summary_documents_interval_seconds=30,
        scheduler_push_summary_documents_cron="0 8 * * *",
    )


class SchedulerConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(bind=engine)

    def task_logs(self) -> list[TaskLog]:
        db = self.SessionLocal()
        try:
            return db.query(TaskLog).order_by(TaskLog.started_at).all()
        finally:
            db.close()

    def test_create_scheduler_can_register_only_fund_jobs(self) -> None:
        with patch("app.scheduler.jobs.get_settings", return_value=settings(True, False)):
            scheduler = create_scheduler()

        self.assertEqual(
            {job.id for job in scheduler.get_jobs()},
            {
                "refresh_fund_navs",
                "refresh_fund_profiles",
                "refresh_fund_holdings",
                "refresh_market_quotes",
                "estimate_fund_navs",
            },
        )

    def test_create_scheduler_can_register_only_information_jobs(self) -> None:
        with patch("app.scheduler.jobs.get_settings", return_value=settings(False, True)):
            scheduler = create_scheduler()

        self.assertEqual(
            {job.id for job in scheduler.get_jobs()},
            {
                "scan_information_videos",
                "generate_information_video_notes",
                "generate_information_summary_documents",
                "poll_information_summary_documents",
                "push_information_summary_documents",
            },
        )

    def test_scheduled_video_notes_job_does_not_log_empty_poll_and_submit(self) -> None:
        service = Mock()
        service.poll_running_notes.return_value = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "started": 0,
            "expired": 0,
        }
        service.submit_pending_note_task.return_value = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "started": 0,
            "expired": 0,
            "video_id": None,
            "note_id": None,
            "external_task_id": None,
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            generate_information_video_notes_job()

        self.assertEqual(self.task_logs(), [])

    def test_scheduled_video_notes_job_logs_poll_when_running_task_exists(self) -> None:
        service = Mock()
        service.poll_running_notes.return_value = {
            "total": 1,
            "completed": 0,
            "failed": 0,
            "running": 1,
            "started": 0,
            "expired": 0,
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            generate_information_video_notes_job()

        logs = self.task_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].task_type, "poll_information_video_notes")
        self.assertEqual(logs[0].status, "success")
        service.submit_pending_note_task.assert_not_called()

    def test_scheduled_video_notes_job_logs_actual_submit(self) -> None:
        service = Mock()
        service.poll_running_notes.return_value = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "started": 0,
            "expired": 0,
        }
        service.submit_pending_note_task.return_value = {
            "total": 1,
            "completed": 0,
            "failed": 0,
            "running": 1,
            "started": 1,
            "expired": 0,
            "video_id": 42,
            "note_id": 7,
            "external_task_id": "task-42",
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            generate_information_video_notes_job()

        logs = self.task_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].task_type, "submit_information_video_note_task")
        self.assertEqual(logs[0].status, "success")
        self.assertEqual(logs[0].target_type, "video")
        self.assertEqual(logs[0].target_id, "42")
        self.assertEqual(logs[0].external_task_id, "task-42")

    def test_scheduled_video_notes_job_logs_submit_error_message(self) -> None:
        service = Mock()
        service.poll_running_notes.return_value = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "started": 0,
            "expired": 0,
        }
        service.submit_pending_note_task.return_value = {
            "total": 1,
            "completed": 0,
            "failed": 1,
            "running": 0,
            "started": 0,
            "expired": 0,
            "video_id": 42,
            "note_id": 7,
            "external_task_id": None,
            "error_message": "ConnectionError('bilinote unavailable')",
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            generate_information_video_notes_job()

        logs = self.task_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].task_type, "submit_information_video_note_task")
        self.assertEqual(logs[0].status, "failed")
        self.assertIn("bilinote unavailable", logs[0].message or "")

    def test_scheduled_scan_job_does_not_log_when_no_video_created(self) -> None:
        service = Mock()
        service.scan_next_source.return_value = {"source_id": 3, "created": 0}

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            scan_information_videos_job()

        self.assertEqual(self.task_logs(), [])

    def test_scheduled_scan_job_logs_error_message_when_scan_fails(self) -> None:
        service = Mock()
        service.scan_next_source.return_value = {
            "source_id": 3,
            "created": 0,
            "error_message": "source_id=3;error=RuntimeError('Bilibili API returned code=-799')",
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            scan_information_videos_job()

        logs = self.task_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].task_type, "scan_information_videos")
        self.assertEqual(logs[0].status, "failed")
        self.assertIn("code=-799", logs[0].message or "")

    def test_scheduled_summary_job_does_not_log_when_no_document_created(self) -> None:
        service = Mock()
        service.create_daily_summary.return_value = None

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            generate_information_summary_documents_job()

        self.assertEqual(self.task_logs(), [])

    def test_scheduled_summary_job_uses_yesterday_as_summary_date(self) -> None:
        service = Mock()
        service.create_daily_summary.return_value = None

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            generate_information_summary_documents_job()

        expected_date = date.today() - timedelta(days=1)
        service.create_daily_summary.assert_called_once_with(platform="bilibili", summary_date=expected_date)

    def test_scheduled_summary_poll_job_does_not_log_empty_poll(self) -> None:
        service = Mock()
        service.poll_running_summary_documents.return_value = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "expired": 0,
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            poll_information_summary_documents_job()

        self.assertEqual(self.task_logs(), [])

    def test_scheduled_summary_poll_job_logs_completed_document(self) -> None:
        service = Mock()
        service.poll_running_summary_documents.return_value = {
            "total": 1,
            "completed": 1,
            "failed": 0,
            "running": 0,
            "expired": 0,
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            poll_information_summary_documents_job()

        logs = self.task_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].task_type, "poll_information_summary_documents")
        self.assertEqual(logs[0].status, "success")

    def test_scheduled_wechat_push_does_not_log_when_no_document_pushed(self) -> None:
        service = Mock()
        service.push_daily_summary_to_wechat.return_value = {
            "pushed": 0,
            "document_id": None,
            "message": "no done daily summary document",
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.VideoInformationService", return_value=service),
        ):
            push_information_summary_documents_job()

        self.assertEqual(self.task_logs(), [])


if __name__ == "__main__":
    unittest.main()
