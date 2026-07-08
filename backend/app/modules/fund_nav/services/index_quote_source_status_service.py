from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.index_quote_source_status import IndexQuoteSourceStatus


@dataclass(frozen=True)
class IndexQuoteSourceDefinition:
    source_key: str
    source_name: str
    source_type: str
    priority: int


DEFAULT_INDEX_QUOTE_SOURCES = (
    IndexQuoteSourceDefinition("eastmoney_http_spot", "东财 HTTP 实时指数", "index", 5),
    IndexQuoteSourceDefinition("eastmoney_spot", "东财 AkShare 实时指数", "index", 10),
    IndexQuoteSourceDefinition("sina_spot", "新浪 AkShare 实时指数", "index", 20),
    IndexQuoteSourceDefinition("sina_http_spot", "新浪 HTTP 实时指数", "index", 25),
    IndexQuoteSourceDefinition("tencent_spot", "腾讯 HTTP 实时指数", "index", 30),
    IndexQuoteSourceDefinition("xueqiu_spot", "雪球 HTTP 实时指数", "index", 40),
    IndexQuoteSourceDefinition("stock_zh_a_spot", "A 股 AkShare 实时行情", "stock", 10),
    IndexQuoteSourceDefinition("stock_zh_a_spot_em", "A 股东财 AkShare 实时行情", "stock", 20),
    IndexQuoteSourceDefinition("stock_hk_spot", "港股 AkShare 实时行情", "stock", 30),
    IndexQuoteSourceDefinition("stock_hk_spot_em", "港股东财 AkShare 实时行情", "stock", 40),
    IndexQuoteSourceDefinition("sina_quote", "新浪 HTTP 股票行情", "stock", 50),
    IndexQuoteSourceDefinition("stock_history_quote", "AkShare 历史行情兜底", "stock", 90),
    IndexQuoteSourceDefinition("fund_etf_spot_em", "ETF 东财 AkShare 实时行情", "etf", 10),
    IndexQuoteSourceDefinition("eastmoney_etf", "东财 HTTP ETF 行情", "etf", 20),
    IndexQuoteSourceDefinition("sina_etf_quote", "新浪 HTTP ETF 行情", "etf", 30),
    IndexQuoteSourceDefinition("etf_history_quote", "AkShare ETF 历史行情兜底", "etf", 90),
)
DEFAULT_INDEX_QUOTE_SOURCE_KEYS = {definition.source_key for definition in DEFAULT_INDEX_QUOTE_SOURCES}

SOURCE_TYPE_LABELS = {
    "index": "指数",
    "stock": "股票",
    "etf": "ETF",
    "realtime": "实时",
    "daily": "日线",
}
SOURCE_TYPE_ORDER = {"index": 0, "stock": 1, "etf": 2, "realtime": 3, "daily": 4}
COOLDOWN_FAILURES = 5
DISABLE_FAILURES = 20
COOLDOWN_MINUTES = 30


