from __future__ import annotations

from datetime import datetime, timedelta
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.services.estimate_service import EstimateService
from app.modules.fund_nav.services.fund_profile_service import FundProfileService
from app.modules.fund_nav.services.fund_service import FundService
from app.modules.fund_nav.services.holding_service import HoldingService
from app.modules.fund_nav.services.market_service import MarketService
from app.modules.information.services.operation_log_service import log_fetch_error, log_task, task_status_from_counts
from app.modules.information.services.video_information_service import VideoInformationService


def _video_note_task_status(result: dict[str, int]) -> str:
    return task_status_from_counts(
        success=result["completed"],
        failed=result["failed"],
        skipped=1 if result["total"] == 0 else 0,
    )


def _video_note_task_message(result: dict[str, int | str | None]) -> str:
    message = (
        f"total={result['total']};completed={result['completed']};"
        f"failed={result['failed']};running={result['running']};"
        f"started={result['started']};expired={result['expired']}"
    )
    error_message = result.get("error_message")
    if error_message:
        message = f"{message};error={error_message}"
    return message


def _summary_document_poll_status(result: dict[str, int]) -> str:
    if result["running"] > 0:
        return "success"
    return task_status_from_counts(
        success=result["completed"],
        failed=result["failed"],
        skipped=1 if result["total"] == 0 else 0,
    )


def _summary_document_poll_message(result: dict[str, int]) -> str:
    return (
        f"total={result['total']};completed={result['completed']};"
        f"failed={result['failed']};running={result['running']};expired={result['expired']}"
    )


def _run_task(task_name: str, task_type: str, handler, persist_skipped: bool = True) -> None:
    started_at = datetime.now()
    db = SessionLocal()
    try:
        status, message = handler(db)
        if status == "skipped" and not persist_skipped:
            return
        log_task(db, task_name, task_type, status, started_at, message)
    except Exception as exc:
        db.rollback()
        log_task(db, task_name, task_type, "failed", started_at, repr(exc))
    finally:
        db.close()


def refresh_fund_navs_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        service = FundService(db)
        funds = db.scalars(select(Fund).where(Fund.enabled == 1)).all()
        success = 0
        failed = 0
        for fund in funds:
            try:
                nav = service.refresh_nav(fund.fund_code)
                success += 1 if nav is not None else 0
                if nav is None:
                    failed += 1
                    log_fetch_error(
                        db,
                        "akshare",
                        "fund_nav",
                        fund.fund_code,
                        "akshare returned no latest fund nav",
                    )
            except Exception as exc:
                db.rollback()
                failed += 1
                log_fetch_error(db, "akshare", "fund_nav", fund.fund_code, repr(exc))
        status = task_status_from_counts(success=success, failed=failed)
        return status, f"success={success};failed={failed}"

    _run_task("刷新基金官方净值", "refresh_nav", handler)


def refresh_fund_profiles_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        profile_count = FundProfileService(db).refresh_profiles()
        service = FundService(db)
        funds = db.scalars(select(Fund).where(Fund.enabled == 1)).all()
        success = 0
        failed = 0
        for fund in funds:
            try:
                refreshed = service.refresh_profile(fund.fund_code)
                success += 1 if refreshed is not None else 0
                if refreshed is None:
                    failed += 1
                    log_fetch_error(
                        db,
                        "akshare",
                        "fund_profile",
                        fund.fund_code,
                        "fund not found in local fund pool",
                    )
            except Exception as exc:
                db.rollback()
                failed += 1
                log_fetch_error(db, "akshare", "fund_profile", fund.fund_code, repr(exc))
        status = task_status_from_counts(success=success, failed=failed)
        return status, f"profiles={profile_count};success={success};failed={failed}"

    _run_task("刷新基金名称和类型", "refresh_profile", handler)


def refresh_fund_holdings_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        service = HoldingService(db)
        funds = db.scalars(select(Fund).where(Fund.enabled == 1)).all()
        success = 0
        failed = 0
        total_holdings = 0
        for fund in funds:
            try:
                holdings = service.refresh_holdings(fund.fund_code)
                total_holdings += len(holdings)
                success += 1 if holdings else 0
                if not holdings:
                    failed += 1
                    log_fetch_error(
                        db,
                        "akshare",
                        "holding",
                        fund.fund_code,
                        "akshare returned no fund holdings",
                    )
            except Exception as exc:
                db.rollback()
                failed += 1
                log_fetch_error(db, "akshare", "holding", fund.fund_code, repr(exc))
        status = task_status_from_counts(success=success, failed=failed)
        return status, f"success={success};failed={failed};holdings={total_holdings}"

    _run_task("刷新基金持仓", "refresh_holding", handler)


def refresh_market_quotes_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        quotes = MarketService(db).refresh_quotes_for_holdings()
        status = task_status_from_counts(success=len(quotes), skipped=0 if quotes else 1)
        if not quotes:
            log_fetch_error(
                db,
                "akshare",
                "quote",
                "holdings",
                "no market quotes refreshed for current holdings",
            )
        return status, f"quotes={len(quotes)}"

    _run_task("刷新持仓资产行情", "refresh_quote", handler)


def estimate_fund_navs_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        result = EstimateService(db).run_estimates()
        skipped_count = result["skipped_count"]
        for skipped in result["skipped"]:
            log_fetch_error(
                db,
                "internal",
                "estimate_nav",
                skipped["fund_code"],
                skipped["reason"],
            )
        status = task_status_from_counts(success=result["estimated_count"], skipped=skipped_count)
        return (
            status,
            f"estimated={result['estimated_count']};skipped={skipped_count};details={result['skipped']}",
        )

    _run_task("估算基金当日净值", "estimate_nav", handler)


