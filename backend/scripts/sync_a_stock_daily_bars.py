from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import logging
import os
from pathlib import Path
import re
import sys
from threading import Lock
from time import monotonic, sleep

for proxy_env_name in (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
):
    os.environ.pop(proxy_env_name, None)

import requests

_original_session_init = requests.sessions.Session.__init__


def _session_init_without_env_proxy(self, *args, **kwargs):
    _original_session_init(self, *args, **kwargs)
    self.trust_env = False


requests.sessions.Session.__init__ = _session_init_without_env_proxy

import akshare as ak
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

ORIGINAL_CWD = Path.cwd()
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app.config import get_settings
from app.logging_config import configure_logging


ADJUST_TABLES = {
    "": "stock_daily_bars_none",
    "qfq": "stock_daily_bars_qfq",
    "hfq": "stock_daily_bars_hfq",
}
PROGRESS_TABLE = "stock_daily_bars_sync_progress"
TASK_TABLE = "a_stock_history_sync_tasks"
PROGRESS_RUNNING_STALE_MINUTES = 30
_hist_source_available = True
_hist_source_lock = Lock()
_akshare_fetch_lock = Lock()
_progress_lock = Lock()
_rebuild_lock = Lock()
logger = logging.getLogger("app.a_stock.daily_sync")


@dataclass(frozen=True)
class StockInfo:
    symbol: str
    name: str | None


def quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def mysql_error_code(exc: OperationalError) -> int | None:
    return getattr(getattr(exc, "orig", None), "args", [None])[0]


def run_progress_transaction(engine: Engine, operation: str, callback):
    for attempt in range(1, 4):
        try:
            with engine.begin() as connection:
                return callback(connection)
        except OperationalError as exc:
            error_code = mysql_error_code(exc)
            if error_code not in (1205, 1213) or attempt >= 3:
                raise
            wait_seconds = 0.2 * attempt
            logger.warning(
                "progress_db_retry operation=%s mysql_error=%s attempt=%s wait_seconds=%.2f",
                operation,
                error_code,
                attempt,
                wait_seconds,
            )
            sleep(wait_seconds)
    raise RuntimeError(f"progress transaction failed: {operation}")


def decimal_or_none(value) -> Decimal | None:
    if value is None:
        return None
    text_value = str(value).strip().replace(",", "")
    if text_value == "" or text_value == "--" or text_value.lower() == "nan":
        return None
    try:
        return Decimal(text_value)
    except (InvalidOperation, ValueError):
        return None


def date_from_value(value) -> date:
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value).split(" ")[0])


def normalize_symbol(value) -> str:
    return str(value).strip().zfill(6)


def prefixed_symbol(symbol: str) -> str:
    if symbol.startswith(("6", "9")):
        return f"sh{symbol}"
    if symbol.startswith(("4", "8")):
        return f"bj{symbol}"
    return f"sz{symbol}"


def fetch_history_dataframe(symbol: str, start_date: str, end_date: str, adjust: str):
    global _hist_source_available
    with _akshare_fetch_lock:
        if _hist_source_available:
            try:
                dataframe = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                    timeout=30,
                )
                return dataframe, "akshare:stock_zh_a_hist"
            except Exception:
                with _hist_source_lock:
                    _hist_source_available = False

        try:
            dataframe = ak.stock_zh_a_daily(
                symbol=prefixed_symbol(symbol),
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
        except KeyError as exc:
            if str(exc).strip("'\"") != "date":
                raise
            logger.warning(
                "akshare_empty_response endpoint=stock_zh_a_daily symbol=%s adjust=%s missing_column=date",
                symbol,
                adjust or "none",
            )
            return pd.DataFrame(), "akshare:stock_zh_a_daily:empty"

        if not dataframe.empty and "date" not in dataframe.columns and "日期" not in dataframe.columns:
            logger.warning(
                "akshare_invalid_response endpoint=stock_zh_a_daily symbol=%s adjust=%s columns=%s",
                symbol,
                adjust or "none",
                ",".join(str(column) for column in dataframe.columns),
            )
            return pd.DataFrame(), "akshare:stock_zh_a_daily:invalid"
        return dataframe, "akshare:stock_zh_a_daily"


def ensure_database_exists(database: str) -> None:
    settings = get_settings()
    server_engine = create_engine(settings.a_stock_mysql_server_url, pool_pre_ping=True)
    with server_engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS {quote_identifier(database)} "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )


def database_engine(database: str) -> Engine:
    settings = get_settings()
    url = settings.a_stock_database_url
    if database != settings.a_stock_mysql_database:
        url = (
            f"mysql+pymysql://{settings.a_stock_mysql_user}:{settings.a_stock_mysql_password}"
            f"@{settings.a_stock_mysql_host}:{settings.a_stock_mysql_port}/{database}?charset=utf8mb4"
        )
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)


