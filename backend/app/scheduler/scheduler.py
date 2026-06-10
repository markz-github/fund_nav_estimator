from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.scheduler.a_stock_jobs import sync_previous_a_stock_trading_day_job
from app.scheduler.fund_jobs import (
    estimate_fund_navs_job,
    refresh_fund_holdings_job,
    refresh_fund_navs_job,
    refresh_fund_profiles_job,
    refresh_market_quotes_job,
)


def _new_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler(timezone="Asia/Shanghai")


def _add_fund_jobs(scheduler: BackgroundScheduler) -> None:
    settings = get_settings()
    fund_jobs = [
        (refresh_fund_navs_job, settings.scheduler_refresh_nav_cron, "refresh_fund_navs"),
        (refresh_fund_profiles_job, settings.scheduler_refresh_profiles_cron, "refresh_fund_profiles"),
        (refresh_fund_holdings_job, settings.scheduler_refresh_holdings_cron, "refresh_fund_holdings"),
        (refresh_market_quotes_job, settings.scheduler_refresh_quotes_cron, "refresh_market_quotes"),
        (estimate_fund_navs_job, settings.scheduler_estimate_nav_cron, "estimate_fund_navs"),
    ]
    for handler, cron, job_id in fund_jobs:
        scheduler.add_job(
            handler,
            trigger=CronTrigger.from_crontab(cron),
            id=job_id,
            replace_existing=True,
            max_instances=1,
        )


def _add_a_stock_jobs(scheduler: BackgroundScheduler) -> None:
    settings = get_settings()
    scheduler.add_job(
        sync_previous_a_stock_trading_day_job,
        trigger=CronTrigger.from_crontab(settings.scheduler_a_stock_history_cron),
        id="sync_previous_a_stock_trading_day",
        replace_existing=True,
        max_instances=1,
    )


def create_fund_scheduler() -> BackgroundScheduler:
    scheduler = _new_scheduler()
    _add_fund_jobs(scheduler)
    return scheduler


def create_a_stock_scheduler() -> BackgroundScheduler:
    scheduler = _new_scheduler()
    _add_a_stock_jobs(scheduler)
    return scheduler


def create_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = _new_scheduler()
    if settings.scheduler_fund_enabled:
        _add_fund_jobs(scheduler)
    if settings.scheduler_a_stock_enabled:
        _add_a_stock_jobs(scheduler)
    return scheduler
