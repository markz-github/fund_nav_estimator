from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class WechatPushResult:
    ok: bool
    raw_response: dict[str, Any]


class WechatPushClient:
    def __init__(self, webhook_url: str, token: str = "", timeout: int = 30) -> None:
        self.webhook_url = webhook_url.strip()
        self.token = token.strip()
        self.timeout = timeout

    def push_summary(
        self,
        *,
        title: str,
        content: str,
        summary_date: str,
        platform: str,
        document_id: int,
    ) -> WechatPushResult:
        if not self.webhook_url:
            raise ValueError("Wechat push webhook URL is not configured")
        payload = {
            "text": f"# {title}\n\n{content}".strip(),
            "format_markdown": True,
        }
        response = requests.post(self.webhook_url, json=payload, headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        data = self._json_or_text(response)
        return WechatPushResult(ok=self._is_success(data), raw_response=data)

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        if self.token.lower().startswith(("bearer ", "token ", "basic ")):
            return {"Authorization": self.token}
        return {"Authorization": f"Bearer {self.token}"}

    @staticmethod
    def _json_or_text(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            return {"text": response.text}
        return data if isinstance(data, dict) else {"data": data}

    @staticmethod
    def _is_success(data: dict[str, Any]) -> bool:
        code = data.get("code", data.get("errcode", data.get("status")))
        if code is None:
            return True
        if isinstance(code, str):
            return code.lower() in {"0", "ok", "success", "done"}
        return code == 0


__all__ = ["WechatPushClient", "WechatPushResult"]
