from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import time

import requests

from app.modules.information.services.bilinote_client import compact_json


@dataclass(frozen=True)
class HermesRunResult:
    run_id: str | None
    status: str
    document_text: str | None
    raw_response: dict[str, Any]


class HermesClient:
    def __init__(
        self,
        base_url: str,
        run_path: str = "/api/runs",
        status_path_template: str = "/api/runs/{run_id}",
        api_key: str = "",
        auth_header_name: str = "Authorization",
        model: str = "hermes-agent",
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.run_path = run_path
        self.status_path_template = status_path_template
        self.api_key = api_key.strip()
        self.auth_header_name = auth_header_name.strip() or "Authorization"
        self.model = model.strip() or "hermes-agent"
        self.timeout = timeout

    def start_run(self, prompt: str, title: str) -> HermesRunResult:
        payload = {
            "model": self.model,
            "input": prompt,
            "instructions": title,
        }
        response = requests.post(self._url(self.run_path), json=payload, headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        return HermesRunResult(
            run_id=self._first_string(data, ("run_id", "id", "task_id", "data.run_id", "data.id")),
            status=self._status(data) or "started",
            document_text=self._document_text(data),
            raw_response=data,
        )

    def poll_run(self, run_id: str, max_attempts: int = 60, interval_seconds: float = 3.0) -> HermesRunResult:
        last_data: dict[str, Any] = {}
        for _ in range(max_attempts):
            result = self.poll_run_once(run_id)
            last_data = result.raw_response
            status = result.status
            document_text = result.document_text
            if status in {"done", "completed", "success", "finished"} or document_text:
                return HermesRunResult(run_id, "done", document_text, last_data)
            if status in {"failed", "error", "cancelled"}:
                return HermesRunResult(run_id, "failed", document_text, last_data)
            time.sleep(interval_seconds)
        return HermesRunResult(run_id, "failed", None, {"error": "Hermes run polling timed out", "last": last_data})

    def poll_run_once(self, run_id: str) -> HermesRunResult:
        path = self.status_path_template.replace("{run_id}", run_id)
        response = requests.get(self._url(path), headers=self._headers(), timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        status = self._status(data) or "running"
        document_text = self._document_text(data)
        if document_text and status not in {"failed", "error", "cancelled"}:
            status = "done"
        elif status in {"completed", "success", "finished"}:
            status = "done"
        elif status in {"error", "cancelled"}:
            status = "failed"
        return HermesRunResult(run_id, status, document_text, data)

    def _url(self, path: str) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{normalized}"

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            return {}
        if self.auth_header_name.lower() != "authorization":
            return {self.auth_header_name: self.api_key}
        if self.api_key.lower().startswith(("bearer ", "token ", "basic ")):
            return {self.auth_header_name: self.api_key}
        return {self.auth_header_name: f"Bearer {self.api_key}"}

    @classmethod
    def _status(cls, data: Any) -> str | None:
        value = cls._first_string(data, ("status", "state", "run_status", "data.status", "result.status"))
        return value.lower() if value else None

    @classmethod
    def _document_text(cls, data: Any) -> str | None:
        text = cls._first_string(
            data,
            (
                "document",
                "document_text",
                "content",
                "result",
                "summary",
                "output",
                "data.document",
                "data.content",
                "data.result",
                "data.output",
                "result.document",
                "result.content",
                "result.output",
                "output_text",
            ),
        )
        if text:
            return text
        output = data.get("output") if isinstance(data, dict) else None
        if isinstance(output, list):
            text_parts: list[str] = []
            cls._collect_output_text(output, text_parts)
            text = "\n".join(part for part in text_parts if part.strip()).strip()
            if text:
                return text
        return None

    @classmethod
    def _collect_output_text(cls, value: Any, text_parts: list[str]) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("text"), str) and value.get("type") in {"output_text", "text"}:
                text_parts.append(value["text"])
            for nested in value.values():
                cls._collect_output_text(nested, text_parts)
        elif isinstance(value, list):
            for item in value:
                cls._collect_output_text(item, text_parts)

    @classmethod
    def _first_string(cls, data: Any, paths: tuple[str, ...]) -> str | None:
        for path in paths:
            current = data
            for part in path.split("."):
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    current = None
                    break
            if isinstance(current, str) and current.strip():
                return current.strip()
        return None


__all__ = ["HermesClient", "HermesRunResult", "compact_json"]
