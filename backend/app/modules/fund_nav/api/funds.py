from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.schemas.fund import FundCreate, FundOut, RefreshFundNavsRequest
from app.modules.fund_nav.schemas.holding import FundHoldingOut
from app.modules.fund_nav.services.fund_service import FundService
from app.modules.fund_nav.schemas.task import FundTaskSubmitOut
from app.modules.fund_nav.services.fund_task_queue_service import FundTaskQueueService
from app.modules.fund_nav.services.holding_service import HoldingService
from app.modules.information.services.operation_log_service import log_task

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
    db: Session = Depends(get_db),
):
    started_at = datetime.now()
    service = FundService(db)
    try:
        fund = service.create_fund(payload)
    except ValueError as exc:
        db.rollback()
        log_task(db, "新增自选基金", "create_fund", "skipped", started_at, f"duplicate;{exc}")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        log_task(db, "新增自选基金", "create_fund", "failed", started_at, repr(exc))
        raise HTTPException(status_code=500, detail="基金添加失败，请稍后重试。") from exc
    FundTaskQueueService(db).submit(
        "sync_new_fund_data",
        "新增基金后同步数据",
        origin="new_fund",
        payload={"fund_code": fund.fund_code},
    )
    log_task(db, "新增自选基金", "create_fund", "success", started_at, fund.fund_code)
    return service._fund_with_latest_data(fund)


@router.post("/actions/refresh-navs", response_model=FundTaskSubmitOut, status_code=status.HTTP_202_ACCEPTED)
def refresh_navs(
    payload: RefreshFundNavsRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    fund_codes = _resolve_fund_codes(db, payload)
    return FundTaskQueueService(db).submit(
        "refresh_nav", "批量刷新基金官方净值", origin="manual", fund_codes=fund_codes
    )


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


@router.post("/{fund_code}/refresh-index-mapping", response_model=FundTaskSubmitOut, status_code=status.HTTP_202_ACCEPTED)
def refresh_index_mapping(fund_code: str, db: Session = Depends(get_db)) -> dict:
    return FundTaskQueueService(db).submit(
        "refresh_index_mapping", "刷新基金指数映射", origin="manual", payload={"fund_code": fund_code}
    )


@router.post("/{fund_code}/refresh-nav", response_model=FundTaskSubmitOut, status_code=status.HTTP_202_ACCEPTED)
def refresh_nav(fund_code: str, db: Session = Depends(get_db)) -> dict:
    return FundTaskQueueService(db).submit(
        "refresh_nav", "手动刷新基金官方净值", origin="manual", fund_codes=[fund_code]
    )


@router.post("/{fund_code}/refresh-holdings", response_model=FundTaskSubmitOut, status_code=status.HTTP_202_ACCEPTED)
def refresh_holdings(fund_code: str, db: Session = Depends(get_db)) -> dict:
    return FundTaskQueueService(db).submit(
        "refresh_holding", "手动刷新基金持仓", origin="manual", fund_codes=[fund_code]
    )


@router.get("/{fund_code}/holdings", response_model=list[FundHoldingOut])
def list_holdings(fund_code: str, db: Session = Depends(get_db)):
    return HoldingService(db).list_holdings(fund_code)


def _resolve_fund_codes(db: Session, payload: RefreshFundNavsRequest | None) -> list[str]:
    if payload is None:
        return []

    codes = [code.strip() for code in (payload.fund_codes or []) if code.strip()]
    if payload.fund_ids:
        rows = db.scalars(
            select(Fund.fund_code).where(Fund.id.in_(payload.fund_ids), Fund.enabled == 1)
        ).all()
        codes.extend(rows)

    seen: set[str] = set()
    unique_codes: list[str] = []
    for code in codes:
        normalized_code = code.zfill(6) if code.isdigit() else code
        if normalized_code not in seen:
            seen.add(normalized_code)
            unique_codes.append(normalized_code)
    return unique_codes
