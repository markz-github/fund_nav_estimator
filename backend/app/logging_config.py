from __future__ import annotations

from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime, time, timedelta
import logging
import sys


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
LOG_FORMAT = (
    "%(asctime)s %(levelname)s [pid=%(process)d thread=%(thread)d] "
    "%(name)s: %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_LEVEL = logging.INFO


class ShanghaiFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        log_time = datetime.fromtimestamp(record.created, SHANGHAI_TZ)
        if datefmt:
            return log_time.strftime(datefmt)
        return log_time.isoformat(timespec="seconds")


class ShanghaiMidnightRotatingFileHandler(TimedRotatingFileHandler):
    """Rotate at Shanghai midnight and name backups by the local log date."""

    def rotation_filename(self, default_name: str) -> str:
        path = Path(default_name)
        try:
            log_date = datetime.strptime(path.suffix.lstrip("."), "%Y-%m-%d").date() + timedelta(days=1)
        except ValueError:
            return super().rotation_filename(default_name)
        return str(path.with_suffix(f".{log_date:%Y-%m-%d}"))


def _parse_log_level(log_level: str) -> int:
    level_name = str(log_level).strip().upper()
    level = logging.getLevelName(level_name)
    if isinstance(level, int):
        return level
    return DEFAULT_LOG_LEVEL


def resolve_log_dir(log_dir: str) -> Path:
    log_path = Path(log_dir)
    if not log_path.is_absolute():
        log_path = Path.cwd() / log_path
    log_path.mkdir(parents=True, exist_ok=True)
    return log_path


def configure_logging(
    log_dir: str,
    backup_days: int,
    log_level: str = "INFO",
    log_file_name: str = "backend.log",
    console: bool = True,
) -> None:
    log_path = resolve_log_dir(log_dir)

    level = _parse_log_level(log_level)
    formatter = ShanghaiFormatter(LOG_FORMAT, DATE_FORMAT)

    file_handler = ShanghaiMidnightRotatingFileHandler(
        log_path / log_file_name,
        when="midnight",
        interval=1,
        backupCount=backup_days,
        encoding="utf-8",
        utc=True,
        atTime=time(16, 0),
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(level)
        logger.propagate = True
