from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fund_nav.data_sources.akshare.index_catalog_source import IndexCatalogSource, MarketIndexSnapshot
from app.modules.fund_nav.models.market_index import MarketIndex
from app.utils.performance import timed


class IndexCatalogService:
    def __init__(self, db: Session, source: IndexCatalogSource | None = None) -> None:
        self.db = db
        self.source = source or IndexCatalogSource()

    @timed()
    def refresh_indexes(self) -> list[MarketIndex]:
        snapshots = self.source.get_indexes()
        indexes = [self._upsert_snapshot(snapshot) for snapshot in snapshots]
        self.db.commit()
        for index in indexes:
            self.db.refresh(index)
        return indexes

    def resolve_index(self, index_name: str | None) -> MarketIndex | None:
        cleaned_name = self._clean_name(index_name)
        if not cleaned_name:
            return None

        preferred_provider = self._preferred_provider(cleaned_name)
        if preferred_provider:
            exact = self._exact_match(cleaned_name, preferred_provider)
            if exact is not None:
                return exact

        if preferred_provider is None:
            exact = self._exact_match(cleaned_name)
            if exact is not None:
                return exact

        normalized_target = self._normalize_index_name(cleaned_name)
        if not normalized_target:
            return None

        candidates = self.db.scalars(select(MarketIndex)).all()
        if preferred_provider:
            preferred_match = self._best_match(
                normalized_target,
                [candidate for candidate in candidates if candidate.provider == preferred_provider],
            )
            return preferred_match

        return self._best_match(normalized_target, candidates)

    def _exact_match(self, cleaned_name: str, provider: str | None = None) -> MarketIndex | None:
        statement = select(MarketIndex).where(
            (MarketIndex.index_name == cleaned_name)
            | (MarketIndex.index_short_name == cleaned_name)
        )
        if provider is not None:
            statement = statement.where(MarketIndex.provider == provider)
        return self.db.scalar(statement.limit(1))

    @classmethod
    def _best_match(cls, normalized_target: str, candidates: list[MarketIndex]) -> MarketIndex | None:
        for candidate in candidates:
            if cls._normalized_match(normalized_target, candidate):
                return candidate
        return None

    def _upsert_snapshot(self, snapshot: MarketIndexSnapshot) -> MarketIndex:
        index = self.db.scalar(
            select(MarketIndex)
            .where(
                MarketIndex.provider == snapshot.provider,
                MarketIndex.index_code == snapshot.index_code,
            )
            .execution_options(include_deleted=True)
        )
        if index is None:
            index = MarketIndex(
                provider=snapshot.provider,
                index_code=snapshot.index_code,
                index_name=snapshot.index_name,
                index_short_name=snapshot.index_short_name,
                currency=snapshot.currency,
                asset_class=snapshot.asset_class,
                source=snapshot.source,
                raw_snapshot=snapshot.raw_snapshot,
            )
            self.db.add(index)
        else:
            index.index_name = snapshot.index_name
            index.index_short_name = snapshot.index_short_name
            index.currency = snapshot.currency
            index.asset_class = snapshot.asset_class
            index.source = snapshot.source
            index.raw_snapshot = snapshot.raw_snapshot
        return index

    @classmethod
    def _normalized_match(cls, normalized_target: str, candidate: MarketIndex) -> bool:
        normalized_names = [
            cls._normalize_index_name(candidate.index_name),
            cls._normalize_index_name(candidate.index_short_name),
        ]
        normalized_names = [name for name in normalized_names if name]
        return normalized_target in normalized_names

    @staticmethod
    def _preferred_provider(value: str) -> str | None:
        if value.startswith("中证"):
            return "csindex"
        if value.startswith("国证"):
            return "cni"
        return None


    @staticmethod
    def _clean_name(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = re.sub(r"\s+", "", value).strip("：:，,。;；")
        return cleaned or None

    @classmethod
    def _normalize_index_name(cls, value: str | None) -> str:
        cleaned = cls._clean_name(value)
        if not cleaned:
            return ""
        normalized = cleaned.upper()
        normalized = re.sub(r"(人民币|港元|美元|全收益|净收益|价格|收益率|指数)+", "", normalized)
        normalized = re.sub(r"^(中证|国证|深证|上证)", "", normalized)
        normalized = re.sub(r"[^0-9A-Z\u4e00-\u9fa5]+", "", normalized)
        return normalized
