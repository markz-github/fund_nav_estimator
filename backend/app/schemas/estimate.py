from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class FundEstimateOut(BaseModel):
    fund_code: str
    estimate_date: date
    estimate_time: datetime
    base_nav_date: date
    base_unit_nav: Decimal
    estimated_growth_rate: Decimal | None = None
    estimated_nav: Decimal | None = None
    coverage_ratio: Decimal | None = None
    source_snapshot: str | None = None

    model_config = {"from_attributes": True}
