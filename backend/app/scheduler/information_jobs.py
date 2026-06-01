from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.modules.information.services.note_service import NoteService
from app.modules.information.services.operation_log_service import log_task, task_status_from_counts
from app.modules.information.services.source_service import SourceService
from app.modules.information.services.summary_document_service import SummaryDocumentService
from app.modules.information.services.summary_task_config_service import SummaryTaskConfigService
from app.scheduler.cron_utils import normalize_cron_expression


SUMMARY_TASK_CONFIG_JOB_PREFIX = "generate_information_summary_task_config_"


def _video_note_task_status(result: dict[str, int | str | None]) -> str:
    if result.get("error_message") or int(result["failed"]) > 0:
        if int(result["completed"]) > 0 or int(result["running"]) > 0 or int(result["started"]) > 0:
            return "partial"
        return "failed"
    if int(result["running"]) > 0 or int(result["started"]) > 0:
        return "success"
    return task_status_from_counts(success=int(result["completed"]), skipped=1 if int(result["total"]) == 0 else 0)


def _video_note_task_message(result: dict[str, int | str | None]) -> str:
    message = (
        f"total={result['total']};completed={result['completed']};"
        f"failed={result['failed']};running={result['running']};"
        f"started={result['started']};expired={result['expired']}"
    )
    error_message = result.get("error_message")
    return f"{message};error={error_message}" if error_message else message


def _video_note_poll_should_log(result: dict[str, int | str | None]) -> bool:
    return bool(result.get("error_message")) or int(result["completed"]) > 0 or int(result["failed"]) > 0 or int(result["expired"]) > 0


def _summary_document_poll_status(result: dict[str, int]) -> str:
    if result["failed"] > 0 or result.get("wechat_failed", 0) > 0:
        if result["completed"] > 0 or result["running"] > 0 or result.get("wechat_pushed", 0) > 0:
            return "partial"
        return "failed"
    if result["running"] > 0:
        return "success"
    return task_status_from_counts(success=result["completed"], failed=result["failed"], skipped=1 if result["total"] == 0 else 0)


def _summary_document_poll_message(result: dict[str, int]) -> str:
    return (
        f"total={result['total']};completed={result['completed']};"
        f"failed={result['failed']};running={result['running']};expired={result['expired']};"
        f"wechat_pushed={result.get('wechat_pushed', 0)};wechat_failed={result.get('wechat_failed', 0)}"
    )


def _summary_document_poll_should_log(result: dict[str, int]) -> bool:
    return result["completed"] > 0 or result["failed"] > 0 or result["expired"] > 0 or result.get("wechat_pushed", 0) > 0 or result.get("wechat_failed", 0) > 0


def _run_task(task_name: str, task_type: str, handler, persist_skipped: bool = True) -> None:
    started_at = datetime.now()
    db = SessionLocal()
    try:
        status, message = handler(db)
        if status == "skipped" and not persist_skipped:
            return
        log_task(db, task_name, task_type, status, started_at, message)
    except Exception as exc:
        db.rollback()
        log_task(db, task_name, task_type, "failed", started_at, repr(exc))
    finally:
        db.close()


def scan_information_videos_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        result = SourceService(db).scan_enabled_sources()
        if result["source_count"] == 0:
            return "skipped", "no enabled video source"
        if result.get("error_message"):
            return "failed", str(result["error_message"])
        if result["created"] == 0:
            return "skipped", f"source_count={result['source_count']};created=0"
        return "success", f"source_count={result['source_count']};created={result['created']}"

    _run_task("扫描信息流视频", "scan_information_videos", handler, persist_skipped=False)


def generate_information_video_notes_job() -> None:
    db = SessionLocal()
    try:
        service = NoteService(db)
        poll_started_at = datetime.now()
        poll_result = service.poll_running_notes()
        if _video_note_poll_should_log(poll_result):
            log_task(db, "轮询信息源笔记任务", "poll_information_video_notes", _video_note_task_status(poll_result), poll_started_at, _video_note_task_message(poll_result))
        if poll_result["running"] > 0:
            return
        submit_started_at = datetime.now()
        try:
            result = service.submit_pending_note_task()
            status = _video_note_task_status(result)
            if status != "failed" and result["failed"] == 0 and (result["started"] > 0 or result["running"] > 0):
                status = "success"
            if status != "skipped":
                log_task(
                    db, "提交信息源笔记任务", "submit_information_video_note_task", status, submit_started_at,
                    _video_note_task_message(result),
                    target_type="video" if result.get("video_id") is not None else None,
                    target_id=str(result["video_id"]) if result.get("video_id") is not None else None,
                    external_task_id=result.get("external_task_id"),
                )
        except Exception as exc:
            db.rollback()
            log_task(db, "提交信息源笔记任务", "submit_information_video_note_task", "failed", submit_started_at, repr(exc))
    except Exception as exc:
        db.rollback()
        log_task(db, "轮询信息源笔记任务", "poll_information_video_notes", "failed", datetime.now(), repr(exc))
    finally:
        db.close()


def generate_information_summary_task_config_job(config_id: int) -> None:
    def handler(db: Session) -> tuple[str, str]:
        document = SummaryDocumentService(db).run_summary_task_config(config_id)
        if document is None:
            return "skipped", f"summary_task_config_id={config_id};no completed notes to summarize"
        status = "success" if document.status in {"done", "running"} else "failed"
        return status, f"summary_task_config_id={config_id};summary_date={document.summary_date};category={document.category};document_id={document.id};status={document.status}"

    _run_task("生成信息流配置汇总", "generate_information_summary_task_config", handler, persist_skipped=False)


def register_information_summary_task_config_jobs(scheduler: BackgroundScheduler) -> None:
    for job in list(scheduler.get_jobs()):
        if job.id.startswith(SUMMARY_TASK_CONFIG_JOB_PREFIX):
            scheduler.remove_job(job.id)
    db = SessionLocal()
    try:
        for config in SummaryTaskConfigService(db).list_summary_task_configs():
            if not config.enabled:
                continue
            scheduler.add_job(
                generate_information_summary_task_config_job,
                args=[config.id],
                trigger=CronTrigger.from_crontab(normalize_cron_expression(config.cron_expression)),
                id=f"{SUMMARY_TASK_CONFIG_JOB_PREFIX}{config.id}",
                name=config.task_name,
                replace_existing=True,
                max_instances=1,
            )
    finally:
        db.close()


def poll_information_summary_documents_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        result = SummaryDocumentService(db).poll_running_summary_documents()
        if not _summary_document_poll_should_log(result):
            return "skipped", _summary_document_poll_message(result)
        return _summary_document_poll_status(result), _summary_document_poll_message(result)

    _run_task("轮询 Hermes 信息流汇总任务", "poll_information_summary_documents", handler, persist_skipped=False)