class IndexQuoteSourceStatusService:
    def __init__(self, db: Session | None) -> None:
        self.db = db

    def ordered_sources(self, source_type: str) -> list[IndexQuoteSourceStatus]:
        if self.db is None:
            return self._default_rows(source_type)
        self.seed_defaults()
        now = datetime.now()
        rows = list(
            self.db.scalars(
                select(IndexQuoteSourceStatus).where(
                    IndexQuoteSourceStatus.source_type == source_type,
                    IndexQuoteSourceStatus.enabled == 1,
                )
            ).all()
        )
        active_rows = [
            row
            for row in rows
            if row.auto_disabled_until is None or row.auto_disabled_until <= now
        ]
        return sorted(active_rows, key=self._sort_key)

    def list_statuses(self) -> list[dict[str, object]]:
        if self.db is None:
            return []
        self.seed_defaults()
        rows = self.db.scalars(
            select(IndexQuoteSourceStatus).where(IndexQuoteSourceStatus.source_key.in_(DEFAULT_INDEX_QUOTE_SOURCE_KEYS))
        ).all()
        return [self._status_out(row) for row in sorted(rows, key=self._sort_key)]

    def record_success(self, source_key: str) -> None:
        if self.db is None:
            return
        row = self._get_or_create(source_key)
        if row is None:
            return
        row.success_count = (row.success_count or 0) + 1
        row.consecutive_failures = 0
        row.auto_disabled_until = None
        row.last_success_at = datetime.now()
        row.last_error = None
        self.db.flush()

    def record_failure(self, source_key: str, error: str | None = None) -> None:
        if self.db is None:
            return
        row = self._get_or_create(source_key)
        if row is None:
            return
        row.failure_count = (row.failure_count or 0) + 1
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        row.last_failure_at = datetime.now()
        row.last_error = (error or "no quote matched")[:500]
        if row.consecutive_failures >= DISABLE_FAILURES:
            row.enabled = 0
        elif row.consecutive_failures >= COOLDOWN_FAILURES:
            row.auto_disabled_until = datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)
        self.db.flush()

    def seed_defaults(self) -> None:
        if self.db is None:
            return
        existing = {
            row.source_key: row
            for row in self.db.scalars(select(IndexQuoteSourceStatus)).all()
        }
        for definition in DEFAULT_INDEX_QUOTE_SOURCES:
            row = existing.get(definition.source_key)
            if row is None:
                self.db.add(
                    IndexQuoteSourceStatus(
                        source_key=definition.source_key,
                        source_name=definition.source_name,
                        source_type=definition.source_type,
                        priority=definition.priority,
                    )
                )
                continue
            row.source_name = definition.source_name
            row.source_type = definition.source_type
        self.db.flush()

    @staticmethod
    def _sort_key(row: IndexQuoteSourceStatus) -> tuple[int, float, int, str]:
        success_count = row.success_count or 0
        failure_count = row.failure_count or 0
        consecutive_failures = row.consecutive_failures or 0
        total = success_count + failure_count
        success_rate = (success_count / total) if total else 0.5
        effective_priority = row.priority - (success_rate * 100) + (consecutive_failures * 10)
        return (SOURCE_TYPE_ORDER.get(row.source_type, 99), effective_priority, row.priority, row.source_key)

    @classmethod
    def _effective_priority(cls, row: IndexQuoteSourceStatus) -> Decimal:
        sort_key = cls._sort_key(row)
        return Decimal(str(sort_key[1])).quantize(Decimal("0.0001"))

    @classmethod
    def _status_out(cls, row: IndexQuoteSourceStatus) -> dict[str, object]:
        success_count = row.success_count or 0
        failure_count = row.failure_count or 0
        total = success_count + failure_count
        success_rate = Decimal(success_count) / Decimal(total) if total else None
        failure_rate = Decimal(failure_count) / Decimal(total) if total else None
        now = datetime.now()
        if row.enabled != 1:
            status_label = "已禁用"
        elif row.auto_disabled_until is not None and row.auto_disabled_until > now:
            status_label = "冷却中"
        else:
            status_label = "启用"
        return {
            "id": row.id,
            "source_key": row.source_key,
            "source_name": row.source_name,
            "source_type": row.source_type,
            "source_type_label": SOURCE_TYPE_LABELS.get(row.source_type, row.source_type),
            "priority": row.priority,
            "enabled": row.enabled,
            "success_count": success_count,
            "failure_count": failure_count,
            "consecutive_failures": row.consecutive_failures or 0,
            "success_rate": success_rate.quantize(Decimal("0.0001")) if success_rate is not None else None,
            "failure_rate": failure_rate.quantize(Decimal("0.0001")) if failure_rate is not None else None,
            "effective_priority": cls._effective_priority(row),
            "auto_disabled_until": row.auto_disabled_until,
            "last_success_at": row.last_success_at,
            "last_failure_at": row.last_failure_at,
            "last_error": row.last_error,
            "status_label": status_label,
        }

    def _get_or_create(self, source_key: str) -> IndexQuoteSourceStatus | None:
        definition = next(
            (item for item in DEFAULT_INDEX_QUOTE_SOURCES if item.source_key == source_key),
            None,
        )
        if definition is None or self.db is None:
            return None
        row = self.db.scalar(
            select(IndexQuoteSourceStatus).where(IndexQuoteSourceStatus.source_key == source_key)
        )
        if row is not None:
            return row
        row = IndexQuoteSourceStatus(
            source_key=definition.source_key,
            source_name=definition.source_name,
            source_type=definition.source_type,
            priority=definition.priority,
        )
        self.db.add(row)
        self.db.flush()
        return row

    @staticmethod
    def _default_rows(source_type: str) -> list[IndexQuoteSourceStatus]:
        return [
            IndexQuoteSourceStatus(
                source_key=definition.source_key,
                source_name=definition.source_name,
                source_type=definition.source_type,
                priority=definition.priority,
            )
            for definition in DEFAULT_INDEX_QUOTE_SOURCES
            if definition.source_type == source_type
        ]


def seed_default_index_quote_source_statuses(db: Session) -> None:
    IndexQuoteSourceStatusService(db).seed_defaults()
