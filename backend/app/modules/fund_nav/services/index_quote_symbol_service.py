from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.fund_nav.models.index_quote_symbol import IndexQuoteSymbol
from app.modules.fund_nav.models.market_index import MarketIndex


@dataclass(frozen=True)
class QuoteSymbol:
    index_code: str
    source_key: str
    quote_symbol: str | None
    supported: bool = True


class IndexQuoteSymbolService:
    def __init__(self, db: Session | None) -> None:
        self.db = db

    def resolve_symbols(self, source_key: str, index_codes: set[str]) -> dict[str, QuoteSymbol]:
        explicit = self._explicit_symbols(source_key, index_codes)
        resolved: dict[str, QuoteSymbol] = {}
        for code in index_codes:
            symbol = explicit.get(code)
            if symbol is None:
                symbol = self._default_symbol(source_key, code)
            resolved[code] = symbol
        return resolved

    def supported_codes(self, source_key: str, index_codes: set[str]) -> set[str]:
        symbols = self.resolve_symbols(source_key, index_codes)
        return {code for code, symbol in symbols.items() if symbol.supported}

    def request_symbols(self, source_key: str, index_codes: set[str]) -> dict[str, str]:
        symbols = self.resolve_symbols(source_key, index_codes)
        return {
            code: symbol.quote_symbol
            for code, symbol in symbols.items()
            if symbol.supported and symbol.quote_symbol
        }

    def list_symbols(
        self,
        *,
        index_code: str | None = None,
        source_key: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[IndexQuoteSymbol], int]:
        if self.db is None:
            return [], 0
        statement = select(IndexQuoteSymbol)
        count_statement = select(func.count()).select_from(IndexQuoteSymbol)
        cleaned_code = (index_code or "").strip().upper()
        cleaned_source = (source_key or "").strip()
        if cleaned_code:
            statement = statement.where(IndexQuoteSymbol.index_code.like(f"{cleaned_code}%"))
            count_statement = count_statement.where(IndexQuoteSymbol.index_code.like(f"{cleaned_code}%"))
        if cleaned_source:
            statement = statement.where(IndexQuoteSymbol.source_key == cleaned_source)
            count_statement = count_statement.where(IndexQuoteSymbol.source_key == cleaned_source)
        safe_limit = max(1, min(int(limit or 200), 500))
        safe_offset = max(0, int(offset or 0))
        total = int(self.db.scalar(count_statement) or 0)
        items = list(
            self.db.scalars(
                statement.order_by(IndexQuoteSymbol.index_code, IndexQuoteSymbol.source_key)
                .offset(safe_offset)
                .limit(safe_limit)
            ).all()
        )
        return items, total

    def upsert_symbol(
        self,
        *,
        index_code: str,
        source_key: str,
        quote_symbol: str | None,
        supported: int,
        description: str | None,
    ) -> IndexQuoteSymbol:
        if self.db is None:
            raise ValueError("Database session is required")
        normalized_code = str(index_code or "").strip().upper()
        normalized_source = str(source_key or "").strip()
        if not normalized_code:
            raise ValueError("index_code is required")
        if not normalized_source:
            raise ValueError("source_key is required")
        normalized_supported = 1 if int(supported or 0) == 1 else 0
        normalized_symbol = (quote_symbol or "").strip() or None
        if normalized_supported == 1 and normalized_symbol is None:
            raise ValueError("quote_symbol is required when supported is 1")

        row = self.db.scalar(
            select(IndexQuoteSymbol).where(
                IndexQuoteSymbol.index_code == normalized_code,
                IndexQuoteSymbol.source_key == normalized_source,
            )
        )
        if row is None:
            row = IndexQuoteSymbol(index_code=normalized_code, source_key=normalized_source)
            self.db.add(row)
        row.quote_symbol = normalized_symbol
        row.supported = normalized_supported
        row.description = (description or "").strip()[:500] or None
        self.db.flush()
        return row

    def seed_csindex_symbols(self) -> int:
        if self.db is None:
            return 0
        indexes = self.db.scalars(
            select(MarketIndex).where(
                MarketIndex.provider == "csindex",
                MarketIndex.index_code.like("9%"),
            )
        ).all()
        index_codes = [index.index_code for index in indexes]
        if not index_codes:
            return 0
        existing = {
            (row.index_code, row.source_key)
            for row in self.db.scalars(
                select(IndexQuoteSymbol).where(IndexQuoteSymbol.index_code.in_(index_codes))
            ).all()
        }
        created = 0
        for index in indexes:
            created += self._seed_symbol(index.index_code, "eastmoney_http_spot", f"2.{index.index_code}", 1, "中证 9xxxxx 指数，东财中证市场 secid", existing)
            created += self._seed_symbol(index.index_code, "xueqiu_spot", f"CSI{index.index_code}", 1, "中证 9xxxxx 指数，雪球 CSI symbol", existing)
            created += self._seed_symbol(index.index_code, "sina_http_spot", None, 0, "新浪 HTTP 不支持该中证 9xxxxx 指数", existing)
            created += self._seed_symbol(index.index_code, "tencent_spot", None, 0, "腾讯 HTTP 不支持该中证 9xxxxx 指数", existing)
        self.db.flush()
        return created

    def _seed_symbol(
        self,
        index_code: str,
        source_key: str,
        quote_symbol: str | None,
        supported: int,
        description: str,
        existing: set[tuple[str, str]],
    ) -> int:
        key = (index_code, source_key)
        if key in existing:
            return 0
        self.db.add(
            IndexQuoteSymbol(
                index_code=index_code,
                source_key=source_key,
                quote_symbol=quote_symbol,
                supported=supported,
                description=description,
            )
        )
        existing.add(key)
        return 1

    def _explicit_symbols(self, source_key: str, index_codes: set[str]) -> dict[str, QuoteSymbol]:
        if self.db is None or not index_codes:
            return {}
        rows = self.db.scalars(
            select(IndexQuoteSymbol).where(
                IndexQuoteSymbol.source_key == source_key,
                IndexQuoteSymbol.index_code.in_(index_codes),
            )
        ).all()
        return {
            row.index_code: QuoteSymbol(
                index_code=row.index_code,
                source_key=row.source_key,
                quote_symbol=row.quote_symbol,
                supported=row.supported == 1,
            )
            for row in rows
        }

    @classmethod
    def _default_symbol(cls, source_key: str, index_code: str) -> QuoteSymbol:
        code = str(index_code or "").strip()
        symbol: str | None
        supported = True
        if source_key == "eastmoney_http_spot":
            symbol = cls._eastmoney_http_symbol(code)
        elif source_key == "sina_http_spot":
            symbol = cls._sina_http_symbol(code)
            supported = not code.startswith("9")
        elif source_key == "tencent_spot":
            symbol = cls._tencent_symbol(code)
            supported = not code.startswith("9")
        elif source_key == "xueqiu_spot":
            symbol = cls._xueqiu_symbol(code)
        else:
            symbol = None
            supported = True
        return QuoteSymbol(
            index_code=code,
            source_key=source_key,
            quote_symbol=symbol,
            supported=supported and (symbol is not None or source_key in {"eastmoney_spot", "sina_spot"}),
        )

    @staticmethod
    def _eastmoney_http_symbol(index_code: str) -> str | None:
        if not index_code.isdigit():
            return None
        if index_code.startswith("9"):
            return f"2.{index_code}"
        if index_code.startswith("3"):
            return f"0.{index_code}"
        if index_code.startswith(("0", "5", "8")):
            return f"1.{index_code}"
        return None

    @staticmethod
    def _sina_http_symbol(index_code: str) -> str | None:
        if not index_code.isdigit():
            return None
        if index_code.startswith("3"):
            return f"s_sz{index_code}"
        if index_code.startswith(("0", "5", "8", "9")):
            return f"s_sh{index_code}"
        return None

    @staticmethod
    def _tencent_symbol(index_code: str) -> str | None:
        if not index_code.isdigit():
            return None
        if index_code.startswith("3"):
            return f"sz{index_code}"
        if index_code.startswith(("0", "5", "8", "9")):
            return f"sh{index_code}"
        return None

    @staticmethod
    def _xueqiu_symbol(index_code: str) -> str | None:
        if not index_code.isdigit():
            return None
        if index_code.startswith("9"):
            return f"CSI{index_code}"
        if index_code.startswith("3"):
            return f"SZ{index_code}"
        if index_code.startswith(("0", "5", "8")):
            return f"SH{index_code}"
        return None


def seed_default_index_quote_symbols(db: Session) -> None:
    # 中证 9xxxxx 指数由市场指数目录动态生成渠道映射，不维护个别指数的固定列表。
    IndexQuoteSymbolService(db).seed_csindex_symbols()
    db.flush()
