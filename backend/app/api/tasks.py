from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.task_log import TaskLog
from app.schemas.task import TaskLogOut

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/logs", response_model=list[TaskLogOut])
def list_task_logs(limit: int = 100, db: Session = Depends(get_db)):
    return db.scalars(
        select(TaskLog).order_by(TaskLog.started_at.desc()).limit(limit)
    ).all()
