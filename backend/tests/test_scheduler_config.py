from __future__ import annotations

from datetime import date, datetime, timedelta
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
from app.modules.information.api.tasks import list_task_logs
from app.modules.information.models.summary_task_config import InformationSummaryTaskConfig
from app.modules.information.models.task_log import TaskLog
from app.modules.information.models.video import InformationVideo
from app.modules.information.models.video_note import InformationVideoNote
from app.modules.information.models.video_source import InformationVideoSource
from app.scheduler.jobs import (
    create_scheduler,
    generate_information_summary_task_config_job,
    generate_information_video_notes_job,
    poll_information_summary_documents_job,
    register_information_summary_task_config_jobs,
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
        scheduler_poll_summary_documents_interval_seconds=30,
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
        db = self.SessionLocal()
        try:
            db.add(
                InformationSummaryTaskConfig(
                    task_name="财经日汇总",
                    platform="bilibili",
                    category="财经",
                    start_days_before=1,
                    cron_expression="0 7 * * *",
                    enabled=1,
                )
            )
            db.add(
                InformationSummaryTaskConfig(
                    task_name="财经周汇总",
                    platform="bilibili",
                    category="财经",
                    start_days_before=7,
                    cron_expression="30 7 * * mon",
                    enabled=1,
                )
            )
            db.commit()
        finally:
            db.close()

        with (
            patch("app.scheduler.jobs.get_settings", return_value=settings(False, True)),
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
        ):
            scheduler = create_scheduler()

        self.assertEqual(
            {job.id for job in scheduler.get_jobs()},
            {
                "scan_information_videos",
                "generate_information_video_notes",
                "generate_information_summary_task_config_1",
                "generate_information_summary_task_config_2",
                "poll_information_summary_documents",
            },
        )

    def test_register_summary_config_jobs_uses_standard_numeric_weekday_cron(self) -> None:
        db = self.SessionLocal()
        try:
            config = InformationSummaryTaskConfig(
                task_name="财经周汇总",
                platform="bilibili",
                category="财经",
                start_days_before=7,
                cron_expression="0 7 * * 1",
                enabled=1,
            )
            db.add(config)
            db.commit()
            config_id = config.id
        finally:
            db.close()

        with (
            patch("app.scheduler.jobs.get_settings", return_value=settings(False, True)),
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
        ):
            scheduler = create_scheduler()
            register_information_summary_task_config_jobs(scheduler)

        job = scheduler.get_job(f"generate_information_summary_task_config_{config_id}")
        next_fire = job.trigger.get_next_fire_time(None, datetime(2026, 5, 25, 6, 50, tzinfo=scheduler.timezone))

        self.assertEqual(next_fire, datetime(2026, 5, 25, 7, 0, tzinfo=scheduler.timezone))

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
            patch("app.scheduler.jobs.NoteService", return_value=service),
        ):
            generate_information_video_notes_job()

        self.assertEqual(self.task_logs(), [])

    def test_scheduled_video_notes_job_does_not_log_poll_when_only_running_task_exists(self) -> None:
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
            patch("app.scheduler.jobs.NoteService", return_value=service),
        ):
            generate_information_video_notes_job()

        self.assertEqual(self.task_logs(), [])
        service.submit_pending_note_task.assert_not_called()

    def test_scheduled_video_notes_job_logs_poll_error_message(self) -> None:
        service = Mock()
        service.poll_running_notes.return_value = {
            "total": 1,
            "completed": 0,
            "failed": 1,
            "running": 0,
            "started": 0,
            "expired": 0,
            "error_message": "Bilinote task failed in external service",
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
            "error_message": None,
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.NoteService", return_value=service),
        ):
            generate_information_video_notes_job()

        logs = self.task_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].task_type, "poll_information_video_notes")
        self.assertEqual(logs[0].status, "failed")
        self.assertIn("external service", logs[0].message or "")

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
            patch("app.scheduler.jobs.NoteService", return_value=service),
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
            patch("app.scheduler.jobs.NoteService", return_value=service),
        ):
            generate_information_video_notes_job()

        logs = self.task_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].task_type, "submit_information_video_note_task")
        self.assertEqual(logs[0].status, "failed")
        self.assertIn("bilinote unavailable", logs[0].message or "")

    def test_scheduled_video_notes_job_marks_mixed_submit_result_partial(self) -> None:
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
            "total": 2,
            "completed": 0,
            "failed": 1,
            "running": 1,
            "started": 1,
            "expired": 0,
            "video_id": 42,
            "note_id": 7,
            "external_task_id": "task-42",
            "error_message": "one note failed",
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.NoteService", return_value=service),
        ):
            generate_information_video_notes_job()

        logs = self.task_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].task_type, "submit_information_video_note_task")
        self.assertEqual(logs[0].status, "partial")
        self.assertIn("one note failed", logs[0].message or "")

    def test_scheduled_scan_job_does_not_log_when_no_video_created(self) -> None:
        service = Mock()
        service.scan_enabled_sources.return_value = {"source_count": 3, "created": 0}

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.SourceService", return_value=service),
        ):
            scan_information_videos_job()

        self.assertEqual(self.task_logs(), [])

    def test_scheduled_scan_job_logs_error_message_when_scan_fails(self) -> None:
        service = Mock()
        service.scan_enabled_sources.return_value = {
            "source_count": 3,
            "created": 0,
            "error_message": "source_id=3;error=RuntimeError('Bilibili API returned code=-400')",
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.SourceService", return_value=service),
        ):
            scan_information_videos_job()

        logs = self.task_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].task_type, "scan_information_videos")
        self.assertEqual(logs[0].status, "failed")
        self.assertIn("code=-400", logs[0].message or "")

    def test_task_log_list_enriches_submit_note_error_message(self) -> None:
        db = self.SessionLocal()
        try:
            source = InformationVideoSource(
                platform="bilibili",
                source_name="测试账号",
                external_source_id="12345",
                enabled=1,
            )
            db.add(source)
            db.commit()
            video = InformationVideo(
                source_id=source.id,
                platform="bilibili",
                external_video_id="BV-error",
                title="失败视频",
                video_url="https://www.bilibili.com/video/BV-error",
                status="note_failed",
            )
            db.add(video)
            db.commit()
            db.add(
                InformationVideoNote(
                    video_id=video.id,
                    provider="bilinote",
                    status="failed",
                    error_message="Bilinote 服务不可用",
                )
            )
            db.add(
                TaskLog(
                    task_name="提交信息源笔记任务",
                    task_type="submit_information_video_note_task",
                    target_type="video",
                    target_id=str(video.id),
                    status="failed",
                    started_at=datetime.now(),
                    message="total=1;completed=0;failed=1;running=0;started=0;expired=0",
                )
            )
            db.commit()

            logs = list_task_logs(module="information", db=db)
        finally:
            db.close()

        self.assertEqual(logs["items"][0]["error_message"], "Bilinote 服务不可用")

    def test_task_log_list_does_not_enrich_success_submit_with_old_note_error(self) -> None:
        db = self.SessionLocal()
        try:
            source = InformationVideoSource(
                platform="bilibili",
                source_name="测试账号",
                external_source_id="12345",
                enabled=1,
            )
            db.add(source)
            db.commit()
            video = InformationVideo(
                source_id=source.id,
                platform="bilibili",
                external_video_id="BV-running",
                title="运行中视频",
                video_url="https://www.bilibili.com/video/BV-running",
                status="note_running",
            )
            db.add(video)
            db.commit()
            db.add(
                InformationVideoNote(
                    video_id=video.id,
                    provider="bilinote",
                    status="failed",
                    error_message="InvalidSchema('Missing dependencies for SOCKS support.')",
                )
            )
            db.add(
                TaskLog(
                    task_name="提交信息源笔记任务",
                    task_type="submit_information_video_note_task",
                    target_type="video",
                    target_id=str(video.id),
                    external_task_id="task-running",
                    status="success",
                    started_at=datetime.now(),
                    message="total=1;completed=0;failed=0;running=1;started=1;expired=0",
                )
            )
            db.commit()

            logs = list_task_logs(module="information", db=db)
        finally:
            db.close()

        self.assertIsNone(logs["items"][0]["error_message"])

    def test_scheduled_summary_task_config_job_does_not_log_when_no_document_created(self) -> None:
        service = Mock()
        service.run_summary_task_config.return_value = None

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.SummaryDocumentService", return_value=service),
        ):
            generate_information_summary_task_config_job(7)

        self.assertEqual(self.task_logs(), [])

    def test_scheduled_summary_task_config_job_uses_config_id(self) -> None:
        service = Mock()
        service.run_summary_task_config.return_value = None

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.SummaryDocumentService", return_value=service),
        ):
            generate_information_summary_task_config_job(7)

        service.run_summary_task_config.assert_called_once_with(7)

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
            patch("app.scheduler.jobs.SummaryDocumentService", return_value=service),
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
            patch("app.scheduler.jobs.SummaryDocumentService", return_value=service),
        ):
            poll_information_summary_documents_job()

        logs = self.task_logs()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].task_type, "poll_information_summary_documents")
        self.assertEqual(logs[0].status, "success")

    def test_scheduled_summary_poll_job_does_not_log_when_only_running_document_exists(self) -> None:
        service = Mock()
        service.poll_running_summary_documents.return_value = {
            "total": 1,
            "completed": 0,
            "failed": 0,
            "running": 1,
            "expired": 0,
        }

        with (
            patch("app.scheduler.jobs.SessionLocal", self.SessionLocal),
            patch("app.scheduler.jobs.SummaryDocumentService", return_value=service),
        ):
            poll_information_summary_documents_job()

        self.assertEqual(self.task_logs(), [])

if __name__ == "__main__":
    unittest.main()
