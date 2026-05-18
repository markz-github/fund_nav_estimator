from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Fund(Base):
    __tablename__ = "funds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    fund_name: Mapped[str] = mapped_column(String(100), nullable=False)
    fund_type: Mapped[Optional[str]] = mapped_column(String(50))
    enabled: Mapped[int] = mapped_column(default=1, nullable=False)
    remark: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
