from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests


SENSITIVE_KEYS = ("authorization", "cookie", "token", "api_key", "apikey", "secret", "password")
MAX_STRING_LENGTH = 1000


def sanitize_external_value(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if any(sensitive in key_text.lower() for sensitive in SENSITIVE_KEYS):
                result[key_text] = "***"
            else:
                result[key_text] = sanitize_external_value(child)
        return result
    if isinstance(value, list):
        return [sanitize_external_value(item) for item in value]
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            return f"{value[:MAX_STRING_LENGTH]}...[truncated {len(value) - MAX_STRING_LENGTH} chars]"
        return value
    return value


def sanitize_external_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "***", parts.fragment))


def external_log_json(value: Any) -> str:
    return json.dumps(sanitize_external_value(value), ensure_ascii=False, default=str)


def response_log_body(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"text": response.text}
