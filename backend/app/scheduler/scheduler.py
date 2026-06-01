from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.scheduler.fund_jobs import (
    estimate_fund_navs_job,
    refresh_fund_holdings_job,
    refresh_fund_navs_job,
    refresh_fund_profiles_job,
    refresh_market_quotes_job,
)
from app.scheduler.information_jobs import (
    generate_information_video_notes_job,
    poll_information_summary_documents_job,
    register_information_summary_task_config_jobs,
    scan_information_videos_job,
)


def create_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    if settings.scheduler_fund_enabled:
        fund_jobs = [
            (refresh_fund_navs_job, settings.scheduler_refresh_nav_cron, "refresh_fund_navs"),
            (refresh_fund_profiles_job, settings.scheduler_refresh_profiles_cron, "refresh_fund_profiles"),
            (refresh_fund_holdings_job, settings.scheduler_refresh_holdings_cron, "refresh_fund_holdings"),
            (refresh_market_quotes_job, settings.scheduler_refresh_quotes_cron, "refresh_market_quotes"),
            (estimate_fund_navs_job, settings.scheduler_estimate_nav_cron, "estimate_fund_navs"),
        ]
        for handler, cron, job_id in fund_jobs:
            scheduler.add_job(handler, trigger=CronTrigger.from_crontab(cron), id=job_id, replace_existing=True, max_instances=1)
    if settings.scheduler_information_enabled:
        scheduler.add_job(scan_information_videos_job, trigger=CronTrigger.from_crontab(settings.scheduler_scan_videos_cron), id="scan_information_videos", replace_existing=True, max_instances=1)
        scheduler.add_job(generate_information_video_notes_job, trigger=IntervalTrigger(seconds=settings.scheduler_generate_video_notes_interval_seconds), id="generate_information_video_notes", replace_existing=True, max_instances=1)
        register_information_summary_task_config_jobs(scheduler)
        scheduler.add_job(poll_information_summary_documents_job, trigger=IntervalTrigger(seconds=settings.scheduler_poll_summary_documents_interval_seconds), id="poll_information_summary_documents", replace_existing=True, max_instances=1)
    return scheduler
