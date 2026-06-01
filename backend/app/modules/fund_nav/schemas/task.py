from __future__ import annotations

from pydantic import BaseModel


class FundTaskSubmitOut(BaseModel):
    task_id: int
    task_log_id: int
    status: str
    reused: bool
    message: str
