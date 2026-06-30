from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusOption:
    value: str
    label: str


TASK_STATUSES = (
    StatusOption("pending", "待执行"),
    StatusOption("running", "运行中"),
    StatusOption("success", "成功"),
    StatusOption("partial", "部分成功"),
    StatusOption("failed", "失败"),
    StatusOption("skipped", "跳过"),
)

FUND_NAV_TASK_TYPES = (
    StatusOption("create_fund", "新增自选基金"),
    StatusOption("refresh_nav", "刷新基金官方净值"),
    StatusOption("check_nav_quality", "检查基金官方净值新鲜度"),
    StatusOption("refresh_profile", "刷新基金名称和类型"),
    StatusOption("refresh_index_catalog", "刷新指数目录"),
    StatusOption("refresh_holding", "刷新基金持仓"),
    StatusOption("refresh_quote", "刷新持仓资产行情"),
    StatusOption("estimate_nav", "估算基金当日净值"),
    StatusOption("refresh_quote_estimate", "刷新行情并估算"),
    StatusOption("refresh_index_mapping", "刷新基金指数映射"),
    StatusOption("sync_new_fund_data", "新增基金后同步数据"),
)


def status_options(options: tuple[StatusOption, ...]) -> list[dict[str, str]]:
    return [{"value": option.value, "label": option.label} for option in options]


def status_label(options: tuple[StatusOption, ...], status: str | None) -> str:
    if status is None:
        return ""
    labels = {option.value: option.label for option in options}
    return labels.get(status, status)
