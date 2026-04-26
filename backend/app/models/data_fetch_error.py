from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DataFetchError(Base):
    __tablename__ = "data_fetch_errors"
    __table_args__ = (
        Index("idx_fetch_errors_target", "target_code"),
        Index("idx_fetch_errors_time", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_code: Mapped[str] = mapped_column(String(30), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    resolved: Mapped[int] = mapped_column(default=0, nullable=False)
