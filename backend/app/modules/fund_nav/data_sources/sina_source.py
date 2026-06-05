from __future__ import annotations

from decimal import Decimal
from html import unescape
import json
import re

import requests

from app.modules.fund_nav.report_period import latest_completed_quarter_period


class SinaFundSource:
    source_name = "sina_fund"

    def get_fund_holdings(self, fund_code: str) -> list[dict]:
        normalized_code = str(fund_code).strip().zfill(6)
        payload = self._fetch_openapi(normalized_code)
        if not payload:
            return []
        return self._parse_holdings(normalized_code, payload)

    def get_target_fund_holdings(self, fund_code: str) -> list[dict]:
        normalized_code = str(fund_code).strip().zfill(6)
        payload = self._fetch_openapi(normalized_code)
        if not payload:
            return []

        text = self._flatten_text(payload)
        match = re.search(
            r"(?P<code>(?<!\d)[15]\d{5}(?!\d))[^，。；;\n]{0,40}"
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

    def _fetch_openapi(self, fund_code: str) -> object | None:
        endpoints = (
            "https://fund.sinajs.cn/fund/api/openapi.php/CaihuiFundInfoService.getFundStock",
            "https://fund.sinajs.cn/fund/api/openapi.php/CaihuiFundInfoService.getFundAssetAllocation",
        )
        for endpoint in endpoints:
            try:
                response = requests.get(
                    endpoint,
                    params={"symbol": fund_code},
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
                    timeout=60,
                )
                if response.status_code >= 400:
                    continue
                response.encoding = response.apparent_encoding or "utf-8"
            except requests.RequestException:
                continue

            payload = self._json_from_text(response.text)
            if payload is not None:
                return payload
        return None

    def _parse_holdings(self, fund_code: str, payload: object) -> list[dict]:
        rows = self._find_rows(payload)
        holdings: list[dict] = []
        for row in rows:
            code = self._first_value(row, ("symbol", "stock_code", "code", "gpdm", "zqdm"))
            name = self._first_value(row, ("name", "stock_name", "gpjc", "zqjc", "jc"))
            ratio = self._first_value(row, ("ratio", "jzbl", "percent", "zjzbl", "hold_ratio"))
            value = self._first_value(row, ("value", "sz", "market_value", "ccsz"))
            if not code or not name or ratio is None:
                continue
            asset_code = str(code).strip().zfill(5 if len(str(code).strip()) == 5 else 6)
            asset_type = self._infer_asset_type(asset_code)
            holdings.append(
                {
                    "fund_code": fund_code,
                    "report_period": str(self._first_value(row, ("date", "rq", "reportdate", "bgrq")) or "latest"),
                    "asset_code": asset_code,
                    "asset_name": str(name).strip(),
                    "asset_type": asset_type,
                    "market": self._infer_market(asset_code, asset_type),
                    "holding_ratio": self._percent(ratio),
                    "holding_value": self._optional_decimal(value),
                    "source": self.source_name,
                }
            )
        return holdings

    def _find_rows(self, value: object) -> list[dict]:
        rows: list[dict] = []
        if isinstance(value, list):
            for item in value:
                rows.extend(self._find_rows(item))
        elif isinstance(value, dict):
            if any(key in value for key in ("symbol", "stock_code", "gpdm", "zqdm")):
                rows.append(value)
            for item in value.values():
                rows.extend(self._find_rows(item))
        return rows

    @staticmethod
    def _json_from_text(text: str) -> object | None:
        text = unescape(text.strip())
        match = re.search(r"(\{[\s\S]*\})", text)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _first_value(row: dict, keys: tuple[str, ...]):
        lower_map = {str(key).lower(): value for key, value in row.items()}
        for key in keys:
            value = lower_map.get(key)
            if value not in (None, "", "--"):
                return value
        return None

    @staticmethod
    def _flatten_text(value: object) -> str:
        if isinstance(value, dict):
            return " ".join(SinaFundSource._flatten_text(item) for item in value.values())
        if isinstance(value, list):
            return " ".join(SinaFundSource._flatten_text(item) for item in value)
        return str(value)

    @staticmethod
    def _optional_decimal(value) -> Decimal | None:
        if value is None:
            return None
        text = str(value).strip().replace(",", "").rstrip("%")
        if not text or text == "--":
            return None
        try:
            return Decimal(text)
        except Exception:
            return None

    @classmethod
    def _percent(cls, value) -> Decimal:
        decimal_value = cls._optional_decimal(value)
        if decimal_value is None:
            return Decimal("0")
        if Decimal("-1") < decimal_value < Decimal("1"):
            return decimal_value
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

    @staticmethod
    def _infer_asset_type(asset_code: str) -> str:
        if len(asset_code) == 6 and asset_code.startswith(("5", "1")):
            return "etf"
        return "stock"

    @staticmethod
    def _infer_market(asset_code: str, asset_type: str) -> str | None:
        if asset_type == "etf":
            return "CN"
        return SinaFundSource._infer_stock_market(asset_code)

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
