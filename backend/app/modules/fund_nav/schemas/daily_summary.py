from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class FundSummaryRuleIn(BaseModel):
    id: int | None = None
    rule_name: str = Field(min_length=1, max_length=100)
    window_days: int = Field(ge=1, le=3650)
    rise_threshold: Decimal = Field(gt=0, le=10)
    fall_threshold: Decimal = Field(gt=0, le=10)
    enabled: int = Field(default=1, ge=0, le=1)


class FundSummaryRuleOut(FundSummaryRuleIn):
    id: int

    model_config = {"from_attributes": True}


class FundSummaryRuleMatchOut(BaseModel):
    rule_id: int
    rule_name: str
    window_days: int
    direction: str
    growth_rate: Decimal
    threshold: Decimal


class FundDailySummaryItemOut(BaseModel):
    fund_code: str
    latest_data_date: date | None = None
    latest_growth_rate: Decimal | None = None
    trend_direction: str | None = None
    trend_days: int = 0
    trend_days_capped: bool = False
    trend_start_date: date | None = None
    trend_end_date: date | None = None
    trend_cumulative_growth_rate: Decimal | None = None
    rule_matches: list[FundSummaryRuleMatchOut] = Field(default_factory=list)


class FundDailySummaryOut(BaseModel):
    summary_date: date | None = None
    generated_at: datetime | None = None
    items: list[FundDailySummaryItemOut]
