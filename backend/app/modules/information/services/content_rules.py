from __future__ import annotations

from app.modules.information.services.common import *


class ContentRules:
    @staticmethod
    def _embedded_generation_error(provider: str, note_text: str | None) -> str | None:
        if not note_text:
            return None
        content_lines = [
            line.strip()
            for line in note_text.splitlines()
            if line.strip() and not line.strip().startswith("> 来源链接")
        ]
        content = "\n".join(content_lines).strip()
        if content in {"'NoneType' object is not iterable", "NoneType object is not iterable"}:
            return f"{provider} returned exception text as markdown: {content}"
        lower_content = content.lower()
        if (
            "api call failed after 3 retries" in lower_content
            and "non-streaming api call timed out" in lower_content
            and "with no response" in lower_content
        ):
            return f"{provider} returned exception text as markdown: {content}"
        return None

    @staticmethod
    def _parse_keywords(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        return [
            item.strip().lower()
            for item in re.split(r"[\n,，;；]+", raw_value)
            if item.strip()
        ]

    def _apply_article_filter(
        self,
        target,
        keywords: list[str],
        *,
        context: str,
        source_id: int | None = None,
    ) -> bool:
        if not self._article_matches_filter(target, keywords):
            return False
        if hasattr(target, "status"):
            target.status = "invalid_content"
        logger.debug(
            "%s marked filtered article invalid source_id=%s platform=%s external_video_id=%s title=%s",
            context,
            source_id,
            getattr(target, "platform", None),
            getattr(target, "external_video_id", None),
            str(getattr(target, "title", ""))[:120],
        )
        return True

    @staticmethod
    def _article_matches_filter(target, keywords: list[str]) -> bool:
        if getattr(target, "content_type", None) != "article" or not keywords:
            return False
        searchable_text = f"{getattr(target, 'title', '')}\n{getattr(target, 'content_text', '') or ''}".lower()
        return any(keyword in searchable_text for keyword in keywords)
