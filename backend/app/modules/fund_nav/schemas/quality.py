from __future__ import annotations

from datetime import datetime
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class FundNavQualityIssueOut(BaseModel):
    id: int
    issue_type: str
    fund_code: str
    fund_name: str | None = None
    latest_nav_date: str | None = None
    expected_nav_date: str | None = None
    nav_rule: str | None = None
    mapping_type: str | None = None
    action: str | None = None
    reason: str | None = None
    occurred_at: datetime
    message: str


class FundNavQualityTaskOut(BaseModel):
    id: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    message: str | None = None


class FundNavQualityReportOut(BaseModel):
    latest_task: FundNavQualityTaskOut | None = None
    issue_count: int
    issues: list[FundNavQualityIssueOut]


class EstimateDriftFundSummaryOut(BaseModel):
    fund_code: str
    fund_name: str
    comparable_count: int
    max_difference_rate: Decimal | None = None
    avg_difference_rate: Decimal | None = None
    recent_7_trading_day_difference_rate: Decimal | None = None
    latest_date: date | None = None
    latest_difference_rate: Decimal | None = None
    threshold_exceeded_count: int = 0


class EstimateDriftPointOut(BaseModel):
    fund_code: str
    estimate_date: date
    estimate_time: datetime
    estimated_nav: Decimal
    official_nav: Decimal
    absolute_difference: Decimal
    difference_rate: Decimal
    coverage_ratio: Decimal | None = None
    base_nav_date: date
    threshold_exceeded: bool = False


class EstimateDriftDetailOut(BaseModel):
    fund_code: str
    fund_name: str | None = None
    start_date: date
    end_date: date
    threshold: Decimal | None = None
    comparable_count: int
    max_difference_rate: Decimal | None = None
    avg_difference_rate: Decimal | None = None
    threshold_exceeded_count: int = 0
    points: list[EstimateDriftPointOut]
