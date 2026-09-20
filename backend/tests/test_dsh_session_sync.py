import gzip
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import zstandard
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.base import Base
from app.models.dsh import DshSession

pytestmark = pytest.mark.asyncio

USER_UUID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _header(sess_id: str, created_ms: int = 1700000000000) -> str:
    return json.dumps(
        {
            "type": "session",
            "version": 0,
            "id": sess_id,
            "createdAt": created_ms,
            "cwd": "C:\\workdir",
            "delegationDepth": 0,
            "agentPreset": "default",
        }
    )


def _line(seq: int, event_type: str, time_ms: int, data: dict) -> str:
    return json.dumps({"seq": seq, "type": event_type, "time": time_ms, "data": data})


def _build_home(tmp_path: Path) -> Path:
    """构造 3 个 DSH JSONL 会话文件：zstd / gzip(伪装 .jsonl.zstd) / 纯文本。"""
    home = tmp_path / "dsh_home"

    sess_a_dir = home / "sessions" / "proj-a" / "sess-a"
    sess_a_dir.mkdir(parents=True)
    a_lines = "\n".join(
        [
            _header("sess-a"),
            _line(0, "turn/start", 1700000000500, {"turn": 1}),
            _line(1, "session/title", 1700000001000, {"title": "stale title", "messageSeqs": [2], "source": {"kind": "fallback"}}),
            _line(2, "user/message", 1700000002000, {"source": {"kind": "user"}, "content": [{"type": "text", "text": "hi"}]}),
            _line(3, "turn/start", 1700000002500, {"turn": 2}),
            _line(4, "session/title", 1700000003000, {"title": "Alpha title", "messageSeqs": [2], "source": {"kind": "fallback"}}),
            _line(5, "assistant/message", 1700000004000, {"message": {"content": [{"type": "text", "text": "ok"}]}}),
        ]
    )
    (sess_a_dir / "session.jsonl.zstd").write_bytes(zstandard.compress(a_lines.encode("utf-8")))

    sess_b_dir = home / "sessions" / "proj-b" / "sess-b"
    sess_b_dir.mkdir(parents=True)
    b_lines = "\n".join(
        [
            _header("sess-b", 1700001000000),
            _line(0, "turn/start", 1700001000500, {"turn": 1}),
            _line(1, "session/title", 1700001001000, {"title": "Beta title", "messageSeqs": [0], "source": {"kind": "user"}}),
        ]
    )
    (sess_b_dir / "session.jsonl.zstd").write_bytes(
        gzip.compress(b_lines.encode("utf-8"))
    )

    sess_c_dir = home / "sessions" / "_no-cwd" / "sess-c"
    sess_c_dir.mkdir(parents=True)
    c_lines = "\n".join(
        [
            _header("sess-c", 1700002000000),
            _line(0, "turn/start", 1700002000500, {"turn": 1}),
            '{"seq":1,"type":"torn-line',  # 坏 JSON 行必须被跳过
            _line(2, "assistant/message", 1700002002000, {"message": {"content": []}}),
        ]
    )
    (sess_c_dir / "session.jsonl").write_text(c_lines + "\n", encoding="utf-8")

    return home


async def test_iter_sessions_decodes_all_formats(tmp_path):
    from app.services.dsh.session_sync import iter_sessions

    home = _build_home(tmp_path)
    records = {r.id: r for r in iter_sessions(home)}

    assert set(records) == {"sess-a", "sess-b", "sess-c"}
    assert records["sess-a"].title == "Alpha title"
    assert records["sess-a"].turn_count == 2
    assert records["sess-a"].last_activity_at == datetime.fromtimestamp(
        1700000004000 / 1000, tz=UTC
    )
    assert records["sess-b"].title == "Beta title"
    assert records["sess-b"].turn_count == 1
    assert records["sess-b"].last_activity_at == datetime.fromtimestamp(
        1700001001000 / 1000, tz=UTC
    )
    assert records["sess-c"].title is None
    assert records["sess-c"].turn_count == 1
    assert records["sess-c"].last_activity_at == datetime.fromtimestamp(
        1700002002000 / 1000, tz=UTC
    )


