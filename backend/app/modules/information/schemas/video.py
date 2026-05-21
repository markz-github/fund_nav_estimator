from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.modules.information.status_enums import (
    NOTE_STATUSES,
    SOURCE_STATUSES,
    SUMMARY_DOCUMENT_STATUSES,
    TASK_STATUSES,
    VIDEO_STATUSES,
    source_status,
    status_label,
)


class StatusOptionOut(BaseModel):
    value: str
    label: str


class InformationStatusOptionsOut(BaseModel):
    source_statuses: list[StatusOptionOut]
    video_statuses: list[StatusOptionOut]
    note_statuses: list[StatusOptionOut]
    summary_document_statuses: list[StatusOptionOut]
    summary_types: list[StatusOptionOut]
    task_statuses: list[StatusOptionOut]
    fund_nav_task_types: list[StatusOptionOut]
    information_task_types: list[StatusOptionOut]


class VideoSourceCreate(BaseModel):
    platform: str = "bilibili"
    source_name: str
    source_url: str | None = None
    external_source_id: str
    remark: str | None = None


class VideoSourceUpdate(BaseModel):
    source_name: str | None = None
    source_url: str | None = None
    external_source_id: str | None = None
    enabled: int | None = None
    remark: str | None = None


class VideoSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    source_name: str
    source_url: str | None
    external_source_id: str
    enabled: int
    last_scanned_at: datetime | None
    remark: str | None
    video_count: int = 0
    note_count: int = 0
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def status(self) -> str:
        return source_status(self.enabled)

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(SOURCE_STATUSES, self.status)


class InformationSettingsOut(BaseModel):
    bilibili_cookie: str
    bilinote_base_url: str
    bilinote_provider_id: str
    bilinote_model_name: str
    bilinote_quality: str
    hermes_base_url: str
    hermes_auth_header_name: str
    hermes_api_key: str
    hermes_model: str
    hermes_run_path: str
    hermes_status_path_template: str
    hermes_summary_instruction: str
    hermes_daily_summary_instruction: str
    hermes_weekly_summary_instruction: str
    wechat_push_webhook_url: str
    wechat_push_token: str
    video_note_recent_days: str


class InformationSettingsUpdate(BaseModel):
    bilibili_cookie: str | None = None
    bilinote_base_url: str | None = None
    bilinote_provider_id: str | None = None
    bilinote_model_name: str | None = None
    bilinote_quality: str | None = None
    hermes_base_url: str | None = None
    hermes_auth_header_name: str | None = None
    hermes_api_key: str | None = None
    hermes_model: str | None = None
    hermes_run_path: str | None = None
    hermes_status_path_template: str | None = None
    hermes_summary_instruction: str | None = None
    hermes_daily_summary_instruction: str | None = None
    hermes_weekly_summary_instruction: str | None = None
    wechat_push_webhook_url: str | None = None
    wechat_push_token: str | None = None
    video_note_recent_days: str | None = None

    @field_validator("video_note_recent_days", mode="before")
    @classmethod
    def normalize_video_note_recent_days(cls, value):
        if value is None:
            return None
        return str(value)


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    platform: str
    external_video_id: str
    title: str
    video_url: str
    content_type: str
    author_name: str | None
    source_name: str | None
    published_at: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(VIDEO_STATUSES, self.status)


class ScanVideosRequest(BaseModel):
    source_ids: list[int] | None = None
    limit: int = 20


class GenerateVideoNotesRequest(BaseModel):
    video_ids: list[int] | None = None
    limit: int = 5


class MarkVideoNotesFailedRequest(BaseModel):
    video_ids: list[int]
    error_message: str | None = None


class GenerateSummaryFromNotesRequest(BaseModel):
    note_ids: list[int]
    title: str | None = None


class VideoNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_id: int
    video_title: str | None = None
    video_url: str | None = None
    video_published_at: datetime | None = None
    source_id: int | None = None
    source_name: str | None = None
    source_url: str | None = None
    provider: str
    external_task_id: str | None
    status: str
    note_text: str | None
    error_message: str | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(NOTE_STATUSES, self.status)


class VideoNoteDetailOut(VideoNoteOut):
    video_title: str | None = None
    video_url: str | None = None
    video_published_at: datetime | None = None
    video_platform: str | None = None
    video_external_id: str | None = None
    source_id: int | None = None
    source_name: str | None = None
    source_url: str | None = None


class VideoNoteRawResponseOut(BaseModel):
    id: int
    raw_response: str | None


class SummaryDocumentNoteOut(BaseModel):
    id: int
    video_id: int
    video_title: str | None = None
    video_url: str | None = None
    video_published_at: datetime | None = None
    source_id: int | None = None
    source_name: str | None = None
    source_url: str | None = None
    status: str
    generated_at: datetime | None = None

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(NOTE_STATUSES, self.status)


class SummaryDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    summary_type: str
    summary_date: date
    title: str
    status: str
    hermes_run_id: str | None
    document_text: str | None
    error_message: str | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    notes: list[SummaryDocumentNoteOut] = Field(default_factory=list)

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(SUMMARY_DOCUMENT_STATUSES, self.status)


class ActionResult(BaseModel):
    status: str
    message: str
    count: int = 0

    @computed_field
    @property
    def status_label(self) -> str:
        return status_label(TASK_STATUSES, self.status)
