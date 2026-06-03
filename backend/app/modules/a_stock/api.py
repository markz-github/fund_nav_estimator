from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.modules.a_stock.schemas import (
    AStockHistorySyncRequest,
    AStockHistorySyncStartOut,
    AStockHistorySyncStatusOut,
)
from app.modules.a_stock.service import AStockHistorySyncService

router = APIRouter(prefix="/a-stocks", tags=["a-stocks"])


@router.post(
    "/history-sync/start",
    response_model=AStockHistorySyncStartOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_history_sync(payload: AStockHistorySyncRequest) -> dict[str, object]:
    return AStockHistorySyncService().start(payload)


@router.get("/history-sync/status", response_model=AStockHistorySyncStatusOut)
def get_history_sync_status(
    start_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    end_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
) -> dict[str, object]:
    return AStockHistorySyncService().status(start_date=start_date, end_date=end_date)
