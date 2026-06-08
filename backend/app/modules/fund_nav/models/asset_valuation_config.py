from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AssetValuationConfig(Base):
    __tablename__ = "asset_valuation_configs"
    __table_args__ = (
        UniqueConstraint("asset_type", "market", name="uk_asset_valuation_config"),
        Index("idx_asset_valuation_config_type_market", "asset_type", "market"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False)
    market: Mapped[str] = mapped_column(String(20), nullable=False, default="*", server_default="*")
    realtime_valuable: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    valuation_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="none", server_default="none")
    enabled: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    remark: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
