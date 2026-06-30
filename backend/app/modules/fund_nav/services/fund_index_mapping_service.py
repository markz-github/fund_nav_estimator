from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.index_mapping_source import FundIndexMappingSource
from app.modules.fund_nav.models.fund import Fund
from app.modules.fund_nav.models.fund_index_mapping import FundIndexMapping
from app.utils.performance import timed


class FundIndexMappingService:
    def __init__(self, db: Session, source: FundIndexMappingSource | None = None) -> None:
        self.db = db
        self.source = source or FundIndexMappingSource()

    @timed()
    def get_mapping(self, fund_code: str) -> FundIndexMapping | None:
        normalized_code = str(fund_code).strip().zfill(6)
        return self.db.scalar(
            select(FundIndexMapping).where(FundIndexMapping.fund_code == normalized_code)
        )

    @timed()
    def refresh_mapping(self, fund_code: str) -> FundIndexMapping | None:
        normalized_code = str(fund_code).strip().zfill(6)
        snapshot = self.source.get_mapping(normalized_code)
        if snapshot is None:
            return None

        mapping = self.db.scalar(
            select(FundIndexMapping)
            .where(FundIndexMapping.fund_code == normalized_code)
            .execution_options(include_deleted=True)
        )
        if mapping is None:
            mapping = FundIndexMapping(
                fund_code=normalized_code,
                index_code=snapshot.index_code,
                index_name=snapshot.index_name,
                benchmark_text=snapshot.benchmark_text,
                source=snapshot.source,
                confidence=snapshot.confidence,
            )
            self.db.add(mapping)
        else:
            mapping.is_deleted = 0
            mapping.index_code = snapshot.index_code
            mapping.index_name = snapshot.index_name
            mapping.benchmark_text = snapshot.benchmark_text
            mapping.source = snapshot.source
            mapping.confidence = snapshot.confidence

        self.db.commit()
        self.db.refresh(mapping)
        return mapping

    @timed()
    def refresh_mappings_for_index_related_funds(self, fund_codes: list[str] | None = None) -> list[FundIndexMapping]:
        normalized_codes = (
            sorted({str(code).strip().zfill(6) for code in fund_codes if str(code).strip()})
            if fund_codes
            else None
        )
        statement = select(Fund).where(Fund.enabled == 1)
        if normalized_codes:
            statement = statement.where(Fund.fund_code.in_(normalized_codes))

        refreshed: list[FundIndexMapping] = []
        for fund in self.db.scalars(statement).all():
            if not self._is_index_related_fund(fund):
                continue
            mapping = self.refresh_mapping(fund.fund_code)
            if mapping is not None:
                refreshed.append(mapping)
        return refreshed

    @staticmethod
    def _is_index_related_fund(fund: Fund) -> bool:
        fund_name = (fund.fund_name or "").upper()
        fund_type = (fund.fund_type or "").upper()
        return "指数" in (fund.fund_type or "") or "ETF" in fund_name or "ETF" in fund_type
