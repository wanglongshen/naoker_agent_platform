from __future__ import annotations
import uuid
from unittest.mock import AsyncMock
import pytest
from app.services.agent import AgentLoopService


@pytest.mark.anyio
async def test_graph_path_used_when_flag_on(monkeypatch, test_db):
    service = AgentLoopService()
    monkeypatch.setattr(service, "langgraph_enabled", True)
    called = {}
    async def fake_graph(*a, **k):
        called["graph"] = True
    monkeypatch.setattr(service, "_do_process_attempt_graph", fake_graph)
    async def fake_loop(*a, **k):
        called["loop"] = True
    monkeypatch.setattr(service, "_do_process_attempt", fake_loop)
    # 直接调用内部分流逻辑
    await service._maybe_run_graph_or_loop(None, None, None, None)
    assert called.get("graph") is True
    assert "loop" not in called
