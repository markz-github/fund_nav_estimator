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

        dataframe = ak.stock_zh_a_daily(
            symbol=prefixed_symbol(symbol),
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
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
        UNIQUE KEY uk_symbol_range (symbol, start_date, end_date),
        INDEX idx_status (status),
        INDEX idx_symbol_status (symbol, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    with engine.begin() as connection:
        for table_name in ADJUST_TABLES.values():
            connection.execute(text(table_sql.format(table_name=quote_identifier(table_name))))
        connection.execute(text(progress_sql))


def load_completed_symbols(engine: Engine, start_date: str, end_date: str) -> set[str]:
    statement = text(
        f"""
        SELECT symbol
        FROM {quote_identifier(PROGRESS_TABLE)}
        WHERE start_date = :start_date
          AND end_date = :end_date
          AND status = 'done'
        """
    )
    with engine.connect() as connection:
        return {
            row.symbol
            for row in connection.execute(
                statement,
                {"start_date": start_date, "end_date": end_date},
            )
        }


def claim_progress_running(engine: Engine, stock: StockInfo, start_date: str, end_date: str) -> str:
    select_statement = text(
        f"""
        SELECT status, started_at
        FROM {quote_identifier(PROGRESS_TABLE)}
        WHERE symbol = :symbol
          AND start_date = :start_date
          AND end_date = :end_date
        FOR UPDATE
        """
    )
    insert_statement = text(
        f"""
        INSERT INTO {quote_identifier(PROGRESS_TABLE)} (
            symbol, stock_name, start_date, end_date, status, started_at, finished_at,
            duration_seconds, error, run_count
        ) VALUES (
            :symbol, :stock_name, :start_date, :end_date, 'running', NOW(), NULL,
            NULL, NULL, 1
        )
        """
    )
    update_statement = text(
        f"""
        UPDATE {quote_identifier(PROGRESS_TABLE)}
        SET stock_name = :stock_name,
            status = 'running',
            started_at = NOW(),
            finished_at = NULL,
            duration_seconds = NULL,
            error = NULL,
            run_count = run_count + 1
        WHERE symbol = :symbol
          AND start_date = :start_date
          AND end_date = :end_date
        """
    )
    with engine.begin() as connection:
        params = {
            "symbol": stock.symbol,
            "stock_name": stock.name,
            "start_date": start_date,
            "end_date": end_date,
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


def mark_progress_done(
    engine: Engine,
    stock: StockInfo,
    start_date: str,
    end_date: str,
    counts: dict[str, int],
    duration_seconds: float,
) -> None:
    statement = text(
        f"""
        INSERT INTO {quote_identifier(PROGRESS_TABLE)} (
            symbol, stock_name, start_date, end_date, status,
            rows_none, rows_qfq, rows_hfq, started_at, finished_at,
            duration_seconds, error, run_count
        ) VALUES (
            :symbol, :stock_name, :start_date, :end_date, 'done',
            :rows_none, :rows_qfq, :rows_hfq, NOW(), NOW(),
            :duration_seconds, NULL, 1
        )
        ON DUPLICATE KEY UPDATE
            stock_name = VALUES(stock_name),
            status = 'done',
            rows_none = VALUES(rows_none),
            rows_qfq = VALUES(rows_qfq),
            rows_hfq = VALUES(rows_hfq),
            finished_at = NOW(),
            duration_seconds = VALUES(duration_seconds),
            error = NULL
        """
    )
    with engine.begin() as connection:
        connection.execute(
            statement,
            {
                "symbol": stock.symbol,
                "stock_name": stock.name,
                "start_date": start_date,
                "end_date": end_date,
                "rows_none": counts.get("stock_daily_bars_none"),
                "rows_qfq": counts.get("stock_daily_bars_qfq"),
                "rows_hfq": counts.get("stock_daily_bars_hfq"),
                "duration_seconds": round(duration_seconds, 3),
            },
        )


def mark_progress_failed(
    engine: Engine,
    stock: StockInfo,
    start_date: str,
    end_date: str,
    error: str,
    duration_seconds: float,
) -> None:
    statement = text(
        f"""
        INSERT INTO {quote_identifier(PROGRESS_TABLE)} (
            symbol, stock_name, start_date, end_date, status, started_at, finished_at,
            duration_seconds, error, run_count
        ) VALUES (
            :symbol, :stock_name, :start_date, :end_date, 'failed', NOW(), NOW(),
            :duration_seconds, :error, 1
        )
        ON DUPLICATE KEY UPDATE
            stock_name = VALUES(stock_name),
            status = 'failed',
            finished_at = NOW(),
            duration_seconds = VALUES(duration_seconds),
            error = VALUES(error)
        """
    )
    with engine.begin() as connection:
        connection.execute(
            statement,
            {
                "symbol": stock.symbol,
                "stock_name": stock.name,
                "start_date": start_date,
                "end_date": end_date,
                "duration_seconds": round(duration_seconds, 3),
                "error": error[:4000],
            },
        )


def get_stock_pool() -> list[StockInfo]:
    dataframe = ak.stock_info_a_code_name()
    code_column = "code" if "code" in dataframe.columns else "代码"
    name_column = "name" if "name" in dataframe.columns else "名称"
    stocks: list[StockInfo] = []
    for _, row in dataframe.iterrows():
        symbol = normalize_symbol(row[code_column])
        name = str(row[name_column]).strip() if name_column in dataframe.columns else None
        if symbol.isdigit() and len(symbol) == 6:
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


def delete_symbol_rows(engine: Engine, symbol: str) -> None:
    with engine.begin() as connection:
        for table_name in ADJUST_TABLES.values():
            connection.execute(
                text(f"DELETE FROM {quote_identifier(table_name)} WHERE symbol = :symbol"),
                {"symbol": symbol},
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
                logger.warning("CONFLICT %s delete_existing_rows=true retry=%s", stock.symbol, retry_count)
                delete_symbol_rows(engine, stock.symbol)
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
                logger.warning("LOCK_TIMEOUT %s delete_existing_rows=true retry=%s", stock.symbol, retry_count)
                delete_symbol_rows(engine, stock.symbol)
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
    with engine.begin() as connection:
        connection.execute(statement, list(imported.values()))
    return len(imported)


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
) -> tuple[str, str | None]:
    with _progress_lock:
        if use_progress and stock.symbol in completed_symbols:
            logger.info("[%s/%s] SKIP %s %s progress=done source=memory", index, total, stock.symbol, stock.name or "")
            return stock.symbol, None

    started = monotonic()
    if use_progress:
        claim_status = claim_progress_running(engine, stock, start_date, end_date)
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
            mark_progress_done(engine, stock, start_date, end_date, counts, duration_seconds)
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
            mark_progress_failed(engine, stock, start_date, end_date, str(exc), duration_seconds)
        logger.exception("[%s/%s] FAILED %s duration=%.2fs error=%s", index, total, stock.symbol, duration_seconds, exc)
        return stock.symbol, str(exc)


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

    completed_symbols = load_completed_symbols(engine, args.start_date, args.end_date) if args.use_progress else set()

    if args.symbols:
        stocks = [StockInfo(symbol=normalize_symbol(symbol), name=None) for symbol in args.symbols]
    else:
        stocks = get_stock_pool()
    if args.start_after:
        start_after = normalize_symbol(args.start_after)
        stocks = [stock for stock in stocks if stock.symbol > start_after]
    if args.limit is not None:
        stocks = stocks[: args.limit]

    total = len(stocks)
    logger.info("Target database: %s", args.database)
    logger.info("Date range: %s - %s", args.start_date, args.end_date)
    logger.info("Stock count: %s", total)
    logger.info("Tables: %s", ", ".join(ADJUST_TABLES.values()))
    logger.info("Workers: %s", args.workers)
    logger.info("Insert only: %s", args.insert_only)
    logger.info("Use progress: %s", args.use_progress)
    logger.info("Completed symbols loaded: %s", len(completed_symbols))

    failures: list[tuple[str, str]] = []
    if args.workers <= 1:
        for index, stock in enumerate(stocks, start=1):
            symbol, error = sync_one_with_status(
                engine=engine,
                stock=stock,
                index=index,
                total=total,
                start_date=args.start_date,
                end_date=args.end_date,
                skip_existing=args.skip_existing,
                insert_only=args.insert_only,
                retry_conflicts=args.retry_conflicts,
                use_progress=args.use_progress,
                completed_symbols=completed_symbols,
            )
            if error is not None:
                failures.append((symbol, error))
            if args.sleep_seconds > 0:
                sleep(args.sleep_seconds)
    else:
        max_workers = max(1, args.workers)
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
                        args.start_date,
                        args.end_date,
                        args.skip_existing,
                        args.insert_only,
                        args.retry_conflicts,
                        args.use_progress,
                        completed_symbols,
                    )
                )
                if args.sleep_seconds > 0:
                    sleep(args.sleep_seconds)
            for future in as_completed(futures):
                symbol, error = future.result()
                if error is not None:
                    failures.append((symbol, error))

    if failures:
        logger.error("Failures:")
        for symbol, error in failures:
            logger.error("- %s: %s", symbol, error)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
