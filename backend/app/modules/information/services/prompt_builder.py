from __future__ import annotations

from app.modules.information.services.common import *


class PromptBuilder(InformationServiceBase):
    def _build_summary_prompt(
        self,
        platform: str,
        summary_date: date,
        notes: list[InformationVideoNote],
        instruction: str = "",
        document_template: str = "",
        period_end: date | None = None,
        category: str = DEFAULT_CATEGORY,
    ) -> str:
        blocks = []
        for idx, note in enumerate(notes, start=1):
            video = self.db.get(InformationVideo, note.video_id)
            source = self.db.get(InformationVideoSource, video.source_id) if video is not None else None
            author = (
                source.source_name
                if source is not None and source.source_name
                else video.author_name
                if video is not None and video.author_name
                else "未知作者"
            )
            title = video.title if video is not None and video.title else f"视频 {note.video_id}"
            url = video.video_url if video is not None and video.video_url else ""
            published_at = video.published_at.isoformat(sep=" ") if video is not None and video.published_at else "未知"
            metadata = [
                f"发布账号：{author}",
                f"作者：{author}",
                f"标题：{title}",
                f"发布时间：{published_at}",
            ]
            if url:
                metadata.append(f"链接：{url}")
            blocks.append(f"## 视频 {idx}\n" + "\n".join(metadata) + f"\n\n{note.note_text or ''}")
        instruction_text = instruction.strip()
        instruction_block = f"补充说明：\n{instruction_text}\n\n" if instruction_text else ""
        period_text = (
            f"{summary_date.isoformat()} 至 {(period_end or summary_date + timedelta(days=6)).isoformat()}"
            if period_end is not None and period_end != summary_date
            else summary_date.isoformat()
        )
        template_text = document_template.strip()
        template_block = (
            "输出文档模板：\n"
            "请严格按以下 Markdown 结构输出；可以在每个章节内增减条目，但不要删除章节标题，不要额外输出一级标题。\n"
            f"{template_text}\n\n"
            if template_text
            else ""
        )
        return (
            f"请将以下 {platform} 视频的 Bilinote 文字总结汇总成一篇中文汇总文档。\n"
            f"汇总周期：{period_text}\n"
            f"视频分类：{normalize_category(category)}\n"
            f"{instruction_block}"
            f"{template_block}"
            "要求：提炼主题、关键观点、可执行信息和待跟进事项；去重，按主题分组。\n"
            "重点标注要求：请主动识别值得关注的核心结论、风险信号、分歧观点和行动建议，使用 **重点：...** 或 **风险：...** 进行醒目标注。\n"
            "标题要求：不要额外输出封面标题或一级标题，正文直接从 ## 二级标题开始。\n"
            f"{markdown_output_instruction()}\n\n"
            + "\n\n".join(blocks)
        )

    def _build_article_summary_prompt(self, article: InformationVideo) -> str:
        source = self.db.get(InformationVideoSource, article.source_id)
        author = source.source_name if source is not None and source.source_name else article.author_name or "未知作者"
        published_at = article.published_at.isoformat(sep=" ") if article.published_at else "未知"
        url = article.video_url or ""
        metadata = [
            f"作者：{author}",
            f"标题：{article.title}",
            f"发布时间：{published_at}",
        ]
        if url:
            metadata.append(f"链接：{url}")
        return (
            "请将以下 B站图文投稿整理成一篇中文 Markdown 摘要。\n"
            "这是单条图文投稿的直接总结任务，不要合并其他视频笔记，也不要假设存在 Bilinote 总结。\n"
            "要求：提炼核心观点、重要依据、风险信号、分歧观点和可跟进行动；保留作者和发布时间背景。\n"
            f"{markdown_output_instruction()}\n\n"
            + "\n".join(metadata)
            + "\n\n正文：\n"
            + (article.content_text or "")
        )
