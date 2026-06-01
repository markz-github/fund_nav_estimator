from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DataFetchErrorOut(BaseModel):
    id: int
    source: str
    data_type: str
    target_code: str
    error_message: str
    occurred_at: datetime
    resolved: int

    model_config = {"from_attributes": True}
