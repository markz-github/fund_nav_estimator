from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re

import requests


@dataclass(frozen=True)
class FundIndexMappingSnapshot:
    fund_code: str
    index_code: str | None
    index_name: str | None
    benchmark_text: str | None
    source: str
    confidence: str


class FundIndexMappingSource:
    source_name = "fund_index_mapping"

    def get_mapping(self, fund_code: str) -> FundIndexMappingSnapshot | None:
        normalized_code = str(fund_code).strip().zfill(6)
        return self._get_99fund_mapping(normalized_code) or self._get_eastmoney_mapping(
            normalized_code
        )

    def _get_99fund_mapping(self, fund_code: str) -> FundIndexMappingSnapshot | None:
        text = self._fetch_text(
            f"https://www.99fund.com/main/products/pofund/{fund_code}/fundgk.shtml"
        )
        if not text:
            return None

        stripped = self._strip_tags(text)
        index_code = self._match_value(stripped, r"基准指数代码[:：]?\s*([A-Z0-9.]+)")
        index_name = self._match_value(
            stripped,
            r"基准指数简称[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]+?)(?:\s+|基准|$)",
        )
        benchmark_text = self._match_value(
            stripped,
            r"业绩比较基准[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()×+%\.，,\-\s]+?)(?:\s+风险收益|$)",
        )
        if not index_code and not index_name and not benchmark_text:
            return None

        return FundIndexMappingSnapshot(
            fund_code=fund_code,
            index_code=index_code,
            index_name=self._clean_name(index_name),
            benchmark_text=self._clean_name(benchmark_text),
            source="99fund",
            confidence="high" if index_code else "medium",
        )

    def _get_eastmoney_mapping(self, fund_code: str) -> FundIndexMappingSnapshot | None:
        text = self._fetch_text(f"https://fundf10.eastmoney.com/{fund_code}.html")
        if not text:
            return None

        stripped = self._strip_tags(text)
        benchmark_text = self._match_value(
            stripped,
            r"业绩比较基准[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()×+%\.，,\-\s]+?)(?:\s+跟踪标的|\s+风险收益|$)",
        )
        index_name = self._match_value(
            stripped,
            r"跟踪标的[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()·\-\s]+?)(?:\s+跟踪方式|\s+基金经理|$)",
        )
        if not index_name and benchmark_text:
            index_name = self._extract_index_name_from_benchmark(benchmark_text)
        if not index_name and not benchmark_text:
            return None

        return FundIndexMappingSnapshot(
            fund_code=fund_code,
            index_code=None,
            index_name=self._clean_name(index_name),
            benchmark_text=self._clean_name(benchmark_text),
            source="eastmoney",
            confidence="medium",
        )

    @staticmethod
    def _fetch_text(url: str) -> str:
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
            if response.status_code >= 400:
                return ""
            response.encoding = response.apparent_encoding or "utf-8"
            return response.text
        except requests.RequestException:
            return ""

    @staticmethod
    def _strip_tags(html_text: str) -> str:
        text = re.sub(r"<script[\s\S]*?</script>", " ", html_text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", unescape(text)).strip()

    @staticmethod
    def _match_value(text: str, pattern: str) -> str | None:
        match = re.search(pattern, text)
        if not match:
            return None
        return match.group(1).strip()

    @staticmethod
    def _clean_name(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = re.sub(r"\s+", "", value).strip("：:，,。;；")
        return cleaned or None

    @staticmethod
    def _extract_index_name_from_benchmark(value: str) -> str | None:
        match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-]+指数)", value)
        return match.group(1) if match else None
