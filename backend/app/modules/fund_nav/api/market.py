from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.fund_nav.schemas.market import IndexQuoteSourceRuleIn, IndexQuoteSourceStatusOut, MarketQuoteOut
from app.modules.fund_nav.schemas.task import FundTaskSubmitOut
from app.modules.fund_nav.services.fund_task_queue_service import FundTaskQueueService
from app.modules.fund_nav.services.index_quote_source_status_service import IndexQuoteSourceStatusService
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


@router.get("/index-quote-sources", response_model=list[IndexQuoteSourceStatusOut])
def index_quote_sources(db: Session = Depends(get_db)):
    return IndexQuoteSourceStatusService(db).list_statuses()


@router.put("/index-quote-sources/{source_key}", response_model=IndexQuoteSourceStatusOut)
def update_index_quote_source(source_key: str, payload: IndexQuoteSourceRuleIn, db: Session = Depends(get_db)):
    service = IndexQuoteSourceStatusService(db)
    try:
        result = service.update_rules(
            source_key,
            source_description=payload.source_description,
            exclude_rule_type=payload.exclude_rule_type,
            exclude_rule_value=payload.exclude_rule_value,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return result
