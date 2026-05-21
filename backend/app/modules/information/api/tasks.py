from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.information.models.data_fetch_error import DataFetchError
from app.modules.information.models.task_log import TaskLog
from app.modules.information.models.video import InformationVideo
from app.modules.information.models.video_note import InformationVideoNote
from app.modules.information.schemas.task import TaskLogOut

router = APIRouter(prefix="/tasks", tags=["tasks"])

INFORMATION_TASK_TYPES = {
    "scan_information_videos",
    "generate_information_video_notes",
    "submit_information_video_note_task",
    "poll_information_video_notes",
    "generate_information_summary_documents",
    "generate_information_weekly_summary_documents",
    "generate_information_custom_summary",
    "retry_information_summary_document",
    "push_information_summary_documents",
}


def _message_error(message: str | None) -> str | None:
    if not message or ";error=" not in message:
        return None
    return message.rsplit(";error=", 1)[1] or None


def _note_error_for_task_log(db: Session, log: TaskLog) -> str | None:
    if log.task_type != "submit_information_video_note_task" or log.target_type != "video" or not log.target_id:
        return None
    if log.status not in {"failed", "partial"}:
        return None
    if not log.target_id.isdigit():
        return None
    video_id = int(log.target_id)
    note = db.scalar(
        select(InformationVideoNote)
        .where(InformationVideoNote.video_id == video_id, InformationVideoNote.status == "failed")
        .order_by(InformationVideoNote.id.desc())
    )
    if note is not None and note.error_message:
        return note.error_message

    video = db.get(InformationVideo, video_id)
    if video is None:
        return None
    error = db.scalar(
        select(DataFetchError)
        .where(
            DataFetchError.data_type.in_(["video_note", "article_note"]),
            DataFetchError.target_code == video.external_video_id,
        )
        .order_by(DataFetchError.occurred_at.desc())
    )
    return error.error_message if error is not None else None


def _task_log_out(db: Session, log: TaskLog) -> dict[str, object]:
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
        "error_message": _message_error(log.message) or _note_error_for_task_log(db, log),
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
    logs = db.scalars(statement.order_by(TaskLog.started_at.desc()).limit(limit)).all()
    return [_task_log_out(db, log) for log in logs]
