from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FundIndexMapping(Base):
    __tablename__ = "fund_index_mappings"
    __table_args__ = (
        UniqueConstraint("fund_code", name="uk_fund_index_mapping_code"),
        Index("idx_fund_index_mapping_index_code", "index_code"),
        Index("idx_fund_index_mapping_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False)
    index_code: Mapped[Optional[str]] = mapped_column(String(30))
    index_name: Mapped[Optional[str]] = mapped_column(String(100))
    benchmark_text: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
