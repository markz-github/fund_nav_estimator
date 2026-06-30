from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ManualFundIndexMapping(Base):
    __tablename__ = "manual_fund_index_mappings"
    __table_args__ = (
        UniqueConstraint("fund_code", name="uk_manual_fund_index_mapping_code"),
        Index("idx_manual_fund_index_mapping_index_code", "index_code"),
        Index("idx_manual_fund_index_mapping_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False)
    fund_name: Mapped[Optional[str]] = mapped_column(String(100))
    index_code: Mapped[str] = mapped_column(String(30), nullable=False)
    index_name: Mapped[str] = mapped_column(String(150), nullable=False)
    benchmark_text: Mapped[Optional[str]] = mapped_column(Text)
    remark: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
