from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_recorder_from_env_returns_none_without_env(monkeypatch):
    from app.services.agent.llm_recorder import recorder_from_env

    monkeypatch.delenv("LANGGRAPH_DIFF_RECORD", raising=False)
    monkeypatch.delenv("LANGGRAPH_DIFF_REPLAY", raising=False)
    assert recorder_from_env() is None


def test_recorder_from_env_is_shared_across_clients(tmp_path: Path, monkeypatch):
    """进程内多个 DeepSeekClient 必须共享同一 recorder（同游标/同文件）。"""
    from app.services.agent.llm_recorder import _REGISTRY, recorder_from_env

    _REGISTRY.clear()
    monkeypatch.delenv("LANGGRAPH_DIFF_REPLAY", raising=False)
    monkeypatch.setenv("LANGGRAPH_DIFF_RECORD", str(tmp_path / "shared.json"))

    first = recorder_from_env()
    second = recorder_from_env()
    assert first is second

    first.record_plan([{"role": "user", "content": "a"}], {"action": {"type": "finish", "input": {}}})
    second.record_stream([{"role": "user", "content": "b"}], ["x"], [])
    first.save()

    data = json.loads((tmp_path / "shared.json").read_text(encoding="utf-8"))
    assert [c["method"] for c in data["calls"]] == ["create_plan", "stream_text"]
    _REGISTRY.clear()


def test_record_then_replay_roundtrip(tmp_path: Path, monkeypatch):
    from app.services.agent.llm_recorder import LlmRecorder

    path = tmp_path / "s1.json"
    rec = LlmRecorder(mode="record", path=path, scenario="s1")
    rec.record_plan([{"role": "user", "content": "hi"}], {"thought_summary": "t", "action": {"type": "finish", "input": {"answer": "a"}}})
    rec.record_stream([{"role": "user", "content": "hi"}], ["你", "好"], [{"total_tokens": 7}])
    rec.save()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["scenario"] == "s1"
    assert [c["method"] for c in data["calls"]] == ["create_plan", "stream_text"]

    rep = LlmRecorder(mode="replay", path=path, scenario="s1")
    assert rep.replay_plan([{"role": "user", "content": "hi"}])["action"]["type"] == "finish"

    usages: list[dict] = []
    rep.bind_usage_sink(usages.append)

    async def _collect():
        return [c async for c in rep.replay_stream([{"role": "user", "content": "hi"}])]

    import asyncio

    assert asyncio.run(_collect()) == ["你", "好"]
    assert usages == [{"total_tokens": 7}]


def test_replay_exhaustion_raises(tmp_path: Path):
    from app.services.agent.llm_recorder import LlmRecorder, ReplayExhaustedError

    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"scenario": "x", "calls": []}), encoding="utf-8")
    rep = LlmRecorder(mode="replay", path=path, scenario="x")
    with pytest.raises(ReplayExhaustedError):
        rep.replay_plan([{"role": "user", "content": "hi"}])
