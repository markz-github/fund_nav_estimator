from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.data_fetch_error import DataFetchError
from app.models.task_log import TaskLog


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
) -> None:
    finished_at = datetime.now()
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    db.add(
        TaskLog(
            task_name=task_name,
            task_type=task_type,
            status=status,
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
) -> TaskLog:
    task_log = TaskLog(
        task_name=task_name,
        task_type=task_type,
        status="running",
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
) -> None:
    finished_at = datetime.now()
    task_log.status = status
    task_log.finished_at = finished_at
    task_log.duration_ms = int((finished_at - task_log.started_at).total_seconds() * 1000)
    task_log.message = message[:2000]
    db.commit()
