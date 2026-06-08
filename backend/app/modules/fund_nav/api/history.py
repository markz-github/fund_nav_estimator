from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.modules.fund_nav.schemas.history import (
    FundNavHistorySyncRequest,
    FundNavHistorySyncStartOut,
    FundNavHistorySyncStatusOut,
    FundNavHistoryTaskDetailOut,
    FundNavHistoryTaskListOut,
)
from app.modules.fund_nav.services.history_sync_service import FundNavHistorySyncService


router = APIRouter(prefix="/fund-nav/history-sync", tags=["fund-nav-history"])


@router.post("/start", response_model=FundNavHistorySyncStartOut, status_code=status.HTTP_202_ACCEPTED)
def start_history_sync(payload: FundNavHistorySyncRequest) -> dict[str, object]:
    return FundNavHistorySyncService().start(payload)


@router.get("/status", response_model=FundNavHistorySyncStatusOut)
def get_history_sync_status(
    start_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
    end_date: str | None = Query(default=None, pattern=r"^\d{8}$"),
) -> dict[str, object]:
    return FundNavHistorySyncService().status(start_date=start_date, end_date=end_date)


@router.post("/stop", status_code=status.HTTP_202_ACCEPTED)
def stop_history_sync() -> dict[str, object]:
    return FundNavHistorySyncService().stop()


@router.get("/tasks", response_model=FundNavHistoryTaskListOut)
def list_history_sync_tasks() -> dict[str, object]:
    return {"tasks": FundNavHistorySyncService().list_tasks()}


@router.get("/tasks/{task_id}", response_model=FundNavHistoryTaskDetailOut)
def get_history_sync_task(task_id: int) -> dict[str, object]:
    task = FundNavHistorySyncService().task_detail(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post("/tasks/{task_id}/rerun", response_model=FundNavHistorySyncStartOut, status_code=status.HTTP_202_ACCEPTED)
def rerun_history_sync_task(task_id: int) -> dict[str, object]:
    try:
        return FundNavHistorySyncService().rerun_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
