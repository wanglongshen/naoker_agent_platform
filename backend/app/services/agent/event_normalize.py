"""差分前的事件归一化：只抹平易变标识/时间戳，不掩盖语义差异。"""
from __future__ import annotations

import re
from typing import Any

from app.services.agent.langgraph_runner import diff_event_streams

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)?")

NORMALIZATION_RULES = [
    "事件主键 id → <id>",
    "键名 in {created_at, updated_at, started_at, finished_at, completed_at} 的字符串值 → <ts>",
    "任意字符串值中的 UUID 子串 → <uuid>（保留前后缀，如 error-<uuid>）",
    "任意字符串值中的 ISO 时间戳子串 → <ts>",
    "payload.stream_id → 按首次出现顺序编号（stream-1、stream-2…）：该值每次运行随机生成，编号保留流的分组结构",
]

_TS_KEYS = {"created_at", "updated_at", "started_at", "finished_at", "completed_at"}


def _norm_value(key: str | None, value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _norm_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm_value(None, v) for v in value]
    if isinstance(value, str):
        if key in _TS_KEYS and TS_RE.fullmatch(value):
            return "<ts>"
        value = UUID_RE.sub("<uuid>", value)
        value = TS_RE.sub("<ts>", value)
        return value
    return value


def normalize_events(events: list[dict]) -> list[dict]:
    out: list[dict] = []
    stream_map: dict[str, str] = {}
    for event in events:
        item = dict(event)
        if "id" in item:
            item["id"] = "<id>"
        payload = item.get("payload")
        if isinstance(payload, dict):
            payload = dict(payload)
            stream_id = payload.get("stream_id")
            if isinstance(stream_id, str) and stream_id:
                payload["stream_id"] = stream_map.setdefault(
                    stream_id, f"stream-{len(stream_map) + 1}"
                )
            item["payload"] = payload
        item = _norm_value(None, item)
        out.append(item)
    return out


def diff_normalized(old: list[dict], new: list[dict]) -> list[str]:
    return diff_event_streams(normalize_events(old), normalize_events(new))
