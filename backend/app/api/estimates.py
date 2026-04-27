from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.fund import Fund
from app.schemas.estimate import FundEstimateOut, RefreshAndEstimateRequest
from app.services.estimate_service import EstimateService
from app.services.market_service import MarketService
from app.services.operation_log_service import log_fetch_error, log_task

router = APIRouter(prefix="/estimates", tags=["estimates"])


@router.get("/latest", response_model=list[FundEstimateOut])
def latest_estimates(db: Session = Depends(get_db)):
    return EstimateService(db).latest_all()


@router.post("/actions/run")
def run_estimates(db: Session = Depends(get_db)) -> dict:
    started_at = datetime.now()
    try:
        result = EstimateService(db).run_estimates()
    except Exception as exc:
        db.rollback()
        log_fetch_error(db, "internal", "estimate_nav", "all", repr(exc))
        log_task(db, "手动估算基金当日净值", "estimate_nav_manual", "failed", started_at, repr(exc))
        raise HTTPException(status_code=500, detail="估算任务执行失败，请查看运行状态中的数据异常。") from exc
    for skipped in result["skipped"]:
        log_fetch_error(
            db,
            "internal",
            "estimate_nav",
            skipped["fund_code"],
            skipped["reason"],
        )
    status = "success" if result["skipped_count"] == 0 else "partial"
    log_task(
        db,
        "手动估算基金当日净值",
        "estimate_nav_manual",
        status,
        started_at,
        f"estimated={result['estimated_count']};skipped={result['skipped_count']};details={result['skipped']}",
    )
    return result


@router.post("/actions/refresh-quotes-and-run")
def refresh_quotes_and_run_estimates(
    payload: RefreshAndEstimateRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    started_at = datetime.now()
    fund_codes = _resolve_fund_codes(db, payload)
    target = ",".join(fund_codes) if fund_codes else "all"
    try:
        quotes = MarketService(db).refresh_quotes_for_holdings(fund_codes or None)
        result = EstimateService(db).run_estimates(fund_codes or None)
    except Exception as exc:
        db.rollback()
        log_fetch_error(db, "internal", "refresh_quote_estimate", target, repr(exc))
        log_task(
            db,
            "手动刷新行情并估算",
            "refresh_quote_estimate_manual",
            "failed",
            started_at,
            repr(exc),
        )
        raise HTTPException(status_code=500, detail="刷新行情并估算失败，请查看运行状态。") from exc

    if not quotes:
        log_fetch_error(
            db,
            "akshare",
            "quote",
            target,
            "no market quotes refreshed for selected funds",
        )
    for skipped in result["skipped"]:
        log_fetch_error(
            db,
            "internal",
            "estimate_nav",
            skipped["fund_code"],
            skipped["reason"],
        )

    status = "success"
    if not quotes or result["skipped_count"] > 0:
        status = "partial"
    log_task(
        db,
        "手动刷新行情并估算",
        "refresh_quote_estimate_manual",
        status,
        started_at,
        (
            f"funds={len(fund_codes) if fund_codes else 'all'};quotes={len(quotes)};"
            f"estimated={result['estimated_count']};skipped={result['skipped_count']};"
            f"details={result['skipped']}"
        ),
    )
    return {
        "fund_codes": fund_codes,
        "quote_count": len(quotes),
        **result,
    }


@router.get("/{fund_code}", response_model=list[FundEstimateOut])
def estimate_history(fund_code: str, limit: int = 100, db: Session = Depends(get_db)):
    return EstimateService(db).history(fund_code=fund_code, limit=limit)


def _resolve_fund_codes(db: Session, payload: RefreshAndEstimateRequest | None) -> list[str]:
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
