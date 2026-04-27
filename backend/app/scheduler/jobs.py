from __future__ import annotations

from datetime import datetime
from apscheduler.triggers.cron import CronTrigger
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.fund import Fund
from app.services.estimate_service import EstimateService
from app.services.fund_service import FundService
from app.services.holding_service import HoldingService
from app.services.market_service import MarketService
from app.services.operation_log_service import log_fetch_error, log_task


def _run_task(task_name: str, task_type: str, handler) -> None:
    started_at = datetime.now()
    db = SessionLocal()
    try:
        status, message = handler(db)
        log_task(db, task_name, task_type, status, started_at, message)
    except Exception as exc:
        db.rollback()
        log_task(db, task_name, task_type, "failed", started_at, repr(exc))
    finally:
        db.close()


def refresh_fund_navs_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        service = FundService(db)
        funds = db.scalars(select(Fund).where(Fund.enabled == 1)).all()
        success = 0
        failed = 0
        for fund in funds:
            try:
                nav = service.refresh_nav(fund.fund_code)
                success += 1 if nav is not None else 0
                if nav is None:
                    failed += 1
                    log_fetch_error(
                        db,
                        "akshare",
                        "fund_nav",
                        fund.fund_code,
                        "akshare returned no latest fund nav",
                    )
            except Exception as exc:
                db.rollback()
                failed += 1
                log_fetch_error(db, "akshare", "fund_nav", fund.fund_code, repr(exc))
        status = "success" if failed == 0 else "partial"
        return status, f"success={success};failed={failed}"

    _run_task("刷新基金官方净值", "refresh_nav", handler)


def refresh_fund_holdings_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        service = HoldingService(db)
        funds = db.scalars(select(Fund).where(Fund.enabled == 1)).all()
        success = 0
        failed = 0
        total_holdings = 0
        for fund in funds:
            try:
                holdings = service.refresh_holdings(fund.fund_code)
                total_holdings += len(holdings)
                success += 1 if holdings else 0
                if not holdings:
                    failed += 1
                    log_fetch_error(
                        db,
                        "akshare",
                        "holding",
                        fund.fund_code,
                        "akshare returned no fund holdings",
                    )
            except Exception as exc:
                db.rollback()
                failed += 1
                log_fetch_error(db, "akshare", "holding", fund.fund_code, repr(exc))
        status = "success" if failed == 0 else "partial"
        return status, f"success={success};failed={failed};holdings={total_holdings}"

    _run_task("刷新基金持仓", "refresh_holding", handler)


def refresh_market_quotes_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        quotes = MarketService(db).refresh_quotes_for_holdings()
        status = "success" if quotes else "partial"
        if not quotes:
            log_fetch_error(
                db,
                "akshare",
                "quote",
                "holdings",
                "no market quotes refreshed for current holdings",
            )
        return status, f"quotes={len(quotes)}"

    _run_task("刷新持仓资产行情", "refresh_quote", handler)


def estimate_fund_navs_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        result = EstimateService(db).run_estimates()
        skipped_count = result["skipped_count"]
        for skipped in result["skipped"]:
            log_fetch_error(
                db,
                "internal",
                "estimate_nav",
                skipped["fund_code"],
                skipped["reason"],
            )
        status = "success" if skipped_count == 0 else "partial"
        return (
            status,
            f"estimated={result['estimated_count']};skipped={skipped_count};details={result['skipped']}",
        )

    _run_task("估算基金当日净值", "estimate_nav", handler)


def create_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        refresh_fund_navs_job,
        trigger=CronTrigger.from_crontab(settings.scheduler_refresh_nav_cron),
        id="refresh_fund_navs",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        refresh_fund_holdings_job,
        trigger=CronTrigger.from_crontab(settings.scheduler_refresh_holdings_cron),
        id="refresh_fund_holdings",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        refresh_market_quotes_job,
        trigger=CronTrigger.from_crontab(settings.scheduler_refresh_quotes_cron),
        id="refresh_market_quotes",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        estimate_fund_navs_job,
        trigger=CronTrigger.from_crontab(settings.scheduler_estimate_nav_cron),
        id="estimate_fund_navs",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler
