from __future__ import annotations

import logging
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.utils.request_logging import request_log_level


def test_request_log_level_ignores_normal_requests() -> None:
    assert request_log_level(200, 499.99) is None
    assert request_log_level(302, 1) is None


def test_request_log_level_reports_slow_and_failed_requests() -> None:
    assert request_log_level(200, 500) == logging.WARNING
    assert request_log_level(404, 1) == logging.WARNING
    assert request_log_level(500, 1) == logging.ERROR
