from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.information.models.data_fetch_error import DataFetchError
from app.modules.information.schemas.error import DataFetchErrorOut

router = APIRouter(prefix="/errors", tags=["errors"])


@router.get("", response_model=list[DataFetchErrorOut])
def list_errors(
    limit: int = 100,
    unresolved_only: bool = False,
    db: Session = Depends(get_db),
):
    statement = select(DataFetchError)
    if unresolved_only:
        statement = statement.where(DataFetchError.resolved == 0)
    return db.scalars(
        statement.order_by(DataFetchError.occurred_at.desc()).limit(limit)
    ).all()
