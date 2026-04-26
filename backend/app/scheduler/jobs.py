from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    # Job implementations will call services once real data-source mapping is tuned.
    return scheduler
