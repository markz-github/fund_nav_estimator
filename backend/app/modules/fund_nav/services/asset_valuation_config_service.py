from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.asset_valuation_config import AssetValuationConfig


@dataclass(frozen=True)
class AssetValuationRule:
    realtime_valuable: bool
    valuation_mode: str


class AssetValuationConfigMap:
    def __init__(self, rules: dict[tuple[str, str], AssetValuationRule]) -> None:
        self.rules = {
            (asset_type.lower(), market.upper() if market != "*" else "*"): rule
            for (asset_type, market), rule in rules.items()
        }

    def resolve(self, asset_type: str | None, market: str | None) -> AssetValuationRule:
        normalized_type = (asset_type or "").strip().lower()
        normalized_market = (market or "*").strip().upper() or "*"
        return (
            self.rules.get((normalized_type, normalized_market))
            or self.rules.get((normalized_type, "*"))
            or AssetValuationRule(realtime_valuable=False, valuation_mode="none")
        )


DEFAULT_ASSET_VALUATION_CONFIGS = [
    ("stock", "SH", True, "quote", "A 股上海市场股票使用行情涨跌幅估算"),
    ("stock", "SZ", True, "quote", "A 股深圳市场股票使用行情涨跌幅估算"),
    ("stock", "BJ", True, "quote", "A 股北交所股票使用行情涨跌幅估算"),
    ("stock", "HK", True, "quote", "港股使用行情涨跌幅估算"),
    ("stock", "US", True, "quote", "美股使用最近可用行情涨跌幅估算"),
    ("etf", "CN", True, "quote", "场内 ETF 使用行情涨跌幅估算"),
    ("index", "CN", True, "quote", "指数型基金使用跟踪指数涨跌幅估算"),
    ("bond", "*", False, "none", "债券暂不参与实时估算"),
]


def default_asset_valuation_config_map() -> AssetValuationConfigMap:
    return AssetValuationConfigMap(
        {
            (asset_type, market): AssetValuationRule(realtime_valuable, valuation_mode)
            for asset_type, market, realtime_valuable, valuation_mode, _remark in DEFAULT_ASSET_VALUATION_CONFIGS
        }
    )


def load_asset_valuation_config_map(db: Session) -> AssetValuationConfigMap:
    rules = {
        (asset_type, market): AssetValuationRule(realtime_valuable, valuation_mode)
        for asset_type, market, realtime_valuable, valuation_mode, _remark in DEFAULT_ASSET_VALUATION_CONFIGS
    }
    rows = db.scalars(select(AssetValuationConfig)).all()
    rules.update(
        {
            (row.asset_type, row.market): AssetValuationRule(
                realtime_valuable=bool(row.realtime_valuable),
                valuation_mode=row.valuation_mode,
            )
            for row in rows
            if row.enabled == 1
        }
    )
    return AssetValuationConfigMap(rules)


def seed_default_asset_valuation_configs(db: Session) -> None:
    for asset_type, market, realtime_valuable, valuation_mode, remark in DEFAULT_ASSET_VALUATION_CONFIGS:
        existing = db.scalar(
            select(AssetValuationConfig)
            .where(
                AssetValuationConfig.asset_type == asset_type,
                AssetValuationConfig.market == market,
            )
            .execution_options(include_deleted=True)
        )
        if existing is None:
            db.add(
                AssetValuationConfig(
                    asset_type=asset_type,
                    market=market,
                    realtime_valuable=1 if realtime_valuable else 0,
                    valuation_mode=valuation_mode,
                    enabled=1,
                    remark=remark,
                )
            )
            continue

        existing.is_deleted = 0
        existing.realtime_valuable = 1 if realtime_valuable else 0
        existing.valuation_mode = valuation_mode
        existing.enabled = 1
        existing.remark = remark
    db.commit()
