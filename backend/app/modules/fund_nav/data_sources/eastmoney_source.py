from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html import unescape
from html.parser import HTMLParser
import re

import requests


@dataclass(frozen=True)
class ParsedHolding:
    fund_code: str
    report_period: str
    asset_code: str
    asset_name: str
    asset_type: str
    market: str | None
    holding_ratio: Decimal
    holding_value: Decimal | None


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "tr":
            self._current_row = []
        elif tag.lower() in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._current_cell)).strip()
            self._current_row.append(text)
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


class EastmoneySource:
    source_name = "eastmoney"

    def get_fund_holdings(self, fund_code: str) -> list[dict]:
        normalized_code = self._normalize_fund_code(fund_code)
        holdings = self._fetch_stock_holdings(normalized_code)
        return [self._to_snapshot(holding) for holding in self._latest_period_holdings(holdings)]

    def get_target_fund_holdings(self, fund_code: str) -> list[dict]:
        normalized_code = self._normalize_fund_code(fund_code)
        text = self._fetch_pages_text(
            [
                f"https://fund.eastmoney.com/{normalized_code}.html",
                f"https://fundf10.eastmoney.com/jbgk_{normalized_code}.html",
                f"https://fundf10.eastmoney.com/zcpz_{normalized_code}.html",
            ]
        )
        if not text:
            return []

        # Some ETF feeder pages mention the target ETF in prose rather than a table.
        # Treat these as low-confidence 100% target mappings only when a code/name is explicit.
        for pattern in (
            r"目标ETF[^0-9]{0,40}(?P<code>[15]\d{5})[^，。；;\n]{0,40}(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()\-\s]+ETF[\u4e00-\u9fa5A-Za-z0-9（）()\-\s]*)",
            r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()\-\s]+ETF[\u4e00-\u9fa5A-Za-z0-9（）()\-\s]*)\((?P<code>[15]\d{5})\)",
            r"(?P<code>[15]\d{5})[^，。；;\n]{0,30}(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()\-\s]+ETF[\u4e00-\u9fa5A-Za-z0-9（）()\-\s]*)",
        ):
            match = re.search(pattern, text)
            if not match:
                continue
            asset_code = match.group("code")
            if asset_code == normalized_code:
                continue
            return [
                {
                    "fund_code": normalized_code,
                    "report_period": self._current_report_period(),
                    "asset_code": asset_code,
                    "asset_name": re.sub(r"\s+", "", match.group("name")),
                    "asset_type": "etf",
                    "market": "CN",
                    "holding_ratio": Decimal("1"),
                    "holding_value": None,
                    "source": f"{self.source_name}:target_hint",
                }
            ]
        return []

    def _fetch_stock_holdings(self, fund_code: str) -> list[ParsedHolding]:
        text = self._fetch_text(
            "https://fundf10.eastmoney.com/FundArchivesDatas.aspx",
            params={"code": fund_code, "type": "jjcc", "topline": "50", "year": ""},
            headers={"Referer": f"https://fundf10.eastmoney.com/ccmx_{fund_code}.html"},
        )
        if not text:
            return []
        return self._parse_fund_archives_holdings(fund_code, text)

    def _parse_fund_archives_holdings(
        self, fund_code: str, html_text: str
    ) -> list[ParsedHolding]:
        normalized = self._normalize_response_html(html_text)
        sections = re.split(r"(?=截止至[:：]\s*\d{4}-\d{2}-\d{2})", normalized)
        holdings: list[ParsedHolding] = []

        for section in sections:
            date_match = re.search(r"截止至[:：]\s*(\d{4}-\d{2}-\d{2})", section)
            if not date_match:
                continue
            report_period = self._report_period_from_date(date_match.group(1))
            parser = _TableParser()
            parser.feed(section)
            for row in parser.rows:
                holding = self._parse_holding_row(fund_code, report_period, row)
                if holding is not None:
                    holdings.append(holding)
        return holdings

    def _parse_holding_row(
        self, fund_code: str, report_period: str, row: list[str]
    ) -> ParsedHolding | None:
        code_index = next(
            (idx for idx, cell in enumerate(row) if re.fullmatch(r"\d{5,6}", cell.strip())),
            None,
        )
        if code_index is None or code_index + 1 >= len(row):
            return None

        asset_code = row[code_index].strip().zfill(5 if len(row[code_index].strip()) == 5 else 6)
        asset_name = row[code_index + 1].strip()
        ratio_index = next(
            (idx for idx in range(len(row) - 1, code_index, -1) if row[idx].strip().endswith("%")),
            None,
        )
        if ratio_index is None:
            return None

        return ParsedHolding(
            fund_code=fund_code,
            report_period=report_period,
            asset_code=asset_code,
            asset_name=asset_name,
            asset_type="stock",
            market=self._infer_stock_market(asset_code),
            holding_ratio=self._percent(row[ratio_index]),
            holding_value=self._optional_decimal(row[ratio_index + 2] if ratio_index + 2 < len(row) else None),
        )

    def _fetch_pages_text(self, urls: list[str]) -> str:
        texts: list[str] = []
        for url in urls:
            text = self._fetch_text(url)
            if text:
                texts.append(self._strip_tags(text))
        return " ".join(texts)

    @staticmethod
    def _fetch_text(url: str, params: dict | None = None, headers: dict | None = None) -> str:
        try:
            response = requests.get(
                url,
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    **(headers or {}),
                },
                timeout=20,
            )
            if response.status_code >= 400:
                return ""
            response.encoding = response.apparent_encoding or "utf-8"
            return response.text
        except requests.RequestException:
            return ""

    @staticmethod
    def _normalize_response_html(value: str) -> str:
        text = value.replace('\\"', '"').replace("\\/", "/")
        return unescape(text)

    @staticmethod
    def _strip_tags(html_text: str) -> str:
        text = re.sub(r"<script[\s\S]*?</script>", " ", html_text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", unescape(text))

    @staticmethod
    def _normalize_fund_code(fund_code: str) -> str:
        return str(fund_code).strip().zfill(6)

    @staticmethod
    def _report_period_from_date(value: str) -> str:
        report_date = date.fromisoformat(value)
        quarter = (report_date.month - 1) // 3 + 1
        return f"{report_date.year}Q{quarter}"

    @staticmethod
    def _current_report_period() -> str:
        today = date.today()
        quarter = (today.month - 1) // 3 + 1
        return f"{today.year}Q{quarter}"

    @staticmethod
    def _optional_decimal(value) -> Decimal | None:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if not text or text == "--":
            return None
        try:
            return Decimal(text.rstrip("%"))
        except Exception:
            return None

    @classmethod
    def _percent(cls, value) -> Decimal:
        decimal_value = cls._optional_decimal(value)
        if decimal_value is None:
            return Decimal("0")
        return decimal_value / Decimal("100")

    @staticmethod
    def _infer_stock_market(asset_code: str) -> str | None:
        if len(asset_code) == 5:
            return "HK"
        if asset_code.startswith(("6", "9")):
            return "SH"
        if asset_code.startswith(("0", "2", "3")):
            return "SZ"
        if asset_code.startswith(("4", "8")):
            return "BJ"
        return None

    @classmethod
    def _latest_period_holdings(cls, holdings: list[ParsedHolding]) -> list[ParsedHolding]:
        if not holdings:
            return []
        latest_period = max(holding.report_period for holding in holdings)
        return [holding for holding in holdings if holding.report_period == latest_period]

    def _to_snapshot(self, holding: ParsedHolding) -> dict:
        return {
            "fund_code": holding.fund_code,
            "report_period": holding.report_period,
            "asset_code": holding.asset_code,
            "asset_name": holding.asset_name,
            "asset_type": holding.asset_type,
            "market": holding.market,
            "holding_ratio": holding.holding_ratio,
            "holding_value": holding.holding_value,
            "source": self.source_name,
        }
