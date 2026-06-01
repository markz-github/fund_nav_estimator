from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InformationSummaryTaskConfig(Base):
    __tablename__ = "information_summary_task_configs"
    __table_args__ = (
        Index("idx_information_summary_task_configs_enabled", "enabled"),
        Index("idx_information_summary_task_configs_category", "category"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(30), nullable=False, default="bilibili", server_default="bilibili")
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="财经", server_default="财经")
    start_days_before: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False, default="0 7 * * *", server_default="0 7 * * *")
    title_template: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="{start_date:%Y-%m-%d} {platform} {category}汇总",
        server_default="{start_date:%Y-%m-%d} {platform} {category}汇总",
    )
    summary_instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    document_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    push_to_wechat: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
