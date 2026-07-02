from __future__ import annotations

from app.modules.fund_nav.models.fund import Fund


class FundClassifier:
    @classmethod
    def is_exchange_traded_fund(cls, fund: Fund) -> bool:
        fund_code = cls._code(fund)
        return fund_code.startswith(("5", "1")) and cls._has_etf_keyword(fund)

    @classmethod
    def is_etf_feeder_fund(cls, fund: Fund) -> bool:
        fund_name = cls._name(fund)
        return "ETF联接" in fund_name or "联接" in fund_name

    @classmethod
    def is_index_tracking_fund(cls, fund: Fund) -> bool:
        return cls._has_index_keyword(fund) and not cls.is_exchange_traded_fund(fund) and not cls.is_etf_feeder_fund(fund)

    @classmethod
    def is_index_related_fund(cls, fund: Fund) -> bool:
        return cls.is_index_tracking_fund(fund) or cls.is_exchange_traded_fund(fund) or cls.is_etf_feeder_fund(fund)

    @classmethod
    def is_delayed_nav_fund(cls, fund: Fund) -> bool:
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

    @staticmethod
    def _code(fund: Fund) -> str:
        return str(getattr(fund, "fund_code", "") or "").strip()

    @staticmethod
    def _name(fund: Fund) -> str:
        return str(getattr(fund, "fund_name", "") or "")

    @staticmethod
    def _type(fund: Fund) -> str:
        return str(getattr(fund, "fund_type", "") or "")

    @classmethod
    def _has_etf_keyword(cls, fund: Fund) -> bool:
        return "ETF" in cls._name(fund).upper() or "ETF" in cls._type(fund).upper()

    @classmethod
    def _has_index_keyword(cls, fund: Fund) -> bool:
        return "指数" in cls._type(fund) or "指数" in cls._name(fund)
