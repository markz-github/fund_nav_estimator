from __future__ import annotations

from decimal import Decimal
from html import unescape
import re

import requests

from app.modules.fund_nav.report_period import latest_completed_quarter_period


class FundCompanySource:
    """Best-effort parser for fund company public product pages.

    These pages are not uniform across companies, so this adapter is intentionally
    conservative: it only returns an ETF target mapping when both code and ETF
    name appear close to target-ETF wording.
    """

    source_name = "fund_company"

    _KNOWN_PRODUCT_PAGES = {
        "012805": "https://www.amcfortune.com/funds/public/012805/index.shtml",
    }

    def get_target_fund_holdings(self, fund_code: str) -> list[dict]:
        normalized_code = str(fund_code).strip().zfill(6)
        url = self._KNOWN_PRODUCT_PAGES.get(normalized_code)
        if not url:
            return []

        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
            if response.status_code >= 400:
                return []
            response.encoding = response.apparent_encoding or "utf-8"
        except requests.RequestException:
            return []

        text = self._strip_tags(response.text)
        match = re.search(
            r"(?:目标ETF|投资.*ETF|跟踪指数)[^0-9]{0,80}"
            r"(?P<code>[15]\d{5})[^，。；;\n]{0,60}"
            r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()\-\s]+ETF[\u4e00-\u9fa5A-Za-z0-9（）()\-\s]*)",
            text,
        )
        if not match or match.group("code") == normalized_code:
            return []

        return [
            {
                "fund_code": normalized_code,
                "report_period": self._current_report_period(),
                "asset_code": match.group("code"),
                "asset_name": re.sub(r"\s+", "", match.group("name")),
                "asset_type": "etf",
                "market": "CN",
                "holding_ratio": Decimal("1"),
                "holding_value": None,
                "source": self.source_name,
            }
        ]

    @staticmethod
    def _strip_tags(html_text: str) -> str:
        text = re.sub(r"<script[\s\S]*?</script>", " ", html_text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", unescape(text))

    @staticmethod
    def _current_report_period() -> str:
        return latest_completed_quarter_period()
