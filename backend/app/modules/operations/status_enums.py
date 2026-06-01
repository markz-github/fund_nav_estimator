from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusOption:
    value: str
    label: str


TASK_STATUSES = (
    StatusOption("running", "运行中"),
    StatusOption("success", "成功"),
    StatusOption("partial", "部分成功"),
    StatusOption("failed", "失败"),
    StatusOption("skipped", "跳过"),
)

FUND_NAV_TASK_TYPES = (
    StatusOption("refresh_nav", "刷新基金官方净值"),
    StatusOption("refresh_profile", "刷新基金名称和类型"),
    StatusOption("refresh_holding", "刷新基金持仓"),
    StatusOption("refresh_quote", "刷新持仓资产行情"),
    StatusOption("estimate_nav", "估算基金当日净值"),
)


def status_label(options: tuple[StatusOption, ...], status: str | None) -> str:
    if status is None:
        return ""
    labels = {option.value: option.label for option in options}
    return labels.get(status, status)