def create_tables(engine: Engine) -> None:
    table_sql = """
    CREATE TABLE IF NOT EXISTS {table_name} (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        symbol VARCHAR(10) NOT NULL COMMENT '股票代码',
        stock_name VARCHAR(100) NULL COMMENT '股票名称',
        trade_date DATE NOT NULL COMMENT '交易日期',
        open_price DECIMAL(20, 6) NULL,
        high_price DECIMAL(20, 6) NULL,
        low_price DECIMAL(20, 6) NULL,
        close_price DECIMAL(20, 6) NULL,
        volume BIGINT NULL COMMENT '成交量',
        amount DECIMAL(24, 4) NULL COMMENT '成交额',
        amplitude DECIMAL(12, 6) NULL COMMENT '振幅，百分数原值',
        change_rate DECIMAL(12, 6) NULL COMMENT '涨跌幅，百分数原值',
        change_amount DECIMAL(20, 6) NULL COMMENT '涨跌额',
        turnover_rate DECIMAL(12, 6) NULL COMMENT '换手率，百分数原值',
        source VARCHAR(50) NOT NULL DEFAULT 'akshare:stock_zh_a_hist',
        synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_symbol_trade_date (symbol, trade_date),
        INDEX idx_trade_date (trade_date),
        INDEX idx_symbol_date (symbol, trade_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    progress_sql = f"""
    CREATE TABLE IF NOT EXISTS {quote_identifier(PROGRESS_TABLE)} (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        task_id BIGINT NULL COMMENT '同步任务 ID',
        symbol VARCHAR(10) NOT NULL COMMENT '股票代码',
        stock_name VARCHAR(100) NULL COMMENT '股票名称',
        start_date CHAR(8) NOT NULL COMMENT '同步开始日期',
        end_date CHAR(8) NOT NULL COMMENT '同步结束日期',
        status VARCHAR(20) NOT NULL COMMENT 'running/done/failed',
        rows_none INT NULL,
        rows_qfq INT NULL,
        rows_hfq INT NULL,
        started_at DATETIME NULL,
        finished_at DATETIME NULL,
        duration_seconds DECIMAL(12, 3) NULL,
        error TEXT NULL,
        run_count INT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_task_symbol_range (task_id, symbol, start_date, end_date),
        INDEX idx_task_status (task_id, status),
        INDEX idx_status (status),
        INDEX idx_symbol_status (symbol, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    task_sql = f"""
    CREATE TABLE IF NOT EXISTS {quote_identifier(TASK_TABLE)} (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        task_type VARCHAR(50) NOT NULL DEFAULT 'history_sync',
        status VARCHAR(20) NOT NULL DEFAULT 'pending'
            COMMENT 'pending/running/success/partial/failed/skipped',
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
    with engine.begin() as connection:
        for table_name in ADJUST_TABLES.values():
            connection.execute(text(table_sql.format(table_name=quote_identifier(table_name))))
        connection.execute(text(task_sql))
        connection.execute(text(progress_sql))
        _ensure_column(
            connection,
            PROGRESS_TABLE,
            "task_id",
            "ADD COLUMN task_id BIGINT NULL COMMENT '同步任务 ID' AFTER id",
        )
        _ensure_index(connection, PROGRESS_TABLE, "idx_task_status", "ADD INDEX idx_task_status (task_id, status)")
        _drop_index_if_exists(connection, PROGRESS_TABLE, "uk_symbol_range")
        _ensure_index(
            connection,
            PROGRESS_TABLE,
            "uk_task_symbol_range",
            "ADD UNIQUE KEY uk_task_symbol_range (task_id, symbol, start_date, end_date)",
        )


def _ensure_column(connection, table_name: str, column_name: str, alter_clause: str) -> None:
    exists = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).scalar()
    if not exists:
        connection.execute(text(f"ALTER TABLE {quote_identifier(table_name)} {alter_clause}"))


def _ensure_index(connection, table_name: str, index_name: str, alter_clause: str) -> None:
    exists = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND index_name = :index_name
            """
        ),
        {"table_name": table_name, "index_name": index_name},
    ).scalar()
    if not exists:
        connection.execute(text(f"ALTER TABLE {quote_identifier(table_name)} {alter_clause}"))


