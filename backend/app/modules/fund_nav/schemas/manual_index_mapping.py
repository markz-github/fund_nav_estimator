from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ManualFundIndexMappingIn(BaseModel):
    fund_code: str = Field(min_length=1, max_length=20)
    fund_name: str | None = Field(default=None, max_length=100)
    index_code: str = Field(min_length=1, max_length=30)
    index_name: str = Field(min_length=1, max_length=150)
    benchmark_text: str | None = None
    remark: str | None = Field(default=None, max_length=255)


class ManualFundIndexMappingOut(BaseModel):
    id: int
    fund_code: str
    fund_name: str | None = None
    index_code: str
    index_name: str
    benchmark_text: str | None = None
    remark: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
