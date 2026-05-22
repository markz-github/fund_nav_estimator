from __future__ import annotations

import re


def normalize_markdown_text(value: str) -> str:
    normalized = value.strip()
    normalized = re.sub(r"(?<=\d)\\\.(?=\d)", ".", normalized)
    normalized = re.sub(r"(?m)^(\s*)(\d+)\\\.(\s+)", r"\1\2.\3", normalized)
    normalized = re.sub(r"(?m)^(\s*#{1,6}\s+\d+)\\\.(\s+)", r"\1.\2", normalized)
    return normalized


def markdown_output_instruction() -> str:
    return (
        "输出格式要求：请以 Markdown 格式输出；使用 #、##、### 组织标题层级；"
        "使用有序列表和无序列表归纳要点；重要观点使用 **加粗**；"
        "不要输出 HTML；不要把正文包裹在 ```markdown 代码块中。"
    )
