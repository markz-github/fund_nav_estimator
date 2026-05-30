from __future__ import annotations

from datetime import date
from datetime import datetime
import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.information.models.summary_task_config import InformationSummaryTaskConfig
from app.modules.information.schemas.video import (
    ActionResult,
    GenerateSummaryTaskConfigNowOut,
    GenerateSummaryFromNotesRequest,
    InformationCategoriesOut,
    GenerateVideoNotesRequest,
    InformationStatusOptionsOut,
    InformationSettingsOut,
    InformationSettingsUpdate,
    ManualLinkActionOut,
    ManualLinkCreate,
    MarkVideoNotesFailedRequest,
    ScanVideosRequest,
    SummaryDocumentOut,
    SummaryDocumentPageOut,
    SummaryTaskConfigCreate,
    SummaryTaskConfigOut,
    SummaryTaskConfigUpdate,
    VideoCategoryUpdate,
    VideoNoteDetailOut,
    VideoNoteOut,
    VideoNotePageOut,
    VideoNoteRawResponseOut,
    VideoOut,
    VideoPageOut,
    VideoSourcePageOut,
    VideoSourceCreate,
    VideoSourceOut,
    VideoSourceUpdate,
)
from app.modules.information.status_enums import (
    FUND_NAV_TASK_TYPES,
    INFORMATION_TASK_TYPES,
    NOTE_STATUSES,
    SOURCE_STATUSES,
    SUMMARY_DOCUMENT_STATUSES,
    TASK_STATUSES,
    VIDEO_STATUSES,
    status_options,
)
from app.modules.information.services.operation_log_service import finish_task, log_fetch_error, start_task, task_status_from_counts
from app.modules.information.services.information_settings_service import InformationSettingsService
from app.modules.information.services.note_service import NoteService
from app.modules.information.services.query_service import QueryService
from app.modules.information.services.source_service import SourceService
from app.modules.information.services.summary_document_service import SummaryDocumentService
from app.modules.information.services.summary_task_config_service import SummaryTaskConfigService
from app.scheduler.runtime import refresh_summary_task_config_jobs

router = APIRouter(prefix="/information", tags=["information"])
logger = logging.getLogger(__name__)


@router.get("/status-options", response_model=InformationStatusOptionsOut)
def get_status_options():
    return {
        "source_statuses": status_options(SOURCE_STATUSES),
        "video_statuses": status_options(VIDEO_STATUSES),
        "note_statuses": status_options(NOTE_STATUSES),
        "summary_document_statuses": status_options(SUMMARY_DOCUMENT_STATUSES),
        "task_statuses": status_options(TASK_STATUSES),
        "fund_nav_task_types": status_options(FUND_NAV_TASK_TYPES),
        "information_task_types": status_options(INFORMATION_TASK_TYPES),
    }


@router.get("/categories", response_model=InformationCategoriesOut)
def list_categories(db: Session = Depends(get_db)):
    return {"categories": SourceService(db).list_categories()}


@router.get("/summary-task-configs", response_model=list[SummaryTaskConfigOut])
def list_summary_task_configs(db: Session = Depends(get_db)):
    return SummaryTaskConfigService(db).list_summary_task_configs()


