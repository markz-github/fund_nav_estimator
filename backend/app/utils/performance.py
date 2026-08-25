from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import logging
from time import perf_counter
from typing import Callable, TypeVar


F = TypeVar("F", bound=Callable)
logger = logging.getLogger("app.performance")
DEFAULT_SLOW_METHOD_THRESHOLD_MS = 500.0
_NO_SLOW_METHOD_THRESHOLD_OVERRIDE = object()
_slow_method_threshold_override: ContextVar[float | None | object] = ContextVar(
    "slow_method_threshold_override",
    default=_NO_SLOW_METHOD_THRESHOLD_OVERRIDE,
)


@contextmanager
def slow_method_threshold(threshold_ms: float | None):
    """Override the slow-method threshold; ``None`` disables method logs in this context."""

    token = _slow_method_threshold_override.set(threshold_ms)
    try:
        yield
    finally:
        _slow_method_threshold_override.reset(token)


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
                override = _slow_method_threshold_override.get()
                effective_threshold_ms = threshold_ms if override is _NO_SLOW_METHOD_THRESHOLD_OVERRIDE else override
                if effective_threshold_ms is not None and duration_ms >= effective_threshold_ms:
                    logger.warning(
                        "slow_method=%s duration_ms=%.2f threshold_ms=%.2f",
                        metric_name,
                        duration_ms,
                        effective_threshold_ms,
                    )

        return wrapper  # type: ignore[return-value]

    return decorator
