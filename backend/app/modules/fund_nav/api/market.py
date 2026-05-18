from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.fund_nav.schemas.market import MarketQuoteOut
from app.modules.fund_nav.services.market_service import MarketService
from app.modules.information.services.operation_log_service import finish_task, log_fetch_error, start_task

router = APIRouter(prefix="/market", tags=["market"])


@router.post("/refresh")
def refresh_market_quotes(db: Session = Depends(get_db)) -> dict:
    started_at = datetime.now()
    task_log = start_task(
        db,
        "手动刷新持仓资产行情",
        "refresh_quote_manual",
        started_at,
        "刷新持仓资产行情执行中",
    )
    try:
        quotes = MarketService(db).refresh_quotes_for_holdings()
    except Exception as exc:
        db.rollback()
        log_fetch_error(db, "akshare", "quote", "holdings", repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise HTTPException(status_code=502, detail="行情同步失败，请查看运行状态中的数据异常。") from exc
    if not quotes:
        message = "no market quotes refreshed for current holdings"
        log_fetch_error(db, "akshare", "quote", "holdings", message)
        finish_task(db, task_log, "partial", message)
    else:
        finish_task(
            db,
            task_log,
            "success",
            f"quotes={len(quotes)}",
        )
    return {
        "refreshed": len(quotes) > 0,
        "quote_count": len(quotes),
    }


@router.get("/quotes/latest", response_model=list[MarketQuoteOut])
def latest_market_quotes(db: Session = Depends(get_db)):
    return MarketService(db).latest_quotes()
