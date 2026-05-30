from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
import logging
import re

from requests import exceptions as requests_exceptions
from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only

from app.scheduler.cron_utils import normalize_cron_expression
from app.modules.information.models.summary_document import (
    InformationSummaryDocument,
    InformationSummaryDocumentItem,
)
from app.modules.information.models.bilinote_extra_template import InformationBilinoteExtraTemplate
from app.modules.information.models.summary_document_template import InformationSummaryDocumentTemplate
from app.modules.information.models.summary_task_config import InformationSummaryTaskConfig
from app.modules.information.models.task_log import TaskLog
from app.modules.information.models.video import InformationVideo
from app.modules.information.models.video_note import InformationVideoNote
from app.modules.information.models.video_source import InformationVideoSource
from app.modules.information.schemas.video import (
    ManualLinkCreate,
    SummaryTaskConfigCreate,
    SummaryTaskConfigUpdate,
    VideoSourceCreate,
    VideoSourceUpdate,
)
from app.modules.information.services.bilinote_client import BilinoteClient, compact_json
from app.modules.information.services.hermes_client import HermesClient
from app.modules.information.services.information_settings_service import (
    InformationSettingsService,
)
from app.modules.information.services.operation_log_service import log_fetch_error
from app.modules.information.services.video_source_adapters import get_video_source_adapter
from app.modules.information.services.wechat_push_client import WechatPushClient
from app.modules.information.utils.markdown import markdown_output_instruction


logger = logging.getLogger(__name__)
VIDEO_NOTE_EXPIRY = timedelta(days=1)
SUMMARY_DOCUMENT_EXPIRY = timedelta(days=1)
DEFAULT_CATEGORY = "财经"
SYSTEM_MANUAL_SOURCE_ID = -1
SYSTEM_MANUAL_SOURCE_PLATFORM = "system"
SYSTEM_MANUAL_SOURCE_EXTERNAL_ID = "manual"
SYSTEM_MANUAL_SOURCE_NAME = "手动录入"
SYSTEM_MANUAL_SOURCE_CATEGORY = "手动录入"

__all__ = [
    "date",
    "datetime",
    "time",
    "timedelta",
    "json",
    "logging",
    "re",
    "requests_exceptions",
    "func",
    "select",
    "Session",
    "load_only",
    "normalize_cron_expression",
    "InformationSummaryDocument",
    "InformationSummaryDocumentItem",
    "InformationBilinoteExtraTemplate",
    "InformationSummaryDocumentTemplate",
    "InformationSummaryTaskConfig",
    "TaskLog",
    "InformationVideo",
    "InformationVideoNote",
    "InformationVideoSource",
    "ManualLinkCreate",
    "SummaryTaskConfigCreate",
    "SummaryTaskConfigUpdate",
    "VideoSourceCreate",
    "VideoSourceUpdate",
    "BilinoteClient",
    "compact_json",
    "HermesClient",
    "InformationSettingsService",
    "log_fetch_error",
    "get_video_source_adapter",
    "WechatPushClient",
    "markdown_output_instruction",
    "logger",
    "VIDEO_NOTE_EXPIRY",
    "SUMMARY_DOCUMENT_EXPIRY",
    "DEFAULT_CATEGORY",
    "SYSTEM_MANUAL_SOURCE_ID",
    "SYSTEM_MANUAL_SOURCE_PLATFORM",
    "SYSTEM_MANUAL_SOURCE_EXTERNAL_ID",
    "SYSTEM_MANUAL_SOURCE_NAME",
    "SYSTEM_MANUAL_SOURCE_CATEGORY",
    "normalize_category",
    "_normalize_start_days_before",
    "_normalize_title_template",
    "_normalize_instruction",
    "_page_params",
    "_normalize_ingest_method",
    "_scannable_source_filter",
    "InformationServiceBase",
]


def normalize_category(category: str | None) -> str:
    return (category or DEFAULT_CATEGORY).strip() or DEFAULT_CATEGORY


def _normalize_start_days_before(value: int | None) -> int:
    days = int(value or 1)
    if days < 1:
        raise ValueError("start_days_before must be greater than or equal to 1")
    return days


def _normalize_title_template(value: str | None) -> str:
    template = (value or "").strip()
    return template or "{start_date:%Y-%m-%d} {platform} {category}汇总"


def _normalize_instruction(value: str | None) -> str:
    return (value or "").strip()


def _page_params(page: int, page_size: int | None, limit: int = 100) -> tuple[int, int, int]:
    effective_page_size = max(1, min(page_size or limit, 200))
    effective_page = max(1, page)
    offset = (effective_page - 1) * effective_page_size
    return effective_page, effective_page_size, offset


def _normalize_ingest_method(value: str | None) -> str | None:
    method = (value or "").strip().lower()
    if not method:
        return None
    if method not in {"scan", "manual"}:
        raise ValueError("ingest_method must be scan or manual")
    return method


def _scannable_source_filter():
    return (
        InformationVideoSource.id != SYSTEM_MANUAL_SOURCE_ID,
        InformationVideoSource.external_source_id != SYSTEM_MANUAL_SOURCE_EXTERNAL_ID,
    )


class InformationServiceBase:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.last_scan_errors: list[str] = []
