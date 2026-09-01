from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, BigInteger, Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FundDailySummary(Base):
    __tablename__ = "fund_daily_summaries"
    __table_args__ = (
        UniqueConstraint("summary_date", "fund_code", name="uk_fund_daily_summary"),
        Index("idx_fund_daily_summary_date", "summary_date"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    summary_date: Mapped[date] = mapped_column(Date, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False)
    latest_data_date: Mapped[Optional[date]] = mapped_column(Date)
    latest_growth_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    trend_direction: Mapped[Optional[str]] = mapped_column(String(10))
    trend_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    trend_days_capped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    trend_start_date: Mapped[Optional[date]] = mapped_column(Date)
    trend_end_date: Mapped[Optional[date]] = mapped_column(Date)
    trend_cumulative_growth_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 8))
    rule_matches_json: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
