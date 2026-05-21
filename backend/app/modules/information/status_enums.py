from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusOption:
    value: str
    label: str


SOURCE_STATUSES = (
    StatusOption("enabled", "启用"),
    StatusOption("disabled", "停用"),
)

VIDEO_STATUSES = (
    StatusOption("discovered", "已发现"),
    StatusOption("note_pending", "待生成笔记"),
    StatusOption("note_running", "笔记生成中"),
    StatusOption("note_done", "笔记已完成"),
    StatusOption("note_failed", "笔记失败"),
)

NOTE_STATUSES = (
    StatusOption("pending", "待提交"),
    StatusOption("running", "生成中"),
    StatusOption("done", "已完成"),
    StatusOption("failed", "失败"),
)

SUMMARY_DOCUMENT_STATUSES = (
    StatusOption("pending", "待提交"),
    StatusOption("running", "生成中"),
    StatusOption("done", "已完成"),
    StatusOption("failed", "失败"),
)

SUMMARY_TYPES = (
    StatusOption("manual", "手动汇总"),
    StatusOption("daily", "日汇总"),
    StatusOption("weekly", "周汇总"),
)

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

INFORMATION_TASK_TYPES = (
    StatusOption("scan_information_videos", "扫描信息流视频"),
    StatusOption("generate_information_video_notes", "处理信息源笔记"),
    StatusOption("submit_information_video_note_task", "提交信息源笔记任务"),
    StatusOption("poll_information_video_notes", "轮询信息源笔记任务"),
    StatusOption("generate_information_summary_documents", "生成信息流每日汇总"),
    StatusOption("generate_information_weekly_summary_documents", "生成信息流周汇总"),
    StatusOption("generate_information_custom_summary", "生成自定义视频笔记汇总"),
    StatusOption("retry_information_summary_document", "重试信息流汇总文档"),
    StatusOption("push_information_summary_documents", "推送信息流每日汇总"),
)


def status_options(options: tuple[StatusOption, ...]) -> list[dict[str, str]]:
    return [{"value": option.value, "label": option.label} for option in options]


def status_label(options: tuple[StatusOption, ...], status: str | None) -> str:
    if status is None:
        return ""
    labels = {option.value: option.label for option in options}
    return labels.get(status, status)


def source_status(enabled: int | bool | None) -> str:
    return "enabled" if enabled else "disabled"


def source_status_label(enabled: int | bool | None) -> str:
    return status_label(SOURCE_STATUSES, source_status(enabled))
