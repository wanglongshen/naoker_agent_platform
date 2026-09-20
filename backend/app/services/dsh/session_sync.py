from __future__ import annotations

import gzip
import io
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import zstandard
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dsh import DshSession

logger = logging.getLogger("dsh.session_sync")

_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_GZIP_MAGIC = b"\x1f\x8b"

# 事件行结构（seq/type/time/data）：deepseek-harness/packages/core/session/src/types.ts:412-415
# writer 端确认（append 时写 seq+time）：deepseek-harness/packages/core/session/src/index.ts:629-631
# header 行键名（type/version/id/createdAt/delegationDepth 等）：
#   deepseek-harness/packages/session/session-persistence-jsonl/src/format.ts:33-63
# session/title 事件 data 键 title：
#   deepseek-harness/packages/session/session-title/src/index.ts:61-68（payload 定义）、:314（fold 读 event.data.title）
# turn/start 事件：deepseek-harness/packages/core/session/src/types.ts:243（data.turn）


@dataclass
class DshSessionRecord:
    id: str
    title: str | None
    turn_count: int
    last_activity_at: datetime | None


def _decode_bytes(raw: bytes) -> bytes:
    if raw.startswith(_ZSTD_MAGIC):
        # DSH 写的是流式 zstd 帧（帧头不含 content size），一次性 API
        # zstandard.decompress() 会抛 "could not determine content size in frame header"。
        return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)).read()
    if raw.startswith(_GZIP_MAGIC):
        return gzip.decompress(raw)
    return raw


def _scan_log(raw: bytes) -> DshSessionRecord | None:
    text = _decode_bytes(raw).decode("utf-8", errors="replace")
    header: dict | None = None
    title: str | None = None
    turn_count = 0
    last_ms: int | None = None

    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("type") == "session":
            header = record
            continue
        etype = record.get("type")
        if etype == "turn/start":
            turn_count += 1
        elif etype == "session/title" and isinstance(record.get("data"), dict):
            candidate = record["data"].get("title")
            if isinstance(candidate, str) and candidate:
                title = candidate[:500]
        time_ms = record.get("time")
        if isinstance(time_ms, (int, float)) and not isinstance(time_ms, bool):
            last_ms = int(time_ms)

    if header is None or not isinstance(header.get("id"), str):
        return None
    if last_ms is None:
        created_ms = header.get("createdAt")
        if isinstance(created_ms, (int, float)) and not isinstance(created_ms, bool):
            last_ms = int(created_ms)
    return DshSessionRecord(
        id=header["id"],
        title=title,
        turn_count=turn_count,
        last_activity_at=(
            datetime.fromtimestamp(last_ms / 1000, tz=UTC)
            if last_ms is not None
            else None
        ),
    )


def iter_sessions(home: Path):
    """递归扫描 <home>/sessions/**/session.jsonl.zstd（或 .jsonl）并解码为记录。"""
    sessions_root = home / "sessions"
    if not home.is_dir() or not sessions_root.is_dir():
        return
    seen: set[str] = set()
    for pattern in ("session.jsonl.zstd", "session.jsonl"):
        for path in sessions_root.rglob(pattern):
            if path in seen:
                continue
            seen.add(path)
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            record = _scan_log(raw)
            if record is not None:
                yield record


async def sync_user_sessions(
    db: AsyncSession, user_id: uuid.UUID, home: Path
) -> int:
    """扫描 home 下全部 DSH 会话 JSONL 并 upsert dsh_sessions。

    仅按 (user_id, dsh_session_id) 插入/更新；home 中已消失的会话行保留（审计）。
    返回新增 + 内容变更的条数；内容未变时不做任何写。
    """
    now = datetime.now(UTC)
    processed = 0
    for record in iter_sessions(home):
        row = (
            await db.execute(
                select(DshSession).where(
                    DshSession.user_id == user_id,
                    DshSession.dsh_session_id == record.id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(
                DshSession(
                    user_id=user_id,
                    dsh_session_id=record.id,
                    title=record.title,
                    turn_count=record.turn_count,
                    last_activity_at=record.last_activity_at,
                    synced_at=now,
                )
            )
            processed += 1
        elif (
            row.title != record.title
            or row.turn_count != record.turn_count
            or row.last_activity_at != record.last_activity_at
        ):
            row.title = record.title
            row.turn_count = record.turn_count
            row.last_activity_at = record.last_activity_at
            row.synced_at = now
            processed += 1
    return processed
