from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ManualFundIndexMapping(Base):
    __tablename__ = "manual_fund_mappings"
    __table_args__ = (
        UniqueConstraint("fund_code", "mapping_type", name="uk_manual_fund_mapping_code_type"),
        Index("idx_manual_fund_mapping_target_code", "target_code"),
        Index("idx_manual_fund_mapping_type", "mapping_type"),
        Index("idx_manual_fund_mapping_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False)
    fund_name: Mapped[Optional[str]] = mapped_column(String(100))
    mapping_type: Mapped[str] = mapped_column(String(30), nullable=False, default="index", server_default="index")
    target_code: Mapped[str] = mapped_column(String(30), nullable=False)
    target_name: Mapped[str] = mapped_column(String(150), nullable=False)
    target_market: Mapped[Optional[str]] = mapped_column(String(20))
    holding_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6))
    holding_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    report_period: Mapped[Optional[str]] = mapped_column(String(20))
    benchmark_text: Mapped[Optional[str]] = mapped_column(Text)
    remark: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def index_code(self) -> str:
        return self.target_code

    @index_code.setter
    def index_code(self, value: str) -> None:
        self.target_code = value

    @property
    def index_name(self) -> str:
        return self.target_name

    @index_name.setter
    def index_name(self, value: str) -> None:
        self.target_name = value
