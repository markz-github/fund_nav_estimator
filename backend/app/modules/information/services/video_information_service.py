from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
import logging
import re

from apscheduler.triggers.cron import CronTrigger
from requests import exceptions as requests_exceptions
from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only

from app.modules.information.models.summary_document import (
    InformationSummaryDocument,
    InformationSummaryDocumentItem,
)
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
from app.modules.information.services.information_settings_service import InformationSettingsService
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
DEFAULT_SUMMARY_TASK_CONFIGS = (
    {
        "task_name": "财经昨日汇总",
        "platform": "bilibili",
        "category": DEFAULT_CATEGORY,
        "start_days_before": 1,
        "cron_expression": "0 7 * * *",
        "title_template": "{start_date:%Y-%m-%d} {platform} {category}汇总",
        "summary_instruction": "",
        "push_to_wechat": 1,
    },
    {
        "task_name": "财经近7天汇总",
        "platform": "bilibili",
        "category": DEFAULT_CATEGORY,
        "start_days_before": 7,
        "cron_expression": "30 7 * * mon",
        "title_template": "{start_date:%Y-%m-%d} 至 {end_date:%Y-%m-%d} {platform} {category}汇总",
        "summary_instruction": "",
        "push_to_wechat": 0,
    },
)


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


_CRON_WEEKDAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]


def _cron_weekday_number_to_name(value: int) -> str:
    if value == 7:
        value = 0
    if value < 0 or value > 6:
        raise ValueError("day_of_week must be between 0 and 7")
    return _CRON_WEEKDAY_NAMES[value]


def _expand_cron_weekday_range(start: int, end: int, step: int = 1) -> str:
    if step < 1:
        raise ValueError("day_of_week step must be greater than or equal to 1")
    if start == 7:
        start = 0
    if end == 7:
        end = 0
    if start > end:
        values = list(range(start, 7)) + list(range(0, end + 1))
    else:
        values = list(range(start, end + 1))
    return ",".join(_cron_weekday_number_to_name(value) for value in values[::step])


def _normalize_cron_weekday_field(value: str) -> str:
    parts: list[str] = []
    for raw_part in value.split(","):
        part = raw_part.strip().lower()
        if not part:
            raise ValueError("day_of_week contains an empty value")
        range_step = re.fullmatch(r"(\d+)-(\d+)/(\d+)", part)
        if range_step:
            parts.append(
                _expand_cron_weekday_range(
                    int(range_step.group(1)),
                    int(range_step.group(2)),
                    int(range_step.group(3)),
                )
            )
            continue
        weekday_range = re.fullmatch(r"(\d+)-(\d+)", part)
        if weekday_range:
            parts.append(_expand_cron_weekday_range(int(weekday_range.group(1)), int(weekday_range.group(2))))
            continue
        wildcard_step = re.fullmatch(r"\*/(\d+)", part)
        if wildcard_step:
            parts.append(_expand_cron_weekday_range(0, 6, int(wildcard_step.group(1))))
            continue
        number_step = re.fullmatch(r"(\d+)/(\d+)", part)
        if number_step:
            parts.append(_expand_cron_weekday_range(int(number_step.group(1)), 6, int(number_step.group(2))))
            continue
        if part.isdigit():
            parts.append(_cron_weekday_number_to_name(int(part)))
            continue
        parts.append(part)
    return ",".join(parts)


def _normalize_cron_expression(value: str | None) -> str:
    expression = (value or "").strip()
    if not expression:
        expression = "0 7 * * *"
    fields = expression.split()
    if len(fields) != 5:
        CronTrigger.from_crontab(expression)
        return expression
    fields[4] = _normalize_cron_weekday_field(fields[4])
    normalized = " ".join(fields)
    CronTrigger.from_crontab(normalized)
    return normalized


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


class VideoInformationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.last_scan_errors: list[str] = []

    def list_sources(self, enabled_only: bool = False) -> list[dict[str, object]]:
        statement = select(InformationVideoSource).order_by(
            (InformationVideoSource.id == SYSTEM_MANUAL_SOURCE_ID).desc(),
            InformationVideoSource.created_at.desc(),
        )
        if enabled_only:
            statement = statement.where(
                InformationVideoSource.enabled == 1,
                InformationVideoSource.id > 0,
            )
        sources = list(self.db.scalars(statement).all())
        return [self._source_payload(source) for source in sources]

    def list_sources_page(
        self,
        enabled_only: bool = False,
        page: int = 1,
        page_size: int | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        statement = select(InformationVideoSource)
        if enabled_only:
            statement = statement.where(
                InformationVideoSource.enabled == 1,
                InformationVideoSource.id > 0,
            )
        total = self.db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        effective_page, effective_page_size, offset = _page_params(page, page_size, limit)
        if total > 0:
            max_page = (total + effective_page_size - 1) // effective_page_size
            effective_page = min(effective_page, max_page)
            offset = (effective_page - 1) * effective_page_size
        sources = list(
            self.db.scalars(
                statement.order_by(
                    (InformationVideoSource.id == SYSTEM_MANUAL_SOURCE_ID).desc(),
                    InformationVideoSource.created_at.desc(),
                )
                .offset(offset)
                .limit(effective_page_size)
            ).all()
        )
        return {
            "items": [self._source_payload(source) for source in sources],
            "total": total,
            "page": effective_page,
            "page_size": effective_page_size,
        }

    def _source_payload(self, source: InformationVideoSource) -> dict[str, object]:
        information_count = self.db.scalar(
            select(func.count(InformationVideo.id)).where(InformationVideo.source_id == source.id)
        ) or 0
        note_count = self.db.scalar(
            select(func.count(InformationVideoNote.id))
            .join(InformationVideo, InformationVideo.id == InformationVideoNote.video_id)
            .where(
                InformationVideo.source_id == source.id,
                InformationVideoNote.status == "done",
            )
        ) or 0
        return {
            "id": source.id,
            "platform": source.platform,
            "source_name": source.source_name,
            "source_url": source.source_url,
            "external_source_id": source.external_source_id,
            "category": source.category,
            "enabled": source.enabled,
            "last_scanned_at": source.last_scanned_at,
            "remark": source.remark,
            "information_count": information_count,
            "note_count": note_count,
            "created_at": source.created_at,
            "updated_at": source.updated_at,
        }

    def list_categories(self) -> list[str]:
        values: set[str] = {DEFAULT_CATEGORY}
        for model in (InformationVideoSource, InformationVideo, InformationSummaryDocument, InformationSummaryTaskConfig):
            rows = self.db.scalars(select(model.category).where(model.category.is_not(None))).all()
            values.update(normalize_category(value) for value in rows if value)
        return sorted(values, key=lambda item: (item != DEFAULT_CATEGORY, item))

    def ensure_default_summary_task_configs(self) -> None:
        existing_count = (
            self.db.scalar(
                select(func.count(InformationSummaryTaskConfig.id)).execution_options(include_deleted=True)
            )
            or 0
        )
        if existing_count > 0:
            return
        for item in DEFAULT_SUMMARY_TASK_CONFIGS:
            self.db.add(InformationSummaryTaskConfig(**item, enabled=1))
        self.db.commit()

    def list_summary_task_configs(self) -> list[InformationSummaryTaskConfig]:
        self.ensure_default_summary_task_configs()
        return list(
            self.db.scalars(
                select(InformationSummaryTaskConfig).order_by(
                    InformationSummaryTaskConfig.enabled.desc(),
                    InformationSummaryTaskConfig.id.asc(),
                )
            ).all()
        )

    def create_summary_task_config(self, payload: SummaryTaskConfigCreate) -> InformationSummaryTaskConfig:
        task_name = payload.task_name.strip() or "信息流汇总任务"
        config = InformationSummaryTaskConfig(
            task_name=task_name,
            platform=(payload.platform or "bilibili").strip().lower(),
            category=normalize_category(payload.category),
            start_days_before=_normalize_start_days_before(payload.start_days_before),
            cron_expression=_normalize_cron_expression(payload.cron_expression),
            title_template=_normalize_title_template(payload.title_template),
            summary_instruction=_normalize_instruction(payload.summary_instruction),
            push_to_wechat=1 if payload.push_to_wechat else 0,
            enabled=1 if payload.enabled else 0,
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_summary_task_config(
        self,
        config_id: int,
        payload: SummaryTaskConfigUpdate,
    ) -> InformationSummaryTaskConfig | None:
        config = self.db.get(InformationSummaryTaskConfig, config_id)
        if config is None:
            return None
        if payload.task_name is not None:
            config.task_name = payload.task_name.strip() or config.task_name
        if payload.platform is not None:
            config.platform = (payload.platform or "bilibili").strip().lower()
        if payload.category is not None:
            config.category = normalize_category(payload.category)
        if payload.start_days_before is not None:
            config.start_days_before = _normalize_start_days_before(payload.start_days_before)
        if payload.cron_expression is not None:
            config.cron_expression = _normalize_cron_expression(payload.cron_expression)
        if payload.title_template is not None:
            config.title_template = _normalize_title_template(payload.title_template)
        if payload.summary_instruction is not None:
            config.summary_instruction = _normalize_instruction(payload.summary_instruction)
        if payload.push_to_wechat is not None:
            config.push_to_wechat = 1 if payload.push_to_wechat else 0
        if payload.enabled is not None:
            config.enabled = 1 if payload.enabled else 0
        self.db.commit()
        self.db.refresh(config)
        return config

    def delete_summary_task_config(self, config_id: int) -> bool:
        config = self.db.get(InformationSummaryTaskConfig, config_id)
        if config is None:
            return False
        self.db.delete(config)
        self.db.commit()
        return True

    def create_source(self, payload: VideoSourceCreate) -> InformationVideoSource:
        adapter = get_video_source_adapter(payload.platform)
        platform = payload.platform.strip().lower()
        normalized_id = adapter.normalize_source_id(payload.external_source_id or payload.source_url or "")
        source = self.db.scalar(
            select(InformationVideoSource)
            .where(
                InformationVideoSource.platform == platform,
                InformationVideoSource.external_source_id == normalized_id,
            )
            .execution_options(include_deleted=True)
        )
        if source is None:
            source = InformationVideoSource(
                platform=platform,
                source_name=payload.source_name.strip(),
                source_url=payload.source_url,
                external_source_id=normalized_id,
                category=normalize_category(payload.category),
                remark=payload.remark,
                enabled=1,
            )
            self.db.add(source)
        else:
            source.is_deleted = 0
            source.source_name = payload.source_name.strip()
            source.source_url = payload.source_url
            source.external_source_id = normalized_id
            source.category = normalize_category(payload.category)
            source.remark = payload.remark
            source.enabled = 1
        self.db.commit()
        self.db.refresh(source)
        return source

    def update_source(self, source_id: int, payload: VideoSourceUpdate) -> InformationVideoSource | None:
        source = self.db.scalar(select(InformationVideoSource).where(InformationVideoSource.id == source_id))
        if source is None:
            return None
        if payload.source_name is not None:
            source.source_name = payload.source_name.strip()
        if payload.source_url is not None:
            source.source_url = payload.source_url
        if payload.external_source_id is not None:
            adapter = get_video_source_adapter(source.platform)
            source.external_source_id = adapter.normalize_source_id(payload.external_source_id)
        if payload.category is not None:
            source.category = normalize_category(payload.category)
        if payload.enabled is not None:
            source.enabled = 1 if payload.enabled else 0
        if payload.remark is not None:
            source.remark = payload.remark
        self.db.commit()
        self.db.refresh(source)
        return source

    def delete_source(self, source_id: int) -> bool:
        source = self.db.scalar(select(InformationVideoSource).where(InformationVideoSource.id == source_id))
        if source is None:
            return False
        self.db.delete(source)
        self.db.commit()
        return True

    def scan_sources(
        self,
        source_id: int | None = None,
        source_ids: list[int] | None = None,
        limit: int = 20,
    ) -> int:
        self.last_scan_errors = []
        statement = select(InformationVideoSource).where(
            InformationVideoSource.enabled == 1,
            *_scannable_source_filter(),
        )
        if source_ids:
            statement = statement.where(InformationVideoSource.id.in_(source_ids))
        elif source_id is not None:
            statement = statement.where(InformationVideoSource.id == source_id)
        sources = self.db.scalars(statement).all()
        settings = InformationSettingsService(self.db).get_settings()
        bilibili_cookie = settings.get("bilibili_cookie", "").strip()
        article_filter_keywords = self._parse_keywords(settings.get("article_filter_keywords", ""))
        logger.debug(
            "video scan started source_id=%s source_ids=%s limit=%s enabled_source_count=%s",
            source_id,
            source_ids,
            limit,
            len(sources),
        )
        created = 0
        for source in sources:
            source_created = 0
            duplicate_count = 0
            try:
                logger.debug(
                    "video source scan started source_id=%s platform=%s external_source_id=%s source_name=%s limit=%s",
                    source.id,
                    source.platform,
                    source.external_source_id,
                    source.source_name,
                    limit,
                )
                adapter = get_video_source_adapter(source.platform)
                snapshots = adapter.fetch_latest_videos(
                    source,
                    limit=limit,
                    bilibili_cookie=bilibili_cookie if source.platform == "bilibili" else None,
                )
                logger.debug(
                    "video source scan fetched source_id=%s platform=%s external_source_id=%s snapshot_count=%s",
                    source.id,
                    source.platform,
                    source.external_source_id,
                    len(snapshots),
                )
                for snapshot in snapshots:
                    is_invalid_content = self._apply_article_filter(
                        snapshot,
                        article_filter_keywords,
                        context="video scan",
                        source_id=source.id,
                    )
                    snapshot_status = "invalid_content" if is_invalid_content else "note_pending"
                    existing = self.db.scalar(
                        select(InformationVideo)
                        .where(
                            InformationVideo.platform == snapshot.platform,
                            InformationVideo.external_video_id == snapshot.external_video_id,
                        )
                        .execution_options(include_deleted=True)
                    )
                    if existing is not None:
                        if existing.is_deleted == 1:
                            existing.is_deleted = 0
                            existing.source_id = source.id
                            existing.title = snapshot.title[:300]
                            existing.video_url = snapshot.video_url
                            existing.content_type = snapshot.content_type
                            existing.content_text = snapshot.content_text
                            existing.duration_seconds = snapshot.duration_seconds
                            existing.author_name = snapshot.author_name
                            existing.category = normalize_category(source.category)
                            existing.ingest_method = "scan"
                            existing.published_at = snapshot.published_at
                            existing.status = snapshot_status
                            existing.raw_response = json.dumps(snapshot.raw_response, ensure_ascii=False)
                            created += 1
                            source_created += 1
                            continue
                        if is_invalid_content and existing.status != "invalid_content":
                            existing.source_id = source.id
                            existing.title = snapshot.title[:300]
                            existing.video_url = snapshot.video_url
                            existing.content_type = snapshot.content_type
                            existing.content_text = snapshot.content_text
                            existing.duration_seconds = snapshot.duration_seconds
                            existing.author_name = snapshot.author_name
                            existing.category = normalize_category(source.category)
                            existing.ingest_method = "scan"
                            existing.published_at = snapshot.published_at
                            existing.status = "invalid_content"
                            existing.raw_response = json.dumps(snapshot.raw_response, ensure_ascii=False)
                        duplicate_count += 1
                        logger.debug(
                            "video scan skipped duplicate source_id=%s platform=%s external_video_id=%s title=%s",
                            source.id,
                            snapshot.platform,
                            snapshot.external_video_id,
                            snapshot.title[:120],
                        )
                        continue
                    self.db.add(
                        InformationVideo(
                            source_id=source.id,
                            platform=snapshot.platform,
                            external_video_id=snapshot.external_video_id,
                            title=snapshot.title[:300],
                            video_url=snapshot.video_url,
                            content_type=snapshot.content_type,
                            content_text=snapshot.content_text,
                            duration_seconds=snapshot.duration_seconds,
                            author_name=snapshot.author_name,
                            category=normalize_category(source.category),
                            ingest_method="scan",
                            published_at=snapshot.published_at,
                            status=snapshot_status,
                            raw_response=json.dumps(snapshot.raw_response, ensure_ascii=False),
                        )
                    )
                    created += 1
                    source_created += 1
                    logger.debug(
                        "video scan discovered new video source_id=%s platform=%s external_video_id=%s published_at=%s title=%s",
                        source.id,
                        snapshot.platform,
                        snapshot.external_video_id,
                        snapshot.published_at,
                        snapshot.title[:120],
                    )
                source.last_scanned_at = datetime.now()
                self.db.commit()
                logger.info(
                    "video source scan succeeded source_id=%s platform=%s external_source_id=%s fetched=%s created=%s duplicates=%s",
                    source.id,
                    source.platform,
                    source.external_source_id,
                    len(snapshots),
                    source_created,
                    duplicate_count,
                )
            except Exception as exc:
                self.db.rollback()
                error_message = repr(exc)
                logger.error(
                    "video source scan failed source_id=%s platform=%s external_source_id=%s error=%r",
                    source.id,
                    source.platform,
                    source.external_source_id,
                    exc,
                )
                logger.debug(
                    "video source scan failed traceback source_id=%s platform=%s external_source_id=%s",
                    source.id,
                    source.platform,
                    source.external_source_id,
                    exc_info=True,
                )
                failed_source = self.db.get(InformationVideoSource, source.id)
                if failed_source is not None:
                    failed_source.last_scanned_at = datetime.now()
                self.last_scan_errors.append(f"source_id={source.id};error={error_message}")
                log_fetch_error(self.db, source.platform, "video_scan", source.external_source_id, error_message)
                self.db.commit()
        logger.info("video scan finished source_id=%s source_ids=%s limit=%s created=%s", source_id, source_ids, limit, created)
        return created

    def scan_enabled_sources(self, limit: int = 20) -> dict[str, int | str]:
        source_count = self.db.scalar(
            select(func.count(InformationVideoSource.id)).where(
                InformationVideoSource.enabled == 1,
                *_scannable_source_filter(),
            )
        ) or 0
        if source_count == 0:
            logger.info("scheduled video scan skipped no enabled source")
            return {"source_count": 0, "created": 0}
        created = self.scan_sources(limit=limit)
        result: dict[str, int | str] = {"source_count": source_count, "created": created}
        if self.last_scan_errors:
            result["error_message"] = ";".join(self.last_scan_errors)
        return result

    def scan_next_source(self, limit: int = 20) -> dict[str, int | str]:
        return self.scan_enabled_sources(limit=limit)

    def add_manual_link(self, payload: ManualLinkCreate) -> InformationVideo:
        link = payload.url.strip()
        category = normalize_category(payload.category)
        if not category:
            raise ValueError("分类不能为空")
        settings = InformationSettingsService(self.db).get_settings()
        bilibili_cookie = settings.get("bilibili_cookie", "").strip()
        adapter = get_video_source_adapter("bilibili")
        snapshot = adapter.fetch_link(link, bilibili_cookie=bilibili_cookie)
        source = self._manual_source()
        published_at = datetime.now()
        article_filter_keywords = self._parse_keywords(settings.get("article_filter_keywords", ""))
        is_invalid_content = self._apply_article_filter(
            snapshot,
            article_filter_keywords,
            context="manual link add",
            source_id=source.id,
        )
        status = "invalid_content" if is_invalid_content else "note_pending"
        existing = self.db.scalar(
            select(InformationVideo)
            .where(
                InformationVideo.platform == snapshot.platform,
                InformationVideo.external_video_id == snapshot.external_video_id,
            )
            .execution_options(include_deleted=True)
        )
        if existing is not None:
            existing.is_deleted = 0
            existing.source_id = source.id
            existing.title = snapshot.title[:300]
            existing.video_url = snapshot.video_url
            existing.content_type = snapshot.content_type
            existing.content_text = snapshot.content_text
            existing.duration_seconds = snapshot.duration_seconds
            existing.author_name = snapshot.author_name
            existing.category = category
            existing.ingest_method = "manual"
            existing.published_at = published_at
            existing.status = status
            existing.raw_response = json.dumps(snapshot.raw_response, ensure_ascii=False)
            self.db.commit()
            self.db.refresh(existing)
            return existing

        video = InformationVideo(
            source_id=source.id,
            platform=snapshot.platform,
            external_video_id=snapshot.external_video_id,
            title=snapshot.title[:300],
            video_url=snapshot.video_url,
            content_type=snapshot.content_type,
            content_text=snapshot.content_text,
            duration_seconds=snapshot.duration_seconds,
            author_name=snapshot.author_name,
            category=category,
            ingest_method="manual",
            published_at=published_at,
            status=status,
            raw_response=json.dumps(snapshot.raw_response, ensure_ascii=False),
        )
        self.db.add(video)
        self.db.commit()
        self.db.refresh(video)
        return video

    def _manual_source(self) -> InformationVideoSource:
        source = self.db.scalar(
            select(InformationVideoSource)
            .where(InformationVideoSource.id == SYSTEM_MANUAL_SOURCE_ID)
            .execution_options(include_deleted=True)
        )
        if source is not None:
            source.is_deleted = 0
            source.platform = SYSTEM_MANUAL_SOURCE_PLATFORM
            source.source_name = SYSTEM_MANUAL_SOURCE_NAME
            source.source_url = None
            source.external_source_id = SYSTEM_MANUAL_SOURCE_EXTERNAL_ID
            source.category = SYSTEM_MANUAL_SOURCE_CATEGORY
            source.enabled = 1
            source.remark = "系统内置手动录入来源"
            return source
        source = InformationVideoSource(
            id=SYSTEM_MANUAL_SOURCE_ID,
            platform=SYSTEM_MANUAL_SOURCE_PLATFORM,
            source_name=SYSTEM_MANUAL_SOURCE_NAME,
            source_url=None,
            external_source_id=SYSTEM_MANUAL_SOURCE_EXTERNAL_ID,
            category=SYSTEM_MANUAL_SOURCE_CATEGORY,
            enabled=1,
            remark="系统内置手动录入来源",
        )
        self.db.add(source)
        self.db.flush()
        return source

    def generate_pending_notes(self, limit: int = 5, video_ids: list[int] | None = None) -> dict[str, int]:
        poll_result = self.poll_running_notes(video_ids=video_ids)
        if poll_result["running"] > 0:
            return poll_result
        submit_result = self.submit_pending_note_task(limit=limit, video_ids=video_ids)
        for key in ("total", "completed", "failed", "running", "started", "expired"):
            poll_result[key] += submit_result[key]
        poll_result.update(
            {
                "video_id": submit_result.get("video_id"),
                "note_id": submit_result.get("note_id"),
                "external_task_id": submit_result.get("external_task_id"),
            }
        )
        return poll_result

    def submit_pending_note_task(self, limit: int = 1, video_ids: list[int] | None = None) -> dict[str, int | str | None]:
        settings = InformationSettingsService(self.db).get_settings()
        result = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "started": 0,
            "expired": 0,
            "video_id": None,
            "note_id": None,
            "external_task_id": None,
            "error_message": None,
        }
        running_note = self.db.scalar(
            select(InformationVideoNote)
            .join(InformationVideo, InformationVideo.id == InformationVideoNote.video_id)
            .where(
                InformationVideoNote.status == "running",
                InformationVideo.status != "note_failed",
            )
        )
        if running_note is not None:
            result["total"] = 1
            result["running"] = 1
            result["video_id"] = running_note.video_id
            result["note_id"] = running_note.id
            result["external_task_id"] = running_note.external_task_id
            return result

        statement = (
            select(InformationVideo)
            .where(
                InformationVideo.content_type == "video",
                InformationVideo.status.in_(["note_pending", "discovered"]),
            )
            .order_by(InformationVideo.published_at.desc(), InformationVideo.created_at.desc())
        )
        cutoff = self._video_note_cutoff(settings)
        if cutoff is not None:
            statement = statement.where(func.coalesce(InformationVideo.published_at, InformationVideo.created_at) >= cutoff)
        if video_ids:
            statement = statement.where(InformationVideo.id.in_(video_ids))
        else:
            handled_video_ids = select(InformationVideoNote.video_id).where(
                InformationVideoNote.status.in_(["running", "done"])
            )
            statement = statement.where(~InformationVideo.id.in_(handled_video_ids)).limit(limit)
        statement = statement.limit(1)
        videos = self.db.scalars(statement).all()
        result["total"] += len(videos)
        if videos:
            self._validate_bilinote_settings(settings)
        client = BilinoteClient(settings["bilinote_base_url"])
        for video in videos:
            note = self._note_for_submit(video)
            try:
                video.status = "note_running"
                note.status = "running"
                note.error_message = None
                note.note_text = None
                note.external_task_id = None
                note.raw_response = None
                note.generated_at = None
                self.db.commit()
                task = client.generate_note(
                    video.video_url,
                    video.platform,
                    settings["bilinote_quality"],
                    settings["bilinote_model_name"],
                    settings["bilinote_provider_id"],
                )
                note.external_task_id = task.task_id
                note.raw_response = compact_json(task.raw_response)
                if task.note_text:
                    note.note_text = task.note_text
                    note.status = "done"
                    note.error_message = None
                    note.generated_at = datetime.now()
                    video.status = "note_done"
                    result["completed"] += 1
                elif task.task_id:
                    note.status = "running"
                    video.status = "note_running"
                    result["running"] += 1
                    result["started"] += 1
                else:
                    note.status = "failed"
                    note.error_message = task.error_message or "Bilinote response did not include task_id or note text"
                    video.status = "note_failed"
                    result["error_message"] = note.error_message
                    result["failed"] += 1
                result["video_id"] = video.id
                result["note_id"] = note.id
                result["external_task_id"] = note.external_task_id
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                logger.error(
                    "video note submit failed video_id=%s platform=%s external_video_id=%s error=%r",
                    video.id,
                    video.platform,
                    video.external_video_id,
                    exc,
                )
                logger.debug(
                    "video note submit failed traceback video_id=%s platform=%s external_video_id=%s",
                    video.id,
                    video.platform,
                    video.external_video_id,
                    exc_info=True,
                )
                note = self.db.get(InformationVideoNote, note.id) or self._create_note(video)
                video.status = "note_failed"
                note.status = "failed"
                note.error_message = repr(exc)[:2000]
                log_fetch_error(self.db, "bilinote", "video_note", video.external_video_id, repr(exc))
                self.db.commit()
                result["error_message"] = note.error_message
                result["failed"] += 1
        if result["total"] == 0:
            article_result = self.submit_pending_article_note_task(limit=limit, video_ids=video_ids)
            result.update(article_result)
        return result

    def submit_pending_article_note_task(self, limit: int = 1, video_ids: list[int] | None = None) -> dict[str, int | str | None]:
        settings = InformationSettingsService(self.db).get_settings()
        article_filter_keywords = self._parse_keywords(settings.get("article_filter_keywords", ""))
        result = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "started": 0,
            "expired": 0,
            "video_id": None,
            "note_id": None,
            "external_task_id": None,
            "error_message": None,
        }
        statement = (
            select(InformationVideo)
            .where(
                InformationVideo.content_type == "article",
                InformationVideo.status == "note_pending",
                InformationVideo.content_text.is_not(None),
            )
            .order_by(InformationVideo.published_at.desc(), InformationVideo.created_at.desc())
        )
        if video_ids:
            statement = statement.where(InformationVideo.id.in_(video_ids))
        else:
            handled_video_ids = select(InformationVideoNote.video_id).where(
                InformationVideoNote.status.in_(["running", "done"])
            )
            statement = statement.where(~InformationVideo.id.in_(handled_video_ids)).limit(limit)
        article = self.db.scalar(statement.limit(1))
        if article is None:
            return result
        result["total"] = 1
        result["video_id"] = article.id
        if self._apply_article_filter(
            article,
            article_filter_keywords,
            context="article note submit",
            source_id=article.source_id,
        ):
            self.db.commit()
            return result
        client = self._hermes_client(settings)
        note = self._note_for_submit(article, provider="hermes")
        try:
            article.status = "note_running"
            note.status = "running"
            note.error_message = None
            note.note_text = None
            note.external_task_id = None
            note.raw_response = None
            note.generated_at = None
            self.db.commit()
            run = client.start_run(self._build_article_summary_prompt(article), f"图文总结：{article.title}"[:200])
            note.external_task_id = run.run_id
            note.raw_response = compact_json(run.raw_response)
            if run.document_text:
                note.note_text = run.document_text
                note.status = "done"
                note.generated_at = datetime.now()
                article.status = "note_done"
                result["completed"] += 1
            elif run.run_id:
                note.status = "running"
                article.status = "note_running"
                result["running"] += 1
                result["started"] += 1
            else:
                note.status = "failed"
                note.error_message = "Hermes response did not include run_id or summary text"
                article.status = "note_failed"
                result["error_message"] = note.error_message
                result["failed"] += 1
            result["video_id"] = article.id
            result["note_id"] = note.id
            result["external_task_id"] = note.external_task_id
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logger.error(
                "article note submit failed video_id=%s platform=%s external_video_id=%s error=%r",
                article.id,
                article.platform,
                article.external_video_id,
                exc,
            )
            logger.debug(
                "article note submit failed traceback video_id=%s platform=%s external_video_id=%s",
                article.id,
                article.platform,
                article.external_video_id,
                exc_info=True,
            )
            note = self.db.get(InformationVideoNote, note.id) or self._create_note(article, provider="hermes")
            article.status = "note_failed"
            note.status = "failed"
            note.error_message = repr(exc)[:2000]
            log_fetch_error(self.db, "hermes", "article_note", article.external_video_id, repr(exc))
            self.db.commit()
            result["error_message"] = note.error_message
            result["failed"] += 1
        return result

    def mark_video_notes_failed(
        self,
        video_ids: list[int],
        error_message: str | None = None,
    ) -> int:
        if not video_ids:
            return 0
        videos = list(
            self.db.scalars(
                select(InformationVideo).where(InformationVideo.id.in_(video_ids))
            ).all()
        )
        message = (error_message or "Manually marked as failed").strip()[:2000]
        for video in videos:
            note = self._get_latest_note(video) or self._create_note(video)
            video.status = "note_failed"
            note.status = "failed"
            note.error_message = message
        self.db.commit()
        return len(videos)

    def retry_video_note(self, video_id: int) -> bool:
        video = self.db.get(InformationVideo, video_id)
        if video is None:
            return False
        if video.status != "note_failed":
            raise ValueError("Only failed information records can be retried")

        note = self._get_latest_note(video) or self._create_note(video)
        video.status = "note_pending"
        note.status = "pending"
        note.external_task_id = None
        note.note_text = None
        note.error_message = None
        note.raw_response = None
        note.generated_at = None
        self.db.commit()
        return True

    def repoll_video_note(self, note_id: int) -> bool:
        note = self.db.get(InformationVideoNote, note_id)
        if note is None:
            return False
        if note.status != "failed":
            raise ValueError("Only failed notes can be repolled")
        if not note.external_task_id:
            raise ValueError("Failed note does not have external_task_id")

        video = self.db.get(InformationVideo, note.video_id)
        note.status = "running"
        note.note_text = None
        note.error_message = None
        note.raw_response = None
        note.generated_at = None
        if video is not None:
            video.status = "note_running"
        self.db.commit()
        return True

    def regenerate_video_note(self, note_id: int) -> bool:
        note = self.db.get(InformationVideoNote, note_id)
        if note is None:
            return False
        if note.status in {"pending", "running"}:
            raise ValueError("Only completed or failed notes can be regenerated")

        video = self.db.get(InformationVideo, note.video_id)
        if video is None:
            return False
        video.status = "note_pending"
        note.status = "pending"
        note.external_task_id = None
        note.note_text = None
        note.error_message = None
        note.raw_response = None
        note.generated_at = None
        self.db.commit()
        return True

    def poll_running_notes(self, video_ids: list[int] | None = None) -> dict[str, int | str | None]:
        settings = InformationSettingsService(self.db).get_settings()
        bilinote_client = BilinoteClient(settings["bilinote_base_url"])
        hermes_client = self._hermes_client(settings)
        return self._check_running_notes(bilinote_client, hermes_client, video_ids=video_ids)

    def _check_running_notes(
        self,
        bilinote_client: BilinoteClient,
        hermes_client: HermesClient,
        video_ids: list[int] | None = None,
    ) -> dict[str, int | str | None]:
        result = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "started": 0,
            "expired": 0,
            "error_message": None,
        }
        statement = (
            select(InformationVideoNote)
            .join(InformationVideo, InformationVideo.id == InformationVideoNote.video_id)
            .where(InformationVideoNote.status == "running")
        )
        if video_ids:
            statement = statement.where(InformationVideoNote.video_id.in_(video_ids))
        notes = self.db.scalars(statement).all()
        now = datetime.now()
        for note in notes:
            video = self.db.get(InformationVideo, note.video_id)
            if video is not None:
                self.db.refresh(video)
            if video is not None and video.status == "note_failed":
                if note.status == "running":
                    note.status = "failed"
                    if not note.error_message:
                        note.error_message = "Information record was marked as failed"
                    self.db.commit()
                continue
            result["total"] += 1
            started_at = note.updated_at or note.created_at
            if started_at and now - started_at > VIDEO_NOTE_EXPIRY:
                note.status = "failed"
                note.error_message = f"{note.provider} task expired after 1 day without result"
                result["error_message"] = self._append_result_error(result.get("error_message"), note.error_message)
                if video is not None:
                    video.status = "note_failed"
                result["failed"] += 1
                result["expired"] += 1
                self.db.commit()
                continue
            if not note.external_task_id:
                note.status = "failed"
                note.error_message = f"{note.provider} running note does not have external_task_id"
                result["error_message"] = self._append_result_error(result.get("error_message"), note.error_message)
                if video is not None:
                    video.status = "note_failed"
                result["failed"] += 1
                self.db.commit()
                continue
            try:
                if note.provider == "hermes":
                    hermes_result = hermes_client.poll_run_once(note.external_task_id)
                    poll_status = hermes_result.status
                    note_text = hermes_result.document_text
                    error_message = None
                    raw_response = hermes_result.raw_response
                else:
                    bilinote_result = bilinote_client.poll_task_once(note.external_task_id)
                    poll_status = bilinote_result.status
                    note_text = bilinote_result.note_text
                    error_message = bilinote_result.error_message
                    raw_response = bilinote_result.raw_response
                embedded_error = self._embedded_generation_error(note.provider, note_text)
                if embedded_error:
                    poll_status = "failed"
                    note_text = None
                    error_message = embedded_error
                if video is not None:
                    self.db.refresh(video)
                self.db.refresh(note)
                if video is not None and video.status == "note_failed":
                    if note.status == "running":
                        note.status = "failed"
                        if not note.error_message:
                            note.error_message = "Information record was marked as failed"
                        self.db.commit()
                    continue
                note.raw_response = compact_json(raw_response)
                note.note_text = note_text
                note.error_message = error_message
                if poll_status == "done" and note_text:
                    note.status = "done"
                    note.generated_at = now
                    if video is not None:
                        video.status = "note_done"
                    result["completed"] += 1
                elif poll_status == "failed":
                    note.status = "failed"
                    note.error_message = note.error_message or f"{note.provider} note generation failed"
                    result["error_message"] = self._append_result_error(result.get("error_message"), note.error_message)
                    if video is not None:
                        video.status = "note_failed"
                    result["failed"] += 1
                else:
                    note.status = "running"
                    if video is not None:
                        video.status = "note_running"
                    result["running"] += 1
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                logger.error(
                    "video note poll failed note_id=%s provider=%s external_task_id=%s error=%r",
                    note.id,
                    note.provider,
                    note.external_task_id,
                    exc,
                )
                logger.debug(
                    "video note poll failed traceback note_id=%s provider=%s external_task_id=%s",
                    note.id,
                    note.provider,
                    note.external_task_id,
                    exc_info=True,
                )
                note = self.db.get(InformationVideoNote, note.id)
                if isinstance(exc, (requests_exceptions.ConnectionError, requests_exceptions.Timeout)):
                    if note is not None:
                        note.status = "running"
                        result["error_message"] = self._append_result_error(result.get("error_message"), repr(exc)[:2000])
                    if video is not None:
                        video.status = "note_running"
                    provider = note.provider if note is not None else "note"
                    log_fetch_error(self.db, provider, "video_note_poll", str(note.video_id if note else "running"), repr(exc))
                    self.db.commit()
                    result["running"] += 1
                    continue
                if note is not None:
                    note.status = "failed"
                    note.error_message = repr(exc)[:2000]
                    result["error_message"] = self._append_result_error(result.get("error_message"), note.error_message)
                if video is not None:
                    video.status = "note_failed"
                provider = note.provider if note is not None else "note"
                log_fetch_error(self.db, provider, "video_note", str(note.video_id if note else "running"), repr(exc))
                self.db.commit()
                result["failed"] += 1
        return result

    def create_configured_summary(
        self,
        config: InformationSummaryTaskConfig,
        today: date | None = None,
    ) -> InformationSummaryDocument | None:
        current_date = today or date.today()
        end_date = current_date - timedelta(days=1)
        start_date = current_date - timedelta(days=config.start_days_before)
        if start_date > end_date:
            start_date = end_date
        title = self._render_summary_title_template(
            config.title_template,
            platform=config.platform,
            category=config.category,
            start_date=start_date,
            end_date=end_date,
        )
        return self._create_period_summary(
            platform=config.platform,
            summary_date=start_date,
            category=config.category,
            start_at=datetime.combine(start_date, time.min),
            end_at=datetime.combine(end_date, time.max),
            period_end=end_date,
            title=title,
            summary_task_config_id=config.id,
            summary_instruction=config.summary_instruction,
        )

    def run_summary_task_config(
        self,
        config_id: int,
        today: date | None = None,
        require_enabled: bool = True,
    ) -> InformationSummaryDocument | None:
        config = self.db.get(InformationSummaryTaskConfig, config_id)
        if config is None or (require_enabled and not config.enabled):
            return None
        return self.create_configured_summary(config, today=today)

    def period_summary_categories(self, platform: str, start_at: datetime, end_at: datetime) -> list[str]:
        rows = self.db.scalars(
            select(InformationVideo.category)
            .join(InformationVideoNote, InformationVideoNote.video_id == InformationVideo.id)
            .where(
                InformationVideo.platform == platform,
                InformationVideoNote.status == "done",
                InformationVideoNote.note_text.is_not(None),
                func.coalesce(InformationVideo.published_at, InformationVideo.created_at) >= start_at,
                func.coalesce(InformationVideo.published_at, InformationVideo.created_at) <= end_at,
            )
            .distinct()
        ).all()
        categories = sorted({normalize_category(row) for row in rows if row})
        return categories or [DEFAULT_CATEGORY]

    def _create_period_summary(
        self,
        platform: str,
        summary_date: date,
        category: str,
        start_at: datetime,
        end_at: datetime,
        period_end: date | None = None,
        title: str | None = None,
        summary_task_config_id: int | None = None,
        summary_instruction: str | None = None,
    ) -> InformationSummaryDocument | None:
        normalized_category = normalize_category(category)
        note_filters = [
            InformationVideo.platform == platform,
            InformationVideo.category == normalized_category,
            InformationVideoNote.status == "done",
            InformationVideoNote.note_text.is_not(None),
            func.coalesce(InformationVideo.published_at, InformationVideo.created_at) >= start_at,
            func.coalesce(InformationVideo.published_at, InformationVideo.created_at) <= end_at,
        ]
        notes = self.db.scalars(
            select(InformationVideoNote)
            .join(InformationVideo, InformationVideo.id == InformationVideoNote.video_id)
            .where(*note_filters)
        ).all()
        if not notes:
            return None

        document = InformationSummaryDocument(
            platform=platform,
            summary_date=summary_date,
            category=normalized_category,
            summary_task_config_id=summary_task_config_id,
            title=self._next_summary_document_title(
                title or self._summary_title(platform, summary_date, period_end, normalized_category),
                platform=platform,
                summary_date=summary_date,
                category=normalized_category,
                summary_task_config_id=summary_task_config_id,
            ),
            status="pending",
        )
        settings = InformationSettingsService(self.db).get_settings()
        prompt = self._build_summary_prompt(
            platform,
            summary_date,
            notes,
            _normalize_instruction(summary_instruction)
            or self._summary_instruction(settings),
            period_end=period_end,
            category=normalized_category,
        )
        return self._submit_summary_document(document, notes, prompt)

    def create_custom_summary(
        self,
        note_ids: list[int],
        title: str | None = None,
        summary_instruction: str | None = None,
    ) -> InformationSummaryDocument:
        if not note_ids:
            raise ValueError("No notes selected for custom summary")
        unique_note_ids = list(dict.fromkeys(note_ids))
        notes = self.db.scalars(
            select(InformationVideoNote)
            .where(
                InformationVideoNote.id.in_(unique_note_ids),
                InformationVideoNote.status == "done",
                InformationVideoNote.note_text.is_not(None),
            )
            .order_by(InformationVideoNote.created_at.desc())
        ).all()
        if not notes:
            raise ValueError("Selected notes do not include completed note text")

        now = datetime.now()
        title_text = (title or "").strip()
        document = InformationSummaryDocument(
            platform=f"custom_{now:%Y%m%d%H%M%S}",
            summary_date=now.date(),
            category=DEFAULT_CATEGORY,
            title=title_text[:200] if title_text else f"自定义视频笔记汇总 {now:%Y-%m-%d %H:%M}",
            status="pending",
        )
        settings = InformationSettingsService(self.db).get_settings()
        prompt = self._build_summary_prompt(
            "custom",
            now.date(),
            notes,
            _normalize_instruction(summary_instruction) or self._summary_instruction(settings),
            category=DEFAULT_CATEGORY,
        )
        return self._submit_summary_document(document, notes, prompt)

    def retry_summary_document(self, document_id: int) -> InformationSummaryDocument | None:
        document = self.db.get(InformationSummaryDocument, document_id)
        if document is None:
            return None
        if document.status in {"done", "running"}:
            return document

        notes = self.db.scalars(
            select(InformationVideoNote)
            .join(InformationSummaryDocumentItem, InformationSummaryDocumentItem.note_id == InformationVideoNote.id)
            .where(
                InformationSummaryDocumentItem.document_id == document.id,
                InformationVideoNote.status == "done",
                InformationVideoNote.note_text.is_not(None),
            )
            .order_by(InformationVideoNote.created_at.desc())
        ).all()
        if not notes:
            notes = self._notes_from_custom_summary_task_log(document)
            if document.summary_task_config_id is not None:
                config = self.db.scalar(
                    select(InformationSummaryTaskConfig)
                    .where(InformationSummaryTaskConfig.id == document.summary_task_config_id)
                    .execution_options(include_deleted=True)
                )
                if config is not None:
                    return self.create_configured_summary(config, today=document.summary_date + timedelta(days=config.start_days_before))
        if not notes:
            raise ValueError("Failed custom summary has no completed note items to retry")

        settings = InformationSettingsService(self.db).get_settings()
        prompt_platform = "custom" if document.summary_task_config_id is None else document.platform
        period_end = None
        if document.summary_task_config_id is not None:
            config = self.db.scalar(
                select(InformationSummaryTaskConfig)
                .where(InformationSummaryTaskConfig.id == document.summary_task_config_id)
                .execution_options(include_deleted=True)
            )
            if config is not None:
                period_end = document.summary_date + timedelta(days=max(config.start_days_before - 1, 0))
        prompt = self._build_summary_prompt(
            prompt_platform,
            document.summary_date,
            notes,
            self._summary_instruction(settings),
            period_end=period_end,
            category=document.category,
        )
        return self._submit_summary_document(document, notes, prompt)

    def delete_summary_document(self, document_id: int) -> bool:
        document = self.db.scalar(select(InformationSummaryDocument).where(InformationSummaryDocument.id == document_id))
        if document is None:
            return False
        self.db.delete(document)
        self.db.commit()
        return True

    def poll_running_summary_documents(self) -> dict[str, int]:
        settings = InformationSettingsService(self.db).get_settings()
        client = HermesClient(
            settings["hermes_base_url"],
            settings["hermes_run_path"],
            settings["hermes_status_path_template"],
            settings.get("hermes_api_key", ""),
            settings.get("hermes_auth_header_name", "Authorization"),
            settings.get("hermes_model", "hermes-agent"),
        )
        result = {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "expired": 0,
            "wechat_pushed": 0,
            "wechat_failed": 0,
        }
        documents = list(
            self.db.scalars(
                select(InformationSummaryDocument)
                .where(InformationSummaryDocument.status == "running")
                .order_by(InformationSummaryDocument.created_at.asc())
            ).all()
        )
        result["total"] = len(documents)
        now = datetime.now()
        for document in documents:
            started_at = document.created_at
            if started_at and now - started_at > SUMMARY_DOCUMENT_EXPIRY:
                document.status = "failed"
                document.error_message = "Hermes summary task expired after 1 day without result"
                result["failed"] += 1
                result["expired"] += 1
                self.db.commit()
                continue
            if not document.hermes_run_id:
                document.status = "failed"
                document.error_message = "Hermes running summary document does not have hermes_run_id"
                result["failed"] += 1
                self.db.commit()
                continue
            try:
                poll_result = client.poll_run_once(document.hermes_run_id)
                document.raw_response = compact_json(poll_result.raw_response)
                document_text = poll_result.document_text
                embedded_error = self._embedded_generation_error("hermes", document_text)
                if embedded_error:
                    document_text = None
                    poll_status = "failed"
                    error_message = embedded_error
                else:
                    poll_status = poll_result.status
                    error_message = "Hermes summary generation failed"
                if poll_status == "done" and document_text:
                    document.document_text = document_text
                    document.status = "done"
                    document.error_message = None
                    document.generated_at = now
                    result["completed"] += 1
                    self.db.commit()
                    try:
                        if self._push_summary_document_to_wechat(document, settings):
                            result["wechat_pushed"] += 1
                    except Exception as exc:
                        result["wechat_failed"] += 1
                        log_fetch_error(self.db, "wechat_push", "summary_document", str(document.id), repr(exc))
                        self.db.commit()
                    continue
                elif poll_status == "failed":
                    document.status = "failed"
                    document.error_message = error_message
                    result["failed"] += 1
                else:
                    document.status = "running"
                    result["running"] += 1
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                document = self.db.get(InformationSummaryDocument, document.id)
                if document is not None:
                    document.status = "failed"
                    document.error_message = repr(exc)[:2000]
                log_fetch_error(self.db, "hermes", "summary_document", str(document.id if document else "running"), repr(exc))
                self.db.commit()
                result["failed"] += 1
        return result

    def _notes_from_custom_summary_task_log(self, document: InformationSummaryDocument) -> list[InformationVideoNote]:
        log = self.db.scalar(
            select(TaskLog)
            .where(
                TaskLog.task_type == "generate_information_custom_summary",
                TaskLog.target_id.is_not(None),
                TaskLog.message.like(f"%document_id={document.id};%"),
            )
            .order_by(TaskLog.started_at.desc())
        )
        if log is None or not log.target_id:
            return []
        note_ids = [int(item) for item in log.target_id.split(",") if item.strip().isdigit()]
        if not note_ids:
            return []
        return self.db.scalars(
            select(InformationVideoNote)
            .where(
                InformationVideoNote.id.in_(note_ids),
                InformationVideoNote.status == "done",
                InformationVideoNote.note_text.is_not(None),
            )
            .order_by(InformationVideoNote.created_at.desc())
        ).all()

    def _push_summary_document_to_wechat(
        self,
        document: InformationSummaryDocument,
        settings: dict[str, str],
    ) -> bool:
        if document.summary_task_config_id is None:
            return False
        config = self.db.get(InformationSummaryTaskConfig, document.summary_task_config_id)
        if config is None or not config.enabled or not config.push_to_wechat:
            return False
        if not settings.get("wechat_push_webhook_url", "").strip():
            return False
        if document.status != "done" or not document.document_text:
            return False
        client = WechatPushClient(
            settings.get("wechat_push_webhook_url", ""),
            settings.get("wechat_push_token", ""),
        )
        result = client.push_summary(
            title=document.title,
            content=document.document_text,
            summary_date=document.summary_date.isoformat(),
            platform=document.platform,
            document_id=document.id,
        )
        if not result.ok:
            raise RuntimeError(f"Wechat push failed: config_id={config.id};response={compact_json(result.raw_response)}")
        return True

    def _submit_summary_document(
        self,
        document: InformationSummaryDocument,
        notes: list[InformationVideoNote],
        prompt: str,
    ) -> InformationSummaryDocument:
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        for note in notes:
            item = self.db.scalar(
                select(InformationSummaryDocumentItem)
                .where(
                    InformationSummaryDocumentItem.document_id == document.id,
                    InformationSummaryDocumentItem.note_id == note.id,
                )
                .execution_options(include_deleted=True)
            )
            if item is None:
                self.db.add(InformationSummaryDocumentItem(document_id=document.id, note_id=note.id))
            else:
                item.is_deleted = 0
        self.db.commit()

        settings = InformationSettingsService(self.db).get_settings()
        client = HermesClient(
            settings["hermes_base_url"],
            settings["hermes_run_path"],
            settings["hermes_status_path_template"],
            settings.get("hermes_api_key", ""),
            settings.get("hermes_auth_header_name", "Authorization"),
            settings.get("hermes_model", "hermes-agent"),
        )
        try:
            document.status = "running"
            document.document_text = None
            document.error_message = None
            document.generated_at = None
            self.db.commit()
            run = client.start_run(prompt, document.title)
            if not run.run_id:
                raise RuntimeError("Hermes response did not include run_id")
            document.hermes_run_id = run.run_id
            document.raw_response = compact_json(run.raw_response)
            document.status = "running"
            self.db.commit()
            self.db.refresh(document)
            return document
        except Exception as exc:
            self.db.rollback()
            document = self.db.get(InformationSummaryDocument, document.id)
            if document is not None:
                document.status = "failed"
                document.error_message = repr(exc)[:2000]
            log_fetch_error(self.db, "hermes", "summary_document", str(document.id if document else "new"), repr(exc))
            self.db.commit()
            return document

    def list_videos(
        self,
        limit: int = 100,
        video_id: int | None = None,
        source_id: int | None = None,
        status: str | None = None,
        category: str | None = None,
        ingest_method: str | None = None,
        published_from: date | None = None,
        published_to: date | None = None,
    ) -> list[InformationVideo]:
        statement = select(InformationVideo)
        if video_id is not None:
            statement = statement.where(InformationVideo.id == video_id)
        if source_id is not None:
            statement = statement.where(InformationVideo.source_id == source_id)
        if status:
            statement = statement.where(InformationVideo.status == status)
        if category:
            statement = statement.where(InformationVideo.category == normalize_category(category))
        normalized_ingest_method = _normalize_ingest_method(ingest_method)
        if normalized_ingest_method:
            statement = statement.where(InformationVideo.ingest_method == normalized_ingest_method)
        if published_from is not None:
            statement = statement.where(InformationVideo.published_at >= datetime.combine(published_from, time.min))
        if published_to is not None:
            statement = statement.where(InformationVideo.published_at <= datetime.combine(published_to, time.max))
        return list(
            self.db.scalars(
                statement.order_by(InformationVideo.published_at.desc(), InformationVideo.created_at.desc()).limit(limit)
            ).all()
        )

    def list_videos_page(
        self,
        limit: int = 20,
        page: int = 1,
        page_size: int | None = None,
        video_id: int | None = None,
        source_id: int | None = None,
        status: str | None = None,
        category: str | None = None,
        ingest_method: str | None = None,
        published_from: date | None = None,
        published_to: date | None = None,
    ) -> dict[str, object]:
        statement = select(InformationVideo)
        if video_id is not None:
            statement = statement.where(InformationVideo.id == video_id)
        if source_id is not None:
            statement = statement.where(InformationVideo.source_id == source_id)
        if status:
            statement = statement.where(InformationVideo.status == status)
        if category:
            statement = statement.where(InformationVideo.category == normalize_category(category))
        normalized_ingest_method = _normalize_ingest_method(ingest_method)
        if normalized_ingest_method:
            statement = statement.where(InformationVideo.ingest_method == normalized_ingest_method)
        if published_from is not None:
            statement = statement.where(InformationVideo.published_at >= datetime.combine(published_from, time.min))
        if published_to is not None:
            statement = statement.where(InformationVideo.published_at <= datetime.combine(published_to, time.max))
        total = self.db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        effective_page, effective_page_size, offset = _page_params(page, page_size, limit)
        if total > 0:
            max_page = (total + effective_page_size - 1) // effective_page_size
            effective_page = min(effective_page, max_page)
            offset = (effective_page - 1) * effective_page_size
        items = list(
            self.db.scalars(
                statement.order_by(InformationVideo.published_at.desc(), InformationVideo.created_at.desc())
                .offset(offset)
                .limit(effective_page_size)
            ).all()
        )
        return {"items": items, "total": total, "page": effective_page, "page_size": effective_page_size}

    def list_notes(
        self,
        limit: int = 100,
        source_id: int | None = None,
        video_id: int | None = None,
        status: str | None = None,
        published_from: date | None = None,
        published_to: date | None = None,
    ) -> list[dict[str, object]]:
        statement = (
            select(InformationVideoNote, InformationVideo.title)
            .join(InformationVideo, InformationVideo.id == InformationVideoNote.video_id)
            .order_by(InformationVideo.published_at.desc(), InformationVideo.created_at.desc(), InformationVideoNote.created_at.desc())
            .limit(limit)
        )
        if source_id is not None:
            statement = statement.where(InformationVideo.source_id == source_id)
        if video_id is not None:
            statement = statement.where(InformationVideoNote.video_id == video_id)
        if status:
            statement = statement.where(InformationVideoNote.status == status)
        if published_from is not None:
            statement = statement.where(InformationVideo.published_at >= datetime.combine(published_from, time.min))
        if published_to is not None:
            statement = statement.where(InformationVideo.published_at <= datetime.combine(published_to, time.max))
        rows = self.db.execute(statement).all()
        return self._video_note_rows_payload(rows)

    def list_notes_page(
        self,
        limit: int = 20,
        page: int = 1,
        page_size: int | None = None,
        source_id: int | None = None,
        video_id: int | None = None,
        status: str | None = None,
        published_from: date | None = None,
        published_to: date | None = None,
    ) -> dict[str, object]:
        statement = select(InformationVideoNote, InformationVideo.title).join(
            InformationVideo,
            InformationVideo.id == InformationVideoNote.video_id,
        )
        if source_id is not None:
            statement = statement.where(InformationVideo.source_id == source_id)
        if video_id is not None:
            statement = statement.where(InformationVideoNote.video_id == video_id)
        if status:
            statement = statement.where(InformationVideoNote.status == status)
        if published_from is not None:
            statement = statement.where(InformationVideo.published_at >= datetime.combine(published_from, time.min))
        if published_to is not None:
            statement = statement.where(InformationVideo.published_at <= datetime.combine(published_to, time.max))
        total = self.db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        effective_page, effective_page_size, offset = _page_params(page, page_size, limit)
        if total > 0:
            max_page = (total + effective_page_size - 1) // effective_page_size
            effective_page = min(effective_page, max_page)
            offset = (effective_page - 1) * effective_page_size
        rows = self.db.execute(
            statement.order_by(
                InformationVideo.published_at.desc(),
                InformationVideo.created_at.desc(),
                InformationVideoNote.created_at.desc(),
            )
            .offset(offset)
            .limit(effective_page_size)
        ).all()
        return {
            "items": self._video_note_rows_payload(rows),
            "total": total,
            "page": effective_page,
            "page_size": effective_page_size,
        }

    def _video_note_rows_payload(self, rows) -> list[dict[str, object]]:
        video_ids = [note.video_id for note, _ in rows]
        videos_by_id = {
            video.id: video
            for video in self.db.scalars(select(InformationVideo).where(InformationVideo.id.in_(video_ids))).all()
        } if video_ids else {}
        source_ids = [video.source_id for video in videos_by_id.values()]
        sources_by_id = {
            source.id: source
            for source in self.db.scalars(select(InformationVideoSource).where(InformationVideoSource.id.in_(source_ids))).all()
        } if source_ids else {}
        return [
            {
                "id": note.id,
                "video_id": note.video_id,
                "video_title": video_title,
                "video_url": videos_by_id[note.video_id].video_url if note.video_id in videos_by_id else None,
                "video_published_at": videos_by_id[note.video_id].published_at if note.video_id in videos_by_id else None,
                "video_duration_seconds": videos_by_id[note.video_id].duration_seconds if note.video_id in videos_by_id else None,
                "source_id": videos_by_id[note.video_id].source_id if note.video_id in videos_by_id else None,
                "source_name": sources_by_id[videos_by_id[note.video_id].source_id].source_name
                if note.video_id in videos_by_id and videos_by_id[note.video_id].source_id in sources_by_id
                else None,
                "source_url": sources_by_id[videos_by_id[note.video_id].source_id].source_url
                if note.video_id in videos_by_id and videos_by_id[note.video_id].source_id in sources_by_id
                else None,
                "provider": note.provider,
                "external_task_id": note.external_task_id,
                "status": note.status,
                "note_text": note.note_text,
                "error_message": note.error_message,
                "generated_at": note.generated_at,
                "created_at": note.created_at,
                "updated_at": note.updated_at,
            }
            for note, video_title in rows
        ]

    def get_note_detail(self, note_id: int) -> dict[str, object] | None:
        note = self.db.scalar(
            select(InformationVideoNote)
            .options(
                load_only(
                    InformationVideoNote.id,
                    InformationVideoNote.video_id,
                    InformationVideoNote.provider,
                    InformationVideoNote.external_task_id,
                    InformationVideoNote.status,
                    InformationVideoNote.note_text,
                    InformationVideoNote.error_message,
                    InformationVideoNote.generated_at,
                    InformationVideoNote.created_at,
                    InformationVideoNote.updated_at,
                )
            )
            .where(InformationVideoNote.id == note_id)
        )
        if note is None:
            return None
        video = self.db.get(InformationVideo, note.video_id)
        source = self.db.get(InformationVideoSource, video.source_id) if video is not None else None
        return {
            "id": note.id,
            "video_id": note.video_id,
            "provider": note.provider,
            "external_task_id": note.external_task_id,
            "status": note.status,
            "note_text": note.note_text,
            "error_message": note.error_message,
            "generated_at": note.generated_at,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
            "video_title": video.title if video is not None else None,
            "video_url": video.video_url if video is not None else None,
            "video_published_at": video.published_at if video is not None else None,
            "video_duration_seconds": video.duration_seconds if video is not None else None,
            "video_platform": video.platform if video is not None else None,
            "video_external_id": video.external_video_id if video is not None else None,
            "source_id": source.id if source is not None else None,
            "source_name": source.source_name if source is not None else video.author_name if video is not None else None,
            "source_url": source.source_url if source is not None else None,
        }

    def get_note_raw_response(self, note_id: int) -> dict[str, object] | None:
        note = self.db.scalar(
            select(InformationVideoNote)
            .options(load_only(InformationVideoNote.id, InformationVideoNote.raw_response))
            .where(InformationVideoNote.id == note_id)
        )
        if note is None:
            return None
        return {"id": note.id, "raw_response": note.raw_response}

    def list_summary_documents(
        self,
        limit: int = 100,
        summary_task_config_id: int | None = None,
        manual_summary: bool = False,
        category: str | None = None,
    ) -> list[dict[str, object]]:
        statement = select(InformationSummaryDocument)
        if manual_summary:
            statement = statement.where(InformationSummaryDocument.summary_task_config_id.is_(None))
        elif summary_task_config_id is not None:
            statement = statement.where(InformationSummaryDocument.summary_task_config_id == summary_task_config_id)
        if category:
            statement = statement.where(InformationSummaryDocument.category == normalize_category(category))
        documents = list(
            self.db.scalars(
                statement.order_by(InformationSummaryDocument.created_at.desc()).limit(limit)
            ).all()
        )
        return [self._summary_document_payload(document) for document in documents]

    def list_summary_documents_page(
        self,
        limit: int = 20,
        page: int = 1,
        page_size: int | None = None,
        summary_task_config_id: int | None = None,
        manual_summary: bool = False,
        category: str | None = None,
    ) -> dict[str, object]:
        statement = select(InformationSummaryDocument)
        if manual_summary:
            statement = statement.where(InformationSummaryDocument.summary_task_config_id.is_(None))
        elif summary_task_config_id is not None:
            statement = statement.where(InformationSummaryDocument.summary_task_config_id == summary_task_config_id)
        if category:
            statement = statement.where(InformationSummaryDocument.category == normalize_category(category))
        total = self.db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        effective_page, effective_page_size, offset = _page_params(page, page_size, limit)
        if total > 0:
            max_page = (total + effective_page_size - 1) // effective_page_size
            effective_page = min(effective_page, max_page)
            offset = (effective_page - 1) * effective_page_size
        documents = list(
            self.db.scalars(
                statement.order_by(InformationSummaryDocument.created_at.desc())
                .offset(offset)
                .limit(effective_page_size)
            ).all()
        )
        return {
            "items": [self._summary_document_payload(document) for document in documents],
            "total": total,
            "page": effective_page,
            "page_size": effective_page_size,
        }

    def get_summary_document(self, document_id: int) -> dict[str, object] | None:
        document = self.db.scalar(select(InformationSummaryDocument).where(InformationSummaryDocument.id == document_id))
        if document is None:
            return None
        return self._summary_document_payload(document)

    def _summary_document_payload(self, document: InformationSummaryDocument) -> dict[str, object]:
        summary_task_name = self._summary_task_name(document.summary_task_config_id)
        return {
            "id": document.id,
            "platform": document.platform,
            "summary_task_config_id": document.summary_task_config_id,
            "summary_task_name": summary_task_name or ("手动汇总" if document.summary_task_config_id is None else None),
            "summary_date": document.summary_date,
            "category": document.category,
            "title": document.title,
            "status": document.status,
            "hermes_run_id": document.hermes_run_id,
            "document_text": document.document_text,
            "error_message": document.error_message,
            "generated_at": document.generated_at,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
            "notes": self._summary_document_notes(document.id),
        }

    def _summary_task_name(self, summary_task_config_id: int | None) -> str | None:
        if summary_task_config_id is None:
            return None
        config = self.db.scalar(
            select(InformationSummaryTaskConfig)
            .where(InformationSummaryTaskConfig.id == summary_task_config_id)
            .execution_options(include_deleted=True)
        )
        return config.task_name if config is not None else None

    def _summary_document_notes(self, document_id: int) -> list[dict[str, object]]:
        rows = self.db.execute(
            select(InformationVideoNote, InformationVideo, InformationVideoSource)
            .join(InformationSummaryDocumentItem, InformationSummaryDocumentItem.note_id == InformationVideoNote.id)
            .join(InformationVideo, InformationVideo.id == InformationVideoNote.video_id)
            .outerjoin(InformationVideoSource, InformationVideoSource.id == InformationVideo.source_id)
            .where(InformationSummaryDocumentItem.document_id == document_id)
            .order_by(InformationVideo.published_at.desc(), InformationVideo.created_at.desc(), InformationVideoNote.created_at.desc())
        ).all()
        return [
            {
                "id": note.id,
                "video_id": note.video_id,
                "video_title": video.title if video is not None else None,
                "video_url": video.video_url if video is not None else None,
                "video_published_at": video.published_at if video is not None else None,
                "video_duration_seconds": video.duration_seconds if video is not None else None,
                "source_id": source.id if source is not None else video.source_id if video is not None else None,
                "source_name": source.source_name if source is not None else video.author_name if video is not None else None,
                "source_url": source.source_url if source is not None else None,
                "category": video.category if video is not None else None,
                "status": note.status,
                "generated_at": note.generated_at,
            }
            for note, video, source in rows
        ]

    def _get_latest_note(self, video: InformationVideo) -> InformationVideoNote | None:
        provider = "hermes" if video.content_type == "article" else "bilinote"
        return self.db.scalar(
            select(InformationVideoNote)
            .where(
                InformationVideoNote.video_id == video.id,
                InformationVideoNote.provider == provider,
            )
            .order_by(InformationVideoNote.created_at.desc(), InformationVideoNote.id.desc())
        )

    def _create_note(self, video: InformationVideo, provider: str | None = None) -> InformationVideoNote:
        note_provider = provider or ("hermes" if video.content_type == "article" else "bilinote")
        note = InformationVideoNote(video_id=video.id, provider=note_provider, status="pending")
        self.db.add(note)
        self.db.commit()
        self.db.refresh(note)
        return note

    def _note_for_submit(self, video: InformationVideo, provider: str | None = None) -> InformationVideoNote:
        note_provider = provider or ("hermes" if video.content_type == "article" else "bilinote")
        note = self.db.scalar(
            select(InformationVideoNote)
            .where(
                InformationVideoNote.video_id == video.id,
                InformationVideoNote.provider == note_provider,
                InformationVideoNote.status.in_(["failed", "pending"]),
            )
            .order_by(InformationVideoNote.created_at.desc(), InformationVideoNote.id.desc())
        )
        return note or self._create_note(video, provider=note_provider)

    @staticmethod
    def _append_result_error(existing: object, error_message: str | None) -> str | None:
        if not error_message:
            return str(existing) if existing else None
        if not existing:
            return error_message
        return f"{existing};{error_message}"

    @staticmethod
    def _embedded_generation_error(provider: str, note_text: str | None) -> str | None:
        if not note_text:
            return None
        content_lines = [
            line.strip()
            for line in note_text.splitlines()
            if line.strip() and not line.strip().startswith("> 来源链接")
        ]
        content = "\n".join(content_lines).strip()
        if content in {"'NoneType' object is not iterable", "NoneType object is not iterable"}:
            return f"{provider} returned exception text as markdown: {content}"
        lower_content = content.lower()
        if (
            "api call failed after 3 retries" in lower_content
            and "non-streaming api call timed out" in lower_content
            and "with no response" in lower_content
        ):
            return f"{provider} returned exception text as markdown: {content}"
        return None

    @staticmethod
    def _parse_keywords(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        return [
            item.strip().lower()
            for item in re.split(r"[\n,，;；]+", raw_value)
            if item.strip()
        ]

    def _apply_article_filter(
        self,
        target,
        keywords: list[str],
        *,
        context: str,
        source_id: int | None = None,
    ) -> bool:
        if not self._article_matches_filter(target, keywords):
            return False
        if hasattr(target, "status"):
            target.status = "invalid_content"
        logger.debug(
            "%s marked filtered article invalid source_id=%s platform=%s external_video_id=%s title=%s",
            context,
            source_id,
            getattr(target, "platform", None),
            getattr(target, "external_video_id", None),
            str(getattr(target, "title", ""))[:120],
        )
        return True

    @staticmethod
    def _article_matches_filter(target, keywords: list[str]) -> bool:
        if getattr(target, "content_type", None) != "article" or not keywords:
            return False
        searchable_text = f"{getattr(target, 'title', '')}\n{getattr(target, 'content_text', '') or ''}".lower()
        return any(keyword in searchable_text for keyword in keywords)

    @staticmethod
    def _hermes_client(settings: dict[str, str]) -> HermesClient:
        return HermesClient(
            settings["hermes_base_url"],
            settings["hermes_run_path"],
            settings["hermes_status_path_template"],
            settings.get("hermes_api_key", ""),
            settings.get("hermes_auth_header_name", "Authorization"),
            settings.get("hermes_model", "hermes-agent"),
        )

    @staticmethod
    def _validate_bilinote_settings(settings: dict[str, str]) -> None:
        missing = [
            key
            for key in ("bilinote_provider_id", "bilinote_model_name", "bilinote_quality")
            if not settings.get(key)
        ]
        if missing:
            raise ValueError(f"Missing Bilinote settings: {', '.join(missing)}")

    @staticmethod
    def _video_note_cutoff(settings: dict[str, str]) -> datetime | None:
        raw_value = settings.get("video_note_recent_days", "3")
        try:
            days = int(str(raw_value).strip())
        except ValueError:
            days = 3
        if days <= 0:
            return None
        return datetime.now() - timedelta(days=days)

    @staticmethod
    def _summary_instruction(settings: dict[str, str]) -> str:
        return settings.get("hermes_summary_instruction", "")

    @staticmethod
    def _summary_title(
        platform: str,
        summary_date: date,
        period_end: date | None = None,
        category: str = DEFAULT_CATEGORY,
    ) -> str:
        category_text = normalize_category(category)
        if period_end is not None and period_end != summary_date:
            end_date = period_end or summary_date + timedelta(days=6)
            return f"{summary_date.isoformat()} 至 {end_date.isoformat()} {platform} {category_text}汇总"
        return f"{summary_date.isoformat()} {platform} {category_text}汇总"

    def _next_summary_document_title(
        self,
        base_title: str,
        *,
        platform: str,
        summary_date: date,
        category: str,
        summary_task_config_id: int | None,
    ) -> str:
        existing_count = self.db.scalar(
            select(func.count(InformationSummaryDocument.id))
            .where(
                InformationSummaryDocument.platform == platform,
                InformationSummaryDocument.summary_date == summary_date,
                InformationSummaryDocument.category == normalize_category(category),
                InformationSummaryDocument.summary_task_config_id == summary_task_config_id,
            )
            .execution_options(include_deleted=True)
        ) or 0
        title = base_title.strip()
        if existing_count <= 0:
            return title[:200]
        suffix = f"（第{existing_count + 1}次）"
        return f"{title[:200 - len(suffix)]}{suffix}"

    @staticmethod
    def _render_summary_title_template(
        template: str,
        *,
        platform: str,
        category: str,
        start_date: date,
        end_date: date,
    ) -> str:
        context = {
            "platform": platform,
            "category": normalize_category(category),
            "start_date": start_date,
            "end_date": end_date,
            "date": start_date,
        }
        try:
            title = _normalize_title_template(template).format(**context)
        except Exception as exc:
            raise ValueError(f"Invalid summary title template: {exc}") from exc
        title = title.strip()
        if not title:
            raise ValueError("summary title template rendered empty title")
        return title[:200]

    def _build_summary_prompt(
        self,
        platform: str,
        summary_date: date,
        notes: list[InformationVideoNote],
        instruction: str = "",
        period_end: date | None = None,
        category: str = DEFAULT_CATEGORY,
    ) -> str:
        blocks = []
        for idx, note in enumerate(notes, start=1):
            video = self.db.get(InformationVideo, note.video_id)
            source = self.db.get(InformationVideoSource, video.source_id) if video is not None else None
            author = (
                source.source_name
                if source is not None and source.source_name
                else video.author_name
                if video is not None and video.author_name
                else "未知作者"
            )
            title = video.title if video is not None and video.title else f"视频 {note.video_id}"
            url = video.video_url if video is not None and video.video_url else ""
            published_at = video.published_at.isoformat(sep=" ") if video is not None and video.published_at else "未知"
            metadata = [
                f"发布账号：{author}",
                f"作者：{author}",
                f"标题：{title}",
                f"发布时间：{published_at}",
            ]
            if url:
                metadata.append(f"链接：{url}")
            blocks.append(f"## 视频 {idx}\n" + "\n".join(metadata) + f"\n\n{note.note_text or ''}")
        instruction_text = instruction.strip()
        instruction_block = f"补充说明：\n{instruction_text}\n\n" if instruction_text else ""
        period_text = (
            f"{summary_date.isoformat()} 至 {(period_end or summary_date + timedelta(days=6)).isoformat()}"
            if period_end is not None and period_end != summary_date
            else summary_date.isoformat()
        )
        return (
            f"请将以下 {platform} 视频的 Bilinote 文字总结汇总成一篇中文汇总文档。\n"
            f"汇总周期：{period_text}\n"
            f"视频分类：{normalize_category(category)}\n"
            f"{instruction_block}"
            "要求：提炼主题、关键观点、可执行信息和待跟进事项；去重，按主题分组。\n"
            "重点标注要求：请主动识别值得关注的核心结论、风险信号、分歧观点和行动建议，使用 **重点：...** 或 **风险：...** 进行醒目标注。\n"
            "标题要求：不要额外输出封面标题或一级标题，正文直接从 ## 二级标题开始。\n"
            f"{markdown_output_instruction()}\n\n"
            + "\n\n".join(blocks)
        )

    def _build_article_summary_prompt(self, article: InformationVideo) -> str:
        source = self.db.get(InformationVideoSource, article.source_id)
        author = source.source_name if source is not None and source.source_name else article.author_name or "未知作者"
        published_at = article.published_at.isoformat(sep=" ") if article.published_at else "未知"
        url = article.video_url or ""
        metadata = [
            f"作者：{author}",
            f"标题：{article.title}",
            f"发布时间：{published_at}",
        ]
        if url:
            metadata.append(f"链接：{url}")
        return (
            "请将以下 B站图文投稿整理成一篇中文 Markdown 摘要。\n"
            "这是单条图文投稿的直接总结任务，不要合并其他视频笔记，也不要假设存在 Bilinote 总结。\n"
            "要求：提炼核心观点、重要依据、风险信号、分歧观点和可跟进行动；保留作者和发布时间背景。\n"
            f"{markdown_output_instruction()}\n\n"
            + "\n".join(metadata)
            + "\n\n正文：\n"
            + (article.content_text or "")
        )