def _drop_index_if_exists(connection, table_name: str, index_name: str) -> None:
    exists = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND index_name = :index_name
            """
        ),
        {"table_name": table_name, "index_name": index_name},
    ).scalar()
    if exists:
        connection.execute(text(f"ALTER TABLE {quote_identifier(table_name)} DROP INDEX {quote_identifier(index_name)}"))


def load_completed_symbols(engine: Engine, start_date: str, end_date: str, task_id: int | None) -> set[str]:
    task_filter = "AND task_id = :task_id" if task_id is not None else "AND task_id IS NULL"
    statement = text(
        f"""
        SELECT symbol
        FROM {quote_identifier(PROGRESS_TABLE)}
        WHERE start_date = :start_date
          AND end_date = :end_date
          AND status = 'done'
          {task_filter}
        """
    )
    with engine.connect() as connection:
        return {
            row.symbol
            for row in connection.execute(
                statement,
                {"start_date": start_date, "end_date": end_date, "task_id": task_id},
            )
        }


def list_progress_by_status(
    engine: Engine,
    start_date: str,
    end_date: str,
    status: str,
    task_id: int | None,
) -> list[StockInfo]:
    task_filter = "AND task_id = :task_id" if task_id is not None else "AND task_id IS NULL"
    statement = text(
        f"""
        SELECT symbol, stock_name
        FROM {quote_identifier(PROGRESS_TABLE)}
        WHERE start_date = :start_date
          AND end_date = :end_date
          AND status = :status
          {task_filter}
        ORDER BY symbol ASC
        """
    )
    with engine.connect() as connection:
        rows = connection.execute(
            statement,
            {
                "start_date": start_date,
                "end_date": end_date,
                "status": status,
                "task_id": task_id,
            },
        ).mappings()
        return [StockInfo(symbol=row["symbol"], name=row["stock_name"]) for row in rows]


def list_stale_running_progress(
    engine: Engine,
    start_date: str,
    end_date: str,
    task_id: int | None,
) -> list[StockInfo]:
    task_filter = "AND task_id = :task_id" if task_id is not None else "AND task_id IS NULL"
    statement = text(
        f"""
        SELECT symbol, stock_name
        FROM {quote_identifier(PROGRESS_TABLE)}
        WHERE start_date = :start_date
          AND end_date = :end_date
          AND status = 'running'
          {task_filter}
          AND (
              started_at IS NULL
              OR TIMESTAMPDIFF(MINUTE, started_at, NOW()) >= :stale_minutes
          )
        ORDER BY symbol ASC
        """
    )
    with engine.connect() as connection:
        rows = connection.execute(
            statement,
            {
                "start_date": start_date,
                "end_date": end_date,
                "stale_minutes": PROGRESS_RUNNING_STALE_MINUTES,
                "task_id": task_id,
            },
        ).mappings()
        return [StockInfo(symbol=row["symbol"], name=row["stock_name"]) for row in rows]


def merge_stocks_by_symbol(stocks: list[StockInfo]) -> list[StockInfo]:
    merged: dict[str, StockInfo] = {}
    for stock in stocks:
        merged[stock.symbol] = stock
    return list(merged.values())


def claim_progress_running(
    engine: Engine,
    stock: StockInfo,
    start_date: str,
    end_date: str,
    task_id: int | None,
) -> str:
    select_statement = text(
        f"""
        SELECT status, started_at
        FROM {quote_identifier(PROGRESS_TABLE)}
        WHERE task_id <=> :task_id
          AND symbol = :symbol
          AND start_date = :start_date
          AND end_date = :end_date
        """
    )
    insert_statement = text(
        f"""
        INSERT INTO {quote_identifier(PROGRESS_TABLE)} (
            task_id, symbol, stock_name, start_date, end_date, status, started_at, finished_at,
            duration_seconds, error, run_count
        ) VALUES (
            :task_id, :symbol, :stock_name, :start_date, :end_date, 'running', NOW(), NULL,
            NULL, NULL, 1
        )
        """
    )
    update_statement = text(
        f"""
        UPDATE {quote_identifier(PROGRESS_TABLE)}
        SET task_id = :task_id,
            stock_name = :stock_name,
            status = 'running',
            started_at = NOW(),
            finished_at = NULL,
            duration_seconds = NULL,
            error = NULL,
            run_count = run_count + 1
        WHERE symbol = :symbol
          AND task_id <=> :task_id
          AND start_date = :start_date
          AND end_date = :end_date
        """
    )
    def execute(connection):
        params = {
            "symbol": stock.symbol,
            "stock_name": stock.name,
            "start_date": start_date,
            "end_date": end_date,
            "task_id": task_id,
        }
        row = connection.execute(select_statement, params).mappings().first()
        if row is None:
            connection.execute(insert_statement, params)
            return "claimed"
        if row["status"] == "done":
            return "done"
        if row["status"] == "running" and row["started_at"] is not None:
            stale = connection.execute(
                text("SELECT TIMESTAMPDIFF(MINUTE, :started_at, NOW())"),
                {"started_at": row["started_at"]},
            ).scalar()
            if stale is not None and int(stale) < PROGRESS_RUNNING_STALE_MINUTES:
                return "running"
        connection.execute(update_statement, params)
        return "claimed"

    return run_progress_transaction(engine, "claim_progress_running", execute)


def mark_progress_done(
    engine: Engine,
    stock: StockInfo,
    start_date: str,
    end_date: str,
    counts: dict[str, int],
    duration_seconds: float,
    task_id: int | None,
) -> None:
    update_statement = text(
        f"""
        UPDATE {quote_identifier(PROGRESS_TABLE)}
        SET task_id = :task_id,
            stock_name = :stock_name,
            status = 'done',
            rows_none = :rows_none,
            rows_qfq = :rows_qfq,
            rows_hfq = :rows_hfq,
            finished_at = NOW(),
            duration_seconds = :duration_seconds,
            error = NULL
        WHERE symbol = :symbol
          AND task_id <=> :task_id
          AND start_date = :start_date
          AND end_date = :end_date
        """
    )
    insert_statement = text(
        f"""
        INSERT INTO {quote_identifier(PROGRESS_TABLE)} (
            task_id, symbol, stock_name, start_date, end_date, status,
            rows_none, rows_qfq, rows_hfq, started_at, finished_at,
            duration_seconds, error, run_count
        ) VALUES (
            :task_id, :symbol, :stock_name, :start_date, :end_date, 'done',
            :rows_none, :rows_qfq, :rows_hfq, NOW(), NOW(),
            :duration_seconds, NULL, 1
        )
        """
    )
    def execute(connection):
        params = {
            "symbol": stock.symbol,
            "stock_name": stock.name,
            "start_date": start_date,
            "end_date": end_date,
            "task_id": task_id,
            "rows_none": counts.get("stock_daily_bars_none"),
            "rows_qfq": counts.get("stock_daily_bars_qfq"),
            "rows_hfq": counts.get("stock_daily_bars_hfq"),
            "duration_seconds": round(duration_seconds, 3),
        }
        result = connection.execute(update_statement, params)
        if result.rowcount == 0:
            logger.warning("progress_missing_before_done symbol=%s task_id=%s", stock.symbol, task_id)
            connection.execute(insert_statement, params)

    run_progress_transaction(engine, "mark_progress_done", execute)


def mark_progress_failed(
    engine: Engine,
    stock: StockInfo,
    start_date: str,
    end_date: str,
    error: str,
    duration_seconds: float,
    task_id: int | None,
) -> None:
    update_statement = text(
        f"""
        UPDATE {quote_identifier(PROGRESS_TABLE)}
        SET task_id = :task_id,
            stock_name = :stock_name,
            status = 'failed',
            finished_at = NOW(),
            duration_seconds = :duration_seconds,
            error = :error
        WHERE symbol = :symbol
          AND task_id <=> :task_id
          AND start_date = :start_date
          AND end_date = :end_date
        """
    )
    insert_statement = text(
        f"""
        INSERT INTO {quote_identifier(PROGRESS_TABLE)} (
            task_id, symbol, stock_name, start_date, end_date, status, started_at, finished_at,
            duration_seconds, error, run_count
        ) VALUES (
            :task_id, :symbol, :stock_name, :start_date, :end_date, 'failed', NOW(), NOW(),
            :duration_seconds, :error, 1
        )
        """
    )
    def execute(connection):
        params = {
            "symbol": stock.symbol,
            "stock_name": stock.name,
            "start_date": start_date,
            "end_date": end_date,
            "task_id": task_id,
            "duration_seconds": round(duration_seconds, 3),
            "error": error[:4000],
        }
        result = connection.execute(update_statement, params)
        if result.rowcount == 0:
            logger.warning("progress_missing_before_failed symbol=%s task_id=%s", stock.symbol, task_id)
            connection.execute(insert_statement, params)

    run_progress_transaction(engine, "mark_progress_failed", execute)


def get_stock_pool() -> list[StockInfo]:
    dataframe = ak.stock_info_a_code_name()
    code_column = "code" if "code" in dataframe.columns else "代码"
    name_column = "name" if "name" in dataframe.columns else "名称"
    stocks: list[StockInfo] = []
    seen_symbols: set[str] = set()
    for _, row in dataframe.iterrows():
        symbol = normalize_symbol(row[code_column])
        name = str(row[name_column]).strip() if name_column in dataframe.columns else None
        if symbol.isdigit() and len(symbol) == 6 and symbol not in seen_symbols:
            seen_symbols.add(symbol)
            stocks.append(StockInfo(symbol=symbol, name=name or None))
    return stocks


def existing_symbol_has_range(engine: Engine, table_name: str, symbol: str, start_date: str, end_date: str) -> bool:
    statement = text(
        f"""
        SELECT 1
        FROM {quote_identifier(table_name)}
        WHERE symbol = :symbol
          AND trade_date BETWEEN :start_date AND :end_date
        LIMIT 1
        """
    )
    with engine.connect() as connection:
        return connection.execute(
            statement,
            {"symbol": symbol, "start_date": start_date, "end_date": end_date},
        ).first() is not None


def history_rows(dataframe, stock: StockInfo, synced_at: datetime) -> list[dict]:
    rows: list[dict] = []
    previous_close: Decimal | None = None
    for _, row in dataframe.iterrows():
        trade_date = date_from_value(row["日期"] if "日期" in row else row["date"])
        open_price = decimal_or_none(row.get("开盘") if "开盘" in row else row.get("open"))
        high_price = decimal_or_none(row.get("最高") if "最高" in row else row.get("high"))
        low_price = decimal_or_none(row.get("最低") if "最低" in row else row.get("low"))
        close_price = decimal_or_none(row.get("收盘") if "收盘" in row else row.get("close"))
        volume = decimal_or_none(row.get("成交量") if "成交量" in row else row.get("volume"))
        amount = decimal_or_none(row.get("成交额") if "成交额" in row else row.get("amount"))
        amplitude = decimal_or_none(row.get("振幅"))
        change_rate = decimal_or_none(row.get("涨跌幅"))
        change_amount = decimal_or_none(row.get("涨跌额"))
        turnover_rate = decimal_or_none(row.get("换手率"))

        if turnover_rate is None:
            turnover_ratio = decimal_or_none(row.get("turnover"))
            turnover_rate = turnover_ratio * Decimal("100") if turnover_ratio is not None else None
        if change_amount is None and close_price is not None and previous_close is not None:
            change_amount = close_price - previous_close
        if change_rate is None and close_price is not None and previous_close not in (None, Decimal("0")):
            change_rate = (close_price - previous_close) / previous_close * Decimal("100")
        if (
            amplitude is None
            and high_price is not None
            and low_price is not None
            and previous_close not in (None, Decimal("0"))
        ):
            amplitude = (high_price - low_price) / previous_close * Decimal("100")

        rows.append(
            {
                "symbol": stock.symbol,
                "stock_name": stock.name,
                "trade_date": trade_date,
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close_price,
                "volume": int(volume) if volume is not None else None,
                "amount": amount,
                "amplitude": amplitude,
                "change_rate": change_rate,
                "change_amount": change_amount,
                "turnover_rate": turnover_rate,
                "synced_at": synced_at,
            }
        )
        previous_close = close_price or previous_close
    return rows


def write_rows(engine: Engine, table_name: str, rows: list[dict], insert_only: bool) -> None:
    if not rows:
        return
    duplicate_clause = ""
    if not insert_only:
        duplicate_clause = """
        ON DUPLICATE KEY UPDATE
            stock_name = VALUES(stock_name),
            open_price = VALUES(open_price),
            high_price = VALUES(high_price),
            low_price = VALUES(low_price),
            close_price = VALUES(close_price),
            volume = VALUES(volume),
            amount = VALUES(amount),
            amplitude = VALUES(amplitude),
            change_rate = VALUES(change_rate),
            change_amount = VALUES(change_amount),
            turnover_rate = VALUES(turnover_rate),
            source = VALUES(source),
            synced_at = VALUES(synced_at)
        """
    statement = text(
        f"""
        INSERT INTO {quote_identifier(table_name)} (
            symbol, stock_name, trade_date,
            open_price, high_price, low_price, close_price,
            volume, amount, amplitude, change_rate, change_amount, turnover_rate,
            source, synced_at
        ) VALUES (
            :symbol, :stock_name, :trade_date,
            :open_price, :high_price, :low_price, :close_price,
            :volume, :amount, :amplitude, :change_rate, :change_amount, :turnover_rate,
            :source, :synced_at
        )
        {duplicate_clause}
        """
    )
    with engine.begin() as connection:
        connection.execute(statement, rows)


def delete_symbol_rows_in_range(engine: Engine, symbol: str, start_date: str, end_date: str) -> None:
    with engine.begin() as connection:
        for table_name in ADJUST_TABLES.values():
            connection.execute(
                text(
                    f"""
                    DELETE FROM {quote_identifier(table_name)}
                    WHERE symbol = :symbol
                      AND trade_date BETWEEN :start_date AND :end_date
                    """
                ),
                {"symbol": symbol, "start_date": start_date, "end_date": end_date},
            )


def sync_stock(
    engine: Engine,
    stock: StockInfo,
    start_date: str,
    end_date: str,
    skip_existing: bool,
    insert_only: bool,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for adjust, table_name in ADJUST_TABLES.items():
        if skip_existing and existing_symbol_has_range(engine, table_name, stock.symbol, start_date, end_date):
            counts[table_name] = -1
            continue
        dataframe, source = fetch_history_dataframe(stock.symbol, start_date, end_date, adjust)
        rows = history_rows(dataframe, stock, datetime.now())
        for row in rows:
            row["source"] = source
        write_rows(engine, table_name, rows, insert_only)
        counts[table_name] = len(rows)
    return counts


def sync_stock_with_conflict_retry(
    engine: Engine,
    stock: StockInfo,
    start_date: str,
    end_date: str,
    skip_existing: bool,
    insert_only: bool,
    retry_conflicts: bool,
) -> tuple[dict[str, int], str | None]:
    retry_count = 0
    while True:
        try:
            return (
                sync_stock(
                    engine=engine,
                    stock=stock,
                    start_date=start_date,
                    end_date=end_date,
                    skip_existing=skip_existing if retry_count == 0 else False,
                    insert_only=insert_only,
                ),
                None,
            )
        except IntegrityError:
            if not insert_only or not retry_conflicts or retry_count >= 1:
                raise
            retry_count += 1
            with _rebuild_lock:
                logger.warning(
                    "CONFLICT %s delete_existing_range=true start_date=%s end_date=%s retry=%s",
                    stock.symbol,
                    start_date,
                    end_date,
                    retry_count,
                )
                delete_symbol_rows_in_range(engine, stock.symbol, start_date, end_date)
                return (
                    sync_stock(
                        engine=engine,
                        stock=stock,
                        start_date=start_date,
                        end_date=end_date,
                        skip_existing=False,
                        insert_only=True,
                    ),
                    "integrity_conflict",
                )
        except OperationalError as exc:
            error_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
            if error_code != 1205 or not insert_only or not retry_conflicts or retry_count >= 4:
                raise
            retry_count += 1
            with _rebuild_lock:
                logger.warning(
                    "LOCK_TIMEOUT %s delete_existing_range=true start_date=%s end_date=%s retry=%s",
                    stock.symbol,
                    start_date,
                    end_date,
                    retry_count,
                )
                delete_symbol_rows_in_range(engine, stock.symbol, start_date, end_date)
                sleep(5 * retry_count)
                return (
                    sync_stock(
                        engine=engine,
                        stock=stock,
                        start_date=start_date,
                        end_date=end_date,
                        skip_existing=False,
                        insert_only=True,
                    ),
                    "lock_timeout",
                )


def import_completed_from_logs(engine: Engine, log_paths: list[str], start_date: str, end_date: str) -> int:
    completed_pattern = re.compile(
        r"\[\d+/\d+\]\s+"
        r"(?:DONE\s+)?"
        r"(?P<symbol>\d{6})\s+.*?"
        r"stock_daily_bars_none=(?P<rows_none>\d+),\s+"
        r"stock_daily_bars_qfq=(?P<rows_qfq>\d+),\s+"
        r"stock_daily_bars_hfq=(?P<rows_hfq>\d+)"
    )
    statement = text(
        f"""
        INSERT INTO {quote_identifier(PROGRESS_TABLE)} (
            symbol, stock_name, start_date, end_date, status,
            rows_none, rows_qfq, rows_hfq, started_at, finished_at,
            duration_seconds, error, run_count
        ) VALUES (
            :symbol, NULL, :start_date, :end_date, 'done',
            :rows_none, :rows_qfq, :rows_hfq, NOW(), NOW(),
            NULL, NULL, 0
        )
        ON DUPLICATE KEY UPDATE
            status = IF(status = 'done', status, VALUES(status)),
            rows_none = VALUES(rows_none),
            rows_qfq = VALUES(rows_qfq),
            rows_hfq = VALUES(rows_hfq),
            finished_at = IF(status = 'done', finished_at, NOW()),
            error = NULL
        """
    )
    imported: dict[str, dict[str, int | str]] = {}
    for log_path in log_paths:
        path = Path(log_path)
        if not path.is_absolute() and not path.exists():
            path = ORIGINAL_CWD / path
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = completed_pattern.search(line)
            if not match:
                continue
            imported[match.group("symbol")] = {
                "symbol": match.group("symbol"),
                "start_date": start_date,
                "end_date": end_date,
                "rows_none": int(match.group("rows_none")),
                "rows_qfq": int(match.group("rows_qfq")),
                "rows_hfq": int(match.group("rows_hfq")),
            }
    if not imported:
        return 0

    def execute(connection):
        connection.execute(statement, list(imported.values()))

    run_progress_transaction(engine, "import_completed_from_logs", execute)
    return len(imported)


def mark_task_running(engine: Engine, task_id: int | None, total_count: int) -> None:
    if task_id is None:
        return
    statement = text(
        f"""
        UPDATE {quote_identifier(TASK_TABLE)}
        SET status = 'running',
            total_count = :total_count,
            started_at = COALESCE(started_at, NOW()),
            message = '任务执行中'
        WHERE id = :task_id
        """
    )
    with engine.begin() as connection:
        connection.execute(statement, {"task_id": task_id, "total_count": total_count})


def finish_task(engine: Engine, task_id: int | None, start_date: str, end_date: str, message: str | None = None) -> None:
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
    statement = text(
        f"""
        UPDATE {quote_identifier(TASK_TABLE)}
        SET status = :status,
            total_count = :total_count,
            success_count = :success_count,
            failed_count = :failed_count,
            running_count = :running_count,
            skipped_count = :skipped_count,
            finished_at = NOW(),
            duration_seconds = CASE
                WHEN started_at IS NULL THEN duration_seconds
                ELSE TIMESTAMPDIFF(SECOND, started_at, NOW())
            END,
            message = :message
        WHERE id = :task_id
        """
    )
    with engine.begin() as connection:
        connection.execute(
            statement,
            {
                "task_id": task_id,
                "status": status,
                "total_count": total_count,
                "success_count": done_count,
                "failed_count": failed_count,
                "running_count": running_count,
                "skipped_count": counts.get("skipped", 0),
                "message": message or f"done={done_count};failed={failed_count};running={running_count}",
            },
        )


def progress_counts(engine: Engine, start_date: str, end_date: str, task_id: int | None) -> dict[str, int]:
    task_filter = "AND task_id = :task_id" if task_id is not None else "AND task_id IS NULL"
    statement = text(
        f"""
        SELECT status, COUNT(*) AS count
        FROM {quote_identifier(PROGRESS_TABLE)}
        WHERE start_date = :start_date AND end_date = :end_date
          {task_filter}
        GROUP BY status
        """
    )
    with engine.connect() as connection:
        return {
            str(row["status"]): int(row["count"])
            for row in connection.execute(
                statement,
                {"start_date": start_date, "end_date": end_date, "task_id": task_id},
            ).mappings()
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync 10 years of A-share daily bars from AkShare into a separate MySQL database.")
    parser.add_argument("--database", default=get_settings().a_stock_mysql_database)
    parser.add_argument("--start-date", default=f"{date.today().year - 10}{date.today():%m%d}")
    parser.add_argument("--end-date", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--symbols", nargs="*", help="Optional stock symbols. Defaults to all current A-share symbols.")
    parser.add_argument("--start-after", help="Skip stock symbols up to and including this symbol.")
    parser.add_argument("--limit", type=int, default=None, help="Limit stock count for a trial run.")
    parser.add_argument("--sleep-seconds", type=float, default=0.2, help="Sleep between symbols to reduce source pressure.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip a symbol/table if the target date range already has rows.")
    parser.add_argument("--workers", type=int, default=1, help="Number of stocks to sync concurrently.")
    parser.add_argument("--insert-only", action="store_true", help="Use plain INSERT instead of upsert.")
    parser.add_argument("--retry-conflicts", action="store_true", help="On insert duplicate key, delete that symbol from all bar tables and retry once.")
    parser.add_argument("--use-progress", action="store_true", help="Skip symbols marked done in the progress table and update progress per symbol.")
    parser.add_argument("--task-id", type=int, default=None, help="Optional a_stock_history_sync_tasks.id to update.")
    parser.add_argument("--import-completed-from-logs", nargs="*", help="Import definitely completed symbols from old stdout logs before syncing.")
    return parser.parse_args()


def sync_one_with_status(
    engine: Engine,
    stock: StockInfo,
    index: int,
    total: int,
    start_date: str,
    end_date: str,
    skip_existing: bool,
    insert_only: bool,
    retry_conflicts: bool,
    use_progress: bool,
    completed_symbols: set[str],
    task_id: int | None,
) -> tuple[str, str | None]:
    with _progress_lock:
        if use_progress and stock.symbol in completed_symbols:
            logger.info("[%s/%s] SKIP %s %s progress=done source=memory", index, total, stock.symbol, stock.name or "")
            return stock.symbol, None

    started = monotonic()
    if use_progress:
        claim_status = claim_progress_running(engine, stock, start_date, end_date, task_id)
        if claim_status == "done":
            with _progress_lock:
                completed_symbols.add(stock.symbol)
            logger.info("[%s/%s] SKIP %s %s progress=done source=database", index, total, stock.symbol, stock.name or "")
            return stock.symbol, None
        if claim_status == "running":
            logger.info("[%s/%s] SKIP %s %s progress=running source=database", index, total, stock.symbol, stock.name or "")
            return stock.symbol, None
    logger.info("[%s/%s] START %s %s", index, total, stock.symbol, stock.name or "")

    try:
        counts, retry_reason = sync_stock_with_conflict_retry(
            engine=engine,
            stock=stock,
            start_date=start_date,
            end_date=end_date,
            skip_existing=skip_existing,
            insert_only=insert_only,
            retry_conflicts=retry_conflicts,
        )
        duration_seconds = monotonic() - started
        if use_progress:
            mark_progress_done(engine, stock, start_date, end_date, counts, duration_seconds, task_id)
            with _progress_lock:
                completed_symbols.add(stock.symbol)
        count_text = ", ".join(
            f"{table}={'skip' if count == -1 else count}" for table, count in counts.items()
        )
        logger.info(
            "[%s/%s] DONE %s %s %s duration=%.2fs retried_rebuild=%s retry_reason=%s",
            index,
            total,
            stock.symbol,
            stock.name or "",
            count_text,
            duration_seconds,
            retry_reason is not None,
            retry_reason or "none",
        )
        return stock.symbol, None
    except Exception as exc:
        duration_seconds = monotonic() - started
        if use_progress:
            mark_progress_failed(engine, stock, start_date, end_date, str(exc), duration_seconds, task_id)
        logger.exception("[%s/%s] FAILED %s duration=%.2fs error=%s", index, total, stock.symbol, duration_seconds, exc)
        return stock.symbol, str(exc)


def sync_stock_batch(
    engine: Engine,
    stocks: list[StockInfo],
    start_date: str,
    end_date: str,
    skip_existing: bool,
    insert_only: bool,
    retry_conflicts: bool,
    use_progress: bool,
    completed_symbols: set[str],
    workers: int,
    sleep_seconds: float,
    task_id: int | None,
) -> list[tuple[str, str]]:
    total = len(stocks)
    failures: list[tuple[str, str]] = []
    if workers <= 1:
        for index, stock in enumerate(stocks, start=1):
            symbol, error = sync_one_with_status(
                engine=engine,
                stock=stock,
                index=index,
                total=total,
                start_date=start_date,
                end_date=end_date,
                skip_existing=skip_existing,
                insert_only=insert_only,
                retry_conflicts=retry_conflicts,
                use_progress=use_progress,
                completed_symbols=completed_symbols,
                task_id=task_id,
            )
            if error is not None:
                failures.append((symbol, error))
            if sleep_seconds > 0:
                sleep(sleep_seconds)
        return failures

    max_workers = max(1, workers)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for index, stock in enumerate(stocks, start=1):
            futures.append(
                executor.submit(
                    sync_one_with_status,
                    engine,
                    stock,
                    index,
                    total,
                    start_date,
                    end_date,
                    skip_existing,
                    insert_only,
                    retry_conflicts,
                    use_progress,
                    completed_symbols,
                    task_id,
                )
            )
            if sleep_seconds > 0:
                sleep(sleep_seconds)
        for future in as_completed(futures):
            symbol, error = future.result()
            if error is not None:
                failures.append((symbol, error))
    return failures


def main() -> None:
    args = parse_args()
    settings = get_settings()
    configure_logging(
        settings.log_dir,
        settings.log_backup_days,
        settings.log_level,
        log_file_name="a_stock_daily_sync.log",
        console=False,
    )
    ensure_database_exists(args.database)
    engine = database_engine(args.database)
    create_tables(engine)
    if args.import_completed_from_logs is not None:
        imported_count = import_completed_from_logs(
            engine=engine,
            log_paths=args.import_completed_from_logs,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        logger.info("Imported completed symbols from logs: %s", imported_count)

    completed_symbols = load_completed_symbols(engine, args.start_date, args.end_date, args.task_id) if args.use_progress else set()

    if args.symbols:
        stocks = [StockInfo(symbol=normalize_symbol(symbol), name=None) for symbol in args.symbols]
    else:
        stocks = get_stock_pool()
    raw_stock_count = len(stocks)
    stocks = merge_stocks_by_symbol(stocks)
    deduped_stock_count = len(stocks)
    if args.start_after:
        start_after = normalize_symbol(args.start_after)
        stocks = [stock for stock in stocks if stock.symbol > start_after]
    if args.limit is not None:
        stocks = stocks[: args.limit]

    total = len(stocks)
    logger.info("Target database: %s", args.database)
    logger.info("Date range: %s - %s", args.start_date, args.end_date)
    logger.info("Stock count: %s", total)
    logger.info("Stock dedupe: raw=%s unique=%s duplicates=%s", raw_stock_count, deduped_stock_count, raw_stock_count - deduped_stock_count)
    logger.info("Tables: %s", ", ".join(ADJUST_TABLES.values()))
    logger.info("Workers: %s", args.workers)
    logger.info("Insert only: %s", args.insert_only)
    logger.info("Use progress: %s", args.use_progress)
    logger.info("Completed symbols loaded: %s", len(completed_symbols))
    mark_task_running(engine, args.task_id, total)

    failures = sync_stock_batch(
        engine=engine,
        stocks=stocks,
        start_date=args.start_date,
        end_date=args.end_date,
        skip_existing=args.skip_existing,
        insert_only=args.insert_only,
        retry_conflicts=args.retry_conflicts,
        use_progress=args.use_progress,
        completed_symbols=completed_symbols,
        workers=args.workers,
        sleep_seconds=args.sleep_seconds,
        task_id=args.task_id,
    )

    if args.use_progress:
        stale_round = 1
        while True:
            stale_stocks = merge_stocks_by_symbol(
                list_stale_running_progress(engine, args.start_date, args.end_date, args.task_id)
            )
            if not stale_stocks:
                break
            logger.info(
                "Stale running progress rescan round=%s count=%s stale_minutes=%s",
                stale_round,
                len(stale_stocks),
                PROGRESS_RUNNING_STALE_MINUTES,
            )
            failures.extend(
                sync_stock_batch(
                    engine=engine,
                    stocks=stale_stocks,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    skip_existing=args.skip_existing,
                    insert_only=args.insert_only,
                    retry_conflicts=args.retry_conflicts,
                    use_progress=args.use_progress,
                    completed_symbols=completed_symbols,
                    workers=args.workers,
                    sleep_seconds=args.sleep_seconds,
                    task_id=args.task_id,
                )
            )
            stale_round += 1

        failed_stocks = merge_stocks_by_symbol(
            list_progress_by_status(engine, args.start_date, args.end_date, "failed", args.task_id)
        )
        if failed_stocks:
            logger.info("Failed progress retry count=%s", len(failed_stocks))
            sync_stock_batch(
                engine=engine,
                stocks=failed_stocks,
                start_date=args.start_date,
                end_date=args.end_date,
                skip_existing=args.skip_existing,
                insert_only=args.insert_only,
                retry_conflicts=args.retry_conflicts,
                use_progress=args.use_progress,
                completed_symbols=completed_symbols,
                workers=args.workers,
                sleep_seconds=args.sleep_seconds,
                task_id=args.task_id,
            )
            failures = [
                (stock.symbol, "failed_after_retry")
                for stock in list_progress_by_status(engine, args.start_date, args.end_date, "failed", args.task_id)
            ]

    finish_task(engine, args.task_id, args.start_date, args.end_date)
    if failures:
        logger.error("Failures:")
        for symbol, error in failures:
            logger.error("- %s: %s", symbol, error)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
