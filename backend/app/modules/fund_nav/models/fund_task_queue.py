from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FundTaskQueue(Base):
    __tablename__ = "fund_task_queue"
    __table_args__ = (
        Index("idx_fund_task_queue_status_time", "status", "queued_at"),
        Index("idx_fund_task_queue_type_time", "task_type", "queued_at"),
        Index("idx_fund_task_queue_dedupe_status", "dedupe_key", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    task_log_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    queued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger)
    message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
