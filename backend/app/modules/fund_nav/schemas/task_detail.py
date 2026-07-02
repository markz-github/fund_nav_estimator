from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, computed_field


class EstimateStrategyKey(str, Enum):
    ETF_QUOTE = "etf_quote"
    ETF_IOPV = "etf_iopv"
    INDEX_TRACKING = "index_tracking"
    HOLDING_WEIGHTED = "holding_weighted"


class EstimateResultKey(str, Enum):
    SUCCESS = "success"
    MISSING_NAV = "missing_nav"
    STALE_NAV = "stale_nav"
    MISSING_INDEX_MAPPING = "missing_index_mapping"
    MISSING_INDEX_QUOTE = "missing_index_quote"
    STALE_INDEX_QUOTE = "stale_index_quote"
    MISSING_HOLDINGS = "missing_holdings"
    ZERO_HOLDING_RATIO = "zero_holding_ratio"
    MISSING_QUOTES = "missing_quotes"
    MISSING_ETF_QUOTE = "missing_etf_quote"
    UNKNOWN = "unknown"


STRATEGY_LABELS = {
    EstimateStrategyKey.ETF_QUOTE.value: "ETF 实时价格",
    EstimateStrategyKey.ETF_IOPV.value: "ETF IOPV",
    EstimateStrategyKey.INDEX_TRACKING.value: "指数法",
    EstimateStrategyKey.HOLDING_WEIGHTED.value: "持仓法",
}

RESULT_LABELS = {
    EstimateResultKey.SUCCESS.value: "成功",
    EstimateResultKey.MISSING_NAV.value: "缺少官方净值",
    EstimateResultKey.STALE_NAV.value: "官方净值滞后",
    EstimateResultKey.MISSING_INDEX_MAPPING.value: "缺少跟踪指数映射",
    EstimateResultKey.MISSING_INDEX_QUOTE.value: "缺少指数行情",
    EstimateResultKey.STALE_INDEX_QUOTE.value: "指数行情滞后",
    EstimateResultKey.MISSING_HOLDINGS.value: "缺少持仓",
    EstimateResultKey.ZERO_HOLDING_RATIO.value: "持仓比例为 0",
    EstimateResultKey.MISSING_QUOTES.value: "缺少可用行情",
    EstimateResultKey.MISSING_ETF_QUOTE.value: "缺少 ETF 行情",
    EstimateResultKey.UNKNOWN.value: "未知原因",
}

STATUS_LABELS = {
    "success": "成功",
    "skipped": "跳过",
    "failed": "失败",
}


def strategy_label(strategy: str | None) -> str | None:
    if not strategy:
        return None
    return STRATEGY_LABELS.get(strategy, strategy)


def result_label(result: str | None) -> str | None:
    if not result:
        return None
    return RESULT_LABELS.get(result, result)


class FundTaskAttemptOut(BaseModel):
    strategy: str
    strategy_label: str
    result: str
    result_label: str


def parse_attempts(message: str | None) -> list[FundTaskAttemptOut]:
    if not message:
        return []

    attempts: list[FundTaskAttemptOut] = []
    for item in message.split(";"):
        strategy, separator, result = item.partition("=")
        strategy = strategy.strip()
        result = result.strip()
        if not strategy or not separator:
            continue
        attempts.append(
            FundTaskAttemptOut(
                strategy=strategy,
                strategy_label=strategy_label(strategy) or strategy,
                result=result,
                result_label=result_label(result) or result,
            )
        )
    return attempts


class FundTaskDetailLogOut(BaseModel):
    id: int
    task_log_id: int | None = None
    task_type: str
    fund_code: str
    fund_name: str | None = None
    status: str
    strategy: str | None = None
    reason: str | None = None
    estimate_date: date | None = None
    estimate_time: datetime | None = None
    estimated_nav: Decimal | None = None
    estimated_growth_rate: Decimal | None = None
    coverage_ratio: Decimal | None = None
    source_snapshot: str | None = None
    message: str | None = None
    created_at: datetime

    @computed_field
    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @computed_field
    @property
    def strategy_label(self) -> str | None:
        return strategy_label(self.strategy)

    @computed_field
    @property
    def reason_label(self) -> str | None:
        return result_label(self.reason)

    @computed_field
    @property
    def attempts(self) -> list[FundTaskAttemptOut]:
        return parse_attempts(self.message)

    model_config = {"from_attributes": True}
