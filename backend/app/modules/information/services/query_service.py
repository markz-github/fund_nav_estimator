from __future__ import annotations

from app.modules.information.services.common import *


class QueryService(InformationServiceBase):
    @staticmethod
    def _sort_order(sort_order: str | None) -> str:
        return "asc" if str(sort_order or "").lower() == "asc" else "desc"

    def _apply_sort(self, statement, sort_column, sort_order: str | None, *fallback_columns):
        direction = self._sort_order(sort_order)
        ordered_column = sort_column.asc() if direction == "asc" else sort_column.desc()
        fallbacks = [column.desc() for column in fallback_columns]
        return statement.order_by(ordered_column, *fallbacks)

    def _video_ordered_statement(self, statement, sort_by: str | None, sort_order: str | None):
        sort_columns = {
            "published_at": InformationVideo.published_at,
            "title": InformationVideo.title,
            "source": func.coalesce(InformationVideoSource.source_name, InformationVideo.author_name),
            "status": InformationVideo.status,
        }
        sort_column = sort_columns.get(sort_by or "published_at", InformationVideo.published_at)
        return self._apply_sort(statement, sort_column, sort_order, InformationVideo.created_at, InformationVideo.id)

    def _note_ordered_statement(self, statement, sort_by: str | None, sort_order: str | None):
        sort_columns = {
            "published_at": InformationVideo.published_at,
            "title": InformationVideo.title,
            "source": func.coalesce(InformationVideoSource.source_name, InformationVideo.author_name),
            "status": InformationVideoNote.status,
            "generated_at": InformationVideoNote.generated_at,
        }
        sort_column = sort_columns.get(sort_by or "published_at", InformationVideo.published_at)
        return self._apply_sort(statement, sort_column, sort_order, InformationVideo.created_at, InformationVideoNote.created_at)

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
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> dict[str, object]:
        statement = select(InformationVideo).outerjoin(InformationVideoSource, InformationVideoSource.id == InformationVideo.source_id)
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
                self._video_ordered_statement(statement, sort_by, sort_order)
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
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> dict[str, object]:
        statement = select(InformationVideoNote, InformationVideo.title).join(
            InformationVideo,
            InformationVideo.id == InformationVideoNote.video_id,
        ).outerjoin(InformationVideoSource, InformationVideoSource.id == InformationVideo.source_id)
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
            self._note_ordered_statement(statement, sort_by, sort_order)
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
