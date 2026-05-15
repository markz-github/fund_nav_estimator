from __future__ import annotations

from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime, time
import logging
import sys


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
LOG_FORMAT = (
    "%(asctime)s %(levelname)s [pid=%(process)d thread=%(thread)d] "
    "%(name)s: %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ShanghaiFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        log_time = datetime.fromtimestamp(record.created, SHANGHAI_TZ)
        if datefmt:
            return log_time.strftime(datefmt)
        return log_time.isoformat(timespec="seconds")


def configure_logging(log_dir: str, backup_days: int) -> None:
    log_path = Path(log_dir)
    if not log_path.is_absolute():
        log_path = Path.cwd() / log_path
    log_path.mkdir(parents=True, exist_ok=True)

    formatter = ShanghaiFormatter(LOG_FORMAT, DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = TimedRotatingFileHandler(
        log_path / "backend.log",
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
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
