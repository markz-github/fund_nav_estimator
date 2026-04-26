from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FundNav(Base):
    __tablename__ = "fund_navs"
    __table_args__ = (
        UniqueConstraint("fund_code", "nav_date", name="uk_fund_nav"),
        Index("idx_fund_nav_date", "nav_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    nav_date: Mapped[date] = mapped_column(Date, nullable=False)
    unit_nav: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    accumulated_nav: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    daily_growth_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
