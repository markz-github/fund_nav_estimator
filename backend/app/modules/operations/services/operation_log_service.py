from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.operations.models.data_fetch_error import DataFetchError
from app.modules.operations.models.task_log import TaskLog

TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_PARTIAL = "partial"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_SKIPPED = "skipped"
TASK_STATUSES = {
    TASK_STATUS_PENDING,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCESS,
    TASK_STATUS_PARTIAL,
    TASK_STATUS_FAILED,
    TASK_STATUS_SKIPPED,
}


def task_status_from_counts(
    *,
    success: int = 0,
    failed: int = 0,
    skipped: int = 0,
    running: int = 0,
) -> str:
    if running > 0:
        return TASK_STATUS_RUNNING
    total = success + failed + skipped
    if total == 0:
        return TASK_STATUS_SKIPPED
    if success > 0 and failed == 0 and skipped == 0:
        return TASK_STATUS_SUCCESS
    if success == 0 and failed > 0 and skipped == 0:
        return TASK_STATUS_FAILED
    if success == 0 and failed == 0 and skipped > 0:
        return TASK_STATUS_SKIPPED
    return TASK_STATUS_PARTIAL


def normalize_task_status(status: str) -> str:
    return status if status in TASK_STATUSES else TASK_STATUS_FAILED


def log_fetch_error(
    db: Session,
    source: str,
    data_type: str,
    target_code: str,
    error_message: str,
) -> None:
    db.add(
        DataFetchError(
            source=source,
            data_type=data_type,
            target_code=target_code,
            error_message=error_message[:2000],
        )
    )


def log_task(
    db: Session,
    task_name: str,
    task_type: str,
    status: str,
    started_at: datetime,
    message: str,
    target_type: str | None = None,
    target_id: str | None = None,
    external_task_id: str | None = None,
) -> None:
    finished_at = datetime.now()
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    db.add(
        TaskLog(
            task_name=task_name,
            task_type=task_type,
            target_type=target_type,
            target_id=target_id,
            external_task_id=external_task_id,
            status=normalize_task_status(status),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            message=message[:2000],
        )
    )
    db.commit()


def start_task(
    db: Session,
    task_name: str,
    task_type: str,
    started_at: datetime,
    message: str = "running",
    target_type: str | None = None,
    target_id: str | None = None,
    external_task_id: str | None = None,
) -> TaskLog:
    task_log = TaskLog(
        task_name=task_name,
        task_type=task_type,
        target_type=target_type,
        target_id=target_id,
        external_task_id=external_task_id,
        status=TASK_STATUS_RUNNING,
        started_at=started_at,
        message=message[:2000],
    )
    db.add(task_log)
    db.commit()
    db.refresh(task_log)
    return task_log


def finish_task(
    db: Session,
    task_log: TaskLog,
    status: str,
    message: str,
    external_task_id: str | None = None,
) -> None:
    finished_at = datetime.now()
    task_log.status = normalize_task_status(status)
    task_log.finished_at = finished_at
    task_log.duration_ms = int((finished_at - task_log.started_at).total_seconds() * 1000)
    task_log.message = message[:2000]
    if external_task_id is not None:
        task_log.external_task_id = external_task_id
    db.commit()
