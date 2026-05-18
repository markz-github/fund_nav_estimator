from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.index_mapping_source import FundIndexMappingSource
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

        mapping = self.get_mapping(normalized_code)
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
            mapping.index_code = snapshot.index_code
            mapping.index_name = snapshot.index_name
            mapping.benchmark_text = snapshot.benchmark_text
            mapping.source = snapshot.source
            mapping.confidence = snapshot.confidence

        self.db.commit()
        self.db.refresh(mapping)
        return mapping
