from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.information.models.data_fetch_error import DataFetchError
from app.modules.information.schemas.error import DataFetchErrorOut

router = APIRouter(prefix="/errors", tags=["errors"])

INFORMATION_DATA_TYPES = {
    "video_scan",
    "video_note",
    "summary_document",
}


@router.get("", response_model=list[DataFetchErrorOut])
def list_errors(
    limit: int = 100,
    unresolved_only: bool = False,
    module: str | None = None,
    db: Session = Depends(get_db),
):
    statement = select(DataFetchError)
    if unresolved_only:
        statement = statement.where(DataFetchError.resolved == 0)
    if module == "information":
        statement = statement.where(DataFetchError.data_type.in_(INFORMATION_DATA_TYPES))
    elif module == "fund_nav":
        statement = statement.where(DataFetchError.data_type.not_in(INFORMATION_DATA_TYPES))
    return db.scalars(
        statement.order_by(DataFetchError.occurred_at.desc()).limit(limit)
    ).all()
