from __future__ import annotations

from datetime import date, timedelta
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.logging_config import resolve_log_dir
from app.modules.a_stock.schemas import AStockHistorySyncRequest


BACKEND_DIR = Path(__file__).resolve().parents[3]
PROJECT_ROOT = BACKEND_DIR.parent
SCRIPT_PATH = BACKEND_DIR / "scripts" / "sync_a_stock_daily_bars.py"
PID_FILE = PROJECT_ROOT / ".runtime" / "a_stock_history_sync.json"
PROGRESS_TABLE = "stock_daily_bars_sync_progress"
TASK_TABLE = "a_stock_history_sync_tasks"
TERMINAL_TASK_STATUSES = {"success", "partial", "failed", "skipped", "stopped"}
DAILY_BARS_TABLE = "stock_daily_bars_none"
logger = logging.getLogger(__name__)


def ymd(value: date) -> str:
    return value.strftime("%Y%m%d")


def date_range_from_request(payload: AStockHistorySyncRequest) -> tuple[str, str]:
    today = date.today()
    if payload.mode == "recent_days":
        days = payload.recent_days or 1
        return ymd(today - timedelta(days=days - 1)), ymd(today)
    return ymd(payload.start_date or today), ymd(payload.end_date or today)


def previous_weekday(today: date) -> date:
    candidate = today - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


