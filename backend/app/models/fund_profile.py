from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FundProfile(Base):
    __tablename__ = "fund_profiles"
    __table_args__ = (
        UniqueConstraint("fund_code", name="uk_fund_profiles_code"),
        Index("idx_fund_profiles_name", "fund_name"),
        Index("idx_fund_profiles_type", "fund_type"),
        Index("idx_fund_profiles_synced_at", "synced_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False)
    fund_name: Mapped[str] = mapped_column(String(100), nullable=False)
    fund_type: Mapped[Optional[str]] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="akshare")
    synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
