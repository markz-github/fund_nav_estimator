from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MarketIndex(Base):
    __tablename__ = "market_indexes"
    __table_args__ = (
        UniqueConstraint("provider", "index_code", name="uk_market_index_provider_code"),
        Index("idx_market_index_code", "index_code"),
        Index("idx_market_index_name", "index_name"),
        Index("idx_market_index_short_name", "index_short_name"),
        Index("idx_market_index_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    index_code: Mapped[str] = mapped_column(String(30), nullable=False)
    index_name: Mapped[str] = mapped_column(String(150), nullable=False)
    index_short_name: Mapped[Optional[str]] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(String(20))
    asset_class: Mapped[Optional[str]] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_snapshot: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