def scan_information_videos_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        result = VideoInformationService(db).scan_next_source()
        if result["source_id"] is None:
            return "skipped", "no enabled video source"
        if result.get("error_message"):
            return "failed", str(result["error_message"])
        if result["created"] == 0:
            return "skipped", f"source_id={result['source_id']};created=0"
        return "success", f"source_id={result['source_id']};created={result['created']}"

    _run_task("扫描信息流视频", "scan_information_videos", handler, persist_skipped=False)


def generate_information_video_notes_job() -> None:
    db = SessionLocal()
    try:
        service = VideoInformationService(db)
        poll_started_at = datetime.now()
        poll_result = service.poll_running_notes()
        poll_status = "success" if poll_result["running"] > 0 else _video_note_task_status(poll_result)
        if poll_status != "skipped":
            log_task(
                db,
                "轮询信息源笔记任务",
                "poll_information_video_notes",
                poll_status,
                poll_started_at,
                _video_note_task_message(poll_result),
            )
        if poll_result["running"] > 0:
            return

        submit_started_at = datetime.now()
        try:
            submit_result = service.submit_pending_note_task()
            status = _video_note_task_status(submit_result)
            if submit_result["started"] > 0 or submit_result["running"] > 0:
                status = "success"
            message = _video_note_task_message(submit_result)
            if status != "skipped":
                log_task(
                    db,
                    "提交信息源笔记任务",
                    "submit_information_video_note_task",
                    status,
                    submit_started_at,
                    message,
                    target_type="video" if submit_result.get("video_id") is not None else None,
                    target_id=str(submit_result["video_id"]) if submit_result.get("video_id") is not None else None,
                    external_task_id=submit_result.get("external_task_id"),
                )
        except Exception as exc:
            db.rollback()
            log_task(
                db,
                "提交信息源笔记任务",
                "submit_information_video_note_task",
                "failed",
                submit_started_at,
                repr(exc),
            )
    except Exception as exc:
        db.rollback()
        log_task(
            db,
            "轮询信息源笔记任务",
            "poll_information_video_notes",
            "failed",
            datetime.now(),
            repr(exc),
        )
    finally:
        db.close()


def generate_information_summary_documents_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        target_date = datetime.now().date() - timedelta(days=1)
        document = VideoInformationService(db).create_daily_summary(platform="bilibili", summary_date=target_date)
        if document is None:
            return "skipped", f"date={target_date};no completed notes to summarize"
        status = "success" if document.status in {"done", "running"} else "failed"
        return status, f"date={target_date};document_id={document.id};status={document.status}"

    _run_task("生成信息流每日汇总", "generate_information_summary_documents", handler, persist_skipped=False)


def poll_information_summary_documents_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        result = VideoInformationService(db).poll_running_summary_documents()
        return _summary_document_poll_status(result), _summary_document_poll_message(result)

    _run_task("轮询 Hermes 信息流汇总任务", "poll_information_summary_documents", handler, persist_skipped=False)


def push_information_summary_documents_job() -> None:
    def handler(db: Session) -> tuple[str, str]:
        target_date = datetime.now().date() - timedelta(days=1)
        result = VideoInformationService(db).push_daily_summary_to_wechat(platform="bilibili", summary_date=target_date)
        if result["pushed"] == 0:
            return "skipped", f"date={target_date};{result['message']}"
        return "success", f"date={target_date};document_id={result['document_id']};{result['message']}"

    _run_task("推送信息流每日汇总到微信", "push_information_summary_documents", handler, persist_skipped=False)


def create_scheduler() -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    if settings.scheduler_fund_enabled:
        scheduler.add_job(
            refresh_fund_navs_job,
            trigger=CronTrigger.from_crontab(settings.scheduler_refresh_nav_cron),
            id="refresh_fund_navs",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            refresh_fund_profiles_job,
            trigger=CronTrigger.from_crontab(settings.scheduler_refresh_profiles_cron),
            id="refresh_fund_profiles",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            refresh_fund_holdings_job,
            trigger=CronTrigger.from_crontab(settings.scheduler_refresh_holdings_cron),
            id="refresh_fund_holdings",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            refresh_market_quotes_job,
            trigger=CronTrigger.from_crontab(settings.scheduler_refresh_quotes_cron),
            id="refresh_market_quotes",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            estimate_fund_navs_job,
            trigger=CronTrigger.from_crontab(settings.scheduler_estimate_nav_cron),
            id="estimate_fund_navs",
            replace_existing=True,
            max_instances=1,
        )
    if settings.scheduler_information_enabled:
        scheduler.add_job(
            scan_information_videos_job,
            trigger=CronTrigger.from_crontab(settings.scheduler_scan_videos_cron),
            id="scan_information_videos",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            generate_information_video_notes_job,
            trigger=IntervalTrigger(seconds=settings.scheduler_generate_video_notes_interval_seconds),
            id="generate_information_video_notes",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            generate_information_summary_documents_job,
            trigger=CronTrigger.from_crontab(settings.scheduler_generate_summary_documents_cron),
            id="generate_information_summary_documents",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            poll_information_summary_documents_job,
            trigger=IntervalTrigger(seconds=settings.scheduler_poll_summary_documents_interval_seconds),
            id="poll_information_summary_documents",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            push_information_summary_documents_job,
            trigger=CronTrigger.from_crontab(settings.scheduler_push_summary_documents_cron),
            id="push_information_summary_documents",
            replace_existing=True,
            max_instances=1,
        )
    return scheduler
