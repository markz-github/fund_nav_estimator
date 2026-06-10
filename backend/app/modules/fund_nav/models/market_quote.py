from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MarketQuote(Base):
    __tablename__ = "market_quotes"
    __table_args__ = (
        UniqueConstraint("asset_code", "quote_time", name="uk_market_quote"),
        Index("idx_market_quote_asset_date", "asset_code", "trade_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    asset_code: Mapped[str] = mapped_column(String(30), nullable=False)
    asset_name: Mapped[Optional[str]] = mapped_column(String(100))
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False)
    market: Mapped[Optional[str]] = mapped_column(String(20))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    quote_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    latest_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6))
    prev_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6))
    change_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
