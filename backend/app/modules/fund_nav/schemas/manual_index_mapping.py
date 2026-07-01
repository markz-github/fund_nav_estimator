from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ManualFundIndexMappingIn(BaseModel):
    fund_code: str = Field(min_length=1, max_length=20)
    fund_name: str | None = Field(default=None, max_length=100)
    mapping_type: Literal["index", "target_etf"] = "index"
    target_code: str = Field(min_length=1, max_length=30)
    target_name: str = Field(min_length=1, max_length=150)
    target_market: str | None = Field(default=None, max_length=20)
    holding_ratio: Decimal | None = None
    holding_value: Decimal | None = None
    report_period: str | None = Field(default=None, max_length=20)
    benchmark_text: str | None = None
    remark: str | None = Field(default=None, max_length=255)


class ManualFundIndexMappingOut(BaseModel):
    id: int
    fund_code: str
    fund_name: str | None = None
    mapping_type: str
    target_code: str
    target_name: str
    target_market: str | None = None
    holding_ratio: Decimal | None = None
    holding_value: Decimal | None = None
    report_period: str | None = None
    benchmark_text: str | None = None
    remark: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PendingManualFundMappingOut(BaseModel):
    id: int
    fund_code: str
    fund_name: str | None = None
    mapping_type: str
    reason: str | None = None
    action: str | None = None
    occurred_at: datetime
    message: str