@router.post("/summary-task-configs", response_model=SummaryTaskConfigOut)
def create_summary_task_config(payload: SummaryTaskConfigCreate, db: Session = Depends(get_db)):
    try:
        config = SummaryTaskConfigService(db).create_summary_task_config(payload)
        refresh_summary_task_config_jobs()
        return config
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/summary-task-configs/{config_id}", response_model=SummaryTaskConfigOut)
def update_summary_task_config(config_id: int, payload: SummaryTaskConfigUpdate, db: Session = Depends(get_db)):
    try:
        config = SummaryTaskConfigService(db).update_summary_task_config(config_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if config is None:
        raise HTTPException(status_code=404, detail="summary task config not found")
    refresh_summary_task_config_jobs()
    return config


@router.delete("/summary-task-configs/{config_id}")
def delete_summary_task_config(config_id: int, db: Session = Depends(get_db)):
    deleted = SummaryTaskConfigService(db).delete_summary_task_config(config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="summary task config not found")
    refresh_summary_task_config_jobs()
    return {"deleted": True}


@router.post("/summary-task-configs/{config_id}/run-now", response_model=GenerateSummaryTaskConfigNowOut)
def run_summary_task_config_now(config_id: int, db: Session = Depends(get_db)):
    config = db.get(InformationSummaryTaskConfig, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="summary task config not found")
    task_log = start_task(
        db,
        "手动执行信息流配置汇总",
        "generate_information_summary_task_config",
        datetime.now(),
        str(config_id),
        target_type="summary_task_config",
        target_id=str(config_id),
    )
    try:
        document = SummaryDocumentService(db).run_summary_task_config(config_id, require_enabled=False)
    except Exception as exc:
        log_fetch_error(db, "hermes", "summary_task_config", str(config_id), repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    if document is None:
        message = f"summary_task_config_id={config_id};no completed notes to summarize"
        finish_task(db, task_log, "skipped", message)
        return {"status": "skipped", "message": message, "document": None}
    status = "success" if document.status in {"done", "running"} else "failed"
    message = f"summary_task_config_id={config_id};document_id={document.id};status={document.status}"
    finish_task(db, task_log, status, message)
    return {"status": status, "message": message, "document": QueryService(db).get_summary_document(document.id)}


def _video_note_task_status(result: dict[str, int | str | None]) -> str:
    if result.get("error_message") or int(result["failed"]) > 0:
        if int(result["completed"]) > 0 or int(result["running"]) > 0 or int(result["started"]) > 0:
            return "partial"
        return "failed"
    if int(result["running"]) > 0 or int(result["started"]) > 0:
        return "success"
    return task_status_from_counts(
        success=int(result["completed"]),
        skipped=1 if int(result["total"]) == 0 else 0,
    )


def _video_note_task_message(result: dict[str, int | str | None], target: str) -> str:
    message = (
        f"target={target};total={result['total']};completed={result['completed']};"
        f"failed={result['failed']};running={result['running']};"
        f"started={result['started']};expired={result['expired']}"
    )
    error_message = result.get("error_message")
    if error_message:
        message = f"{message};error={error_message}"
    return message


@router.get("/video-sources", response_model=list[VideoSourceOut])
def list_video_sources(enabled_only: bool = False, db: Session = Depends(get_db)):
    return SourceService(db).list_sources(enabled_only=enabled_only)


@router.get("/video-sources/page", response_model=VideoSourcePageOut)
def list_video_sources_page(
    enabled_only: bool = False,
    limit: int = 20,
    page: int = 1,
    page_size: int | None = None,
    db: Session = Depends(get_db),
):
    return SourceService(db).list_sources_page(
        enabled_only=enabled_only,
        limit=limit,
        page=page,
        page_size=page_size,
    )


@router.post("/video-sources", response_model=VideoSourceOut)
def create_video_source(payload: VideoSourceCreate, db: Session = Depends(get_db)):
    try:
        return SourceService(db).create_source(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/video-sources/{source_id}", response_model=VideoSourceOut)
def update_video_source(source_id: int, payload: VideoSourceUpdate, db: Session = Depends(get_db)):
    try:
        source = SourceService(db).update_source(source_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if source is None:
        raise HTTPException(status_code=404, detail="video source not found")
    return source


@router.delete("/video-sources/{source_id}")
def delete_video_source(source_id: int, db: Session = Depends(get_db)):
    deleted = SourceService(db).delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="video source not found")
    return {"deleted": True}


@router.get("/settings", response_model=InformationSettingsOut)
def get_information_settings(db: Session = Depends(get_db)):
    return InformationSettingsService(db).get_settings()


@router.put("/settings", response_model=InformationSettingsOut)
def update_information_settings(payload: InformationSettingsUpdate, db: Session = Depends(get_db)):
    return InformationSettingsService(db).update_settings(payload.model_dump())


@router.get("/videos", response_model=list[VideoOut])
def list_videos(
    limit: int = 100,
    video_id: int | None = None,
    source_id: int | None = None,
    status: str | None = None,
    category: str | None = None,
    ingest_method: str | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
    db: Session = Depends(get_db),
):
    return QueryService(db).list_videos(
        limit=limit,
        video_id=video_id,
        source_id=source_id,
        status=status,
        category=category,
        ingest_method=ingest_method,
        published_from=published_from,
        published_to=published_to,
    )


@router.get("/videos/page", response_model=VideoPageOut)
def list_videos_page(
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
    db: Session = Depends(get_db),
):
    return QueryService(db).list_videos_page(
        limit=limit,
        page=page,
        page_size=page_size,
        video_id=video_id,
        source_id=source_id,
        status=status,
        category=category,
        ingest_method=ingest_method,
        published_from=published_from,
        published_to=published_to,
    )


def _add_manual_link_with_log(payload: ManualLinkCreate, db: Session) -> VideoOut:
    task_log = start_task(
        db,
        "手动添加信息链接",
        "add_information_manual_link",
        datetime.now(),
        payload.url,
        target_type="link",
        target_id=payload.url[:200],
    )
    try:
        video = SourceService(db).add_manual_link(payload)
    except ValueError as exc:
        finish_task(db, task_log, "failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log_fetch_error(db, "internal", "manual_link", payload.url, repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    finish_task(db, task_log, "success", f"video_id={video.id};status={video.status};category={video.category}")
    return video


@router.post("/videos/manual-link", response_model=VideoOut)
def add_manual_link(payload: ManualLinkCreate, db: Session = Depends(get_db)):
    return _add_manual_link_with_log(payload, db)


@router.patch("/videos/{video_id}/category", response_model=VideoOut)
def update_video_category(video_id: int, payload: VideoCategoryUpdate, db: Session = Depends(get_db)):
    try:
        video = SourceService(db).update_video_category(video_id, payload.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if video is None:
        raise HTTPException(status_code=404, detail="内容不存在")
    return video


@router.post("/actions/add-manual-link", response_model=ManualLinkActionOut)
def add_manual_link_action(payload: ManualLinkCreate, db: Session = Depends(get_db)):
    video = _add_manual_link_with_log(payload, db)
    return {
        "status": "success",
        "message": f"video_id={video.id};status={video.status};category={video.category}",
        "count": 1,
        "video": video,
    }


@router.get("/video-notes", response_model=list[VideoNoteOut])
def list_video_notes(
    limit: int = 100,
    source_id: int | None = None,
    video_id: int | None = None,
    status: str | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
    db: Session = Depends(get_db),
):
    return QueryService(db).list_notes(
        limit=limit,
        source_id=source_id,
        video_id=video_id,
        status=status,
        published_from=published_from,
        published_to=published_to,
    )


@router.get("/video-notes/page", response_model=VideoNotePageOut)
def list_video_notes_page(
    limit: int = 20,
    page: int = 1,
    page_size: int | None = None,
    source_id: int | None = None,
    video_id: int | None = None,
    status: str | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
    db: Session = Depends(get_db),
):
    return QueryService(db).list_notes_page(
        limit=limit,
        page=page,
        page_size=page_size,
        source_id=source_id,
        video_id=video_id,
        status=status,
        published_from=published_from,
        published_to=published_to,
    )


@router.get("/video-notes/{note_id}", response_model=VideoNoteDetailOut)
def get_video_note(note_id: int, db: Session = Depends(get_db)):
    note = QueryService(db).get_note_detail(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="video note not found")
    return note


@router.get("/video-notes/{note_id}/raw", response_model=VideoNoteRawResponseOut)
def get_video_note_raw_response(note_id: int, db: Session = Depends(get_db)):
    note = QueryService(db).get_note_raw_response(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="video note not found")
    return note


@router.get("/summary-documents", response_model=list[SummaryDocumentOut])
def list_summary_documents(
    limit: int = 100,
    summary_task_config_id: int | None = None,
    manual_summary: bool = False,
    category: str | None = None,
    db: Session = Depends(get_db),
):
    return QueryService(db).list_summary_documents(
        limit=limit,
        summary_task_config_id=summary_task_config_id,
        manual_summary=manual_summary,
        category=category,
    )


@router.get("/summary-documents/page", response_model=SummaryDocumentPageOut)
def list_summary_documents_page(
    limit: int = 20,
    page: int = 1,
    page_size: int | None = None,
    summary_task_config_id: int | None = None,
    manual_summary: bool = False,
    category: str | None = None,
    db: Session = Depends(get_db),
):
    return QueryService(db).list_summary_documents_page(
        limit=limit,
        page=page,
        page_size=page_size,
        summary_task_config_id=summary_task_config_id,
        manual_summary=manual_summary,
        category=category,
    )


@router.get("/summary-documents/{document_id}", response_model=SummaryDocumentOut)
def get_summary_document(document_id: int, db: Session = Depends(get_db)):
    document = QueryService(db).get_summary_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="summary document not found")
    return document


@router.delete("/summary-documents/{document_id}")
def delete_summary_document(document_id: int, db: Session = Depends(get_db)):
    deleted = SummaryDocumentService(db).delete_summary_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="summary document not found")
    return {"deleted": True}


@router.post("/actions/scan-videos", response_model=ActionResult)
def scan_videos(
    source_id: int | None = None,
    limit: int = 20,
    payload: ScanVideosRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    source_ids = payload.source_ids if payload else None
    scan_limit = payload.limit if payload else limit
    target = ",".join(str(item) for item in source_ids) if source_ids else str(source_id) if source_id is not None else "all"
    logger.debug("manual video scan requested target=%s limit=%s", target, scan_limit)
    task_log = start_task(db, "手动扫描信息流视频", "scan_information_videos", datetime.now(), target)
    service = SourceService(db)
    try:
        count = service.scan_sources(source_id=source_id, source_ids=source_ids, limit=scan_limit)
    except Exception as exc:
        logger.error("manual video scan failed target=%s limit=%s error=%r", target, scan_limit, exc)
        logger.debug("manual video scan failed traceback target=%s limit=%s", target, scan_limit, exc_info=True)
        log_fetch_error(db, "internal", "video_scan", target, repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    message = f"created={count};target={target}"
    status = "success"
    if service.last_scan_errors:
        status = "partial" if count > 0 else "failed"
        message = f"{message};errors={';'.join(service.last_scan_errors)}"
    logger.info("manual video scan finished target=%s limit=%s created=%s status=%s", target, scan_limit, count, status)
    finish_task(db, task_log, status, message)
    return ActionResult(status=status, message=message, count=count)


@router.post("/actions/generate-video-notes", response_model=ActionResult)
def generate_video_notes(
    limit: int = 5,
    payload: GenerateVideoNotesRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    video_ids = payload.video_ids if payload else None
    note_limit = payload.limit if payload else limit
    target = ",".join(str(item) for item in video_ids) if video_ids else f"limit={note_limit}"
    task_log = start_task(
        db,
        "手动提交信息源笔记任务",
        "submit_information_video_note_task",
        datetime.now(),
        target,
        target_type="video",
        target_id=target,
    )
    try:
        result = NoteService(db).submit_pending_note_task(limit=note_limit, video_ids=video_ids)
    except ValueError as exc:
        log_fetch_error(db, "bilinote", "video_note", "settings", str(exc))
        finish_task(db, task_log, "failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log_fetch_error(db, "bilinote", "video_note", target, repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    status = _video_note_task_status(result)
    message = _video_note_task_message(result, target)
    if status != "failed" and result["failed"] == 0 and result["started"] > 0:
        status = "success"
    finish_task(db, task_log, status, message, external_task_id=result.get("external_task_id"))
    return ActionResult(status=status, message=message, count=result["started"])


@router.post("/actions/mark-video-notes-failed", response_model=ActionResult)
def mark_video_notes_failed(
    payload: MarkVideoNotesFailedRequest,
    db: Session = Depends(get_db),
):
    target = ",".join(str(item) for item in payload.video_ids)
    task_log = start_task(
        db,
        "手动标记信息源笔记失败",
        "mark_information_video_notes_failed",
        datetime.now(),
        target,
    )
    try:
        count = NoteService(db).mark_video_notes_failed(
            payload.video_ids,
            payload.error_message,
        )
    except Exception as exc:
        log_fetch_error(db, "internal", "video_note", target, repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    message = f"failed={count};target={target}"
    status = "success" if count > 0 else "skipped"
    finish_task(db, task_log, status, message)
    return ActionResult(status=status, message=message, count=count)


@router.post("/videos/{video_id}/retry-note", response_model=ActionResult)
def retry_video_note(video_id: int, db: Session = Depends(get_db)):
    task_log = start_task(
        db,
        "手动重试信息源笔记",
        "retry_information_video_note",
        datetime.now(),
        str(video_id),
        target_type="video",
        target_id=str(video_id),
    )
    try:
        retried = NoteService(db).retry_video_note(video_id)
    except ValueError as exc:
        finish_task(db, task_log, "failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log_fetch_error(db, "internal", "video_note", str(video_id), repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    if not retried:
        finish_task(db, task_log, "failed", "information record not found")
        raise HTTPException(status_code=404, detail="information record not found")
    message = f"video_id={video_id};status=note_pending"
    finish_task(db, task_log, "success", message)
    return ActionResult(status="success", message=message, count=1)


@router.post("/video-notes/{note_id}/repoll", response_model=ActionResult)
def repoll_video_note(note_id: int, db: Session = Depends(get_db)):
    task_log = start_task(
        db,
        "手动重新轮询信息源笔记",
        "repoll_information_video_note",
        datetime.now(),
        str(note_id),
        target_type="note",
        target_id=str(note_id),
    )
    try:
        repolled = NoteService(db).repoll_video_note(note_id)
    except ValueError as exc:
        finish_task(db, task_log, "failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log_fetch_error(db, "internal", "video_note", str(note_id), repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    if not repolled:
        finish_task(db, task_log, "failed", "video note not found")
        raise HTTPException(status_code=404, detail="video note not found")
    message = f"note_id={note_id};status=running"
    finish_task(db, task_log, "success", message)
    return ActionResult(status="success", message=message, count=1)


@router.post("/video-notes/{note_id}/regenerate", response_model=ActionResult)
def regenerate_video_note(note_id: int, db: Session = Depends(get_db)):
    task_log = start_task(
        db,
        "手动重新生成信息源笔记",
        "regenerate_information_video_note",
        datetime.now(),
        str(note_id),
        target_type="note",
        target_id=str(note_id),
    )
    try:
        regenerated = NoteService(db).regenerate_video_note(note_id)
    except ValueError as exc:
        finish_task(db, task_log, "failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log_fetch_error(db, "internal", "video_note", str(note_id), repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    if not regenerated:
        finish_task(db, task_log, "failed", "video note not found")
        raise HTTPException(status_code=404, detail="video note not found")
    message = f"note_id={note_id};status=pending"
    finish_task(db, task_log, "success", message)
    return ActionResult(status="success", message=message, count=1)


@router.post("/actions/generate-summary-from-notes", response_model=SummaryDocumentOut)
def generate_summary_from_notes(
    payload: GenerateSummaryFromNotesRequest,
    db: Session = Depends(get_db),
):
    target = ",".join(str(item) for item in payload.note_ids)
    task_log = start_task(
        db,
        "手动生成自定义视频笔记汇总",
        "generate_information_custom_summary",
        datetime.now(),
        target,
        target_type="note",
        target_id=target,
    )
    try:
        document = SummaryDocumentService(db).create_custom_summary(
            payload.note_ids,
            title=payload.title,
            summary_instruction=payload.summary_instruction,
        )
    except ValueError as exc:
        finish_task(db, task_log, "failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log_fetch_error(db, "hermes", "summary_document", target, repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    status = "success" if document.status in {"done", "running"} else "failed"
    finish_task(db, task_log, status, f"document_id={document.id};status={document.status}")
    return document


@router.post("/summary-documents/{document_id}/retry", response_model=SummaryDocumentOut)
def retry_summary_document(document_id: int, db: Session = Depends(get_db)):
    task_log = start_task(
        db,
        "手动重试信息流汇总文档",
        "retry_information_summary_document",
        datetime.now(),
        str(document_id),
        target_type="summary_document",
        target_id=str(document_id),
    )
    try:
        document = SummaryDocumentService(db).retry_summary_document(document_id)
    except ValueError as exc:
        finish_task(db, task_log, "failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log_fetch_error(db, "hermes", "summary_document", str(document_id), repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    if document is None:
        finish_task(db, task_log, "failed", "summary document not found")
        raise HTTPException(status_code=404, detail="summary document not found")
    status = "success" if document.status in {"done", "running"} else "failed"
    finish_task(db, task_log, status, f"document_id={document.id};status={document.status}")
    return document
