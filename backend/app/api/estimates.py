from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.estimate import FundEstimateOut
from app.services.estimate_service import EstimateService

router = APIRouter(prefix="/estimates", tags=["estimates"])


@router.get("/latest", response_model=list[FundEstimateOut])
def latest_estimates(db: Session = Depends(get_db)):
    return EstimateService(db).latest_all()


@router.post("/actions/run")
def run_estimates(db: Session = Depends(get_db)) -> dict:
    return EstimateService(db).run_estimates()


@router.get("/{fund_code}", response_model=list[FundEstimateOut])
def estimate_history(fund_code: str, limit: int = 100, db: Session = Depends(get_db)):
    return EstimateService(db).history(fund_code=fund_code, limit=limit)
