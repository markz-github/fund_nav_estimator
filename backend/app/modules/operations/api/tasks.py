from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.operations.models.task_log import TaskLog
from app.modules.operations.schemas.task import TaskLogOptionsOut, TaskLogPageOut
from app.modules.operations.status_enums import FUND_NAV_TASK_TYPES, TASK_STATUSES, status_options

router = APIRouter(prefix="/tasks", tags=["tasks"])
FUND_NAV_TASK_TYPE_VALUES = {option.value for option in FUND_NAV_TASK_TYPES}


def _message_error(message: str | None) -> str | None:
    if not message or ";error=" not in message:
        return None
    return message.rsplit(";error=", 1)[1] or None


def _task_log_out(log: TaskLog) -> dict[str, object]:
    return {
        "id": log.id,
        "task_name": log.task_name,
        "task_type": log.task_type,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "external_task_id": log.external_task_id,
        "status": log.status,
        "started_at": log.started_at,
        "finished_at": log.finished_at,
        "duration_ms": log.duration_ms,
        "message": log.message,
        "error_message": _message_error(log.message),
    }


@router.get("/status-options", response_model=TaskLogOptionsOut)
def get_task_log_options():
    return {
        "task_statuses": status_options(TASK_STATUSES),
        "fund_nav_task_types": status_options(FUND_NAV_TASK_TYPES),
    }


@router.get("/logs", response_model=TaskLogPageOut)
def list_task_logs(
    limit: int = 20,
    page: int = 1,
    page_size: int | None = None,
    module: str | None = None,
    task_type: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    effective_page_size = max(1, min(page_size or limit, 200))
    effective_page = max(1, page)
    statement = select(TaskLog)
    if module == "fund_nav":
        statement = statement.where(TaskLog.task_type.in_(FUND_NAV_TASK_TYPE_VALUES))
    if task_type:
        statement = statement.where(TaskLog.task_type == task_type)
    if status:
        statement = statement.where(TaskLog.status == status)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    if total > 0:
        max_page = (total + effective_page_size - 1) // effective_page_size
        effective_page = min(effective_page, max_page)
    logs = db.scalars(
        statement.order_by(TaskLog.started_at.desc())
        .offset((effective_page - 1) * effective_page_size)
        .limit(effective_page_size)
    ).all()
    return {
        "items": [_task_log_out(log) for log in logs],
        "total": total,
        "page": effective_page,
        "page_size": effective_page_size,
    }
