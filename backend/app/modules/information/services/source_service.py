from __future__ import annotations

import random
import time as time_module

from app.modules.information.services.common import *
from app.modules.information.services.content_rules import ContentRules


class SourceService(ContentRules, InformationServiceBase):
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
        source_rows = self.db.scalars(
            select(InformationVideoSource.category).where(
                InformationVideoSource.id > 0,
                InformationVideoSource.category.is_not(None),
            )
        ).all()
        values.update(normalize_category(value) for value in source_rows if value)
        for model in (InformationVideo, InformationSummaryDocument, InformationSummaryTaskConfig):
            rows = self.db.scalars(select(model.category).where(model.category.is_not(None))).all()
            values.update(normalize_category(value) for value in rows if value)
        return sorted(values, key=lambda item: (item != DEFAULT_CATEGORY, item))

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

    def update_video_category(self, video_id: int, category: str) -> InformationVideo | None:
        normalized_category = normalize_category(category)
        if not normalized_category:
            raise ValueError("分类不能为空")
        video = self.db.scalar(select(InformationVideo).where(InformationVideo.id == video_id))
        if video is None:
            return None
        video.category = normalized_category
        self.db.commit()
        self.db.refresh(video)
        return video

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
        sources = list(self.db.scalars(statement).all())
        settings_service = InformationSettingsService(self.db)
        settings = settings_service.get_settings()
        bilibili_cookie = settings.get("bilibili_cookie", "").strip()
        article_filter_keywords = self._parse_keywords(settings.get("article_filter_keywords", ""))
        article_min_content_chars = self._article_min_content_chars(settings)
        jitter_min_seconds, jitter_max_seconds = settings_service.scan_jitter_range_seconds(settings)
        logger.debug(
            "video scan started source_id=%s source_ids=%s limit=%s enabled_source_count=%s",
            source_id,
            source_ids,
            limit,
            len(sources),
        )
        created = 0
        for index, source in enumerate(sources):
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
                        article_min_content_chars,
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
            finally:
                self._wait_before_next_source_scan(
                    source,
                    is_last_source=index >= len(sources) - 1,
                    min_seconds=jitter_min_seconds,
                    max_seconds=jitter_max_seconds,
                )
        logger.info("video scan finished source_id=%s source_ids=%s limit=%s created=%s", source_id, source_ids, limit, created)
        return created

    def _wait_before_next_source_scan(
        self,
        source: InformationVideoSource,
        *,
        is_last_source: bool,
        min_seconds: float,
        max_seconds: float,
    ) -> None:
        if is_last_source or max_seconds <= 0:
            return
        lower = max(0.0, min_seconds)
        upper = max(lower, max_seconds)
        wait_seconds = random.uniform(lower, upper)
        if wait_seconds <= 0:
            return
        logger.info(
            "video source scan jitter wait source_id=%s min_seconds=%s max_seconds=%s wait_seconds=%.3f",
            source.id,
            lower,
            upper,
            wait_seconds,
        )
        time_module.sleep(wait_seconds)

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
        article_min_content_chars = self._article_min_content_chars(settings)
        is_invalid_content = self._apply_article_filter(
            snapshot,
            article_filter_keywords,
            article_min_content_chars,
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
