from __future__ import annotations

from functools import wraps
import logging
from time import perf_counter
from typing import Callable, TypeVar


F = TypeVar("F", bound=Callable)
logger = logging.getLogger("app.performance")
DEFAULT_SLOW_METHOD_THRESHOLD_MS = 500.0


def timed(label: str | None = None, *, threshold_ms: float = DEFAULT_SLOW_METHOD_THRESHOLD_MS):
    """Log only method calls that exceed the configured slow-call threshold."""

    def decorator(func: F) -> F:
        metric_name = label or f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        def wrapper(*args, **kwargs):
            started_at = perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration_ms = (perf_counter() - started_at) * 1000
                if duration_ms >= threshold_ms:
                    logger.warning(
                        "slow_method=%s duration_ms=%.2f threshold_ms=%.2f",
                        metric_name,
                        duration_ms,
                        threshold_ms,
                    )

        return wrapper  # type: ignore[return-value]

    return decorator
