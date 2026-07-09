from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.index_quote_source_status import IndexQuoteSourceStatus


@dataclass(frozen=True)
class IndexQuoteSourceDefinition:
    source_key: str
    source_name: str
    source_type: str
    priority: int
    description: str
    exclude_rule_type: str = "none"
    exclude_rule_value: str | None = None


DEFAULT_INDEX_QUOTE_SOURCES = (
    IndexQuoteSourceDefinition("eastmoney_http_spot", "东财 HTTP 实时指数", "index", 5, "覆盖中证 9xxxxx、深证 399xxx、上证 000xxx 等实时指数，优先用于中证主题指数。"),
    IndexQuoteSourceDefinition("eastmoney_spot", "东财 AkShare 实时指数", "index", 10, "通过 AkShare 东财指数分组接口获取实时指数，覆盖深证、中证、沪深重要、上证系列。"),
    IndexQuoteSourceDefinition("sina_spot", "新浪 AkShare 实时指数", "index", 20, "通过 AkShare 新浪指数实时表获取，作为东财源未命中后的补充。"),
    IndexQuoteSourceDefinition("sina_http_spot", "新浪 HTTP 实时指数", "index", 25, "直接请求新浪简版行情，适合常见上证、深证指数；已知不覆盖中证 9xxxxx 主题指数，调度时会跳过。", "regex", "^9"),
    IndexQuoteSourceDefinition("tencent_spot", "腾讯 HTTP 实时指数", "index", 30, "直接请求腾讯简版行情，适合常见上证、深证指数；已知不覆盖大量中证 9xxxxx 主题指数，调度时会跳过。", "regex", "^9"),
    IndexQuoteSourceDefinition("xueqiu_spot", "雪球 HTTP 实时指数", "index", 40, "直接请求雪球实时行情，适合常见上证、深证指数；已知不覆盖中证 9xxxxx 主题指数，调度时会跳过。", "regex", "^9"),
    IndexQuoteSourceDefinition("stock_zh_a_spot", "A 股 AkShare 实时行情", "stock", 10, "AkShare A 股实时行情主源。"),
    IndexQuoteSourceDefinition("stock_zh_a_spot_em", "A 股东财 AkShare 实时行情", "stock", 20, "AkShare 东财 A 股实时行情补充源。"),
    IndexQuoteSourceDefinition("stock_hk_spot", "港股 AkShare 实时行情", "stock", 30, "AkShare 港股实时行情主源。"),
    IndexQuoteSourceDefinition("stock_hk_spot_em", "港股东财 AkShare 实时行情", "stock", 40, "AkShare 东财港股实时行情补充源。"),
    IndexQuoteSourceDefinition("sina_quote", "新浪 HTTP 股票行情", "stock", 50, "新浪 HTTP 个股行情兜底。"),
    IndexQuoteSourceDefinition("stock_history_quote", "AkShare 历史行情兜底", "stock", 90, "股票历史行情兜底，仅在实时行情缺失时使用。"),
    IndexQuoteSourceDefinition("fund_etf_spot_em", "ETF 东财 AkShare 实时行情", "etf", 10, "AkShare 东财 ETF 实时行情主源。"),
    IndexQuoteSourceDefinition("eastmoney_etf", "东财 HTTP ETF 行情", "etf", 20, "东财 HTTP ETF 单标的行情兜底。"),
    IndexQuoteSourceDefinition("sina_etf_quote", "新浪 HTTP ETF 行情", "etf", 30, "新浪 HTTP ETF 行情兜底。"),
    IndexQuoteSourceDefinition("etf_history_quote", "AkShare ETF 历史行情兜底", "etf", 90, "ETF 历史行情兜底，仅在实时行情缺失时使用。"),
)
DEFAULT_INDEX_QUOTE_SOURCE_KEYS = {definition.source_key for definition in DEFAULT_INDEX_QUOTE_SOURCES}
DEFAULT_INDEX_QUOTE_SOURCE_DESCRIPTIONS = {
    definition.source_key: definition.description for definition in DEFAULT_INDEX_QUOTE_SOURCES
}
EXCLUDE_RULE_TYPES = {"none", "regex", "enum"}

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
                        source_description=definition.description,
                        source_type=definition.source_type,
                        exclude_rule_type=definition.exclude_rule_type,
                        exclude_rule_value=definition.exclude_rule_value,
                        priority=definition.priority,
                    )
                )
                continue
            row.source_name = definition.source_name
            row.source_description = definition.description
            row.source_type = definition.source_type
            if not row.exclude_rule_type or row.exclude_rule_type == "none" and not row.exclude_rule_value:
                row.exclude_rule_type = definition.exclude_rule_type
                row.exclude_rule_value = definition.exclude_rule_value
        self.db.flush()

    def update_rules(
        self,
        source_key: str,
        *,
        source_description: str | None = None,
        exclude_rule_type: str = "none",
        exclude_rule_value: str | None = None,
    ) -> dict[str, object]:
        if self.db is None:
            raise ValueError("Database session is required")
        row = self._get_or_create(source_key)
        if row is None:
            raise LookupError(f"Unknown source: {source_key}")
        rule_type = (exclude_rule_type or "none").strip().lower()
        rule_value = (exclude_rule_value or "").strip()
        self._validate_exclude_rule(rule_type, rule_value)
        row.source_description = (source_description or "").strip()[:1000] or None
        row.exclude_rule_type = rule_type
        row.exclude_rule_value = rule_value[:1000] if rule_type != "none" else None
        self.db.flush()
        return self._status_out(row)

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
            "source_description": row.source_description or DEFAULT_INDEX_QUOTE_SOURCE_DESCRIPTIONS.get(row.source_key, ""),
            "source_type": row.source_type,
            "source_type_label": SOURCE_TYPE_LABELS.get(row.source_type, row.source_type),
            "exclude_rule_type": row.exclude_rule_type or "none",
            "exclude_rule_value": row.exclude_rule_value,
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

    @staticmethod
    def _validate_exclude_rule(rule_type: str, rule_value: str) -> None:
        if rule_type not in EXCLUDE_RULE_TYPES:
            raise ValueError("exclude_rule_type must be one of none, regex, enum")
        if rule_type == "none":
            return
        if not rule_value:
            raise ValueError("exclude_rule_value is required")
        if rule_type == "regex":
            try:
                re.compile(rule_value)
            except re.error as exc:
                raise ValueError(f"Invalid regex exclude rule: {exc}") from exc

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
            source_description=definition.description,
            source_type=definition.source_type,
            exclude_rule_type=definition.exclude_rule_type,
            exclude_rule_value=definition.exclude_rule_value,
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
                source_description=definition.description,
                source_type=definition.source_type,
                exclude_rule_type=definition.exclude_rule_type,
                exclude_rule_value=definition.exclude_rule_value,
                priority=definition.priority,
            )
            for definition in DEFAULT_INDEX_QUOTE_SOURCES
            if definition.source_type == source_type
        ]


def seed_default_index_quote_source_statuses(db: Session) -> None:
    IndexQuoteSourceStatusService(db).seed_defaults()
