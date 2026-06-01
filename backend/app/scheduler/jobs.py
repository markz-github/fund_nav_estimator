from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.database import SessionLocal
from app.modules.fund_nav.services.fund_task_queue_service import FundTaskQueueService


def _enqueue(task_type: str, task_name: str) -> None:
    with SessionLocal() as db:
        FundTaskQueueService(db).submit(task_type, task_name, origin="scheduled")


def refresh_fund_navs_job() -> None:
    _enqueue("refresh_nav", "刷新基金官方净值")


def refresh_fund_profiles_job() -> None:
    _enqueue("refresh_profile", "刷新基金名称和类型")


def refresh_fund_holdings_job() -> None:
    _enqueue("refresh_holding", "刷新基金持仓")


def refresh_market_quotes_job() -> None:
    _enqueue("refresh_quote", "刷新持仓资产行情")


def estimate_fund_navs_job() -> None:
    _enqueue("estimate_nav", "估算基金当日净值")


def create_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    jobs = [
        (refresh_fund_navs_job, settings.scheduler_refresh_nav_cron, "refresh_fund_navs"),
        (refresh_fund_profiles_job, settings.scheduler_refresh_profiles_cron, "refresh_fund_profiles"),
        (refresh_fund_holdings_job, settings.scheduler_refresh_holdings_cron, "refresh_fund_holdings"),
        (refresh_market_quotes_job, settings.scheduler_refresh_quotes_cron, "refresh_market_quotes"),
        (estimate_fund_navs_job, settings.scheduler_estimate_nav_cron, "estimate_fund_navs"),
    ]
    for handler, cron, job_id in jobs:
        scheduler.add_job(
            handler,
            trigger=CronTrigger.from_crontab(cron),
            id=job_id,
            replace_existing=True,
            max_instances=1,
        )
    return scheduler
