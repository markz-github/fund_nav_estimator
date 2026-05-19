from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InformationVideoNote(Base):
    __tablename__ = "information_video_notes"
    __table_args__ = (
        Index("idx_information_video_notes_video_provider", "video_id", "provider"),
        Index("idx_information_video_notes_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("information_videos.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="bilinote")
    external_task_id: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    note_text: Mapped[Optional[str]] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    raw_response: Mapped[Optional[str]] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
