"""Quill delta JSON 素材解析。

`var/kb_industry/markdown/*.md` 的真实结构：元数据头（`# 标题` + `> 来源/URL/...`）
后跟一行 Quill delta JSON。delta 中：

- 主流程 group（键 `0`，zoneType `Z`）保存正文，`insert` 为字符串时按序拼接；
- 标题有两种编码：标准 Quill（换行 op 带 `attributes.heading`）与编辑器标记
  （`*` 标记 op 带 `attributes.heading`，其后紧跟标题文本）；
- 表格内容保存在独立 group（zoneType `R`/`C` 的结构组 + `x<row>x<col>` 单元格组），
  由主流程的 `aceTable` 标记引用，解析时就地内联为 Markdown 表格；
- `attachments` 忽略，仅在 `source_meta` 记录数量。

解析失败（非 JSON / 结构异常）回退为纯文本返回，不抛异常。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_META_PAIR_RE = re.compile(r"([^:：·]+?)\s*[:：]\s*([^·]+)")
_DIGITS_RE = re.compile(r"\d+")
_MARKER_INSERTS = {"*", "", " "}


@dataclass
class ParsedDoc:
    title: str
    markdown: str
    source_meta: dict[str, Any] = field(default_factory=dict)


def parse_source_file(path: Path) -> ParsedDoc:
    """解析 `var/kb_industry/markdown/` 下的素材文件（元数据头 + delta JSON）。"""
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    json_index = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith("{")), None
    )
    header_lines = lines[:json_index] if json_index is not None else []
    body_lines = lines[json_index:] if json_index is not None else []

    title, source_meta = _parse_header(header_lines)
    markdown = ""
    parse_mode = "text"
    if json_index is not None:
        try:
            payload = json.loads("\n".join(body_lines))
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            parse_mode = "delta"
            markdown = delta_json_to_markdown(payload)
            source_meta["attachment_count"] = len(payload.get("attachments") or [])

    if parse_mode == "text":
        markdown = ("\n".join(body_lines) if json_index is not None else raw).strip()
        source_meta.setdefault("attachment_count", 0)

    if not title:
        title = _first_heading(markdown) or path.stem
    source_meta["file"] = path.name
    source_meta["parse_mode"] = parse_mode
    return ParsedDoc(title=title, markdown=markdown, source_meta=source_meta)


def delta_json_to_markdown(payload: dict) -> str:
    """把 Quill delta payload 渲染为 Markdown（标题/段落/表格），失败时返回空串。"""
    if not isinstance(payload, dict):
        return ""
    deltas = payload.get("deltas")
    if not isinstance(deltas, dict) or not deltas:
        return ""
    groups = {str(key): value for key, value in deltas.items() if isinstance(value, dict)}
    if not groups:
        return ""

    main_key = "0" if "0" in groups else next(iter(groups))
    consumed: set[str] = {main_key}
    lines = _render_ops(groups[main_key].get("ops") or [], groups, consumed)

    extras: list[str] = []
    for key, group in groups.items():
        if key in consumed:
            continue
        block = _render_ops(group.get("ops") or [], groups, consumed)
        if any(line.strip() for line in block):
            extras.extend(block)
    if extras:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(extras)

    return _clean_markdown("\n".join(lines))


def _parse_header(lines: list[str]) -> tuple[str, dict[str, Any]]:
    title = ""
    meta: dict[str, Any] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            if not title:
                title = stripped[2:].strip()
            continue
        if not stripped.startswith(">"):
            continue
        content = stripped[1:].strip()
        key, sep, rest = content.partition(":")
        if sep and key.strip() in {"来源", "URL"}:
            # 这两个字段的值自身含 "·"（如「…学习中心(school.jinritemai.com) · 官方公开课程」）
            _store_meta(meta, key.strip(), rest.strip())
            continue
        for pair_key, pair_value in _META_PAIR_RE.findall(content):
            _store_meta(meta, pair_key.strip(), pair_value.strip())
    return title, meta


def _store_meta(meta: dict[str, Any], key: str, value: str) -> None:
    if key == "来源":
        meta["source"] = value
    elif key.upper() == "URL":
        meta["source_url"] = value
    elif key == "字数":
        meta["word_count"] = _to_int(value)
    elif key == "折算页数":
        meta["pages_estimate"] = value
    elif key == "浏览量":
        meta["views"] = _to_int(value)
    elif key == "更新时间":
        meta["updated_at"] = value
    else:
        meta[key] = value


def _to_int(value: str) -> int | None:
    match = _DIGITS_RE.search(value)
    return int(match.group()) if match else None


def _first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped:
            break
    return ""


def _heading_level(attrs: dict) -> int | None:
    if "heading" not in attrs:
        return None
    value = attrs.get("heading")
    if value is None or value is False:
        return None
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return value if 1 <= value <= 6 else 1
    if isinstance(value, str):
        text = value.strip().lower()
        if text.startswith("h") and text[1:].isdigit():
            level = int(text[1:])
        elif text.isdigit():
            level = int(text)
        else:
            return 1
        return level if 1 <= level <= 6 else 1
    return 1


def _render_ops(ops: list, groups: dict[str, dict], consumed: set[str]) -> list[str]:
    lines: list[str] = []
    buf: list[str] = []
    pending_heading: int | None = None

    def close(level: int | None) -> None:
        nonlocal buf
        text = "".join(buf).strip()
        buf = []
        if not text:
            if lines and lines[-1] != "":
                lines.append("")
            return
        lines.append("#" * level + " " + text if level else text)

    for op in ops:
        if not isinstance(op, dict):
            continue
        attrs = op.get("attributes")
        if not isinstance(attrs, dict):
            attrs = {}
        insert = op.get("insert")
        if not isinstance(insert, str) or insert == "":
            continue

        heading = _heading_level(attrs)
        if "aceTable" in attrs:
            close(pending_heading)
            pending_heading = None
            lines.extend(_render_table(str(attrs.get("aceTable") or ""), groups, consumed))
            continue
        if "lmkr" in attrs and insert.strip() in _MARKER_INSERTS:
            if heading is not None and not attrs.get("list"):
                pending_heading = heading
            continue
        if "IMAGE" in attrs or "fileSrc" in attrs:
            continue

        text_heading = heading if heading is not None and not attrs.get("list") else None
        if text_heading is not None and "\n" not in insert:
            pending_heading = text_heading
        parts = insert.split("\n")
        for index, part in enumerate(parts):
            if part:
                buf.append(part)
            if index < len(parts) - 1:
                close(text_heading if text_heading is not None else pending_heading)
                pending_heading = None

    close(pending_heading)
    return lines


def _render_table(ref_value: str, groups: dict[str, dict], consumed: set[str]) -> list[str]:
    parts = ref_value.split()
    if len(parts) < 2:
        return []
    rows_group = groups.get(parts[0])
    cols_group = groups.get(parts[1])
    if not isinstance(rows_group, dict) or not isinstance(cols_group, dict):
        return []
    consumed.add(parts[0])
    consumed.add(parts[1])
    row_ids = _group_ref_ids(rows_group)
    col_ids = _group_ref_ids(cols_group)
    if not row_ids or not col_ids:
        return []

    lines: list[str] = []
    for index, row_id in enumerate(row_ids):
        cells = []
        for col_id in col_ids:
            key = f"x{row_id}x{col_id}"
            consumed.add(key)
            cells.append(_cell_text(groups.get(key)))
        lines.append("| " + " | ".join(cells) + " |")
        if index == 0:
            lines.append("| " + " | ".join("---" for _ in col_ids) + " |")
    return lines


def _group_ref_ids(group: dict) -> list[str]:
    ids: list[str] = []
    for op in group.get("ops") or []:
        if not isinstance(op, dict):
            continue
        insert = op.get("insert")
        if isinstance(insert, dict) and isinstance(insert.get("id"), str):
            ids.append(insert["id"])
    return ids


def _cell_text(group: dict | None) -> str:
    if not isinstance(group, dict):
        return ""
    parts = [
        op.get("insert")
        for op in group.get("ops") or []
        if isinstance(op, dict) and isinstance(op.get("insert"), str)
    ]
    text = " ".join("".join(parts).split())
    return text.replace("|", "\\|")


def _clean_markdown(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line and lines and not lines[-1]:
            continue
        lines.append(line)
    return "\n".join(lines).strip()