class AStockHistorySyncService:
    _start_lock = Lock()

    def __init__(self) -> None:
        self.settings = get_settings()

    def engine(self) -> Engine:
        return create_engine(self.settings.a_stock_database_url, pool_pre_ping=True)

    def previous_trading_day(self, today: date | None = None) -> date:
        today = today or date.today()
        try:
            import akshare as ak

            calendar = ak.tool_trade_date_hist_sina()
            if "trade_date" not in calendar.columns:
                return previous_weekday(today)
            trade_dates = [
                value.date() if hasattr(value, "date") else date.fromisoformat(str(value)[:10])
                for value in calendar["trade_date"].dropna().tolist()
            ]
            previous_dates = [trade_date for trade_date in trade_dates if trade_date < today]
            return max(previous_dates) if previous_dates else previous_weekday(today)
        except Exception:
            logger.exception("previous_trading_day calendar_failed")
            return previous_weekday(today)

    def has_daily_bars_for_date(self, trade_date: date) -> bool:
        try:
            with self.engine().connect() as connection:
                exists = connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = DATABASE()
                          AND table_name = :table_name
                        """
                    ),
                    {"table_name": DAILY_BARS_TABLE},
                ).scalar()
                if not exists:
                    return False
                count = connection.execute(
                    text(f"SELECT COUNT(*) FROM {DAILY_BARS_TABLE} WHERE trade_date = :trade_date"),
                    {"trade_date": trade_date},
                ).scalar()
                return int(count or 0) > 0
        except Exception:
            logger.exception("has_daily_bars_for_date failed trade_date=%s", trade_date)
            return False

    def sync_previous_trading_day_if_missing(self, today: date | None = None) -> dict[str, object]:
        trade_date = self.previous_trading_day(today)
        date_text = ymd(trade_date)
        if self.has_daily_bars_for_date(trade_date):
            return {
                "started": False,
                "trade_date": date_text,
                "message": f"前一交易日 {date_text} 的 A 股数据已存在。",
            }
        result = self.start(
            AStockHistorySyncRequest(
                mode="date_range",
                start_date=trade_date,
                end_date=trade_date,
                workers=self.settings.scheduler_a_stock_history_workers,
            )
        )
        return {**result, "trade_date": date_text}

    def start(self, payload: AStockHistorySyncRequest) -> dict[str, object]:
        with self._start_lock:
            existing = self.current_process()
            start_date, end_date = date_range_from_request(payload)
            if existing["running"]:
                return {
                    "task_id": existing.get("task_id"),
                    "pid": existing["pid"],
                    "started": False,
                    "start_date": existing.get("start_date") or start_date,
                    "end_date": existing.get("end_date") or end_date,
                    "workers": existing.get("workers") or payload.workers,
                    "stdout_log": existing.get("stdout_log") or "",
                    "stderr_log": existing.get("stderr_log") or "",
                    "message": "A 股历史行情同步任务已在运行。",
                }

            task_id = self._create_task(start_date, end_date, payload.workers)
            return self._start_task_process(
                task_id=task_id,
                start_date=start_date,
                end_date=end_date,
                workers=payload.workers,
                message="A 股历史行情同步任务已启动。",
            )

    def rerun_task(self, task_id: int) -> dict[str, object]:
        with self._start_lock:
            existing = self.current_process()
            task = self.get_task(task_id)
            if task is None:
                raise ValueError("任务不存在")
            if existing["running"]:
                return {
                    "task_id": existing.get("task_id"),
                    "pid": existing["pid"],
                    "started": False,
                    "start_date": existing.get("start_date") or task["start_date"],
                    "end_date": existing.get("end_date") or task["end_date"],
                    "workers": existing.get("workers") or task["workers"],
                    "stdout_log": existing.get("stdout_log") or "",
                    "stderr_log": existing.get("stderr_log") or "",
                    "message": "A 股历史行情同步任务已在运行。",
                }
            return self._restart_task(task)

    def rerun_failed(self, task_id: int) -> dict[str, object]:
        return self.rerun_task(task_id)

    def stop(self) -> dict[str, object]:
        with self._start_lock:
            process = self.current_process()
            if not process["running"] or process.get("pid") is None:
                return {"stopped": False, "message": "当前没有正在运行的 A 股历史行情同步任务。"}
            pid = int(process["pid"])
            task_id = process.get("task_id") if isinstance(process.get("task_id"), int) else None
            self._terminate_pid(pid)
            self._clear_pid_file({"task_id": task_id, "pid": pid})
            if task_id is not None:
                self._mark_task_stopped(task_id)
            return {"stopped": True, "task_id": task_id, "pid": pid, "message": "A 股历史行情同步任务已停止。"}

    def status(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, object]:
        process = self.current_process()
        effective_start = start_date or process.get("start_date") or ymd(date.today() - timedelta(days=9))
        effective_end = end_date or process.get("end_date") or ymd(date.today())
        progress = self.progress(str(effective_start), str(effective_end))
        return {
            **process,
            "start_date": str(effective_start),
            "end_date": str(effective_end),
            **progress,
        }

    def current_process(self) -> dict[str, object]:
        record: dict[str, object] = {}
        if PID_FILE.exists():
            try:
                record = json.loads(PID_FILE.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                record = {}
        pid = record.get("pid")
        task_id = record.get("task_id") if isinstance(record.get("task_id"), int) else None
        running = isinstance(pid, int) and self._is_pid_running(pid)
        if running and task_id is not None:
            task_status = self._task_status(task_id)
            if task_status in TERMINAL_TASK_STATUSES:
                running = False
                self._clear_pid_file(record)
        return {
            "running": running,
            "task_id": task_id,
            "pid": pid if isinstance(pid, int) else None,
            "workers": record.get("workers"),
            "stdout_log": record.get("stdout_log"),
            "stderr_log": record.get("stderr_log"),
            "start_date": record.get("start_date"),
            "end_date": record.get("end_date"),
        }

    def list_tasks(self, limit: int = 20) -> list[dict[str, object]]:
        try:
            self._ensure_task_table()
            with self.engine().connect() as connection:
                rows = connection.execute(
                    text(
                        f"""
                        SELECT id, task_type, status, start_date, end_date, workers,
                               total_count, success_count, failed_count, running_count,
                               skipped_count, retry_count, pid, stdout_log, stderr_log,
                               message, started_at, finished_at, duration_seconds, created_at
                        FROM {TASK_TABLE}
                        ORDER BY id DESC
                        LIMIT :limit
                        """
                    ),
                    {"limit": limit},
                ).mappings()
                return [dict(row) for row in rows]
        except Exception:
            return []

    def _task_status(self, task_id: int) -> str | None:
        try:
            with self.engine().connect() as connection:
                value = connection.execute(
                    text(f"SELECT status FROM {TASK_TABLE} WHERE id = :task_id"),
                    {"task_id": task_id},
                ).scalar()
                return str(value) if value is not None else None
        except Exception:
            return None

    def _clear_pid_file(self, expected_record: dict[str, object]) -> None:
        try:
            if not PID_FILE.exists():
                return
            current = json.loads(PID_FILE.read_text(encoding="utf-8-sig"))
            if current.get("task_id") == expected_record.get("task_id") and current.get("pid") == expected_record.get("pid"):
                PID_FILE.unlink()
        except Exception:
            return

    def task_detail(self, task_id: int) -> dict[str, object] | None:
        task = self.get_task(task_id)
        if task is None:
            return None
        progress = self.progress(str(task["start_date"]), str(task["end_date"]), task_id=task_id)
        return {**task, **progress}

    def get_task(self, task_id: int) -> dict[str, object] | None:
        self._ensure_task_table()
        with self.engine().connect() as connection:
            row = connection.execute(
                text(
                    f"""
                    SELECT id, task_type, status, start_date, end_date, workers,
                           total_count, success_count, failed_count, running_count,
                           skipped_count, retry_count, pid, stdout_log, stderr_log,
                           message, started_at, finished_at, duration_seconds, created_at
                    FROM {TASK_TABLE}
                    WHERE id = :task_id
                    """
                ),
                {"task_id": task_id},
            ).mappings().first()
            return dict(row) if row else None

    def progress(self, start_date: str, end_date: str, task_id: int | None = None) -> dict[str, object]:
        try:
            engine = self.engine()
            with engine.connect() as connection:
                exists = connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.tables
                        WHERE table_schema = DATABASE()
                          AND table_name = :table_name
                        """
                    ),
                    {"table_name": PROGRESS_TABLE},
                ).scalar()
                if not exists:
                    return self._empty_progress()
                task_filter = "AND task_id = :task_id" if task_id is not None else ""
                params = {"start_date": start_date, "end_date": end_date, "task_id": task_id}
                counts = [
                    {"status": row["status"], "count": int(row["count"])}
                    for row in connection.execute(
                        text(
                            f"""
                            SELECT status, COUNT(*) AS count
                            FROM {PROGRESS_TABLE}
                            WHERE start_date = :start_date AND end_date = :end_date
                              {task_filter}
                            GROUP BY status
                            """
                        ),
                        params,
                    ).mappings()
                ]
                return {
                    "counts": counts,
                    "latest_done": self._items(connection, start_date, end_date, "done", "updated_at DESC", 50, task_id),
                    "running_items": self._items(connection, start_date, end_date, "running", "symbol ASC", 50, task_id),
                    "failed_items": self._items(connection, start_date, end_date, "failed", "updated_at DESC", 100, task_id),
                }
        except Exception:
            return self._empty_progress()

    def _items(self, connection, start_date: str, end_date: str, status: str, order_by: str, limit: int, task_id: int | None = None):
        task_filter = "AND task_id = :task_id" if task_id is not None else ""
        rows = connection.execute(
            text(
                f"""
                SELECT symbol, stock_name, status, started_at, finished_at,
                       duration_seconds, SUBSTRING(error FROM 1 FOR 500) AS error
                FROM {PROGRESS_TABLE}
                WHERE start_date = :start_date
                  AND end_date = :end_date
                  AND status = :status
                  {task_filter}
                ORDER BY {order_by}
                LIMIT :limit
                """
            ),
            {"start_date": start_date, "end_date": end_date, "status": status, "limit": limit, "task_id": task_id},
        ).mappings()
        return [dict(row) for row in rows]

    def _restart_task(self, task: dict[str, object]) -> dict[str, object]:
        task_id = int(task["id"])
        start_date = str(task["start_date"])
        end_date = str(task["end_date"])
        workers = int(task["workers"] or 1)
        self._mark_task_restarting(task_id)
        return self._start_task_process(
            task_id=task_id,
            start_date=start_date,
            end_date=end_date,
            workers=workers,
            message="已重新启动该 A 股历史行情同步任务。",
        )

    def _start_task_process(
        self,
        *,
        task_id: int,
        start_date: str,
        end_date: str,
        workers: int,
        message: str,
    ) -> dict[str, object]:
        log_dir = resolve_log_dir(self.settings.log_dir)
        runtime_dir = PID_FILE.parent
        runtime_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = log_dir / "a_stock_daily_sync.log"
        stderr_log = log_dir / "a_stock_daily_sync.err.log"
        command = [
            sys.executable,
            "-B",
            str(SCRIPT_PATH),
            "--use-progress",
            "--insert-only",
            "--retry-conflicts",
            "--workers",
            str(workers),
            "--sleep-seconds",
            "0",
            "--start-date",
            start_date,
            "--end-date",
            end_date,
            "--task-id",
            str(task_id),
        ]
        try:
            with stderr_log.open("ab") as stderr_file:
                process = subprocess.Popen(
                    command,
                    cwd=PROJECT_ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_file,
                    stdin=subprocess.DEVNULL,
                    close_fds=os.name != "nt",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
        except Exception as exc:
            self._mark_task_failed_to_start(task_id, repr(exc))
            raise
        record = {
            "task_id": task_id,
            "pid": process.pid,
            "start_date": start_date,
            "end_date": end_date,
            "workers": workers,
            "stdout_log": self._display_path(stdout_log),
            "stderr_log": self._display_path(stderr_log),
        }
        self._mark_task_started(task_id, process.pid, record["stdout_log"], record["stderr_log"])
        PID_FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**record, "started": True, "message": message}

    def _create_task(
        self,
        start_date: str,
        end_date: str,
        workers: int,
        *,
        retry_count: int = 0,
        total_count: int = 0,
    ) -> int:
        self._ensure_task_table()
        with self.engine().begin() as connection:
            result = connection.execute(
                text(
                    f"""
                    INSERT INTO {TASK_TABLE} (
                        task_type, status, start_date, end_date, workers, total_count,
                        retry_count, message
                    ) VALUES (
                        'history_sync', 'pending', :start_date, :end_date, :workers, :total_count,
                        :retry_count, '任务已提交'
                    )
                    """
                ),
                {
                    "start_date": start_date,
                    "end_date": end_date,
                    "workers": workers,
                    "total_count": total_count,
                    "retry_count": retry_count,
                },
            )
            return int(result.lastrowid)

    def _mark_task_started(self, task_id: int, pid: int, stdout_log: str, stderr_log: str) -> None:
        with self.engine().begin() as connection:
            connection.execute(
                text(
                    f"""
                    UPDATE {TASK_TABLE}
                    SET pid = :pid,
                        stdout_log = :stdout_log,
                        stderr_log = :stderr_log,
                        message = '任务进程已启动'
                    WHERE id = :task_id
                    """
                ),
                {"task_id": task_id, "pid": pid, "stdout_log": stdout_log, "stderr_log": stderr_log},
            )

    def _mark_task_restarting(self, task_id: int) -> None:
        with self.engine().begin() as connection:
            connection.execute(
                text(
                    f"""
                    UPDATE {TASK_TABLE}
                    SET status = 'pending',
                        retry_count = retry_count + 1,
                        finished_at = NULL,
                        duration_seconds = NULL,
                        message = '任务重新提交'
                    WHERE id = :task_id
                    """
                ),
                {"task_id": task_id},
            )

    def _mark_task_failed_to_start(self, task_id: int, message: str) -> None:
        with self.engine().begin() as connection:
            connection.execute(
                text(
                    f"""
                    UPDATE {TASK_TABLE}
                    SET status = 'failed',
                        finished_at = NOW(),
                        message = :message
                    WHERE id = :task_id
                    """
                ),
                {"task_id": task_id, "message": message[:2000]},
            )

    def _mark_task_stopped(self, task_id: int) -> None:
        task = self.get_task(task_id)
        start_date = str(task["start_date"]) if task else ""
        end_date = str(task["end_date"]) if task else ""
        with self.engine().begin() as connection:
            if start_date and end_date:
                connection.execute(
                    text(
                        f"""
                        UPDATE {PROGRESS_TABLE}
                        SET status = 'failed',
                            finished_at = NOW(),
                            error = '任务已手动停止'
                        WHERE task_id = :task_id
                          AND start_date = :start_date
                          AND end_date = :end_date
                          AND status = 'running'
                        """
                    ),
                    {"task_id": task_id, "start_date": start_date, "end_date": end_date},
                )
            connection.execute(
                text(
                    f"""
                    UPDATE {TASK_TABLE}
                    SET status = 'stopped',
                        running_count = 0,
                        finished_at = NOW(),
                        duration_seconds = CASE
                            WHEN started_at IS NULL THEN duration_seconds
                            ELSE TIMESTAMPDIFF(SECOND, started_at, NOW())
                        END,
                        message = '任务已手动停止'
                    WHERE id = :task_id
                    """
                ),
                {"task_id": task_id},
            )

    def _ensure_task_table(self) -> None:
        with self.engine().begin() as connection:
            connection.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {TASK_TABLE} (
                        id BIGINT PRIMARY KEY AUTO_INCREMENT,
                        task_type VARCHAR(50) NOT NULL DEFAULT 'history_sync',
                        status VARCHAR(20) NOT NULL DEFAULT 'pending',
                        start_date CHAR(8) NOT NULL,
                        end_date CHAR(8) NOT NULL,
                        workers INT NOT NULL DEFAULT 1,
                        total_count INT NOT NULL DEFAULT 0,
                        success_count INT NOT NULL DEFAULT 0,
                        failed_count INT NOT NULL DEFAULT 0,
                        running_count INT NOT NULL DEFAULT 0,
                        skipped_count INT NOT NULL DEFAULT 0,
                        retry_count INT NOT NULL DEFAULT 0,
                        pid INT NULL,
                        stdout_log VARCHAR(500) NULL,
                        stderr_log VARCHAR(500) NULL,
                        message TEXT NULL,
                        started_at DATETIME NULL,
                        finished_at DATETIME NULL,
                        duration_seconds DECIMAL(12, 3) NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_status_time (status, created_at),
                        INDEX idx_range_time (start_date, end_date, created_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                    """
                )
            )
            progress_exists = connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name = :table_name
                    """
                ),
                {"table_name": PROGRESS_TABLE},
            ).scalar()
            if progress_exists:
                task_column_exists = connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.columns
                        WHERE table_schema = DATABASE()
                          AND table_name = :table_name
                          AND column_name = 'task_id'
                        """
                    ),
                    {"table_name": PROGRESS_TABLE},
                ).scalar()
                if not task_column_exists:
                    connection.execute(text(f"ALTER TABLE {PROGRESS_TABLE} ADD COLUMN task_id BIGINT NULL AFTER id"))
                task_index_exists = connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.statistics
                        WHERE table_schema = DATABASE()
                          AND table_name = :table_name
                          AND index_name = 'idx_task_status'
                        """
                    ),
                    {"table_name": PROGRESS_TABLE},
                ).scalar()
                if not task_index_exists:
                    connection.execute(text(f"ALTER TABLE {PROGRESS_TABLE} ADD INDEX idx_task_status (task_id, status)"))
                old_unique_exists = connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.statistics
                        WHERE table_schema = DATABASE()
                          AND table_name = :table_name
                          AND index_name = 'uk_symbol_range'
                        """
                    ),
                    {"table_name": PROGRESS_TABLE},
                ).scalar()
                if old_unique_exists:
                    connection.execute(text(f"ALTER TABLE {PROGRESS_TABLE} DROP INDEX uk_symbol_range"))
                task_unique_exists = connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.statistics
                        WHERE table_schema = DATABASE()
                          AND table_name = :table_name
                          AND index_name = 'uk_task_symbol_range'
                        """
                    ),
                    {"table_name": PROGRESS_TABLE},
                ).scalar()
                if not task_unique_exists:
                    connection.execute(
                        text(
                            f"ALTER TABLE {PROGRESS_TABLE} "
                            "ADD UNIQUE KEY uk_task_symbol_range (task_id, symbol, start_date, end_date)"
                        )
                    )

    @staticmethod
    def _empty_progress() -> dict[str, list[object]]:
        return {"counts": [], "latest_done": [], "running_items": [], "failed_items": []}

    @staticmethod
    def _display_path(path: Path) -> str:
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path)

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            return str(pid) in result.stdout
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def _terminate_pid(pid: int) -> None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, check=False)
            return
        try:
            os.kill(pid, 15)
        except OSError:
            return
