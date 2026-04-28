from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.fund import FundCreate, FundOut
from app.schemas.holding import FundHoldingOut
from app.services.fund_service import FundService
from app.services.fund_sync_service import sync_new_fund_data
from app.services.holding_service import HoldingService
from app.services.operation_log_service import log_fetch_error, log_task

router = APIRouter(prefix="/funds", tags=["funds"])


@router.get("", response_model=list[FundOut])
def list_funds(
    sort_by: str | None = Query(default=None, pattern="^latest_estimated_growth_rate$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> list[dict]:
    return FundService(db).list_funds(sort_by=sort_by, sort_order=sort_order)


@router.post("", response_model=FundOut, status_code=status.HTTP_201_CREATED)
def create_fund(
    payload: FundCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    started_at = datetime.now()
    service = FundService(db)
    try:
        fund = service.create_fund(payload)
    except ValueError as exc:
        db.rollback()
        log_task(db, "新增自选基金", "create_fund", "duplicate", started_at, str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        log_task(db, "新增自选基金", "create_fund", "failed", started_at, repr(exc))
        raise HTTPException(status_code=500, detail="基金添加失败，请稍后重试。") from exc
    background_tasks.add_task(sync_new_fund_data, fund.fund_code)
    log_task(db, "新增自选基金", "create_fund", "success", started_at, fund.fund_code)
    return service._fund_with_latest_data(fund)


@router.delete("/{fund_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fund(fund_code: str, db: Session = Depends(get_db)) -> Response:
    deleted = FundService(db).delete_fund(fund_code)
    if not deleted:
        raise HTTPException(status_code=404, detail="Fund not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{fund_code}", response_model=FundOut)
def get_fund(fund_code: str, db: Session = Depends(get_db)) -> dict:
    fund = FundService(db).get_fund_detail(fund_code)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund not found")
    return fund


@router.post("/{fund_code}/refresh-nav")
def refresh_nav(fund_code: str, db: Session = Depends(get_db)) -> dict:
    started_at = datetime.now()
    try:
        nav = FundService(db).refresh_nav(fund_code)
    except LookupError as exc:
        db.rollback()
        log_fetch_error(db, "akshare", "fund_nav", fund_code, str(exc))
        log_task(db, "手动刷新基金官方净值", "refresh_nav_manual", "failed", started_at, str(exc))
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        log_fetch_error(db, "akshare", "fund_nav", fund_code, repr(exc))
        log_task(db, "手动刷新基金官方净值", "refresh_nav_manual", "failed", started_at, repr(exc))
        raise HTTPException(status_code=502, detail="官方净值同步失败，请查看运行状态中的数据异常。") from exc
    if nav is None:
        message = "akshare returned no latest fund nav"
        log_fetch_error(db, "akshare", "fund_nav", fund_code, message)
        log_task(db, "手动刷新基金官方净值", "refresh_nav_manual", "partial", started_at, message)
    else:
        log_task(db, "手动刷新基金官方净值", "refresh_nav_manual", "success", started_at, fund_code)
    return {
        "fund_code": fund_code,
        "refreshed": nav is not None,
        "nav_date": nav.nav_date if nav else None,
        "unit_nav": nav.unit_nav if nav else None,
    }


@router.post("/{fund_code}/refresh-holdings")
def refresh_holdings(fund_code: str, db: Session = Depends(get_db)) -> dict:
    started_at = datetime.now()
    try:
        holdings = HoldingService(db).refresh_holdings(fund_code)
    except Exception as exc:
        db.rollback()
        log_fetch_error(db, "akshare", "holding", fund_code, repr(exc))
        log_task(db, "手动刷新基金持仓", "refresh_holding_manual", "failed", started_at, repr(exc))
        raise HTTPException(status_code=502, detail="基金持仓同步失败，请查看运行状态中的数据异常。") from exc
    if not holdings:
        message = "akshare returned no fund holdings"
        log_fetch_error(db, "akshare", "holding", fund_code, message)
        log_task(db, "手动刷新基金持仓", "refresh_holding_manual", "partial", started_at, message)
    else:
        log_task(
            db,
            "手动刷新基金持仓",
            "refresh_holding_manual",
            "success",
            started_at,
            f"holdings={len(holdings)}",
        )
    return {
        "fund_code": fund_code,
        "refreshed": len(holdings) > 0,
        "holding_count": len(holdings),
    }


@router.get("/{fund_code}/holdings", response_model=list[FundHoldingOut])
def list_holdings(fund_code: str, db: Session = Depends(get_db)):
    return HoldingService(db).list_holdings(fund_code)
