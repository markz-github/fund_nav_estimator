"""Backward-compatible scheduler exports.

New code should import from fund_jobs, information_jobs, or scheduler directly.
"""

from app.scheduler.fund_jobs import (
    estimate_fund_navs_job,
    refresh_fund_holdings_job,
    refresh_fund_navs_job,
    refresh_fund_profiles_job,
    refresh_market_quotes_job,
)
from app.scheduler.information_jobs import (
    SUMMARY_TASK_CONFIG_JOB_PREFIX,
    generate_information_summary_task_config_job,
    generate_information_video_notes_job,
    poll_information_summary_documents_job,
    register_information_summary_task_config_jobs,
    scan_information_videos_job,
)
from app.scheduler.scheduler import create_scheduler

__all__ = [
    "SUMMARY_TASK_CONFIG_JOB_PREFIX",
    "create_scheduler",
    "estimate_fund_navs_job",
    "generate_information_summary_task_config_job",
    "generate_information_video_notes_job",
    "poll_information_summary_documents_job",
    "refresh_fund_holdings_job",
    "refresh_fund_navs_job",
    "refresh_fund_profiles_job",
    "refresh_market_quotes_job",
    "register_information_summary_task_config_jobs",
    "scan_information_videos_job",
]
