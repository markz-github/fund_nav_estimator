from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FundTaskDetailLog(Base):
    __tablename__ = "fund_task_detail_logs"
    __table_args__ = (
        Index("idx_fund_task_detail_task", "task_log_id"),
        Index("idx_fund_task_detail_fund_time", "fund_code", "created_at"),
        UniqueConstraint("fund_code", "estimate_date", name="uk_fund_task_detail_daily"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    task_log_id: Mapped[Optional[int]] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("task_logs.id"))
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False)
    fund_name: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy: Mapped[Optional[str]] = mapped_column(String(50))
    reason: Mapped[Optional[str]] = mapped_column(String(100))
    estimate_date: Mapped[date] = mapped_column(Date, nullable=False)
    estimate_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    estimated_nav: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    estimated_growth_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    coverage_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    source_snapshot: Mapped[Optional[str]] = mapped_column(String(255))
    message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
