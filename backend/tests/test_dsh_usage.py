from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import zstandard

from app.services.dsh.usage import collect_dsh_usage


def _write_session(home, session_id: str, lines: list[dict], *, project: str = "proj") -> None:
    directory = home / "sessions" / project / session_id
    directory.mkdir(parents=True, exist_ok=True)
    raw = "\n".join(json.dumps(line) for line in lines).encode("utf-8")
    (directory / "session.jsonl.zstd").write_bytes(zstandard.ZstdCompressor().compress(raw))


def test_collect_usage_sums_window(tmp_path):
    _write_session(
        tmp_path,
        "s1",
        [
            {"type": "session", "id": "s1", "time": 1_000_000},
            {"type": "assistant/message", "time": 1_500_000, "usage": {"inputTokens": 100, "outputTokens": 20}},
            {"type": "assistant/message", "time": 2_500_000, "usage": {"inputTokens": 10, "outputTokens": 5}},
        ],
    )
    assert collect_dsh_usage(tmp_path, since=1400, until=2000) == 120
    assert collect_dsh_usage(tmp_path, since=0, until=9999) == 135


def test_collect_usage_reads_real_dsh_event_shape(tmp_path):
    """真实 DSH 事件把 usage 放在 data.usage 下（headless 实测 2026-09-15）。"""
    _write_session(
        tmp_path,
        "s3",
        [
            {
                "type": "assistant/message",
                "seq": 2722,
                "time": 1_789_459_554_094,
                "data": {
                    "turn": 1,
                    "step": 1,
                    "message": {"role": "assistant", "content": []},
                    "usage": {
                        "inputTokens": 7312,
                        "outputTokens": 2731,
                        "cacheReadTokens": 8192,
                        "reasoningTokens": 2691,
                    },
                },
            }
        ],
    )
    since = 1_789_459_554_000 / 1000
    until = 1_789_459_555_000 / 1000
    assert collect_dsh_usage(tmp_path, since=since, until=until) == 7312 + 2731 + 8192 + 2691


def test_collect_usage_sums_all_usage_fields(tmp_path):
    _write_session(
        tmp_path,
        "s2",
        [
            {
                "type": "assistant/message",
                "time": 1500,
                "usage": {
                    "inputTokens": 1,
                    "outputTokens": 2,
                    "cacheReadTokens": 4,
                    "cacheWriteTokens": 8,
                    "reasoningTokens": 16,
                },
            },
        ],
    )
    assert collect_dsh_usage(tmp_path, since=0, until=9999) == 31


def test_collect_usage_skips_bad_files_and_lines(tmp_path):
    _write_session(
        tmp_path,
        "good",
        [
            {"type": "assistant/message", "time": 1500, "usage": {"inputTokens": 7}},
            {"type": "assistant/message", "time": 1600, "usage": {"outputTokens": 3}},
        ],
    )
    broken = tmp_path / "sessions" / "proj" / "broken"
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "session.jsonl.zstd").write_bytes(b"definitely not a zstd stream")

    mixed = tmp_path / "sessions" / "proj" / "mixed"
    mixed.mkdir(parents=True, exist_ok=True)
    raw = (
        b'{"type": "assistant/message", "time": 1500, "usage": {"inputTokens": 5}}\n'
        b"not-json\n"
        b'{"type": "assistant/message", "time": "oops", "usage": {"inputTokens": 100}}\n'
        b'{"type": "assistant/message", "time": 1500, "usage": "nope"}\n'
    )
    (mixed / "session.jsonl.zstd").write_bytes(zstandard.ZstdCompressor().compress(raw))

    assert collect_dsh_usage(tmp_path, since=0, until=9999) == 15
    assert collect_dsh_usage(tmp_path / "missing", since=0, until=9999) == 0


class _FakePoints:
    def __init__(self) -> None:
        self.deducted: list[tuple] = []

    def tokens_to_points(self, tokens: int) -> int:
        return max(1, tokens // 10000) if tokens > 0 else 0

    async def deduct_for_run(self, db, user_id, run_id, tokens):
        self.deducted.append((user_id, run_id, tokens))
        return 1


class _FakeRepo:
    def __init__(self, chain) -> None:
        self.db = None
        self.chain = chain
        self.stages: list = []

    async def get_chain(self, chain_id, user_id=None):
        return self.chain if chain_id == self.chain.id else None

    async def list_stages(self, chain_id):
        return list(self.stages)

    async def add_stage(self, chain_id, stage, seq):
        item = SimpleNamespace(id=uuid.uuid4(), chain_id=chain_id, stage=stage, seq=seq, status="pending")
        self.stages.append(item)
        return item

    async def update_stage(self, stage_id, **fields):
        for item in self.stages:
            if item.id == stage_id:
                for key, value in fields.items():
                    setattr(item, key, value)
                return item
        return None

    async def set_chain_status(self, chain_id, status, **fields):
        self.chain.status = status
        for key, value in fields.items():
            setattr(self.chain, key, value)
        return self.chain


def _fake_chain() -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="running",
        started_at=now - timedelta(minutes=1),
        created_at=now - timedelta(minutes=2),
        total_tokens=0,
        points_cost=0,
    )


@pytest.mark.anyio
async def test_stage_bill_adds_dsh_usage_to_platform_tokens(monkeypatch):
    from app.core.config import get_settings
    from app.services import task_chain as package
    from app.services.task_chain.service import TaskChainService

    calls: dict = {}

    def fake_collect(home, *, since, until):
        calls.update(home=home, since=since, until=until)
        return 350

    monkeypatch.setattr(package.service, "collect_dsh_usage", fake_collect)

    chain = _fake_chain()
    points = _FakePoints()
    service = TaskChainService(_FakeRepo(chain), points=points)

    await service._stage_bill({"chain_id": str(chain.id), "llm_tokens": 650})

    assert points.deducted == [(chain.user_id, chain.id, 1000)]
    assert chain.total_tokens == 1000
    assert calls["home"] == get_settings().dsh_home_root_path / str(chain.user_id)
    assert calls["since"] < calls["until"]


@pytest.mark.anyio
async def test_stage_bill_falls_back_to_flat_points_without_usage(monkeypatch):
    from app.core.config import get_settings
    from app.services import task_chain as package
    from app.services.task_chain.service import TaskChainService

    monkeypatch.setattr(package.service, "collect_dsh_usage", lambda home, *, since, until: 0)

    chain = _fake_chain()
    points = _FakePoints()
    service = TaskChainService(_FakeRepo(chain), points=points)

    await service._stage_bill({"chain_id": str(chain.id)})

    settings = get_settings()
    expected = int(settings.task_chain_flat_points) * int(settings.points_tokens_per_point)
    assert points.deducted == [(chain.user_id, chain.id, expected)]
    assert chain.total_tokens == expected
