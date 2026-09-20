"""标题感知切分：段落优先聚合，超长段落按句子边界切，overlap 取尾部字符。

`section_path` 由标题栈维护（如 `投放手册 > 出价策略`）；切分参数默认 512/64
（spec §3）。任何 chunk 长度不超过 `size + overlap`。

兜底：正文非空但只含标题（一图读懂/一页纸类微内容）时，退化为「整篇一个
chunk」（按 `size + overlap` 截断），避免素材被静默丢弃。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SENTENCE_RE = re.compile(r"(?<=[。！？!?\n])")


@dataclass(frozen=True)
class Chunk:
    section_path: str
    content: str
    index: int


def chunk_markdown(
    markdown: str, *, size: int = 512, overlap: int = 64
) -> list[Chunk]:
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")

    chunks: list[Chunk] = []
    stack: list[tuple[int, str]] = []
    section_path = ""
    buf: list[str] = []
    buf_len = 0
    limit = size + overlap

    def flush(carry: bool) -> None:
        nonlocal buf, buf_len
        content = "".join(buf).strip()
        buf = []
        buf_len = 0
        if not content:
            return
        chunks.append(Chunk(section_path=section_path, content=content, index=len(chunks)))
        if carry and overlap > 0:
            tail = content[-overlap:]
            buf = [tail]
            buf_len = len(tail)

    def add_unit(unit: str) -> None:
        nonlocal buf_len
        if not unit:
            return
        if len(unit) > size:
            for start in range(0, len(unit), size):
                add_unit(unit[start : start + size])
            return
        if buf and buf_len + len(unit) > limit:
            flush(carry=True)
        buf.append(unit)
        buf_len += len(unit)

    for kind, *payload in _iter_blocks(markdown):
        if kind == "heading":
            level, title = payload
            flush(carry=False)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            section_path = " > ".join(text for _, text in stack)
            continue

        text = payload[0]
        units = _split_sentences(text)
        if not units:
            continue
        if buf and buf_len + 2 <= limit:
            buf.append("\n\n")
            buf_len += 2
        for sentence in units:
            add_unit(sentence)

    flush(carry=False)
    if not chunks:
        fallback = markdown.strip()
        if fallback:
            chunks.append(
                Chunk(section_path="", content=fallback[:limit], index=0)
            )
    return chunks


def _iter_blocks(markdown: str):
    paragraph: list[str] = []
    in_fence = False

    def take() -> list[str]:
        nonlocal paragraph
        text = "\n".join(paragraph).strip()
        paragraph = []
        return [text] if text else []

    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            paragraph.append(line)
            continue
        match = None if in_fence else _HEADING_RE.match(line)
        if match:
            for text in take():
                yield ("para", text)
            yield ("heading", len(match.group(1)), match.group(2).strip())
            continue
        if not in_fence and not line.strip():
            for text in take():
                yield ("para", text)
            continue
        paragraph.append(line)
    for text in take():
        yield ("para", text)


def _split_sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE_RE.split(text) if part.strip()]
