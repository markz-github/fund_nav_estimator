from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FundLatestSnapshot(Base):
    __tablename__ = "fund_latest_snapshots"

    fund_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    latest_nav_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    latest_estimate_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    target_etf_holding_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
