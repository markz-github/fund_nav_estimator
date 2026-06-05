from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AStockHistorySyncRequest(BaseModel):
    mode: Literal["recent_days", "date_range"] = "recent_days"
    recent_days: int | None = Field(default=10, ge=1, le=3650)
    start_date: date | None = None
    end_date: date | None = None
    workers: int = Field(default=8, ge=1, le=16)

    @model_validator(mode="after")
    def validate_range(self) -> "AStockHistorySyncRequest":
        if self.mode == "recent_days":
            if self.recent_days is None:
                raise ValueError("recent_days is required")
            return self
        if self.start_date is None or self.end_date is None:
            raise ValueError("start_date and end_date are required")
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class AStockHistorySyncStartOut(BaseModel):
    task_id: int | None = None
    pid: int
    started: bool
    start_date: str
    end_date: str
    workers: int
    stdout_log: str
    stderr_log: str
    message: str


class AStockProgressCount(BaseModel):
    status: str
    count: int


class AStockProgressItem(BaseModel):
    symbol: str
    stock_name: str | None = None
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    error: str | None = None


class AStockHistorySyncStatusOut(BaseModel):
    running: bool
    task_id: int | None = None
    pid: int | None = None
    start_date: str
    end_date: str
    workers: int | None = None
    stdout_log: str | None = None
    stderr_log: str | None = None
    counts: list[AStockProgressCount]
    latest_done: list[AStockProgressItem]
    running_items: list[AStockProgressItem]
    failed_items: list[AStockProgressItem]


class AStockHistoryTaskOut(BaseModel):
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


class AStockHistoryTaskListOut(BaseModel):
    tasks: list[AStockHistoryTaskOut]


class AStockHistoryTaskDetailOut(AStockHistoryTaskOut):
    counts: list[AStockProgressCount]
    latest_done: list[AStockProgressItem]
    running_items: list[AStockProgressItem]
    failed_items: list[AStockProgressItem]
