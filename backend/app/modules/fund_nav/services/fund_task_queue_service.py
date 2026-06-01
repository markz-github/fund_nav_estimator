from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import logging
from threading import Event, Lock, Thread
from time import perf_counter

from contextlib import contextmanager
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_task_queue import FundTaskQueue
from app.modules.fund_nav.schemas.task import FundTaskSubmitOut
from app.modules.fund_nav.services.estimate_service import EstimateService
from app.modules.fund_nav.services.fund_index_mapping_service import FundIndexMappingService
from app.modules.fund_nav.services.fund_profile_service import FundProfileService
from app.modules.fund_nav.services.fund_service import FundService
from app.modules.fund_nav.services.holding_service import HoldingService
from app.modules.fund_nav.services.market_service import MarketService
from app.modules.information.models.task_log import TaskLog
from app.modules.information.services.operation_log_service import log_fetch_error


logger = logging.getLogger("app.performance")
WORKER_COUNT = 2
POLL_INTERVAL_SECONDS = 2
INTERRUPTED_MESSAGE = "Fund task worker interrupted before completion"


def normalize_fund_codes(fund_codes: list[str] | None) -> list[str] | None:
    if not fund_codes:
        return None
    return sorted({str(code).strip().zfill(6) for code in fund_codes if str(code).strip()})


