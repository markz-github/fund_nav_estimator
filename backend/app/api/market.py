from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.market import MarketQuoteOut
from app.services.market_service import MarketService

router = APIRouter(prefix="/market", tags=["market"])


@router.post("/refresh")
def refresh_market_quotes(db: Session = Depends(get_db)) -> dict:
    quotes = MarketService(db).refresh_quotes_for_holdings()
    return {
        "refreshed": len(quotes) > 0,
        "quote_count": len(quotes),
    }


@router.get("/quotes/latest", response_model=list[MarketQuoteOut])
def latest_market_quotes(db: Session = Depends(get_db)):
    return MarketService(db).latest_quotes()
