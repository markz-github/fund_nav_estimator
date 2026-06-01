from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.schemas.estimate import FundEstimateOut, RefreshAndEstimateRequest
from app.modules.fund_nav.schemas.task import FundTaskSubmitOut
from app.modules.fund_nav.services.estimate_service import EstimateService
from app.modules.fund_nav.services.fund_task_queue_service import FundTaskQueueService

router = APIRouter(prefix="/estimates", tags=["estimates"])


@router.get("/latest", response_model=list[FundEstimateOut])
def latest_estimates(db: Session = Depends(get_db)):
    return EstimateService(db).latest_all()


@router.post("/actions/run", response_model=FundTaskSubmitOut, status_code=status.HTTP_202_ACCEPTED)
def run_estimates(db: Session = Depends(get_db)) -> dict:
    return FundTaskQueueService(db).submit(
        "estimate_nav", "手动估算基金当日净值", origin="manual"
    )


@router.post("/actions/refresh-quotes-and-run", response_model=FundTaskSubmitOut, status_code=status.HTTP_202_ACCEPTED)
def refresh_quotes_and_run_estimates(
    payload: RefreshAndEstimateRequest | None = None,
    db: Session = Depends(get_db),
) -> dict:
    fund_codes = _resolve_fund_codes(db, payload)
    return FundTaskQueueService(db).submit(
        "refresh_quote_estimate",
        "手动刷新行情并估算",
        origin="manual",
        fund_codes=fund_codes,
    )


@router.get("/{fund_code}", response_model=list[FundEstimateOut])
def estimate_history(fund_code: str, limit: int = 100, db: Session = Depends(get_db)):
    return EstimateService(db).history(fund_code=fund_code, limit=limit)


def _resolve_fund_codes(db: Session, payload: RefreshAndEstimateRequest | None) -> list[str]:
    if payload is None:
        return []

    codes = [code.strip() for code in (payload.fund_codes or []) if code.strip()]
    if payload.fund_ids:
        rows = db.scalars(select(Fund.fund_code).where(Fund.id.in_(payload.fund_ids), Fund.enabled == 1)).all()
        codes.extend(rows)

    seen: set[str] = set()
    unique_codes: list[str] = []
    for code in codes:
        normalized_code = code.zfill(6) if code.isdigit() else code
        if normalized_code not in seen:
            seen.add(normalized_code)
            unique_codes.append(normalized_code)
    return unique_codes
