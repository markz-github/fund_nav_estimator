from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.modules.a_stock.schemas import (
    AStockHistoryTaskDetailOut,
    AStockHistoryTaskListOut,
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


@router.post("/history-sync/stop", status_code=status.HTTP_202_ACCEPTED)
def stop_history_sync() -> dict[str, object]:
    return AStockHistorySyncService().stop()


@router.get("/history-sync/tasks", response_model=AStockHistoryTaskListOut)
def list_history_sync_tasks() -> dict[str, object]:
    return {"tasks": AStockHistorySyncService().list_tasks()}


@router.get("/history-sync/tasks/{task_id}", response_model=AStockHistoryTaskDetailOut)
def get_history_sync_task(task_id: int) -> dict[str, object]:
    task = AStockHistorySyncService().task_detail(task_id)
    if task is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post(
    "/history-sync/tasks/{task_id}/rerun",
    response_model=AStockHistorySyncStartOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def rerun_history_sync_task(task_id: int) -> dict[str, object]:
    try:
        return AStockHistorySyncService().rerun_task(task_id)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/history-sync/tasks/{task_id}/rerun-failed",
    response_model=AStockHistorySyncStartOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def rerun_failed_history_sync_task(task_id: int) -> dict[str, object]:
    return rerun_history_sync_task(task_id)
