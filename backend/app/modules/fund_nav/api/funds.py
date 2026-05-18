from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.schemas.fund import FundCreate, FundOut, RefreshFundNavsRequest
from app.modules.fund_nav.schemas.holding import FundHoldingOut
from app.modules.fund_nav.services.fund_service import FundService
from app.modules.fund_nav.services.fund_sync_service import sync_new_fund_data
from app.modules.fund_nav.services.fund_index_mapping_service import FundIndexMappingService
from app.modules.fund_nav.services.holding_service import HoldingService
from app.modules.information.services.operation_log_service import finish_task, log_fetch_error, log_task, start_task

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


@router.post("/actions/refresh-navs")
def refresh_navs(
    payload: RefreshFundNavsRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    started_at = datetime.now()
    task_log = start_task(
        db,
        "批量刷新基金官方净值",
        "refresh_nav_manual_batch",
        started_at,
        "批量刷新基金官方净值执行中",
    )
    fund_codes = _resolve_fund_codes(db, payload)
    if not fund_codes:
        fund_codes = db.scalars(select(Fund.fund_code).where(Fund.enabled == 1)).all()

    service = FundService(db)
    results: list[dict] = []
    refreshed_count = 0
    from_cache_count = 0
    failed_count = 0

    for fund_code in fund_codes:
        try:
            nav = service.refresh_nav(fund_code)
        except Exception as exc:
            db.rollback()
            failed_count += 1
            log_fetch_error(db, "akshare", "fund_nav", fund_code, repr(exc))
            results.append({"fund_code": fund_code, "refreshed": False, "error": repr(exc)})
            continue

        if nav is None:
            failed_count += 1
            log_fetch_error(db, "akshare", "fund_nav", fund_code, "akshare returned no latest fund nav")
            results.append({"fund_code": fund_code, "refreshed": False})
            continue

        from_cache = nav.created_at < started_at
        if from_cache:
            from_cache_count += 1
        else:
            refreshed_count += 1
        results.append(
            {
                "fund_code": fund_code,
                "refreshed": True,
                "from_cache": from_cache,
                "nav_date": nav.nav_date,
                "unit_nav": nav.unit_nav,
            }
        )

    status_text = "success" if failed_count == 0 else "partial"
    finish_task(
        db,
        task_log,
        status_text,
        (
            f"funds={len(fund_codes)};refreshed={refreshed_count};"
            f"from_cache={from_cache_count};failed={failed_count}"
        ),
    )
    return {
        "fund_codes": fund_codes,
        "refreshed_count": refreshed_count,
        "from_cache_count": from_cache_count,
        "failed_count": failed_count,
        "results": results,
    }


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


@router.post("/{fund_code}/refresh-index-mapping")
def refresh_index_mapping(fund_code: str, db: Session = Depends(get_db)) -> dict:
    mapping = FundIndexMappingService(db).refresh_mapping(fund_code)
    return {
        "fund_code": fund_code,
        "refreshed": mapping is not None,
        "index_code": mapping.index_code if mapping else None,
        "index_name": mapping.index_name if mapping else None,
        "source": mapping.source if mapping else None,
        "confidence": mapping.confidence if mapping else None,
    }


@router.post("/{fund_code}/refresh-nav")
def refresh_nav(fund_code: str, db: Session = Depends(get_db)) -> dict:
    started_at = datetime.now()
    task_log = start_task(
        db,
        "手动刷新基金官方净值",
        "refresh_nav_manual",
        started_at,
        f"{fund_code} 执行中",
    )
    try:
        nav = FundService(db).refresh_nav(fund_code)
    except LookupError as exc:
        db.rollback()
        log_fetch_error(db, "akshare", "fund_nav", fund_code, str(exc))
        finish_task(db, task_log, "failed", str(exc))
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        log_fetch_error(db, "akshare", "fund_nav", fund_code, repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise HTTPException(status_code=502, detail="官方净值同步失败，请查看运行状态中的数据异常。") from exc
    if nav is None:
        message = "akshare returned no latest fund nav"
        log_fetch_error(db, "akshare", "fund_nav", fund_code, message)
        finish_task(db, task_log, "partial", message)
    else:
        finish_task(db, task_log, "success", fund_code)
    return {
        "fund_code": fund_code,
        "refreshed": nav is not None,
        "from_cache": nav is not None and nav.created_at < started_at,
        "nav_date": nav.nav_date if nav else None,
        "unit_nav": nav.unit_nav if nav else None,
    }


@router.post("/{fund_code}/refresh-holdings")
def refresh_holdings(fund_code: str, db: Session = Depends(get_db)) -> dict:
    started_at = datetime.now()
    task_log = start_task(
        db,
        "手动刷新基金持仓",
        "refresh_holding_manual",
        started_at,
        f"{fund_code} 执行中",
    )
    try:
        holdings = HoldingService(db).refresh_holdings(fund_code)
    except Exception as exc:
        db.rollback()
        log_fetch_error(db, "akshare", "holding", fund_code, repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise HTTPException(status_code=502, detail="基金持仓同步失败，请查看运行状态中的数据异常。") from exc
    if not holdings:
        message = "akshare returned no fund holdings"
        log_fetch_error(db, "akshare", "holding", fund_code, message)
        finish_task(db, task_log, "partial", message)
    else:
        finish_task(
            db,
            task_log,
            "success",
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
