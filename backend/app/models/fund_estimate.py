from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FundEstimate(Base):
    __tablename__ = "fund_estimates"
    __table_args__ = (
        UniqueConstraint("fund_code", "estimate_time", name="uk_fund_estimate"),
        Index("idx_fund_estimate_date", "estimate_date"),
        Index("idx_fund_estimate_fund_date", "fund_code", "estimate_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False)
    estimate_date: Mapped[date] = mapped_column(Date, nullable=False)
    estimate_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    base_nav_date: Mapped[date] = mapped_column(Date, nullable=False)
    base_unit_nav: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    estimated_growth_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    estimated_nav: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    coverage_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    source_snapshot: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
