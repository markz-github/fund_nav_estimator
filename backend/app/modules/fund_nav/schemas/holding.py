from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class FundHoldingOut(BaseModel):
    fund_code: str
    report_period: str
    asset_code: str
    asset_name: str
    asset_type: str
    market: str | None = None
    holding_ratio: Decimal
    holding_value: Decimal | None = None
    source: str

    model_config = {"from_attributes": True}
