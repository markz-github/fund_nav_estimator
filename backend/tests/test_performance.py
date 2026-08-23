from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.utils.performance import timed


def test_timed_logs_only_calls_at_or_above_slow_threshold(caplog) -> None:
    @timed("fast", threshold_ms=100)
    def fast():
        return None

    @timed("slow", threshold_ms=100)
    def slow():
        return None

    with patch("app.utils.performance.perf_counter", side_effect=[0.0, 0.05, 1.0, 1.1]):
        fast()
        slow()

    assert "fast" not in caplog.text
    assert "slow_method=slow duration_ms=100.00 threshold_ms=100.00" in caplog.text
