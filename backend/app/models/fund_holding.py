from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FundHolding(Base):
    __tablename__ = "fund_holdings"
    __table_args__ = (
        UniqueConstraint("fund_code", "report_period", "asset_code", name="uk_fund_holding"),
        Index("idx_fund_holding_fund", "fund_code"),
        Index("idx_fund_holding_asset", "asset_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False)
    report_period: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_code: Mapped[str] = mapped_column(String(30), nullable=False)
    asset_name: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False)
    market: Mapped[Optional[str]] = mapped_column(String(20))
    holding_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    holding_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