class FundTaskQueueService:
    _submit_lock = Lock()

    def __init__(self, db: Session) -> None:
        self.db = db

    def submit(
        self,
        task_type: str,
        task_name: str,
        *,
        origin: str,
        fund_codes: list[str] | None = None,
        payload: dict | None = None,
    ) -> FundTaskSubmitOut:
        normalized_codes = normalize_fund_codes(fund_codes)
        normalized_payload = dict(payload or {})
        if normalized_codes:
            normalized_payload["fund_codes"] = normalized_codes
        target = normalized_codes or ["all"]
        dedupe_source = json.dumps({"task_type": task_type, "target": target, **normalized_payload}, sort_keys=True)
        digest = hashlib.sha256(dedupe_source.encode("utf-8")).hexdigest()
        dedupe_key = f"{task_type}:{digest}"
        with self._dedupe_guard(digest):
            existing = self.db.scalar(
                select(FundTaskQueue)
                .where(FundTaskQueue.dedupe_key == dedupe_key, FundTaskQueue.status == "pending")
                .order_by(FundTaskQueue.id.asc())
            )
            if existing is not None:
                return self._result(existing, reused=True)

            now = datetime.now()
            target_fund_code = normalized_codes[0] if normalized_codes and len(normalized_codes) == 1 else normalized_payload.get("fund_code")
            task_log = TaskLog(
                task_name=task_name,
                task_type=task_type,
                target_type="fund" if target_fund_code else None,
                target_id=target_fund_code,
                status="pending",
                started_at=now,
                message=f"queued origin={origin};target={','.join(target)}",
            )
            self.db.add(task_log)
            self.db.flush()
            task = FundTaskQueue(
                task_log_id=task_log.id,
                task_type=task_type,
                task_name=task_name,
                origin=origin,
                payload_json=normalized_payload or None,
                dedupe_key=dedupe_key,
                status="pending",
                queued_at=now,
                message="任务已提交",
            )
            self.db.add(task)
            self.db.commit()
            self.db.refresh(task)
        logger.info("fund_queue event=submitted task_id=%s type=%s origin=%s target=%s", task.id, task_type, origin, target)
        return self._result(task, reused=False)

    @contextmanager
    def _dedupe_guard(self, digest: str):
        advisory_lock_name = f"fund_task_dedupe_{digest[:40]}"
        with self._submit_lock:
            if self.db.get_bind().dialect.name != "mysql":
                yield
                return
            with self.db.get_bind().connect() as connection:
                acquired = connection.scalar(text("SELECT GET_LOCK(:name, 5)"), {"name": advisory_lock_name})
                if acquired != 1:
                    raise TimeoutError("Timed out waiting for fund task dedupe lock")
                try:
                    yield
                finally:
                    connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": advisory_lock_name})

    def recover_interrupted(self) -> int:
        tasks = list(self.db.scalars(select(FundTaskQueue).where(FundTaskQueue.status == "running")).all())
        for task in tasks:
            self._finish(task, "failed", INTERRUPTED_MESSAGE)
        if tasks:
            logger.warning("fund_queue event=recover_interrupted count=%s", len(tasks))
        return len(tasks)

    def claim_next(self) -> FundTaskQueue | None:
        task = self.db.scalar(
            select(FundTaskQueue)
            .where(FundTaskQueue.status == "pending")
            .order_by(FundTaskQueue.queued_at.asc(), FundTaskQueue.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if task is None:
            self.db.rollback()
            return None
        now = datetime.now()
        task.status = "running"
        task.started_at = now
        task.message = "任务执行中"
        task_log = self.db.get(TaskLog, task.task_log_id)
        if task_log is not None:
            task_log.status = "running"
            task_log.message = "任务执行中"
        self.db.commit()
        self.db.refresh(task)
        wait_ms = int((now - task.queued_at).total_seconds() * 1000)
        logger.info("fund_queue event=claimed task_id=%s type=%s wait_ms=%s", task.id, task.task_type, wait_ms)
        return task

    def execute(self, task_id: int) -> None:
        task = self.db.get(FundTaskQueue, task_id)
        if task is None:
            return
        started = perf_counter()
        try:
            status, message = self._handler(task)
        except Exception as exc:
            self.db.rollback()
            log_fetch_error(self.db, "internal", task.task_type, str(task.id), repr(exc))
            status, message = "failed", repr(exc)
        task = self.db.get(FundTaskQueue, task_id)
        if task is not None:
            self._finish(task, status, message)
        logger.info(
            "fund_queue event=finished task_id=%s type=%s status=%s duration_ms=%.2f",
            task_id,
            task.task_type if task else "unknown",
            status,
            (perf_counter() - started) * 1000,
        )

    def _handler(self, task: FundTaskQueue) -> tuple[str, str]:
        payload = task.payload_json or {}
        fund_codes = payload.get("fund_codes")
        if task.task_type == "refresh_profile":
            count = FundProfileService(self.db).refresh_profiles()
            for code in self._codes(fund_codes):
                FundService(self.db).refresh_profile(code)
            return "success", f"profiles={count}"
        if task.task_type == "refresh_nav":
            success = sum(FundService(self.db).refresh_nav(code) is not None for code in self._codes(fund_codes))
            return ("success" if success else "partial"), f"funds={len(self._codes(fund_codes))};success={success}"
        if task.task_type == "refresh_holding":
            total = sum(len(HoldingService(self.db).refresh_holdings(code)) for code in self._codes(fund_codes))
            return ("success" if total else "partial"), f"holdings={total}"
        if task.task_type == "refresh_quote":
            quotes = MarketService(self.db).refresh_quotes_for_holdings(fund_codes)
            return ("success" if quotes else "partial"), f"quotes={len(quotes)}"
        if task.task_type == "estimate_nav":
            result = EstimateService(self.db).run_estimates(fund_codes)
            return ("success" if not result["skipped_count"] else "partial"), self._estimate_message(result)
        if task.task_type == "refresh_quote_estimate":
            quotes = MarketService(self.db).refresh_quotes_for_holdings(fund_codes)
            result = EstimateService(self.db).run_estimates(fund_codes)
            return ("success" if quotes and not result["skipped_count"] else "partial"), f"quotes={len(quotes)};{self._estimate_message(result)}"
        if task.task_type == "refresh_index_mapping":
            refreshed = FundIndexMappingService(self.db).refresh_mapping(payload["fund_code"])
            return ("success" if refreshed else "partial"), f"fund_code={payload['fund_code']};refreshed={refreshed is not None}"
        if task.task_type == "sync_new_fund_data":
            return self._sync_new_fund(payload["fund_code"])
        raise ValueError(f"Unsupported fund task type: {task.task_type}")

    def _sync_new_fund(self, fund_code: str) -> tuple[str, str]:
        fund_service = FundService(self.db)
        profile = fund_service.refresh_profile(fund_code)
        mapping = FundIndexMappingService(self.db).refresh_mapping(fund_code)
        nav = fund_service.refresh_nav(fund_code)
        holdings = HoldingService(self.db).refresh_holdings(fund_code)
        quotes = MarketService(self.db).refresh_quotes_for_holdings([fund_code]) if holdings else []
        estimates = EstimateService(self.db).run_estimates([fund_code])
        status = "success" if profile and nav and holdings and not estimates["skipped_count"] else "partial"
        return status, (
            f"profile={profile is not None};index_mapping={mapping is not None};nav={nav is not None};"
            f"holdings={len(holdings)};quotes={len(quotes)};{self._estimate_message(estimates)}"
        )

    def _codes(self, fund_codes: list[str] | None) -> list[str]:
        return fund_codes or list(self.db.scalars(select(Fund.fund_code).where(Fund.enabled == 1)).all())

    @staticmethod
    def _estimate_message(result: dict) -> str:
        return f"estimated={result['estimated_count']};skipped={result['skipped_count']};details={result['skipped']}"

    def _finish(self, task: FundTaskQueue, status: str, message: str) -> None:
        now = datetime.now()
        started_at = task.started_at or task.queued_at
        task.status = status
        task.finished_at = now
        task.duration_ms = int((now - started_at).total_seconds() * 1000)
        task.message = message[:2000]
        task_log = self.db.get(TaskLog, task.task_log_id)
        if task_log is not None:
            task_log.status = status
            task_log.finished_at = now
            task_log.duration_ms = task.duration_ms
            task_log.message = task.message
        self.db.commit()

    @staticmethod
    def _result(task: FundTaskQueue, *, reused: bool) -> FundTaskSubmitOut:
        return FundTaskSubmitOut(
            task_id=task.id,
            task_log_id=task.task_log_id or 0,
            status=task.status,
            reused=reused,
            message="相同任务已在等待执行" if reused else "任务已提交",
        )


class FundTaskDispatcher:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=WORKER_COUNT, thread_name_prefix="fund-task")
        self.stop_event = Event()
        self.thread = Thread(target=self._run, name="fund-task-dispatcher", daemon=True)
        self.active = 0
        self.active_lock = Lock()
        self.started = False

    def start(self) -> None:
        if self.started:
            return
        with _all_worker_slots() as can_recover:
            if can_recover:
                with SessionLocal() as db:
                    FundTaskQueueService(db).recover_interrupted()
            else:
                logger.info("fund_queue event=recover_interrupted skipped=active_workers")
        self.thread.start()
        self.started = True

    def shutdown(self) -> None:
        if not self.started:
            return
        self.stop_event.set()
        self.thread.join(timeout=5)
        self.executor.shutdown(wait=False, cancel_futures=False)

    def _run(self) -> None:
        while not self.stop_event.wait(POLL_INTERVAL_SECONDS):
            with self.active_lock:
                available = WORKER_COUNT - self.active
            for _ in range(available):
                with self.active_lock:
                    self.active += 1
                    active = self.active
                logger.info("fund_queue event=dispatch_attempt active=%s", active)
                self.executor.submit(self._execute_next)

    def _execute_next(self) -> None:
        try:
            with _worker_slot() as acquired:
                if not acquired:
                    return
                with SessionLocal() as db:
                    task = FundTaskQueueService(db).claim_next()
                if task is None:
                    return
                with SessionLocal() as db:
                    FundTaskQueueService(db).execute(task.id)
        finally:
            with self.active_lock:
                self.active -= 1


@contextmanager
def _worker_slot():
    if engine.dialect.name != "mysql":
        yield True
        return
    with engine.connect() as connection:
        slot_name = None
        for index in range(WORKER_COUNT):
            candidate = f"fund_task_worker_slot_{index}"
            acquired = connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": candidate})
            if acquired == 1:
                slot_name = candidate
                break
        try:
            yield slot_name is not None
        finally:
            if slot_name is not None:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": slot_name})


@contextmanager
def _all_worker_slots():
    if engine.dialect.name != "mysql":
        yield True
        return
    with engine.connect() as connection:
        acquired_names: list[str] = []
        try:
            for index in range(WORKER_COUNT):
                candidate = f"fund_task_worker_slot_{index}"
                acquired = connection.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": candidate})
                if acquired != 1:
                    yield False
                    return
                acquired_names.append(candidate)
            yield True
        finally:
            for lock_name in acquired_names:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})


dispatcher = FundTaskDispatcher()
