from __future__ import annotations

from typing import Any

from app.modules.fund_nav.models.fund import Fund


FUND_CATEGORY_NORMAL = "normal"
FUND_CATEGORY_INDEX_TRACKING = "index_tracking"
FUND_CATEGORY_ETF = "etf"
FUND_CATEGORY_ETF_FEEDER = "etf_feeder"
FUND_CATEGORY_QDII = "qdii"

VALID_FUND_CATEGORIES = {
    FUND_CATEGORY_NORMAL,
    FUND_CATEGORY_INDEX_TRACKING,
    FUND_CATEGORY_ETF,
    FUND_CATEGORY_ETF_FEEDER,
    FUND_CATEGORY_QDII,
}

FUND_CATEGORY_LABELS = {
    FUND_CATEGORY_NORMAL: "普通基金",
    FUND_CATEGORY_INDEX_TRACKING: "指数跟踪基金",
    FUND_CATEGORY_ETF: "场内 ETF",
    FUND_CATEGORY_ETF_FEEDER: "ETF 联接基金",
    FUND_CATEGORY_QDII: "QDII/海外基金",
}


class FundClassifier:
    @classmethod
    def is_exchange_traded_fund(cls, fund: Fund) -> bool:
        return cls.category_for(fund) == FUND_CATEGORY_ETF

    @classmethod
    def is_etf_feeder_fund(cls, fund: Fund) -> bool:
        return cls.category_for(fund) == FUND_CATEGORY_ETF_FEEDER

    @classmethod
    def is_index_tracking_fund(cls, fund: Fund) -> bool:
        return cls.category_for(fund) == FUND_CATEGORY_INDEX_TRACKING

    @classmethod
    def is_index_related_fund(cls, fund: Fund) -> bool:
        return cls.is_index_tracking_fund(fund) or cls.is_exchange_traded_fund(fund) or cls.is_etf_feeder_fund(fund)

    @classmethod
    def is_delayed_nav_fund(cls, fund: Fund) -> bool:
        if cls.category_for(fund) == FUND_CATEGORY_QDII:
            return True
        return cls._has_delayed_nav_keyword(fund)

    @classmethod
    def category_for(cls, fund: Any) -> str:
        stored_category = cls._stored_category(fund)
        if stored_category:
            return stored_category
        return cls.classify_from_attributes(fund)

    @classmethod
    def classify_from_attributes(cls, fund: Any) -> str:
        if cls._is_etf_feeder_by_attributes(fund):
            return FUND_CATEGORY_ETF_FEEDER
        if cls._is_exchange_traded_by_attributes(fund):
            return FUND_CATEGORY_ETF
        if cls._has_index_keyword(fund):
            return FUND_CATEGORY_INDEX_TRACKING
        if cls._has_delayed_nav_keyword(fund):
            return FUND_CATEGORY_QDII
        return FUND_CATEGORY_NORMAL

    @classmethod
    def category_label(cls, category: str | None) -> str:
        return FUND_CATEGORY_LABELS.get(str(category or ""), "未分类")

    @classmethod
    def _has_delayed_nav_keyword(cls, fund: Any) -> bool:
        fund_type = cls._type(fund).upper()
        fund_name = cls._name(fund).upper()
        if "QDII" in fund_type or "QDII" in fund_name:
            return True
        delayed_name_keywords = (
            "纳斯达克",
            "标普",
            "道琼斯",
            "海外",
            "全球",
            "美国",
            "美股",
            "印度",
            "德国",
            "日经",
        )
        return any(keyword in fund_name for keyword in delayed_name_keywords)

    @classmethod
    def _stored_category(cls, fund: Any) -> str | None:
        category = str(getattr(fund, "fund_category", "") or "").strip()
        return category if category in VALID_FUND_CATEGORIES else None

    @classmethod
    def _is_exchange_traded_by_attributes(cls, fund: Any) -> bool:
        fund_code = cls._code(fund)
        return fund_code.startswith(("5", "1")) and cls._has_etf_keyword(fund)

    @classmethod
    def _is_etf_feeder_by_attributes(cls, fund: Any) -> bool:
        fund_name = cls._name(fund)
        return "ETF联接" in fund_name or "联接" in fund_name

    @staticmethod
    def _code(fund: Any) -> str:
        return str(getattr(fund, "fund_code", "") or "").strip()

    @staticmethod
    def _name(fund: Any) -> str:
        return str(getattr(fund, "fund_name", "") or "")

    @staticmethod
    def _type(fund: Any) -> str:
        return str(getattr(fund, "fund_type", "") or "")

    @classmethod
    def _has_etf_keyword(cls, fund: Fund) -> bool:
        return "ETF" in cls._name(fund).upper() or "ETF" in cls._type(fund).upper()

    @classmethod
    def _has_index_keyword(cls, fund: Fund) -> bool:
        return "指数" in cls._type(fund) or "指数" in cls._name(fund)
