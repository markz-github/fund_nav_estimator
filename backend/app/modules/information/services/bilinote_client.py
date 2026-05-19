from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any

import requests


@dataclass(frozen=True)
class BilinoteTaskResult:
    task_id: str | None
    status: str
    note_text: str | None
    raw_response: dict[str, Any]
    error_message: str | None = None


class BilinoteClient:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate_note(
        self,
        video_url: str,
        platform: str,
        quality: str,
        model_name: str,
        provider_id: str,
    ) -> BilinoteTaskResult:
        payload = {
            "video_url": video_url,
            "platform": platform,
            "quality": quality,
            "model_name": model_name,
            "provider_id": provider_id,
            "screenshot": False,
            "link": False,
            "format": [],
            "style": "default",
            "extras": None,
            "video_understanding": False,
            "video_interval": 0,
            "grid_size": [],
        }
        response = requests.post(f"{self.base_url}/api/generate_note", json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        return BilinoteTaskResult(
            task_id=self._first_string(
                data,
                (
                    "task_id",
                    "taskid",
                    "taskId",
                    "id",
                    "data.task_id",
                    "data.taskid",
                    "data.taskId",
                    "data.id",
                    "result.task_id",
                    "result.taskid",
                    "result.taskId",
                    "result.id",
                ),
            ),
            status=self._status(data) or "running",
            note_text=self._note_text(data),
            raw_response=data,
            error_message=self._error_message(data),
        )

    def poll_task_once(self, task_id: str) -> BilinoteTaskResult:
        response = requests.get(f"{self.base_url}/api/task_status/{task_id}", timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        status = self._status(data) or "running"
        note_text = self._note_text(data)
        error_message = self._error_message(data)
        if status in {"done", "completed", "success", "finished"} or note_text:
            return BilinoteTaskResult(task_id, "done", note_text, data, error_message)
        if status in {"failed", "error", "cancelled"}:
            return BilinoteTaskResult(task_id, "failed", note_text, data, error_message)
        return BilinoteTaskResult(task_id, "running", note_text, data, error_message)

    def poll_task(self, task_id: str, max_attempts: int = 2880, interval_seconds: float = 30.0) -> BilinoteTaskResult:
        last_data: dict[str, Any] = {}
        for _ in range(max_attempts):
            result = self.poll_task_once(task_id)
            last_data = result.raw_response
            if result.status in {"done", "failed"}:
                return result
            time.sleep(interval_seconds)
        return BilinoteTaskResult(
            task_id,
            "failed",
            None,
            {"error": "Bilinote task polling timed out", "last": last_data},
            "Bilinote task polling timed out",
        )

    @classmethod
    def _status(cls, data: Any) -> str | None:
        value = cls._first_string(
            data,
            (
                "status",
                "state",
                "task_status",
                "data.status",
                "data.state",
                "data.task_status",
                "result.status",
                "result.state",
                "result.task_status",
            ),
        )
        return value.lower() if value else None

    @classmethod
    def _note_text(cls, data: Any) -> str | None:
        note_text = cls._first_string(
            data,
            (
                "note",
                "note_text",
                "markdown",
                "content",
                "result",
                "summary",
                "data.note",
                "data.content",
                "data.markdown",
                "data.result",
                "data.result.note",
                "data.result.note_text",
                "data.result.content",
                "data.result.markdown",
                "data.result.summary",
                "result.note",
                "result.note_text",
                "result.content",
                "result.markdown",
                "result.summary",
            ),
        )
        return normalize_markdown_text(note_text) if note_text is not None else None

    @classmethod
    def _error_message(cls, data: Any) -> str | None:
        return cls._first_string(
            data,
            (
                "error",
                "message",
                "detail",
                "error_message",
                "data.error",
                "data.message",
                "data.detail",
                "data.error_message",
                "result.error",
                "result.message",
                "result.detail",
                "result.error_message",
            ),
        )

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


def compact_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def normalize_markdown_text(value: str) -> str:
    normalized = value.strip()
    normalized = re.sub(r"(?m)^(\s*)(\d+)\\\.(\s+)", r"\1\2.\3", normalized)
    normalized = re.sub(r"(?m)^(\s*#{1,6}\s+\d+)\\\.(\s+)", r"\1.\2", normalized)
    return normalized
