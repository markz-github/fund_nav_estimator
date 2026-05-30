from __future__ import annotations

import re

from apscheduler.triggers.cron import CronTrigger


_CRON_WEEKDAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]


def _cron_weekday_number_to_name(value: int) -> str:
    if value == 7:
        value = 0
    if value < 0 or value > 6:
        raise ValueError("day_of_week must be between 0 and 7")
    return _CRON_WEEKDAY_NAMES[value]


def _expand_cron_weekday_range(start: int, end: int, step: int = 1) -> str:
    if step < 1:
        raise ValueError("day_of_week step must be greater than or equal to 1")
    if start == 7:
        start = 0
    if end == 7:
        end = 0
    if start > end:
        values = list(range(start, 7)) + list(range(0, end + 1))
    else:
        values = list(range(start, end + 1))
    return ",".join(_cron_weekday_number_to_name(value) for value in values[::step])


def _normalize_cron_weekday_field(value: str) -> str:
    parts: list[str] = []
    for raw_part in value.split(","):
        part = raw_part.strip().lower()
        if not part:
            raise ValueError("day_of_week contains an empty value")
        range_step = re.fullmatch(r"(\d+)-(\d+)/(\d+)", part)
        if range_step:
            parts.append(
                _expand_cron_weekday_range(
                    int(range_step.group(1)),
                    int(range_step.group(2)),
                    int(range_step.group(3)),
                )
            )
            continue
        weekday_range = re.fullmatch(r"(\d+)-(\d+)", part)
        if weekday_range:
            parts.append(_expand_cron_weekday_range(int(weekday_range.group(1)), int(weekday_range.group(2))))
            continue
        wildcard_step = re.fullmatch(r"\*/(\d+)", part)
        if wildcard_step:
            parts.append(_expand_cron_weekday_range(0, 6, int(wildcard_step.group(1))))
            continue
        number_step = re.fullmatch(r"(\d+)/(\d+)", part)
        if number_step:
            parts.append(_expand_cron_weekday_range(int(number_step.group(1)), 6, int(number_step.group(2))))
            continue
        if part.isdigit():
            parts.append(_cron_weekday_number_to_name(int(part)))
            continue
        parts.append(part)
    return ",".join(parts)


def normalize_cron_expression(value: str | None, default: str = "0 7 * * *") -> str:
    expression = (value or "").strip()
    if not expression:
        expression = default
    fields = expression.split()
    if len(fields) != 5:
        CronTrigger.from_crontab(expression)
        return expression
    fields[4] = _normalize_cron_weekday_field(fields[4])
    normalized = " ".join(fields)
    CronTrigger.from_crontab(normalized)
    return normalized
