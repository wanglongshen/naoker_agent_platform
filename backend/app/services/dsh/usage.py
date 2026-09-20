"""DSH usage 采集：从会话 JSONL(zstd) 累加 `assistant/message.usage`。

证据：
- 会话文件布局（`<home>/sessions/<项目>/<会话>/session.jsonl.zstd`，JSONL+zstd）：`dsh-platform/NOTES.md` 第 1 项。
- `assistant/message` 事件带可选 `usage`：`deepseek-harness/packages/core/session/src/types.ts:269-277`。
- `TokenUsage` 字段（inputTokens/outputTokens/cacheReadTokens?/cacheWriteTokens?/reasoningTokens?）：
  `deepseek-harness/packages/llm/llm/src/types.ts:135-141`。
- 解压/逐行解析口径与既有同步器一致：`app/services/dsh/session_sync.py:39-62`。

口径：只累加 `time`（毫秒）落在 `[since, until]`（秒）窗口内的事件；坏行/坏文件跳过，
采集失败不抛异常（计费按 0 处理，由调用方决定降级）。
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from pathlib import Path

import zstandard

logger = logging.getLogger("dsh.usage")

USAGE_FIELDS = (
    "inputTokens",
    "outputTokens",
    "cacheReadTokens",
    "cacheWriteTokens",
    "reasoningTokens",
)
_SESSION_PATTERNS = ("session.jsonl.zstd", "session.jsonl")


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _iter_lines(path: Path) -> Iterator[str]:
    with path.open("rb") as fh:
        if path.name.endswith(".zstd"):
            with zstandard.ZstdDecompressor().stream_reader(fh) as reader:
                with io.BufferedReader(reader) as buffered:
                    for raw in buffered:
                        yield raw.decode("utf-8", errors="replace")
        else:
            for raw in fh:
                yield raw.decode("utf-8", errors="replace")


def _sum_file(path: Path, since_ms: float, until_ms: float) -> int:
    total = 0
    for line in _iter_lines(path):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant/message":
            continue
        time_ms = event.get("time")
        if isinstance(time_ms, bool) or not isinstance(time_ms, (int, float)):
            continue
        if time_ms < since_ms or time_ms > until_ms:
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict):
            data = event.get("data")
            usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict):
            continue
        total += sum(_as_int(usage.get(field)) for field in USAGE_FIELDS)
    return total


def collect_dsh_usage(home_dir: Path, *, since: float, until: float) -> int:
    """累加 `<home>/sessions/**/session.jsonl.zstd` 中窗口内事件的 usage tokens。

    `since` / `until` 为 epoch 秒（含端点），事件 `time` 为 epoch 毫秒。
    目录不存在返回 0；坏文件（截断/非 zstd/IO 错误）与坏行整段跳过，不抛异常。
    """
    sessions_root = Path(home_dir) / "sessions"
    if not sessions_root.is_dir():
        return 0
    since_ms = since * 1000
    until_ms = until * 1000
    total = 0
    seen: set[Path] = set()
    for pattern in _SESSION_PATTERNS:
        for path in sessions_root.rglob(pattern):
            if path in seen:
                continue
            seen.add(path)
            try:
                total += _sum_file(path, since_ms, until_ms)
            except Exception:  # noqa: BLE001 - 坏文件跳过，usage 采集不阻断计费
                logger.debug("skip unreadable dsh session file: %s", path, exc_info=True)
    return total
