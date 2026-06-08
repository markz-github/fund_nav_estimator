from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import logging
import os
from pathlib import Path
import sys
from time import monotonic

for proxy_env_name in (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
):
    os.environ.pop(proxy_env_name, None)

import akshare as ak
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.config import get_settings
from app.logging_config import configure_logging


HISTORY_TABLE = "fund_nav_history"
PROGRESS_TABLE = "fund_nav_history_sync_progress"
TASK_TABLE = "fund_nav_history_sync_tasks"
logger = logging.getLogger("app.fund_nav.history_sync")


@dataclass(frozen=True)
class FundInfo:
    fund_code: str
    fund_name: str | None


def quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    text_value = str(value).strip().replace(",", "").rstrip("%")
    if text_value == "" or text_value == "--" or text_value.lower() == "nan":
        return None
    try:
        return Decimal(text_value)
    except (InvalidOperation, ValueError):
        return None


def ymd_to_date(value: str) -> date:
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def database_engine() -> Engine:
    return create_engine(get_settings().a_stock_database_url, pool_pre_ping=True, pool_recycle=3600)


def fund_pool_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, pool_recycle=3600)


def ensure_database_exists() -> None:
    settings = get_settings()
    server_engine = create_engine(settings.a_stock_mysql_server_url, pool_pre_ping=True)
    with server_engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS {quote_identifier(settings.a_stock_mysql_database)} "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )


