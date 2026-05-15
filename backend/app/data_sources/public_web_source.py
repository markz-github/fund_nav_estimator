from __future__ import annotations

from decimal import Decimal
from html import unescape
import re

import requests


class PublicWebFundSource:
    """Conservative scraper for secondary public fund pages.

    Covers pages that are useful for manual verification, such as 基金速查网,
    理杏仁 and Investing search/detail pages. These sites do not expose a stable
    public holdings API, so this source only emits target ETF mappings when the
    page text contains an explicit ETF code and ETF name close together.
    """

    source_name = "public_web"

    def get_target_fund_holdings(self, fund_code: str) -> list[dict]:
        normalized_code = str(fund_code).strip().zfill(6)
        text = self._fetch_candidate_text(normalized_code)
        if not text:
            return []

        match = re.search(
            r"(?P<code>[15]\d{5})[^，。；;\n]{0,40}"
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
                "source": f"{self.source_name}:target_hint",
            }
        ]

    def _fetch_candidate_text(self, fund_code: str) -> str:
        market = "sh" if fund_code.startswith("5") else "sz"
        urls = [
            f"https://www.dayfund.cn/fund/{fund_code}.html",
            f"https://www.dayfund.cn/fundinfo/{fund_code}.html",
            f"https://www.dayfund.cn/fundmanager/{fund_code}.html",
            f"https://www.lixinger.com/equity/fund/detail/{market}/{fund_code}/{fund_code}",
            f"https://cn.investing.com/search/?q={fund_code}",
        ]
        texts: list[str] = []
        for url in urls:
            try:
                response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                if response.status_code >= 400:
                    continue
                response.encoding = response.apparent_encoding or "utf-8"
            except requests.RequestException:
                continue
            texts.append(self._strip_tags(response.text))
        return " ".join(texts)

    @staticmethod
    def _strip_tags(html_text: str) -> str:
        text = re.sub(r"<script[\s\S]*?</script>", " ", html_text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", unescape(text))

    @staticmethod
    def _current_report_period() -> str:
        from datetime import date

        today = date.today()
        quarter = (today.month - 1) // 3 + 1
        return f"{today.year}Q{quarter}"
