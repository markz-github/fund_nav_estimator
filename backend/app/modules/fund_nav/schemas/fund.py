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


class RefreshFundNavsRequest(BaseModel):
    fund_codes: list[str] | None = None
    fund_ids: list[int] | None = None


class FundNavOut(BaseModel):
    fund_code: str
    nav_date: date
    unit_nav: Decimal
    accumulated_nav: Decimal | None = None
    daily_growth_rate: Decimal | None = None
    source: str

    model_config = {"from_attributes": True}


class FundOut(BaseModel):
    id: int
    fund_code: str
    fund_name: str
    fund_type: str | None = None
    fund_category: str | None = None
    fund_category_label: str | None = None
    fund_category_source: str | None = None
    fund_category_updated_at: datetime | None = None
    enabled: int
    remark: str | None = None
    tracked_index_code: str | None = None
    tracked_index_name: str | None = None
    tracked_index_source: str | None = None
    tracked_index_confidence: str | None = None
    target_etf_code: str | None = None
    target_etf_name: str | None = None
    target_etf_source: str | None = None
    latest_unit_nav: Decimal | None = None
    latest_nav_date: date | None = None
    latest_daily_growth_rate: Decimal | None = None
    latest_estimated_nav: Decimal | None = None
    latest_estimated_growth_rate: Decimal | None = None
    latest_estimate_date: date | None = None
    latest_estimate_time: datetime | None = None
    latest_coverage_ratio: Decimal | None = None

    model_config = {"from_attributes": True}
