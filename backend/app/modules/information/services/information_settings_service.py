from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.information.models.information_setting import InformationSetting


DEFAULT_SETTINGS: dict[str, str] = {
    "bilibili_cookie": "",
    "article_filter_keywords": "",
    "bilinote_base_url": "http://192.168.50.50:18483",
    "bilinote_provider_id": "",
    "bilinote_model_name": "",
    "bilinote_quality": "fast",
    "hermes_base_url": "http://192.168.50.50:8642",
    "hermes_auth_header_name": "Authorization",
    "hermes_api_key": "",
    "hermes_model": "hermes-agent",
    "hermes_run_path": "/v1/runs",
    "hermes_status_path_template": "/v1/runs/{run_id}",
    "hermes_summary_instruction": "",
    "hermes_daily_summary_instruction": "",
    "hermes_weekly_summary_instruction": "",
    "wechat_push_webhook_url": "",
    "wechat_push_token": "",
    "video_note_recent_days": "3",
}


class InformationSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_settings(self) -> dict[str, str]:
        rows = self.db.scalars(select(InformationSetting)).all()
        values = DEFAULT_SETTINGS.copy()
        values.update({row.setting_key: row.setting_value for row in rows})
        if values.get("hermes_base_url") == "http://192.168.50.50:9119":
            values["hermes_base_url"] = "http://192.168.50.50:8642"
        if values.get("hermes_run_path") == "/api/runs":
            values["hermes_run_path"] = "/v1/runs"
        if values.get("hermes_status_path_template") == "/api/runs/{run_id}":
            values["hermes_status_path_template"] = "/v1/runs/{run_id}"
        return values

    def update_settings(self, values: dict[str, str | None]) -> dict[str, str]:
        for key, value in values.items():
            if value is None or key not in DEFAULT_SETTINGS:
                continue
            row = self.db.scalar(
                select(InformationSetting)
                .where(InformationSetting.setting_key == key)
                .execution_options(include_deleted=True)
            )
            if row is None:
                self.db.add(InformationSetting(setting_key=key, setting_value=str(value)))
            else:
                row.is_deleted = 0
                row.setting_value = str(value)
        self.db.commit()
        return self.get_settings()
