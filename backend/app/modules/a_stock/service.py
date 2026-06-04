from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

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


def ymd(value: date) -> str:
    return value.strftime("%Y%m%d")


def date_range_from_request(payload: AStockHistorySyncRequest) -> tuple[str, str]:
    today = date.today()
    if payload.mode == "recent_days":
        days = payload.recent_days or 1
        return ymd(today - timedelta(days=days - 1)), ymd(today)
    return ymd(payload.start_date or today), ymd(payload.end_date or today)


class AStockHistorySyncService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def engine(self) -> Engine:
        return create_engine(self.settings.a_stock_database_url, pool_pre_ping=True)

    def start(self, payload: AStockHistorySyncRequest) -> dict[str, object]:
        existing = self.current_process()
        start_date, end_date = date_range_from_request(payload)
        if existing["running"]:
            return {
                "pid": existing["pid"],
                "started": False,
                "start_date": existing.get("start_date") or start_date,
                "end_date": existing.get("end_date") or end_date,
                "workers": existing.get("workers") or payload.workers,
                "stdout_log": existing.get("stdout_log") or "",
                "stderr_log": existing.get("stderr_log") or "",
                "message": "A 股历史行情同步任务已在运行。",
            }

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
            str(payload.workers),
            "--sleep-seconds",
            "0",
            "--start-date",
            start_date,
            "--end-date",
            end_date,
        ]
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

        record = {
            "pid": process.pid,
            "start_date": start_date,
            "end_date": end_date,
            "workers": payload.workers,
            "stdout_log": self._display_path(stdout_log),
            "stderr_log": self._display_path(stderr_log),
        }
        PID_FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            **record,
            "started": True,
            "message": "A 股历史行情同步任务已启动。",
        }

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
        running = isinstance(pid, int) and self._is_pid_running(pid)
        return {
            "running": running,
            "pid": pid if isinstance(pid, int) else None,
            "workers": record.get("workers"),
            "stdout_log": record.get("stdout_log"),
            "stderr_log": record.get("stderr_log"),
            "start_date": record.get("start_date"),
            "end_date": record.get("end_date"),
        }

    def progress(self, start_date: str, end_date: str) -> dict[str, object]:
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
                counts = [
                    {"status": row["status"], "count": int(row["count"])}
                    for row in connection.execute(
                        text(
                            f"""
                            SELECT status, COUNT(*) AS count
                            FROM {PROGRESS_TABLE}
                            WHERE start_date = :start_date AND end_date = :end_date
                            GROUP BY status
                            """
                        ),
                        {"start_date": start_date, "end_date": end_date},
                    ).mappings()
                ]
                return {
                    "counts": counts,
                    "latest_done": self._items(connection, start_date, end_date, "done", "updated_at DESC", 8),
                    "running_items": self._items(connection, start_date, end_date, "running", "symbol ASC", 12),
                    "failed_items": self._items(connection, start_date, end_date, "failed", "updated_at DESC", 12),
                }
        except Exception:
            return self._empty_progress()

    def _items(self, connection, start_date: str, end_date: str, status: str, order_by: str, limit: int):
        rows = connection.execute(
            text(
                f"""
                SELECT symbol, stock_name, status, started_at, finished_at,
                       duration_seconds, SUBSTRING(error FROM 1 FOR 500) AS error
                FROM {PROGRESS_TABLE}
                WHERE start_date = :start_date
                  AND end_date = :end_date
                  AND status = :status
                ORDER BY {order_by}
                LIMIT :limit
                """
            ),
            {"start_date": start_date, "end_date": end_date, "status": status, "limit": limit},
        ).mappings()
        return [dict(row) for row in rows]

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
