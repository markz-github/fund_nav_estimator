from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, computed_field

from app.modules.operations.status_enums import TASK_STATUSES, status_label


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

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(TASK_STATUSES, self.status)

    model_config = {"from_attributes": True}


class TaskLogPageOut(BaseModel):
    items: list[TaskLogOut]
    total: int
    page: int
    page_size: int


class TaskLogOptionsOut(BaseModel):
    task_statuses: list[dict[str, str]]
    fund_nav_task_types: list[dict[str, str]]
