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
    content_type: str = "video"
    content_text: str | None = None


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
                    content_type="video",
                )
            )
        source.raw_response = json.dumps(payload, ensure_ascii=False)
        snapshots.extend(self._fetch_latest_articles(source, mid, page_size, headers))
        logger.debug(
            "bilibili fetch latest videos parsed source_id=%s mid=%s raw_count=%s snapshot_count=%s",
            source.id,
            mid,
            len(vlist),
            len(snapshots),
        )
        return snapshots

    def _fetch_latest_articles(
        self,
        source: InformationVideoSource,
        mid: str,
        limit: int,
        headers: dict[str, str],
    ) -> list[VideoSnapshot]:
        try:
            response = requests.get(
                "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space",
                params={
                    "host_mid": mid,
                    "features": "itemOpusStyle",
                    "offset": "",
                },
                headers={**headers, "Referer": f"https://space.bilibili.com/{mid}/dynamic"},
                timeout=20,
            )
            logger.debug(
                "bilibili fetch latest articles response source_id=%s mid=%s http_status=%s",
                source.id,
                mid,
                response.status_code,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("bilibili fetch latest articles skipped source_id=%s mid=%s error=%r", source.id, mid, exc)
            return []

        code = payload.get("code")
        if code not in (None, 0):
            logger.warning(
                "bilibili fetch latest articles skipped source_id=%s mid=%s code=%s message=%s",
                source.id,
                mid,
                code,
                payload.get("message"),
            )
            return []

        snapshots: list[VideoSnapshot] = []
        for item in (payload.get("data", {}).get("items", []) or [])[:limit]:
            snapshot = self._article_snapshot_from_dynamic_item(source, item)
            if snapshot is not None:
                snapshots.append(snapshot)
        logger.debug(
            "bilibili fetch latest articles parsed source_id=%s mid=%s snapshot_count=%s",
            source.id,
            mid,
            len(snapshots),
        )
        return snapshots

    def _article_snapshot_from_dynamic_item(
        self,
        source: InformationVideoSource,
        item: dict,
    ) -> VideoSnapshot | None:
        item_type = str(item.get("type") or "")
        if item_type in {"DYNAMIC_TYPE_AV", "DYNAMIC_TYPE_PGC"}:
            return None

        modules = item.get("modules") or {}
        dynamic = modules.get("module_dynamic") or {}
        major = dynamic.get("major") or {}
        major_type = str(major.get("type") or "")
        if major_type not in {"MAJOR_TYPE_OPUS", "MAJOR_TYPE_ARTICLE", "MAJOR_TYPE_DRAW", "MAJOR_TYPE_NONE"}:
            return None

        opus = major.get("opus") or {}
        article = major.get("article") or {}
        draw = major.get("draw") or {}
        desc = dynamic.get("desc") or {}
        author = modules.get("module_author") or {}

        external_id = str(opus.get("opus_id") or article.get("id") or item.get("id_str") or item.get("id") or "").strip()
        if not external_id:
            return None
        external_video_id = f"article_{external_id}"
        title = str(opus.get("title") or article.get("title") or desc.get("text") or external_video_id).strip()
        if len(title) > 80:
            title = title[:80]
        content_text = self._extract_article_text(opus, article, draw, desc)
        if not content_text:
            return None

        published_at = None
        timestamp = author.get("pub_ts") or item.get("pub_ts")
        if isinstance(timestamp, (int, float)):
            published_at = datetime.fromtimestamp(timestamp)
        url = str(opus.get("jump_url") or article.get("jump_url") or item.get("jump_url") or "").strip()
        if url.startswith("//"):
            url = f"https:{url}"
        if not url:
            url = f"https://www.bilibili.com/opus/{external_id}"
        return VideoSnapshot(
            platform=self.platform,
            external_video_id=external_video_id,
            title=title or external_video_id,
            video_url=url,
            author_name=source.source_name,
            published_at=published_at,
            raw_response=item,
            content_type="article",
            content_text=content_text,
        )

    @classmethod
    def _extract_article_text(cls, *parts: dict) -> str:
        values: list[str] = []
        for part in parts:
            cls._collect_text_values(part, values)
        deduped = list(dict.fromkeys(value.strip() for value in values if value and value.strip()))
        return "\n\n".join(deduped)

    @classmethod
    def _collect_text_values(cls, value, values: list[str]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"text", "raw_text", "summary", "desc"} and isinstance(child, str):
                    values.append(child)
                else:
                    cls._collect_text_values(child, values)
        elif isinstance(value, list):
            for item in value:
                cls._collect_text_values(item, values)

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
