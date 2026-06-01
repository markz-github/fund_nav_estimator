from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.operations.models.task_log import TaskLog
from app.modules.operations.schemas.task import TaskLogPageOut

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/logs", response_model=TaskLogPageOut)
def list_task_logs(
    limit: int = 20,
    page: int = 1,
    page_size: int | None = None,
    task_type: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    effective_page_size = max(1, min(page_size or limit, 200))
    effective_page = max(1, page)
    statement = select(TaskLog)
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
        "items": logs,
        "total": total,
        "page": effective_page,
        "page_size": effective_page_size,
    }
