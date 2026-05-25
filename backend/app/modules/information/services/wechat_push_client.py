from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

import requests

from app.modules.information.services.external_call_logging import external_log_json
from app.modules.information.services.external_call_logging import response_log_body
from app.modules.information.services.external_call_logging import sanitize_external_url


logger = logging.getLogger(__name__)


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().strip("#").strip()).casefold()


def _strip_duplicate_heading(content: str, title: str) -> str:
    title_text = _normalize_title(title)
    if not title_text:
        return content
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*(?:\r?\n|$)", content)
    if not match:
        return content
    if _normalize_title(match.group(1)) != title_text:
        return content
    return content[match.end():].lstrip()


@dataclass(frozen=True)
class WechatPushResult:
    ok: bool
    raw_response: dict[str, Any]


class WechatPushClient:
    def __init__(self, webhook_url: str, token: str = "", timeout: int = 60) -> None:
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
        content_text = _strip_duplicate_heading(content, title)
        payload = {
            "text": f"# {title}\n\n{content_text}".strip(),
            "format_markdown": True,
        }
        logger.info(
            "external request system=wechat_push method=POST url=%s payload=%s",
            sanitize_external_url(self.webhook_url),
            external_log_json(payload),
        )
        response = requests.post(self.webhook_url, json=payload, headers=self._headers(), timeout=self.timeout)
        data = response_log_body(response)
        if not isinstance(data, dict):
            data = {"data": data}
        logger.info(
            "external response system=wechat_push method=POST url=%s status=%s body=%s",
            sanitize_external_url(self.webhook_url),
            response.status_code,
            external_log_json(data),
        )
        response.raise_for_status()
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
