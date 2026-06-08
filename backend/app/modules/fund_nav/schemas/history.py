from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FundNavHistorySyncRequest(BaseModel):
    mode: Literal["recent_days", "date_range"] = "recent_days"
    recent_days: int | None = Field(default=30, ge=1, le=3650)
    start_date: date | None = None
    end_date: date | None = None
    workers: int = Field(default=4, ge=1, le=16)

    @model_validator(mode="after")
    def validate_range(self) -> "FundNavHistorySyncRequest":
        if self.mode == "recent_days":
            if self.recent_days is None:
                raise ValueError("recent_days is required")
            return self
        if self.start_date is None or self.end_date is None:
            raise ValueError("start_date and end_date are required")
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class FundNavHistorySyncStartOut(BaseModel):
    task_id: int | None = None
    pid: int
    started: bool
    start_date: str
    end_date: str
    workers: int
    stdout_log: str
    stderr_log: str
    message: str


class FundNavHistoryProgressCount(BaseModel):
    status: str
    count: int


class FundNavHistoryProgressItem(BaseModel):
    fund_code: str
    fund_name: str | None = None
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    error: str | None = None


class FundNavHistorySyncStatusOut(BaseModel):
    running: bool
    task_id: int | None = None
    pid: int | None = None
    start_date: str
    end_date: str
    workers: int | None = None
    stdout_log: str | None = None
    stderr_log: str | None = None
    counts: list[FundNavHistoryProgressCount]
    latest_done: list[FundNavHistoryProgressItem]
    running_items: list[FundNavHistoryProgressItem]
    failed_items: list[FundNavHistoryProgressItem]


class FundNavHistoryTaskOut(BaseModel):
    id: int
    task_type: str
    status: str
    start_date: str
    end_date: str
    workers: int
    total_count: int
    success_count: int
    failed_count: int
    running_count: int
    skipped_count: int
    retry_count: int
    pid: int | None = None
    stdout_log: str | None = None
    stderr_log: str | None = None
    message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    created_at: datetime


class FundNavHistoryTaskListOut(BaseModel):
    tasks: list[FundNavHistoryTaskOut]


class FundNavHistoryTaskDetailOut(FundNavHistoryTaskOut):
    counts: list[FundNavHistoryProgressCount]
    latest_done: list[FundNavHistoryProgressItem]
    running_items: list[FundNavHistoryProgressItem]
    failed_items: list[FundNavHistoryProgressItem]
