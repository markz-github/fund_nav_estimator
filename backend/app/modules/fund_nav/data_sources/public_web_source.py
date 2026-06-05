from __future__ import annotations

from decimal import Decimal
from html import unescape
import re

import requests

from app.modules.fund_nav.report_period import latest_completed_quarter_period


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
            r"(?:目标ETF|投资[^，。；;\n]{0,20}ETF|联接[^，。；;\n]{0,20}ETF)"
            r"[^0-9]{0,80}(?P<code>(?<!\d)[15]\d{5}(?!\d))[^，。；;\n]{0,40}"
            r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9（）()\-\s]+ETF[\u4e00-\u9fa5A-Za-z0-9（）()\-\s]*)",
            text,
        )
        if not match:
            return []
        asset_code = match.group("code")
        asset_name = re.sub(r"\s+", "", match.group("name"))
        if not self._is_valid_target_hint(normalized_code, asset_code, asset_name):
            return []

        return [
            {
                "fund_code": normalized_code,
                "report_period": self._current_report_period(),
                "asset_code": asset_code,
                "asset_name": asset_name,
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
                response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
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
    def _is_valid_target_hint(fund_code: str, asset_code: str, asset_name: str) -> bool:
        if asset_code == fund_code:
            return False
        if fund_code in asset_name:
            return False
        return not any(
            marker in asset_name
            for marker in (
                "基金资产配置",
                "基金基本概况",
                "基金档案",
                "天天基金",
                "网站备案号",
            )
        )

    @staticmethod
    def _current_report_period() -> str:
        return latest_completed_quarter_period()
