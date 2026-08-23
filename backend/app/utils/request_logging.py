from __future__ import annotations

import logging


DEFAULT_SLOW_REQUEST_THRESHOLD_MS = 500.0


def request_log_level(
    status_code: int,
    duration_ms: float,
    *,
    slow_threshold_ms: float = DEFAULT_SLOW_REQUEST_THRESHOLD_MS,
) -> int | None:
    """Return a log level only for failed or slow HTTP requests."""

    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400 or duration_ms >= slow_threshold_ms:
        return logging.WARNING
    return None
