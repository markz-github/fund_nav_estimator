from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class FundCreate(BaseModel):
    fund_code: str = Field(min_length=1, max_length=20)
    remark: str | None = None


class FundUpdate(BaseModel):
    enabled: int | None = None
    remark: str | None = None


class FundOut(BaseModel):
    id: int
    fund_code: str
    fund_name: str
    fund_type: str | None = None
    enabled: int
    remark: str | None = None
    latest_unit_nav: Decimal | None = None
    latest_nav_date: date | None = None
    latest_estimated_nav: Decimal | None = None
    latest_estimated_growth_rate: Decimal | None = None
    latest_estimate_time: datetime | None = None
    latest_coverage_ratio: Decimal | None = None

    model_config = {"from_attributes": True}
