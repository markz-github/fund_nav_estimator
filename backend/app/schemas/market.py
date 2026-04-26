from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class MarketQuoteOut(BaseModel):
    asset_code: str
    asset_name: str | None = None
    asset_type: str
    market: str | None = None
    trade_date: date
    quote_time: datetime
    latest_price: Decimal | None = None
    prev_close: Decimal | None = None
    change_rate: Decimal | None = None
    source: str

    model_config = {"from_attributes": True}
