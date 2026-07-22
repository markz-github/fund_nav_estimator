from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

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


class IndexQuoteSourceStatusOut(BaseModel):
    id: int
    source_key: str
    source_name: str
    source_description: str | None = None
    source_type: str
    source_type_label: str
    exclude_rule_type: str
    exclude_rule_value: str | None = None
    priority: int
    enabled: int
    success_count: int
    failure_count: int
    consecutive_failures: int
    success_rate: Decimal | None = None
    failure_rate: Decimal | None = None
    effective_priority: Decimal
    auto_disabled_until: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str | None = None
    status_label: str


class IndexQuoteSourceRuleIn(BaseModel):
    enabled: Literal[0, 1] | None = None
    source_description: str | None = None
    exclude_rule_type: str = "none"
    exclude_rule_value: str | None = None


class IndexQuoteSymbolOut(BaseModel):
    id: int
    index_code: str
    source_key: str
    quote_symbol: str | None = None
    supported: int
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IndexQuoteSymbolIn(BaseModel):
    index_code: str
    source_key: str
    quote_symbol: str | None = None
    supported: int = 1
    description: str | None = None


class IndexQuoteSymbolPageOut(BaseModel):
    items: list[IndexQuoteSymbolOut]
    total: int
    limit: int
    offset: int
