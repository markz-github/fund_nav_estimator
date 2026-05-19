from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.modules.information.models.video_source import InformationVideoSource


class InformationVideo(Base):
    __tablename__ = "information_videos"
    __table_args__ = (
        Index("uk_information_videos_platform_external", "platform", "external_video_id", unique=True),
        Index("idx_information_videos_source", "source_id"),
        Index("idx_information_videos_status", "status"),
        Index("idx_information_videos_published_at", "published_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("information_video_sources.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    external_video_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    video_url: Mapped[str] = mapped_column(String(500), nullable=False)
    author_name: Mapped[Optional[str]] = mapped_column(String(100))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="discovered")
    raw_response: Mapped[Optional[str]] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    source: Mapped[InformationVideoSource] = relationship(lazy="joined")

    @property
    def source_name(self) -> str | None:
        return self.source.source_name if self.source is not None else None
