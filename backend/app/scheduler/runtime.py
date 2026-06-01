from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler


logger = logging.getLogger(__name__)
_scheduler: Optional[BackgroundScheduler] = None


def set_scheduler(scheduler: BackgroundScheduler | None) -> None:
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def refresh_summary_task_config_jobs() -> None:
    scheduler = get_scheduler()
    if scheduler is None:
        return
    try:
        from app.scheduler.information_jobs import register_information_summary_task_config_jobs

        register_information_summary_task_config_jobs(scheduler)
    except Exception:
        logger.exception("failed to refresh information summary task config jobs")
