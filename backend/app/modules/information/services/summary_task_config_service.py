from __future__ import annotations

from app.modules.information.services.common import *


class SummaryTaskConfigService(InformationServiceBase):
    def list_summary_task_configs(self) -> list[InformationSummaryTaskConfig]:
        return list(
            self.db.scalars(
                select(InformationSummaryTaskConfig).order_by(
                    InformationSummaryTaskConfig.enabled.desc(),
                    InformationSummaryTaskConfig.id.asc(),
                )
            ).all()
        )

    def create_summary_task_config(self, payload: SummaryTaskConfigCreate) -> InformationSummaryTaskConfig:
        task_name = payload.task_name.strip() or "信息流汇总任务"
        category = normalize_category(payload.category)
        config = InformationSummaryTaskConfig(
            task_name=task_name,
            platform=(payload.platform or "bilibili").strip().lower(),
            category=category,
            start_days_before=_normalize_start_days_before(payload.start_days_before),
            cron_expression=normalize_cron_expression(payload.cron_expression),
            title_template=_normalize_title_template(payload.title_template),
            summary_instruction=_normalize_instruction(payload.summary_instruction),
            document_template=(
                self._default_document_template(category)
                if payload.document_template is None
                else _normalize_document_template(payload.document_template)
            ),
            push_to_wechat=1 if payload.push_to_wechat else 0,
            enabled=1 if payload.enabled else 0,
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_summary_task_config(
        self,
        config_id: int,
        payload: SummaryTaskConfigUpdate,
    ) -> InformationSummaryTaskConfig | None:
        config = self.db.get(InformationSummaryTaskConfig, config_id)
        if config is None:
            return None
        if payload.task_name is not None:
            config.task_name = payload.task_name.strip() or config.task_name
        if payload.platform is not None:
            config.platform = (payload.platform or "bilibili").strip().lower()
        if payload.category is not None:
            config.category = normalize_category(payload.category)
        if payload.start_days_before is not None:
            config.start_days_before = _normalize_start_days_before(payload.start_days_before)
        if payload.cron_expression is not None:
            config.cron_expression = normalize_cron_expression(payload.cron_expression)
        if payload.title_template is not None:
            config.title_template = _normalize_title_template(payload.title_template)
        if payload.summary_instruction is not None:
            config.summary_instruction = _normalize_instruction(payload.summary_instruction)
        if payload.document_template is not None:
            config.document_template = _normalize_document_template(payload.document_template)
        if payload.push_to_wechat is not None:
            config.push_to_wechat = 1 if payload.push_to_wechat else 0
        if payload.enabled is not None:
            config.enabled = 1 if payload.enabled else 0
        self.db.commit()
        self.db.refresh(config)
        return config

    def delete_summary_task_config(self, config_id: int) -> bool:
        config = self.db.get(InformationSummaryTaskConfig, config_id)
        if config is None:
            return False
        self.db.delete(config)
        self.db.commit()
        return True

    def _default_document_template(self, category: str) -> str:
        return (
            self.db.scalar(
                select(InformationSummaryDocumentTemplate.template_text).where(
                    InformationSummaryDocumentTemplate.category == normalize_category(category),
                )
            )
            or ""
        )
