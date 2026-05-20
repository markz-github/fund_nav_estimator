from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only

from app.modules.information.models.summary_document import (
    InformationSummaryDocument,
    InformationSummaryDocumentItem,
)
from app.modules.information.models.task_log import TaskLog
from app.modules.information.models.video import InformationVideo
from app.modules.information.models.video_note import InformationVideoNote
from app.modules.information.models.video_source import InformationVideoSource
from app.modules.information.schemas.video import VideoSourceCreate, VideoSourceUpdate
from app.modules.information.services.bilinote_client import BilinoteClient, compact_json
from app.modules.information.services.hermes_client import HermesClient
from app.modules.information.services.information_settings_service import InformationSettingsService
from app.modules.information.services.operation_log_service import log_fetch_error
from app.modules.information.services.video_source_adapters import get_video_source_adapter
from app.modules.information.services.wechat_push_client import WechatPushClient


logger = logging.getLogger(__name__)
VIDEO_NOTE_EXPIRY = timedelta(days=1)
SUMMARY_DOCUMENT_EXPIRY = timedelta(days=1)


class VideoInformationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.last_scan_errors: list[str] = []

    def list_sources(self, enabled_only: bool = False) -> list[dict[str, object]]:
        statement = select(InformationVideoSource).order_by(InformationVideoSource.created_at.desc())
        if enabled_only:
            statement = statement.where(InformationVideoSource.enabled == 1)
        sources = list(self.db.scalars(statement).all())
        result = []
        for source in sources:
            video_count = self.db.scalar(
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
            result.append(
                {
                    "id": source.id,
                    "platform": source.platform,
                    "source_name": source.source_name,
                    "source_url": source.source_url,
                    "external_source_id": source.external_source_id,
                    "enabled": source.enabled,
                    "last_scanned_at": source.last_scanned_at,
                    "remark": source.remark,
                    "video_count": video_count,
                    "note_count": note_count,
                    "created_at": source.created_at,
                    "updated_at": source.updated_at,
                }
            )
        return result

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
                remark=payload.remark,
                enabled=1,
            )
            self.db.add(source)
        else:
            source.is_deleted = 0
            source.source_name = payload.source_name.strip()
            source.source_url = payload.source_url
            source.external_source_id = normalized_id
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
        statement = select(InformationVideoSource).where(InformationVideoSource.enabled == 1)
        if source_ids:
            statement = statement.where(InformationVideoSource.id.in_(source_ids))
        elif source_id is not None:
            statement = statement.where(InformationVideoSource.id == source_id)
        sources = self.db.scalars(statement).all()
        settings = InformationSettingsService(self.db).get_settings()
        bilibili_cookie = settings.get("bilibili_cookie", "").strip()
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
                            existing.author_name = snapshot.author_name
                            existing.published_at = snapshot.published_at
                            existing.status = "note_pending"
                            existing.raw_response = json.dumps(snapshot.raw_response, ensure_ascii=False)
                            created += 1
                            source_created += 1
                            continue
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
                            author_name=snapshot.author_name,
                            published_at=snapshot.published_at,
                            status="note_pending",
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

    def scan_next_source(self, limit: int = 20) -> dict[str, int | str | None]:
        source = self.db.scalar(
            select(InformationVideoSource)
            .where(InformationVideoSource.enabled == 1)
            .order_by(InformationVideoSource.last_scanned_at.is_not(None), InformationVideoSource.last_scanned_at.asc())
        )
        if source is None:
            logger.info("scheduled video scan skipped no enabled source")
            return {"source_id": None, "created": 0}
        created = self.scan_sources(source_id=source.id, limit=limit)
        result: dict[str, int | str | None] = {"source_id": source.id, "created": created}
        if self.last_scan_errors:
            result["error_message"] = ";".join(self.last_scan_errors)
        return result

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
        running_note = self.db.scalar(select(InformationVideoNote).where(InformationVideoNote.status == "running"))
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
                InformationVideo.status.in_(["note_pending", "discovered", "note_failed"]),
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
        client = self._hermes_client(settings)
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
                InformationVideo.status.in_(["note_pending", "note_failed"]),
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
        result["total"] = len(notes)
        now = datetime.now()
        for note in notes:
            video = self.db.get(InformationVideo, note.video_id)
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

    def create_daily_summary(self, platform: str = "bilibili", summary_date: date | None = None) -> InformationSummaryDocument | None:
        target_date = summary_date or date.today()
        start_at = datetime.combine(target_date, time.min)
        end_at = datetime.combine(target_date, time.max)
        existing = self.db.scalar(
            select(InformationSummaryDocument)
            .where(
                InformationSummaryDocument.platform == platform,
                InformationSummaryDocument.summary_date == target_date,
            )
            .execution_options(include_deleted=True)
        )
        if existing is not None:
            existing.is_deleted = 0
        if existing and existing.status in {"done", "running"}:
            return existing

        notes = self.db.scalars(
            select(InformationVideoNote)
            .join(InformationVideo, InformationVideo.id == InformationVideoNote.video_id)
            .where(
                InformationVideo.platform == platform,
                InformationVideoNote.status == "done",
                InformationVideoNote.note_text.is_not(None),
                func.coalesce(InformationVideo.published_at, InformationVideo.created_at) >= start_at,
                func.coalesce(InformationVideo.published_at, InformationVideo.created_at) <= end_at,
                ~InformationVideoNote.id.in_(
                    select(InformationSummaryDocumentItem.note_id)
                    .join(InformationSummaryDocument, InformationSummaryDocument.id == InformationSummaryDocumentItem.document_id)
                    .where(
                        InformationSummaryDocument.platform == platform,
                        InformationSummaryDocument.summary_date == target_date,
                        InformationSummaryDocument.status == "done",
                    )
                ),
            )
        ).all()
        if not notes:
            return existing

        document = existing or InformationSummaryDocument(
            platform=platform,
            summary_date=target_date,
            title=f"{target_date.isoformat()} {platform} 视频摘要",
            status="pending",
        )
        settings = InformationSettingsService(self.db).get_settings()
        prompt = self._build_summary_prompt(
            platform,
            target_date,
            notes,
            settings.get("hermes_summary_instruction", ""),
        )
        return self._submit_summary_document(document, notes, prompt)

    def create_custom_summary(self, note_ids: list[int], title: str | None = None) -> InformationSummaryDocument:
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
            title=title_text[:200] if title_text else f"自定义视频笔记汇总 {now:%Y-%m-%d %H:%M}",
            status="pending",
        )
        settings = InformationSettingsService(self.db).get_settings()
        prompt = self._build_summary_prompt(
            "custom",
            now.date(),
            notes,
            settings.get("hermes_summary_instruction", ""),
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
            if not document.platform.startswith("custom_"):
                return self.create_daily_summary(platform=document.platform, summary_date=document.summary_date)
        if not notes:
            raise ValueError("Failed custom summary has no completed note items to retry")

        settings = InformationSettingsService(self.db).get_settings()
        prompt_platform = "custom" if document.platform.startswith("custom_") else document.platform
        prompt = self._build_summary_prompt(
            prompt_platform,
            document.summary_date,
            notes,
            settings.get("hermes_summary_instruction", ""),
        )
        return self._submit_summary_document(document, notes, prompt)

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
                if poll_result.status == "done" and poll_result.document_text:
                    document.document_text = poll_result.document_text
                    document.status = "done"
                    document.error_message = None
                    document.generated_at = now
                    result["completed"] += 1
                elif poll_result.status == "failed":
                    document.status = "failed"
                    document.error_message = "Hermes summary generation failed"
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

    def push_daily_summary_to_wechat(self, platform: str = "bilibili", summary_date: date | None = None) -> dict[str, object]:
        target_date = summary_date or date.today()
        document = self.db.scalar(
            select(InformationSummaryDocument).where(
                InformationSummaryDocument.platform == platform,
                InformationSummaryDocument.summary_date == target_date,
                InformationSummaryDocument.status == "done",
                InformationSummaryDocument.document_text.is_not(None),
            )
        )
        if document is None:
            return {"pushed": 0, "document_id": None, "message": "no done daily summary document"}

        settings = InformationSettingsService(self.db).get_settings()
        if not settings.get("wechat_push_webhook_url", "").strip():
            return {"pushed": 0, "document_id": document.id, "message": "wechat push webhook url is not configured"}
        client = WechatPushClient(
            settings.get("wechat_push_webhook_url", ""),
            settings.get("wechat_push_token", ""),
        )
        result = client.push_summary(
            title=document.title,
            content=document.document_text or "",
            summary_date=document.summary_date.isoformat(),
            platform=document.platform,
            document_id=document.id,
        )
        if not result.ok:
            raise RuntimeError(f"Wechat push failed: {compact_json(result.raw_response)}")
        return {"pushed": 1, "document_id": document.id, "message": compact_json(result.raw_response)}

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
        if published_from is not None:
            statement = statement.where(InformationVideo.published_at >= datetime.combine(published_from, time.min))
        if published_to is not None:
            statement = statement.where(InformationVideo.published_at <= datetime.combine(published_to, time.max))
        return list(
            self.db.scalars(
                statement.order_by(InformationVideo.published_at.desc(), InformationVideo.created_at.desc()).limit(limit)
            ).all()
        )

    def list_notes(
        self,
        limit: int = 100,
        source_id: int | None = None,
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
        if published_from is not None:
            statement = statement.where(InformationVideo.published_at >= datetime.combine(published_from, time.min))
        if published_to is not None:
            statement = statement.where(InformationVideo.published_at <= datetime.combine(published_to, time.max))
        rows = self.db.execute(statement).all()
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

    def list_summary_documents(self, limit: int = 100) -> list[dict[str, object]]:
        documents = list(
            self.db.scalars(
                select(InformationSummaryDocument).order_by(InformationSummaryDocument.created_at.desc()).limit(limit)
            ).all()
        )
        return [self._summary_document_payload(document) for document in documents]

    def get_summary_document(self, document_id: int) -> dict[str, object] | None:
        document = self.db.get(InformationSummaryDocument, document_id)
        if document is None:
            return None
        return self._summary_document_payload(document)

    def _summary_document_payload(self, document: InformationSummaryDocument) -> dict[str, object]:
        return {
            "id": document.id,
            "platform": document.platform,
            "summary_date": document.summary_date,
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
                "source_id": source.id if source is not None else video.source_id if video is not None else None,
                "source_name": source.source_name if source is not None else video.author_name if video is not None else None,
                "source_url": source.source_url if source is not None else None,
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

    def _build_summary_prompt(
        self,
        platform: str,
        summary_date: date,
        notes: list[InformationVideoNote],
        instruction: str = "",
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
                f"作者：{author}",
                f"标题：{title}",
                f"发布时间：{published_at}",
            ]
            if url:
                metadata.append(f"链接：{url}")
            blocks.append(f"## 视频 {idx}\n" + "\n".join(metadata) + f"\n\n{note.note_text or ''}")
        instruction_text = instruction.strip()
        instruction_block = f"补充说明：\n{instruction_text}\n\n" if instruction_text else ""
        return (
            f"请将以下 {platform} 视频的 Bilinote 文字总结汇总成一篇中文文档。\n"
            f"日期：{summary_date.isoformat()}\n"
            f"{instruction_block}"
            "要求：提炼主题、关键观点、可执行信息和待跟进事项；去重，按主题分组。\n"
            "重点标注要求：请主动识别值得关注的核心结论、风险信号、分歧观点和行动建议，使用 **重点：...** 或 **风险：...** 进行醒目标注。\n"
            "输出格式要求：请以 Markdown 格式输出；使用 #、##、### 组织标题层级；"
            "使用有序列表和无序列表归纳要点；重要观点使用 **加粗**；"
            "不要输出 HTML；不要把正文包裹在 ```markdown 代码块中。\n\n"
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
            "输出格式要求：使用 #、##、### 组织标题层级；使用列表归纳要点；重要观点使用 **加粗**；"
            "不要输出 HTML；不要把正文包裹在 ```markdown 代码块中。\n\n"
            + "\n".join(metadata)
            + "\n\n正文：\n"
            + (article.content_text or "")
        )
