from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.manual_fund_index_mapping import ManualFundIndexMapping
from app.modules.fund_nav.schemas.manual_index_mapping import ManualFundIndexMappingIn


class ManualIndexMappingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_mappings(self) -> list[ManualFundIndexMapping]:
        return list(
            self.db.scalars(
                select(ManualFundIndexMapping).order_by(ManualFundIndexMapping.fund_code.asc())
            ).all()
        )

    def get_mapping(self, fund_code: str) -> ManualFundIndexMapping | None:
        normalized_code = self._normalize_fund_code(fund_code)
        return self.db.scalar(
            select(ManualFundIndexMapping).where(ManualFundIndexMapping.fund_code == normalized_code)
        )

    def save_mapping(self, payload: ManualFundIndexMappingIn) -> ManualFundIndexMapping:
        normalized_code = self._normalize_fund_code(payload.fund_code)
        mapping = self.get_mapping(normalized_code)
        fund = self.db.scalar(select(Fund).where(Fund.fund_code == normalized_code))
        if mapping is None:
            mapping = ManualFundIndexMapping(fund_code=normalized_code)
            self.db.add(mapping)

        mapping.fund_name = self._clean(payload.fund_name) or (fund.fund_name if fund else None)
        mapping.index_code = self._clean(payload.index_code) or normalized_code
        mapping.index_name = self._clean(payload.index_name) or mapping.index_code
        mapping.benchmark_text = self._clean(payload.benchmark_text)
        mapping.remark = self._clean(payload.remark)
        self.db.commit()
        self.db.refresh(mapping)
        return mapping

    def delete_mapping(self, fund_code: str) -> bool:
        mapping = self.get_mapping(fund_code)
        if mapping is None:
            return False
        self.db.delete(mapping)
        self.db.commit()
        return True

    @staticmethod
    def _normalize_fund_code(fund_code: str) -> str:
        value = str(fund_code).strip()
        return value.zfill(6) if value.isdigit() else value

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None
