from __future__ import annotations

from datetime import date
from datetime import datetime
import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.information.schemas.video import (
    ActionResult,
    InformationSettingsOut,
    InformationSettingsUpdate,
    GenerateSummaryFromNotesRequest,
    GenerateVideoNotesRequest,
    MarkVideoNotesFailedRequest,
    ScanVideosRequest,
    SummaryDocumentOut,
    VideoNoteDetailOut,
    VideoNoteOut,
    VideoNoteRawResponseOut,
    VideoOut,
    VideoSourceCreate,
    VideoSourceOut,
    VideoSourceUpdate,
)
from app.modules.information.services.operation_log_service import finish_task, log_fetch_error, start_task, task_status_from_counts
from app.modules.information.services.information_settings_service import InformationSettingsService
from app.modules.information.services.video_information_service import VideoInformationService

router = APIRouter(prefix="/information", tags=["information"])
logger = logging.getLogger(__name__)


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
    return VideoInformationService(db).list_sources(enabled_only=enabled_only)


@router.post("/video-sources", response_model=VideoSourceOut)
def create_video_source(payload: VideoSourceCreate, db: Session = Depends(get_db)):
    try:
        return VideoInformationService(db).create_source(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/video-sources/{source_id}", response_model=VideoSourceOut)
def update_video_source(source_id: int, payload: VideoSourceUpdate, db: Session = Depends(get_db)):
    try:
        source = VideoInformationService(db).update_source(source_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if source is None:
        raise HTTPException(status_code=404, detail="video source not found")
    return source


@router.delete("/video-sources/{source_id}")
def delete_video_source(source_id: int, db: Session = Depends(get_db)):
    deleted = VideoInformationService(db).delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="video source not found")
    return {"deleted": True}


@router.get("/settings", response_model=InformationSettingsOut)
def get_information_settings(db: Session = Depends(get_db)):
    return InformationSettingsService(db).get_settings()


@router.put("/settings", response_model=InformationSettingsOut)
def update_information_settings(payload: InformationSettingsUpdate, db: Session = Depends(get_db)):
    return InformationSettingsService(db).update_settings(payload.model_dump())


# 临时排查记录：曾短暂启用 GET /debug/bilibili-dynamic-fields，
# 用于验证 B 站图文投稿发布时间字段来自 modules.module_author.pub_ts。
# 调试实现已从可执行代码中移除，避免长期保留未使用入口和 Cookie 相关请求逻辑。


@router.get("/videos", response_model=list[VideoOut])
def list_videos(
    limit: int = 100,
    video_id: int | None = None,
    source_id: int | None = None,
    status: str | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
    db: Session = Depends(get_db),
):
    return VideoInformationService(db).list_videos(
        limit=limit,
        video_id=video_id,
        source_id=source_id,
        status=status,
        published_from=published_from,
        published_to=published_to,
    )


@router.get("/video-notes", response_model=list[VideoNoteOut])
def list_video_notes(
    limit: int = 100,
    source_id: int | None = None,
    published_from: date | None = None,
    published_to: date | None = None,
    db: Session = Depends(get_db),
):
    return VideoInformationService(db).list_notes(
        limit=limit,
        source_id=source_id,
        published_from=published_from,
        published_to=published_to,
    )


@router.get("/video-notes/{note_id}", response_model=VideoNoteDetailOut)
def get_video_note(note_id: int, db: Session = Depends(get_db)):
    note = VideoInformationService(db).get_note_detail(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="video note not found")
    return note


@router.get("/video-notes/{note_id}/raw", response_model=VideoNoteRawResponseOut)
def get_video_note_raw_response(note_id: int, db: Session = Depends(get_db)):
    note = VideoInformationService(db).get_note_raw_response(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="video note not found")
    return note


@router.get("/summary-documents", response_model=list[SummaryDocumentOut])
def list_summary_documents(limit: int = 100, db: Session = Depends(get_db)):
    return VideoInformationService(db).list_summary_documents(limit=limit)


@router.get("/summary-documents/{document_id}", response_model=SummaryDocumentOut)
def get_summary_document(document_id: int, db: Session = Depends(get_db)):
    document = VideoInformationService(db).get_summary_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="summary document not found")
    return document


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
    service = VideoInformationService(db)
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
        result = VideoInformationService(db).submit_pending_note_task(limit=note_limit, video_ids=video_ids)
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
        "generate_information_video_notes",
        datetime.now(),
        target,
    )
    try:
        count = VideoInformationService(db).mark_video_notes_failed(
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


@router.post("/actions/generate-summary", response_model=SummaryDocumentOut | None)
def generate_summary(
    platform: str = "bilibili",
    summary_date: date | None = None,
    db: Session = Depends(get_db),
):
    target_date = summary_date or date.today()
    task_log = start_task(
        db,
        "手动生成信息流每日汇总",
        "generate_information_summary_documents",
        datetime.now(),
        f"{platform}:{target_date}",
    )
    try:
        document = VideoInformationService(db).create_daily_summary(platform=platform, summary_date=summary_date)
    except Exception as exc:
        log_fetch_error(db, "hermes", "summary_document", f"{platform}:{target_date}", repr(exc))
        finish_task(db, task_log, "failed", repr(exc))
        raise
    if document is None:
        finish_task(db, task_log, "skipped", "no completed notes to summarize")
        return None
    status = "success" if document.status in {"done", "running"} else "failed"
    finish_task(db, task_log, status, f"document_id={document.id};status={document.status}")
    return document


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
        document = VideoInformationService(db).create_custom_summary(payload.note_ids, title=payload.title)
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
        document = VideoInformationService(db).retry_summary_document(document_id)
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
