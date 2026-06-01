from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.fund_nav.schemas.market import MarketQuoteOut
from app.modules.fund_nav.schemas.task import FundTaskSubmitOut
from app.modules.fund_nav.services.fund_task_queue_service import FundTaskQueueService
from app.modules.fund_nav.services.market_service import MarketService

router = APIRouter(prefix="/market", tags=["market"])


@router.post("/refresh", response_model=FundTaskSubmitOut, status_code=status.HTTP_202_ACCEPTED)
def refresh_market_quotes(db: Session = Depends(get_db)) -> dict:
    return FundTaskQueueService(db).submit(
        "refresh_quote", "手动刷新持仓资产行情", origin="manual"
    )


@router.get("/quotes/latest", response_model=list[MarketQuoteOut])
def latest_market_quotes(db: Session = Depends(get_db)):
    return MarketService(db).latest_quotes()