def create_tables(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {quote_identifier(HISTORY_TABLE)} (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    fund_code VARCHAR(20) NOT NULL COMMENT '基金代码',
                    fund_name VARCHAR(100) NULL COMMENT '基金名称',
                    nav_date DATE NOT NULL COMMENT '净值日期',
                    unit_nav DECIMAL(12, 6) NULL COMMENT '单位净值',
                    daily_growth_rate DECIMAL(10, 6) NULL COMMENT '日涨跌幅',
                    source VARCHAR(50) NOT NULL DEFAULT 'akshare:fund_open_fund_info_em',
                    synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_fund_nav_history (fund_code, nav_date),
                    INDEX idx_fund_nav_history_date (nav_date),
                    INDEX idx_fund_nav_history_code_date (fund_code, nav_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        )
        connection.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {quote_identifier(TASK_TABLE)} (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    task_type VARCHAR(50) NOT NULL DEFAULT 'fund_nav_history_sync',
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
        connection.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {quote_identifier(PROGRESS_TABLE)} (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    task_id BIGINT NULL COMMENT '同步任务 ID',
                    fund_code VARCHAR(20) NOT NULL COMMENT '基金代码',
                    fund_name VARCHAR(100) NULL COMMENT '基金名称',
                    start_date CHAR(8) NOT NULL COMMENT '同步开始日期',
                    end_date CHAR(8) NOT NULL COMMENT '同步结束日期',
                    status VARCHAR(20) NOT NULL COMMENT 'running/done/failed',
                    rows_count INT NULL,
                    started_at DATETIME NULL,
                    finished_at DATETIME NULL,
                    duration_seconds DECIMAL(12, 3) NULL,
                    error TEXT NULL,
                    run_count INT NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_task_fund_range (task_id, fund_code, start_date, end_date),
                    INDEX idx_task_status (task_id, status),
                    INDEX idx_status (status),
                    INDEX idx_fund_status (fund_code, status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
        )


def get_fund_pool() -> list[FundInfo]:
    with fund_pool_engine().connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT fund_code, fund_name
                FROM funds
                WHERE enabled = 1 AND is_deleted = 0
                ORDER BY fund_code ASC
                """
            )
        ).mappings()
        return [FundInfo(fund_code=str(row["fund_code"]), fund_name=row["fund_name"]) for row in rows]


def fetch_history_rows(fund: FundInfo, start_date: str, end_date: str) -> list[dict[str, object]]:
    start = ymd_to_date(start_date)
    end = ymd_to_date(end_date)
    dataframe = ak.fund_open_fund_info_em(symbol=fund.fund_code, indicator="单位净值走势", period="成立来")
    rows: list[dict[str, object]] = []
    for _, row in dataframe.iterrows():
        nav_date = row.get("净值日期")
        if hasattr(nav_date, "date"):
            nav_date = nav_date.date()
        else:
            nav_date = date.fromisoformat(str(nav_date).split(" ")[0])
        if nav_date < start or nav_date > end:
            continue
        growth = decimal_or_none(row.get("日增长率"))
        rows.append(
            {
                "fund_code": fund.fund_code,
                "fund_name": fund.fund_name,
                "nav_date": nav_date,
                "unit_nav": decimal_or_none(row.get("单位净值")),
                "daily_growth_rate": growth / Decimal("100") if growth is not None else None,
                "source": "akshare:fund_open_fund_info_em",
            }
        )
    return rows


def upsert_history_rows(engine: Engine, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0
    statement = text(
        f"""
        INSERT INTO {quote_identifier(HISTORY_TABLE)} (
            fund_code, fund_name, nav_date, unit_nav, daily_growth_rate, source, synced_at
        ) VALUES (
            :fund_code, :fund_name, :nav_date, :unit_nav, :daily_growth_rate, :source, NOW()
        )
        ON DUPLICATE KEY UPDATE
            fund_name = VALUES(fund_name),
            unit_nav = VALUES(unit_nav),
            daily_growth_rate = VALUES(daily_growth_rate),
            source = VALUES(source),
            synced_at = NOW()
        """
    )
    with engine.begin() as connection:
        connection.execute(statement, rows)
    return len(rows)


def claim_progress_running(engine: Engine, fund: FundInfo, start_date: str, end_date: str, task_id: int | None) -> str:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                f"""
                SELECT status
                FROM {quote_identifier(PROGRESS_TABLE)}
                WHERE task_id <=> :task_id
                  AND fund_code = :fund_code
                  AND start_date = :start_date
                  AND end_date = :end_date
                """
            ),
            {"task_id": task_id, "fund_code": fund.fund_code, "start_date": start_date, "end_date": end_date},
        ).mappings().first()
        if row is not None and row["status"] == "done":
            return "done"
        if row is None:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {quote_identifier(PROGRESS_TABLE)} (
                        task_id, fund_code, fund_name, start_date, end_date, status, started_at, run_count
                    ) VALUES (
                        :task_id, :fund_code, :fund_name, :start_date, :end_date, 'running', NOW(), 1
                    )
                    """
                ),
                {
                    "task_id": task_id,
                    "fund_code": fund.fund_code,
                    "fund_name": fund.fund_name,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            return "claimed"
        connection.execute(
            text(
                f"""
                UPDATE {quote_identifier(PROGRESS_TABLE)}
                SET fund_name = :fund_name,
                    status = 'running',
                    started_at = NOW(),
                    finished_at = NULL,
                    duration_seconds = NULL,
                    error = NULL,
                    run_count = run_count + 1
                WHERE task_id <=> :task_id
                  AND fund_code = :fund_code
                  AND start_date = :start_date
                  AND end_date = :end_date
                """
            ),
            {
                "task_id": task_id,
                "fund_code": fund.fund_code,
                "fund_name": fund.fund_name,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return "claimed"


def mark_progress_done(engine: Engine, fund: FundInfo, start_date: str, end_date: str, rows_count: int, duration_seconds: float, task_id: int | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                UPDATE {quote_identifier(PROGRESS_TABLE)}
                SET status = 'done',
                    rows_count = :rows_count,
                    finished_at = NOW(),
                    duration_seconds = :duration_seconds,
                    error = NULL
                WHERE task_id <=> :task_id
                  AND fund_code = :fund_code
                  AND start_date = :start_date
                  AND end_date = :end_date
                """
            ),
            {
                "task_id": task_id,
                "fund_code": fund.fund_code,
                "start_date": start_date,
                "end_date": end_date,
                "rows_count": rows_count,
                "duration_seconds": duration_seconds,
            },
        )


def mark_progress_failed(engine: Engine, fund: FundInfo, start_date: str, end_date: str, error: str, duration_seconds: float, task_id: int | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                UPDATE {quote_identifier(PROGRESS_TABLE)}
                SET status = 'failed',
                    finished_at = NOW(),
                    duration_seconds = :duration_seconds,
                    error = :error
                WHERE task_id <=> :task_id
                  AND fund_code = :fund_code
                  AND start_date = :start_date
                  AND end_date = :end_date
                """
            ),
            {
                "task_id": task_id,
                "fund_code": fund.fund_code,
                "start_date": start_date,
                "end_date": end_date,
                "duration_seconds": duration_seconds,
                "error": error[:2000],
            },
        )


def sync_one(engine: Engine, fund: FundInfo, start_date: str, end_date: str, task_id: int | None) -> tuple[str, str | None]:
    started = monotonic()
    claim_status = claim_progress_running(engine, fund, start_date, end_date, task_id)
    if claim_status == "done":
        logger.info("SKIP %s %s progress=done", fund.fund_code, fund.fund_name or "")
        return fund.fund_code, None
    try:
        rows = fetch_history_rows(fund, start_date, end_date)
        rows_count = upsert_history_rows(engine, rows)
        duration_seconds = monotonic() - started
        mark_progress_done(engine, fund, start_date, end_date, rows_count, duration_seconds, task_id)
        logger.info("DONE %s %s rows=%s duration=%.2fs", fund.fund_code, fund.fund_name or "", rows_count, duration_seconds)
        return fund.fund_code, None
    except Exception as exc:
        duration_seconds = monotonic() - started
        mark_progress_failed(engine, fund, start_date, end_date, repr(exc), duration_seconds, task_id)
        logger.exception("FAILED %s duration=%.2fs error=%s", fund.fund_code, duration_seconds, exc)
        return fund.fund_code, repr(exc)


def mark_task_running(engine: Engine, task_id: int | None, total_count: int) -> None:
    if task_id is None:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                UPDATE {quote_identifier(TASK_TABLE)}
                SET status = 'running',
                    total_count = :total_count,
                    started_at = COALESCE(started_at, NOW()),
                    message = '任务执行中'
                WHERE id = :task_id
                """
            ),
            {"task_id": task_id, "total_count": total_count},
        )


def progress_counts(engine: Engine, start_date: str, end_date: str, task_id: int | None) -> dict[str, int]:
    task_filter = "AND task_id = :task_id" if task_id is not None else "AND task_id IS NULL"
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"""
                SELECT status, COUNT(*) AS count
                FROM {quote_identifier(PROGRESS_TABLE)}
                WHERE start_date = :start_date AND end_date = :end_date
                  {task_filter}
                GROUP BY status
                """
            ),
            {"start_date": start_date, "end_date": end_date, "task_id": task_id},
        ).mappings()
        return {str(row["status"]): int(row["count"]) for row in rows}


def finish_task(engine: Engine, task_id: int | None, start_date: str, end_date: str) -> None:
    if task_id is None:
        return
    counts = progress_counts(engine, start_date, end_date, task_id)
    done_count = counts.get("done", 0)
    failed_count = counts.get("failed", 0)
    running_count = counts.get("running", 0)
    total_count = sum(counts.values())
    if total_count == 0:
        status = "skipped"
    elif failed_count == 0 and running_count == 0:
        status = "success"
    elif done_count == 0 and failed_count > 0:
        status = "failed"
    else:
        status = "partial"
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                UPDATE {quote_identifier(TASK_TABLE)}
                SET status = :status,
                    total_count = :total_count,
                    success_count = :success_count,
                    failed_count = :failed_count,
                    running_count = :running_count,
                    skipped_count = 0,
                    finished_at = NOW(),
                    duration_seconds = CASE
                        WHEN started_at IS NULL THEN duration_seconds
                        ELSE TIMESTAMPDIFF(SECOND, started_at, NOW())
                    END,
                    message = :message
                WHERE id = :task_id
                """
            ),
            {
                "task_id": task_id,
                "status": status,
                "total_count": total_count,
                "success_count": done_count,
                "failed_count": failed_count,
                "running_count": running_count,
                "message": f"done={done_count};failed={failed_count};running={running_count}",
            },
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync fund NAV history into the market history database.")
    parser.add_argument("--start-date", default=f"{date.today().year - 1}{date.today():%m%d}")
    parser.add_argument("--end-date", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--fund-codes", nargs="*", help="Optional fund codes. Defaults to all enabled funds.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--task-id", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    configure_logging(
        settings.log_dir,
        settings.log_backup_days,
        settings.log_level,
        log_file_name="fund_nav_history_sync.log",
        console=False,
    )
    ensure_database_exists()
    engine = database_engine()
    create_tables(engine)
    fund_pool = get_fund_pool()
    if args.fund_codes:
        target_codes = {str(code).strip().zfill(6) for code in args.fund_codes if str(code).strip()}
        fund_pool = [fund for fund in fund_pool if fund.fund_code in target_codes]

    mark_task_running(engine, args.task_id, len(fund_pool))
    failures: list[tuple[str, str]] = []
    max_workers = max(1, args.workers)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(sync_one, engine, fund, args.start_date, args.end_date, args.task_id)
            for fund in fund_pool
        ]
        for future in as_completed(futures):
            fund_code, error = future.result()
            if error is not None:
                failures.append((fund_code, error))

    finish_task(engine, args.task_id, args.start_date, args.end_date)
    if failures:
        for fund_code, error in failures:
            logger.error("- %s: %s", fund_code, error)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
