from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import re
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import requests

from app.modules.information.models.video_source import InformationVideoSource
from app.modules.information.services.external_call_logging import external_log_json
from app.modules.information.services.external_call_logging import response_log_body
from app.modules.information.services.external_call_logging import sanitize_external_url


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
    duration_seconds: int | None = None


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

    def fetch_link(self, video_url: str, bilibili_cookie: str | None = None) -> VideoSnapshot:
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
        url = "https://api.bilibili.com/x/space/arc/search"
        params = {
            "mid": mid,
            "pn": 1,
            "ps": page_size,
            "order": "pubdate",
            "jsonp": "jsonp",
        }
        logger.info("external request system=bilibili method=GET url=%s params=%s", sanitize_external_url(url), external_log_json(params))
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=60,
        )
        logger.debug(
            "bilibili fetch latest videos response source_id=%s mid=%s http_status=%s",
            source.id,
            mid,
            response.status_code,
        )
        payload = response_log_body(response)
        logger.info(
            "external response system=bilibili method=GET url=%s status=%s body=%s",
            sanitize_external_url(url),
            response.status_code,
            external_log_json(payload),
        )
        response.raise_for_status()
        if not isinstance(payload, dict):
            payload = {"data": payload}
        code = payload.get("code")
        if code not in (None, 0):
            if code == -799:
                logger.info(
                    "bilibili fetch latest videos rate limited source_id=%s mid=%s code=%s message=%s",
                    source.id,
                    mid,
                    code,
                    payload.get("message"),
                )
                source.raw_response = json.dumps(payload, ensure_ascii=False)
                return []
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
            duration_seconds = self._duration_seconds(item.get("length") or item.get("duration"))
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
                    duration_seconds=duration_seconds,
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

    def fetch_link(self, video_url: str, bilibili_cookie: str | None = None) -> VideoSnapshot:
        resolved_url = self._resolve_url(video_url, bilibili_cookie)
        parsed = self._parse_bilibili_url(resolved_url)
        headers = self._build_headers("0", bilibili_cookie)
        if parsed["type"] == "video":
            return self._fetch_video_detail(str(parsed["id"]), resolved_url, headers)
        return self._fetch_article_detail(str(parsed["id"]), str(parsed["type"]), resolved_url, headers)

    def _fetch_video_detail(self, bvid: str, original_url: str, headers: dict[str, str]) -> VideoSnapshot:
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {"aid": bvid[2:]} if bvid.lower().startswith("av") else {"bvid": bvid}
        logger.info("external request system=bilibili method=GET url=%s params=%s", sanitize_external_url(url), external_log_json(params))
        response = requests.get(url, params=params, headers={**headers, "Referer": original_url}, timeout=60)
        payload = response_log_body(response)
        logger.info(
            "external response system=bilibili method=GET url=%s status=%s body=%s",
            sanitize_external_url(url),
            response.status_code,
            external_log_json(payload),
        )
        response.raise_for_status()
        if not isinstance(payload, dict):
            payload = {"data": payload}
        code = payload.get("code")
        if code not in (None, 0):
            message = str(payload.get("message") or "unknown bilibili api error")
            raise RuntimeError(f"Bilibili API returned code={code};message={message}")
        data = payload.get("data") or {}
        owner = data.get("owner") or {}
        actual_bvid = str(data.get("bvid") or bvid).strip()
        pubdate = data.get("pubdate") or data.get("ctime")
        published_at = datetime.fromtimestamp(pubdate) if isinstance(pubdate, (int, float)) else None
        return VideoSnapshot(
            platform=self.platform,
            external_video_id=actual_bvid,
            title=str(data.get("title") or actual_bvid).strip() or actual_bvid,
            video_url=f"https://www.bilibili.com/video/{actual_bvid}",
            author_name=str(owner.get("name") or "").strip() or None,
            published_at=published_at,
            raw_response=payload,
            content_type="video",
            duration_seconds=self._duration_seconds(data.get("duration")),
        )

    def _fetch_article_detail(self, content_id: str, content_kind: str, original_url: str, headers: dict[str, str]) -> VideoSnapshot:
        if content_kind == "read":
            snapshot = self._fetch_read_article_detail(content_id, original_url, headers)
            if snapshot is not None:
                return snapshot

        url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"
        params = {"id": content_id, "features": "itemOpusStyle"}
        logger.info("external request system=bilibili method=GET url=%s params=%s", sanitize_external_url(url), external_log_json(params))
        response = requests.get(url, params=params, headers={**headers, "Referer": original_url}, timeout=60)
        payload = response_log_body(response)
        logger.info(
            "external response system=bilibili method=GET url=%s status=%s body=%s",
            sanitize_external_url(url),
            response.status_code,
            external_log_json(payload),
        )
        response.raise_for_status()
        if not isinstance(payload, dict):
            payload = {"data": payload}
        code = payload.get("code")
        if code not in (None, 0):
            message = str(payload.get("message") or "unknown bilibili api error")
            raise RuntimeError(f"Bilibili API returned code={code};message={message}")
        item = (payload.get("data") or {}).get("item") or {}
        snapshot = self._article_snapshot_from_dynamic_item(self._manual_source(), item)
        if snapshot is None:
            raise ValueError("无法从该 B站图文链接获取正文")
        return snapshot

    def _fetch_read_article_detail(self, article_id: str, original_url: str, headers: dict[str, str]) -> VideoSnapshot | None:
        url = "https://api.bilibili.com/x/article/view"
        params = {"id": article_id}
        logger.info("external request system=bilibili method=GET url=%s params=%s", sanitize_external_url(url), external_log_json(params))
        response = requests.get(url, params=params, headers={**headers, "Referer": original_url}, timeout=60)
        payload = response_log_body(response)
        logger.info(
            "external response system=bilibili method=GET url=%s status=%s body=%s",
            sanitize_external_url(url),
            response.status_code,
            external_log_json(payload),
        )
        response.raise_for_status()
        if not isinstance(payload, dict):
            payload = {"data": payload}
        code = payload.get("code")
        if code not in (None, 0):
            return None
        data = payload.get("data") or {}
        content_text = self._extract_article_text(data)
        if not content_text:
            return None
        author = data.get("author") or {}
        timestamp = data.get("publish_time") or data.get("ctime")
        published_at = datetime.fromtimestamp(timestamp) if isinstance(timestamp, (int, float)) else None
        external_id = f"article_cv{article_id}"
        return VideoSnapshot(
            platform=self.platform,
            external_video_id=external_id,
            title=str(data.get("title") or external_id).strip() or external_id,
            video_url=original_url,
            author_name=str(author.get("name") or data.get("author_name") or "").strip() or None,
            published_at=published_at,
            raw_response=payload,
            content_type="article",
            content_text=content_text,
        )

    def _fetch_latest_articles(
        self,
        source: InformationVideoSource,
        mid: str,
        limit: int,
        headers: dict[str, str],
    ) -> list[VideoSnapshot]:
        try:
            url = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
            params = {
                "host_mid": mid,
                "features": "itemOpusStyle",
                "offset": "",
            }
            logger.info("external request system=bilibili method=GET url=%s params=%s", sanitize_external_url(url), external_log_json(params))
            response = requests.get(
                url,
                params=params,
                headers={**headers, "Referer": f"https://space.bilibili.com/{mid}/dynamic"},
                timeout=60,
            )
            logger.debug(
                "bilibili fetch latest articles response source_id=%s mid=%s http_status=%s",
                source.id,
                mid,
                response.status_code,
            )
            payload = response_log_body(response)
            logger.info(
                "external response system=bilibili method=GET url=%s status=%s body=%s",
                sanitize_external_url(url),
                response.status_code,
                external_log_json(payload),
            )
            response.raise_for_status()
            if not isinstance(payload, dict):
                payload = {"data": payload}
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

        published_at = self._published_at_from_article_item(item, author, opus, article, draw)
        url = str(opus.get("jump_url") or article.get("jump_url") or item.get("jump_url") or "").strip()
        if url.startswith("//"):
            url = f"https:{url}"
        if not url:
            url = f"https://www.bilibili.com/opus/{external_id}"
        author_name = str(author.get("name") or source.source_name or "").strip() or None
        return VideoSnapshot(
            platform=self.platform,
            external_video_id=external_video_id,
            title=title or external_video_id,
            video_url=url,
            author_name=author_name,
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
                if key in {"text", "raw_text", "summary", "desc", "content"} and isinstance(child, str):
                    values.append(child)
                else:
                    cls._collect_text_values(child, values)
        elif isinstance(value, list):
            for item in value:
                cls._collect_text_values(item, values)

    @staticmethod
    def _published_at_from_article_item(
        item: dict,
        author: dict,
        opus: dict,
        article: dict,
        draw: dict,
    ) -> datetime | None:
        candidates = (
            author.get("pub_ts"),
            item.get("pub_ts"),
            (item.get("basic") or {}).get("pub_ts"),
            opus.get("pub_ts"),
            article.get("pub_ts"),
            draw.get("pub_ts"),
            item.get("ctime"),
            (item.get("basic") or {}).get("ctime"),
            opus.get("ctime"),
            article.get("ctime"),
            draw.get("ctime"),
        )
        for timestamp in candidates:
            if isinstance(timestamp, (int, float)):
                return datetime.fromtimestamp(timestamp)
            if isinstance(timestamp, str) and timestamp.strip().isdigit():
                return datetime.fromtimestamp(int(timestamp.strip()))
        return None

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

    @staticmethod
    def _resolve_url(video_url: str, bilibili_cookie: str | None = None) -> str:
        text = str(video_url or "").strip()
        if not text:
            raise ValueError("链接不能为空")
        if not re.match(r"^https?://", text, re.IGNORECASE):
            text = f"https://{text}"
        parsed = urlparse(text)
        if parsed.netloc.lower() not in {"b23.tv", "bili2233.cn"}:
            return text
        headers = BilibiliVideoSourceAdapter._build_headers("0", bilibili_cookie)
        response = requests.get(text, headers=headers, allow_redirects=True, timeout=30)
        response.raise_for_status()
        return response.url or text

    @staticmethod
    def _parse_bilibili_url(video_url: str) -> dict[str, str]:
        parsed = urlparse(video_url)
        host = parsed.netloc.lower()
        path = parsed.path.strip("/")
        if "bilibili.com" not in host:
            raise ValueError("目前只支持 B站链接")

        video_match = re.search(r"(BV[0-9A-Za-z]+)", path)
        if video_match:
            return {"type": "video", "id": video_match.group(1)}
        av_match = re.search(r"(?:^|/)av(\d+)(?:/|$)", path, re.IGNORECASE)
        if av_match:
            return {"type": "video", "id": f"av{av_match.group(1)}"}
        opus_match = re.search(r"(?:^|/)opus/(\d+)", path)
        if opus_match:
            return {"type": "opus", "id": opus_match.group(1)}
        dynamic_match = re.search(r"(?:^|/)(?:dynamic|t)/(\d+)", path)
        if dynamic_match:
            return {"type": "dynamic", "id": dynamic_match.group(1)}
        if host == "t.bilibili.com" and path.isdigit():
            return {"type": "dynamic", "id": path}
        read_match = re.search(r"(?:^|/)read/(?:cv)?(\d+)", path, re.IGNORECASE)
        if read_match:
            return {"type": "read", "id": read_match.group(1)}

        query = parse_qs(parsed.query)
        for key in ("bvid", "BVID"):
            if query.get(key):
                return {"type": "video", "id": query[key][0]}
        if query.get("id"):
            return {"type": "dynamic", "id": query["id"][0]}
        raise ValueError("无法识别该 B站链接的内容类型")

    @staticmethod
    def _manual_source() -> InformationVideoSource:
        return InformationVideoSource(
            platform="bilibili",
            source_name="手动录入",
            external_source_id="manual",
            category="手动录入",
        )

    @staticmethod
    def _duration_seconds(value) -> int | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value) if value >= 0 else None
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        parts = text.split(":")
        if not all(part.isdigit() for part in parts):
            return None
        if len(parts) == 2:
            minutes, seconds = (int(part) for part in parts)
            return minutes * 60 + seconds
        if len(parts) == 3:
            hours, minutes, seconds = (int(part) for part in parts)
            return hours * 3600 + minutes * 60 + seconds
        return None


def get_video_source_adapter(platform: str) -> VideoSourceAdapter:
    normalized = platform.strip().lower()
    if normalized == "bilibili":
        return BilibiliVideoSourceAdapter()
    raise ValueError(f"Unsupported video platform: {platform}")
