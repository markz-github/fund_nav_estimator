from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IndexQuoteSymbol(Base):
    __tablename__ = "index_quote_symbols"
    __table_args__ = (
        UniqueConstraint("index_code", "source_key", name="uk_index_quote_symbol_code_source"),
        Index("idx_index_quote_symbol_source", "source_key", "supported"),
        Index("idx_index_quote_symbol_code", "index_code"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    index_code: Mapped[str] = mapped_column(String(30), nullable=False)
    source_key: Mapped[str] = mapped_column(String(50), nullable=False)
    quote_symbol: Mapped[Optional[str]] = mapped_column(String(80))
    supported: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    description: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
