from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InformationVideoSource(Base):
    __tablename__ = "information_video_sources"
    __table_args__ = (
        Index("uk_information_video_source_platform_external", "platform", "external_source_id", unique=True),
        Index("idx_information_video_sources_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    external_source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[int] = mapped_column(nullable=False, default=1)
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    remark: Mapped[Optional[str]] = mapped_column(String(255))
    raw_response: Mapped[Optional[str]] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
