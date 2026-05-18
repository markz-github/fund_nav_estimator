from __future__ import annotations

class FallbackSource:
    source_name = "fallback"

    def get_fund_holdings(self, fund_code: str) -> list[dict]:
        return []
