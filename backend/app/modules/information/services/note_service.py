from __future__ import annotations

from app.modules.information.services.common import *
from app.modules.information.services.content_rules import ContentRules
from app.modules.information.services.prompt_builder import PromptBuilder


class NoteService(ContentRules, PromptBuilder, InformationServiceBase):
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
        if video_ids:
            statement = statement.where(InformationVideo.id.in_(video_ids))
        else:
            cutoff = self._video_note_cutoff(settings)
            if cutoff is not None:
                statement = statement.where(func.coalesce(InformationVideo.published_at, InformationVideo.created_at) >= cutoff)
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
                    InformationSettingsService(self.db).bilinote_extras_for_category(video.category),
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
        article_min_content_chars = self._article_min_content_chars(settings)
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
            article_min_content_chars,
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

    def mark_videos_invalid(
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
        message = (error_message or "Manually marked as invalid content").strip()[:2000]
        for video in videos:
            video.status = "invalid_content"
            notes = list(
                self.db.scalars(
                    select(InformationVideoNote).where(InformationVideoNote.video_id == video.id)
                ).all()
            )
            for note in notes:
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
