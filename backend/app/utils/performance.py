from __future__ import annotations

from functools import wraps
import logging
from time import perf_counter
from typing import Callable, TypeVar


F = TypeVar("F", bound=Callable)
logger = logging.getLogger("app.performance")


def timed(label: str | None = None):
    def decorator(func: F) -> F:
        metric_name = label or f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        def wrapper(*args, **kwargs):
            started_at = perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration_ms = (perf_counter() - started_at) * 1000
                logger.info("method=%s duration_ms=%.2f", metric_name, duration_ms)

        return wrapper  # type: ignore[return-value]

    return decorator
