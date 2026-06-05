from __future__ import annotations

from datetime import date


def latest_completed_quarter_period(today: date | None = None) -> str:
    value = today or date.today()
    current_quarter = (value.month - 1) // 3 + 1
    if current_quarter == 1:
        return f"{value.year - 1}Q4"
    return f"{value.year}Q{current_quarter - 1}"
