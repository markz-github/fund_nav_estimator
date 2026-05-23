from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InformationSummaryDocument(Base):
    __tablename__ = "information_summary_documents"
    __table_args__ = (
        Index(
            "uk_information_summary_documents_platform_date_category_task",
            "platform",
            "summary_date",
            "category",
            "summary_task_config_id",
            unique=True,
        ),
        Index("idx_information_summary_documents_status", "status"),
        Index("idx_information_summary_documents_date_category", "summary_date", "category"),
        Index("idx_information_summary_documents_task_config", "summary_task_config_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    summary_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="财经", server_default="财经")
    summary_task_config_id: Mapped[Optional[int]] = mapped_column(ForeignKey("information_summary_task_configs.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    hermes_run_id: Mapped[Optional[str]] = mapped_column(String(100))
    document_text: Mapped[Optional[str]] = mapped_column(Text().with_variant(LONGTEXT, "mysql"))
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


class InformationSummaryDocumentItem(Base):
    __tablename__ = "information_summary_document_items"
    __table_args__ = (
        Index("uk_information_summary_document_items_doc_note", "document_id", "note_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("information_summary_documents.id"), nullable=False)
    note_id: Mapped[int] = mapped_column(ForeignKey("information_video_notes.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
