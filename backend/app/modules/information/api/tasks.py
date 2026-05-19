from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.information.models.task_log import TaskLog
from app.modules.information.schemas.task import TaskLogOut

router = APIRouter(prefix="/tasks", tags=["tasks"])

INFORMATION_TASK_TYPES = {
    "scan_information_videos",
    "generate_information_video_notes",
    "submit_information_video_note_task",
    "poll_information_video_notes",
    "generate_information_summary_documents",
    "generate_information_custom_summary",
    "retry_information_summary_document",
    "push_information_summary_documents",
}


@router.get("/logs", response_model=list[TaskLogOut])
def list_task_logs(
    limit: int = 100,
    module: str | None = None,
    task_type: str | None = None,
    db: Session = Depends(get_db),
):
    statement = select(TaskLog)
    if module == "information":
        statement = statement.where(TaskLog.task_type.in_(INFORMATION_TASK_TYPES))
    elif module == "fund_nav":
        statement = statement.where(TaskLog.task_type.not_in(INFORMATION_TASK_TYPES))
    if task_type:
        statement = statement.where(TaskLog.task_type == task_type)
    return db.scalars(statement.order_by(TaskLog.started_at.desc()).limit(limit)).all()
