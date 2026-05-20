from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TaskLogOut(BaseModel):
    id: int
    task_name: str
    task_type: str
    target_type: str | None = None
    target_id: str | None = None
    external_task_id: str | None = None
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    message: str | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}
