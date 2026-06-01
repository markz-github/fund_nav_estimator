from __future__ import annotations

from app.modules.information.services.common import *
from app.modules.information.services.content_rules import ContentRules
from app.modules.information.services.prompt_builder import PromptBuilder


class SummaryDocumentService(ContentRules, PromptBuilder, InformationServiceBase):
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
            document_template=config.document_template,
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
        document_template: str | None = None,
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
        prompt = self._build_summary_prompt(
            platform,
            summary_date,
            notes,
            _normalize_instruction(summary_instruction)
            or self._summary_instruction(normalized_category),
            (
                self._summary_document_template(normalized_category)
                if document_template is None
                else _normalize_document_template(document_template)
            ),
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
        prompt = self._build_summary_prompt(
            "custom",
            now.date(),
            notes,
            _normalize_instruction(summary_instruction) or self._summary_instruction(DEFAULT_CATEGORY),
            self._summary_document_template(DEFAULT_CATEGORY),
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

        prompt_platform = "custom" if document.summary_task_config_id is None else document.platform
        period_end = None
        config = None
        if document.summary_task_config_id is not None:
            config = self.db.scalar(
                select(InformationSummaryTaskConfig)
                .where(InformationSummaryTaskConfig.id == document.summary_task_config_id)
                .execution_options(include_deleted=True)
            )
            if config is not None:
                period_end = document.summary_date + timedelta(days=max(config.start_days_before - 1, 0))
        summary_instruction = self._summary_instruction(document.category)
        document_template = self._summary_document_template(document.category)
        if config is not None:
            summary_instruction = _normalize_instruction(config.summary_instruction) or summary_instruction
            document_template = _normalize_document_template(config.document_template)
        prompt = self._build_summary_prompt(
            prompt_platform,
            document.summary_date,
            notes,
            summary_instruction,
            document_template,
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

    def _summary_instruction(self, category: str | None = None) -> str:
        normalized_category = normalize_category(category)
        return (
            self.db.scalar(
                select(InformationSummaryDocumentTemplate.summary_instruction).where(
                    InformationSummaryDocumentTemplate.category == normalized_category,
                    InformationSummaryDocumentTemplate.summary_instruction != "",
                )
            )
            or ""
        )

    def _summary_document_template(self, category: str | None = None) -> str:
        normalized_category = normalize_category(category)
        return (
            self.db.scalar(
                select(InformationSummaryDocumentTemplate.template_text).where(
                    InformationSummaryDocumentTemplate.category == normalized_category,
                    InformationSummaryDocumentTemplate.template_text != "",
                )
            )
            or ""
        )

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
