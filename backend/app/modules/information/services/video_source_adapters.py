from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import re
from typing import Protocol

import requests

from app.modules.information.models.video_source import InformationVideoSource


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoSnapshot:
    platform: str
    external_video_id: str
    title: str
    video_url: str
    author_name: str | None
    published_at: datetime | None
    raw_response: dict


class VideoSourceAdapter(Protocol):
    platform: str

    def normalize_source_id(self, value: str) -> str:
        ...

    def fetch_latest_videos(
        self,
        source: InformationVideoSource,
        limit: int = 20,
        bilibili_cookie: str | None = None,
    ) -> list[VideoSnapshot]:
        ...


class BilibiliVideoSourceAdapter:
    platform = "bilibili"

    def normalize_source_id(self, value: str) -> str:
        text = str(value).strip()
        match = re.search(r"(?:space\.bilibili\.com/|/space/)(\d+)", text)
        if match:
            return match.group(1)
        match = re.search(r"mid=(\d+)", text)
        if match:
            return match.group(1)
        if re.fullmatch(r"\d+", text):
            return text
        raise ValueError("B站来源需要填写 UID 或 space 主页 URL")

    def fetch_latest_videos(
        self,
        source: InformationVideoSource,
        limit: int = 20,
        bilibili_cookie: str | None = None,
    ) -> list[VideoSnapshot]:
        mid = self.normalize_source_id(source.external_source_id)
        page_size = min(max(limit, 1), 50)
        logger.debug(
            "bilibili fetch latest videos started source_id=%s mid=%s page=1 page_size=%s order=pubdate",
            source.id,
            mid,
            page_size,
        )
        headers = self._build_headers(mid, bilibili_cookie)
        response = requests.get(
            "https://api.bilibili.com/x/space/arc/search",
            params={
                "mid": mid,
                "pn": 1,
                "ps": page_size,
                "order": "pubdate",
                "jsonp": "jsonp",
            },
            headers=headers,
            timeout=20,
        )
        logger.debug(
            "bilibili fetch latest videos response source_id=%s mid=%s http_status=%s",
            source.id,
            mid,
            response.status_code,
        )
        response.raise_for_status()
        payload = response.json()
        code = payload.get("code")
        if code not in (None, 0):
            message = str(payload.get("message") or "unknown bilibili api error")
            raise RuntimeError(f"Bilibili API returned code={code};message={message}")
        vlist = payload.get("data", {}).get("list", {}).get("vlist", []) or []
        snapshots: list[VideoSnapshot] = []
        for item in vlist:
            bvid = str(item.get("bvid") or item.get("aid") or "").strip()
            if not bvid:
                continue
            created = item.get("created")
            published_at = datetime.fromtimestamp(created) if isinstance(created, (int, float)) else None
            snapshots.append(
                VideoSnapshot(
                    platform=self.platform,
                    external_video_id=bvid,
                    title=str(item.get("title") or bvid),
                    video_url=f"https://www.bilibili.com/video/{bvid}",
                    author_name=source.source_name,
                    published_at=published_at,
                    raw_response=item,
                )
            )
        source.raw_response = json.dumps(payload, ensure_ascii=False)
        logger.debug(
            "bilibili fetch latest videos parsed source_id=%s mid=%s raw_count=%s snapshot_count=%s",
            source.id,
            mid,
            len(vlist),
            len(snapshots),
        )
        return snapshots

    @staticmethod
    def _build_headers(mid: str, bilibili_cookie: str | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": "https://space.bilibili.com",
            "Referer": f"https://space.bilibili.com/{mid}/video",
        }
        cookie = (bilibili_cookie or "").strip()
        if cookie:
            headers["Cookie"] = cookie
        return headers


def get_video_source_adapter(platform: str) -> VideoSourceAdapter:
    normalized = platform.strip().lower()
    if normalized == "bilibili":
        return BilibiliVideoSourceAdapter()
    raise ValueError(f"Unsupported video platform: {platform}")
