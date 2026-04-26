from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.fund import FundCreate, FundOut
from app.schemas.holding import FundHoldingOut
from app.services.fund_service import FundService
from app.services.holding_service import HoldingService

router = APIRouter(prefix="/funds", tags=["funds"])


@router.get("", response_model=list[FundOut])
def list_funds(db: Session = Depends(get_db)) -> list[dict]:
    return FundService(db).list_funds()


@router.post("", response_model=FundOut, status_code=status.HTTP_201_CREATED)
def create_fund(payload: FundCreate, db: Session = Depends(get_db)):
    service = FundService(db)
    try:
        fund = service.create_fund(payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    try:
        nav = FundService(db).refresh_nav(fund_code)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "fund_code": fund_code,
        "refreshed": nav is not None,
        "nav_date": nav.nav_date if nav else None,
        "unit_nav": nav.unit_nav if nav else None,
    }


@router.post("/{fund_code}/refresh-holdings")
def refresh_holdings(fund_code: str, db: Session = Depends(get_db)) -> dict:
    holdings = HoldingService(db).refresh_holdings(fund_code)
    return {
        "fund_code": fund_code,
        "refreshed": len(holdings) > 0,
        "holding_count": len(holdings),
    }


@router.get("/{fund_code}/holdings", response_model=list[FundHoldingOut])
def list_holdings(fund_code: str, db: Session = Depends(get_db)):
    return HoldingService(db).list_holdings(fund_code)
