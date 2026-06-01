from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.services.estimate_service import EstimateService
from app.modules.fund_nav.services.fund_profile_service import FundProfileService
from app.modules.fund_nav.services.fund_service import FundService
from app.modules.fund_nav.services.holding_service import HoldingService
from app.modules.fund_nav.services.market_service import MarketService
from app.modules.information.services.operation_log_service import log_fetch_error, log_task, task_status_from_counts


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
                    log_fetch_error(db, "akshare", "fund_nav", fund.fund_code, "akshare returned no latest fund nav")
            except Exception as exc:
                db.rollback()
                failed += 1
                log_fetch_error(db, "akshare", "fund_nav", fund.fund_code, repr(exc))
        return task_status_from_counts(success=success, failed=failed), f"success={success};failed={failed}"

    _run_task("刷新基金官方净值", "refresh_nav", handler)


def refresh_fund_profiles_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        profile_count = FundProfileService(db).refresh_profiles()
        service = FundService(db)
        funds = db.scalars(select(Fund).where(Fund.enabled == 1)).all()
        success = 0
        failed = 0
        for fund in funds:
            try:
                refreshed = service.refresh_profile(fund.fund_code)
                success += 1 if refreshed is not None else 0
                if refreshed is None:
                    failed += 1
                    log_fetch_error(db, "akshare", "fund_profile", fund.fund_code, "fund not found in local fund pool")
            except Exception as exc:
                db.rollback()
                failed += 1
                log_fetch_error(db, "akshare", "fund_profile", fund.fund_code, repr(exc))
        status = task_status_from_counts(success=success, failed=failed)
        return status, f"profiles={profile_count};success={success};failed={failed}"

    _run_task("刷新基金名称和类型", "refresh_profile", handler)


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
                    log_fetch_error(db, "akshare", "holding", fund.fund_code, "akshare returned no fund holdings")
            except Exception as exc:
                db.rollback()
                failed += 1
                log_fetch_error(db, "akshare", "holding", fund.fund_code, repr(exc))
        status = task_status_from_counts(success=success, failed=failed)
        return status, f"success={success};failed={failed};holdings={total_holdings}"

    _run_task("刷新基金持仓", "refresh_holding", handler)


def refresh_market_quotes_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        quotes = MarketService(db).refresh_quotes_for_holdings()
        status = task_status_from_counts(success=len(quotes), skipped=0 if quotes else 1)
        if not quotes:
            log_fetch_error(db, "akshare", "quote", "holdings", "no market quotes refreshed for current holdings")
        return status, f"quotes={len(quotes)}"

    _run_task("刷新持仓资产行情", "refresh_quote", handler)


def estimate_fund_navs_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        result = EstimateService(db).run_estimates()
        skipped_count = result["skipped_count"]
        for skipped in result["skipped"]:
            log_fetch_error(db, "internal", "estimate_nav", skipped["fund_code"], skipped["reason"])
        status = task_status_from_counts(success=result["estimated_count"], skipped=skipped_count)
        return status, f"estimated={result['estimated_count']};skipped={skipped_count};details={result['skipped']}"

    _run_task("估算基金当日净值", "estimate_nav", handler)
