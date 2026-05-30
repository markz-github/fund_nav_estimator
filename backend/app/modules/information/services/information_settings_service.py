from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.information.models.bilinote_extra_template import InformationBilinoteExtraTemplate
from app.modules.information.models.information_setting import InformationSetting
from app.modules.information.models.summary_document_template import InformationSummaryDocumentTemplate

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
    "wechat_push_webhook_url": "",
    "wechat_push_token": "",
    "video_note_recent_days": "3",
    "video_source_scan_jitter_min_seconds": "1",
    "video_source_scan_jitter_max_seconds": "3",
}
BILINOTE_QUALITY_OPTIONS = {"fast", "medium", "slow"}
NON_NEGATIVE_NUMBER_SETTINGS = {
    "video_source_scan_jitter_min_seconds",
    "video_source_scan_jitter_max_seconds",
}


class InformationSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_settings(self) -> dict[str, object]:
        rows = self.db.scalars(select(InformationSetting)).all()
        values: dict[str, object] = DEFAULT_SETTINGS.copy()
        values.update({row.setting_key: row.setting_value for row in rows})
        if values.get("hermes_base_url") == "http://192.168.50.50:9119":
            values["hermes_base_url"] = "http://192.168.50.50:8642"
        if values.get("hermes_run_path") == "/api/runs":
            values["hermes_run_path"] = "/v1/runs"
        if values.get("hermes_status_path_template") == "/api/runs/{run_id}":
            values["hermes_status_path_template"] = "/v1/runs/{run_id}"
        values["bilinote_extra_templates"] = self._bilinote_extra_templates()
        values["hermes_summary_document_templates"] = self._summary_document_templates()
        return values

    def update_settings(self, values: dict[str, object | None]) -> dict[str, object]:
        bilinote_extra_values = values.get("bilinote_extra_templates")
        template_values = values.get("hermes_summary_document_templates")
        self._validate_scan_jitter_range(values)
        for key, value in values.items():
            if value is None or key not in DEFAULT_SETTINGS:
                continue
            if key == "bilinote_quality":
                quality = str(value).strip()
                if quality not in BILINOTE_QUALITY_OPTIONS:
                    raise ValueError("bilinote_quality must be one of: fast, medium, slow")
                value = quality
            if key in NON_NEGATIVE_NUMBER_SETTINGS:
                value = self._normalize_non_negative_number(key, value)
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
        if bilinote_extra_values is not None:
            self._update_bilinote_extra_templates(bilinote_extra_values)
        if template_values is not None:
            self._update_summary_document_templates(template_values)
        self.db.commit()
        return self.get_settings()

    def scan_jitter_range_seconds(self, settings: dict[str, object] | None = None) -> tuple[float, float]:
        values = settings or self.get_settings()
        minimum = self._number_value(values.get("video_source_scan_jitter_min_seconds"), 1.0)
        maximum = self._number_value(values.get("video_source_scan_jitter_max_seconds"), 3.0)
        if maximum < minimum:
            maximum = minimum
        return minimum, maximum

    @classmethod
    def _normalize_non_negative_number(cls, key: str, value: object) -> str:
        number = cls._number_value(value, 0.0)
        if number < 0:
            raise ValueError(f"{key} must be greater than or equal to 0")
        return f"{number:g}"

    @classmethod
    def _number_value(cls, value: object, default: float) -> float:
        text = str(value if value is not None else "").strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"{text} is not a valid number") from exc

    def _validate_scan_jitter_range(self, incoming_values: dict[str, object | None]) -> None:
        current = self.get_settings()
        minimum = self._number_value(
            incoming_values.get("video_source_scan_jitter_min_seconds", current.get("video_source_scan_jitter_min_seconds")),
            1.0,
        )
        maximum = self._number_value(
            incoming_values.get("video_source_scan_jitter_max_seconds", current.get("video_source_scan_jitter_max_seconds")),
            3.0,
        )
        if maximum < minimum:
            raise ValueError("video_source_scan_jitter_max_seconds must be greater than or equal to min seconds")

    def bilinote_extras_for_category(self, category: str | None) -> str:
        lookup_category = str(category or "").strip()
        if not lookup_category:
            return ""
        return (
            self.db.scalar(
                select(InformationBilinoteExtraTemplate.extras).where(
                    InformationBilinoteExtraTemplate.category == lookup_category,
                    InformationBilinoteExtraTemplate.extras != "",
                )
            )
            or ""
        )

    def _bilinote_extra_templates(self) -> list[dict[str, str]]:
        rows = list(
            self.db.scalars(
                select(InformationBilinoteExtraTemplate).order_by(InformationBilinoteExtraTemplate.category.asc())
            ).all()
        )
        return [
            {
                "category": row.category,
                "extras": row.extras,
            }
            for row in rows
        ]

    def _update_bilinote_extra_templates(self, values: object) -> None:
        if not isinstance(values, list):
            return
        for item in values:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "").strip()
            extras = str(item.get("extras") or "")
            if not category:
                continue
            row = self.db.scalar(
                select(InformationBilinoteExtraTemplate)
                .where(InformationBilinoteExtraTemplate.category == category)
                .execution_options(include_deleted=True)
            )
            if row is None:
                self.db.add(
                    InformationBilinoteExtraTemplate(
                        category=category,
                        extras=extras,
                    )
                )
            else:
                row.is_deleted = 0
                row.extras = extras

    def _summary_document_templates(self) -> list[dict[str, str]]:
        rows = list(
            self.db.scalars(
                select(InformationSummaryDocumentTemplate).order_by(InformationSummaryDocumentTemplate.category.asc())
            ).all()
        )
        return [
            {
                "category": row.category,
                "summary_instruction": row.summary_instruction,
                "template_text": row.template_text,
            }
            for row in rows
        ]

    def _update_summary_document_templates(self, values: object) -> None:
        if not isinstance(values, list):
            return
        for item in values:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "").strip()
            summary_instruction = str(item.get("summary_instruction") or "")
            template_text = str(item.get("template_text") or "")
            if not category:
                continue
            row = self.db.scalar(
                select(InformationSummaryDocumentTemplate)
                .where(InformationSummaryDocumentTemplate.category == category)
                .execution_options(include_deleted=True)
            )
            if row is None:
                self.db.add(
                    InformationSummaryDocumentTemplate(
                        category=category,
                        summary_instruction=summary_instruction,
                        template_text=template_text,
                    )
                )
            else:
                row.is_deleted = 0
                row.summary_instruction = summary_instruction
                row.template_text = template_text