async def test_iter_sessions_decodes_streaming_zstd_without_content_size(tmp_path):
    """回归（2026-09-16）：DSH 写的是流式 zstd 帧（帧头无 content size），
    一次性 zstandard.decompress() 会抛 ZstdError；必须用流式解码器。"""
    from app.services.dsh.session_sync import iter_sessions

    home = _build_home(tmp_path)
    lines = "\n".join(
        [
            _header("sess-stream", 1700003000000),
            _line(0, "turn/start", 1700003000500, {"turn": 1}),
            _line(1, "session/title", 1700003005000, {"title": "Streaming frame", "messageSeqs": [0], "source": {"kind": "user"}}),
        ]
    ).encode("utf-8")
    streaming = zstandard.ZstdCompressor(write_content_size=False).compress(lines)
    with pytest.raises(zstandard.ZstdError):
        zstandard.decompress(streaming)

    target = home / "sessions" / "proj-stream" / "sess-stream"
    target.mkdir(parents=True)
    (target / "session.jsonl.zstd").write_bytes(streaming)

    records = {r.id: r for r in iter_sessions(home)}
    assert records["sess-stream"].title == "Streaming frame"
    assert records["sess-stream"].last_activity_at == datetime.fromtimestamp(
        1700003005000 / 1000, tz=UTC
    )


@pytest.fixture
async def api_db(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def test_sync_user_sessions_inserts_and_is_idempotent(tmp_path, api_db):
    from app.services.dsh.session_sync import sync_user_sessions

    home = _build_home(tmp_path)

    inserted = await sync_user_sessions(api_db, user_id=USER_UUID, home=home)
    await api_db.commit()
    assert inserted == 3

    rows = (
        (await api_db.execute(select(DshSession))).scalars().all()
    )
    assert {r.dsh_session_id for r in rows} == {"sess-a", "sess-b", "sess-c"}
    by_id = {r.dsh_session_id: r for r in rows}
    assert by_id["sess-a"].title == "Alpha title"
    assert by_id["sess-a"].turn_count == 2
    assert by_id["sess-a"].last_activity_at == datetime.fromtimestamp(
        1700000004000 / 1000, tz=UTC
    )
    assert by_id["sess-a"].synced_at is not None

    again = await sync_user_sessions(api_db, user_id=USER_UUID, home=home)
    await api_db.commit()
    assert again == 0


async def test_sync_updates_changed_turns_and_prunes_never(tmp_path, api_db):
    from app.services.dsh.session_sync import sync_user_sessions

    home = _build_home(tmp_path)
    await sync_user_sessions(api_db, user_id=USER_UUID, home=home)
    await api_db.commit()

    sess_a_dir = home / "sessions" / "proj-a" / "sess-a"
    extra = _line(6, "turn/start", 1700000005000, {"turn": 3})
    with (sess_a_dir / "session.jsonl.zstd").open("rb") as f:
        old = zstandard.decompress(f.read())
    new_content = (old.decode("utf-8") + "\n" + extra + "\n").encode("utf-8")
    (sess_a_dir / "session.jsonl.zstd").write_bytes(zstandard.compress(new_content))

    changed = await sync_user_sessions(api_db, user_id=USER_UUID, home=home)
    await api_db.commit()
    assert changed == 1

    row = (
        await api_db.execute(
            select(DshSession).where(DshSession.dsh_session_id == "sess-a")
        )
    ).scalar_one()
    assert row.turn_count == 3
    assert row.last_activity_at == datetime.fromtimestamp(
        1700000005000 / 1000, tz=UTC
    )

    (home / "sessions" / "_no-cwd" / "sess-c" / "session.jsonl").unlink()
    removed = await sync_user_sessions(api_db, user_id=USER_UUID, home=home)
    await api_db.commit()
    assert removed == 0
    by_id = {}
    for r in (await api_db.execute(select(DshSession))).scalars().all():
        by_id[r.dsh_session_id] = r
    assert by_id["sess-c"].turn_count == 1
