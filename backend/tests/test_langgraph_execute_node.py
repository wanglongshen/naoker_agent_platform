from __future__ import annotations
import uuid

import pytest

from app.services.agent.langgraph_runner import route_after_execute


def test_route_finish_on_finish_action():
    gs = {"pending_action": {"action": {"type": "finish"}}}
    assert route_after_execute(gs) == "finalize"


def test_route_end_on_tool_action():
    gs = {"pending_action": {"action": {"type": "write_file"}}}
    assert route_after_execute(gs) == "end"


@pytest.mark.anyio
async def test_finalize_merges_verified_save_answer(monkeypatch):
    from app.services.agent.loop import AgentLoopService, _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    service = AgentLoopService()
    run = AgentRun(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        goal="写一份方案",
        owner_user_id=uuid.uuid4(),
        status="running",
        max_steps=5,
    )
    attempt = AgentRunAttempt(
        id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1, status="running"
    )
    ctx = _AttemptContext(run=run, attempt=attempt)
    runtime = {"service": service, "repo": None, "ctx": ctx, "owner_user_id": None, "is_super_admin": False}
    wf = {
        "verified_save_receipts": [{"path": "a.md", "verified": True}],
        "read_receipts": [],
        "save_receipts": [],
        "dependency_receipts": [],
        "stages_done": [],
    }
    state = {
        "previous_observation": {"final_answer": "方案已完成"},
        "workflow": wf,
        "pending_action": {"action": {"type": "finish", "input": {}}, "thought_summary": "写文件"},
    }

    calls = []

    async def fake_persist(**kw):
        calls.append(kw)
        return None

    monkeypatch.setattr(service, "_has_save_intent", lambda goal: True)
    monkeypatch.setattr(service, "_merge_save_answer", lambda answer, receipts: answer + "（已回读校验）")
    monkeypatch.setattr(service, "_enforce_answer_truthfulness", lambda answer, run_id: None)
    monkeypatch.setattr(service, "_persist_successful_completion", fake_persist)

    out = await service._do_node_finalize(state, runtime)

    assert out["terminal"]["action"] == "finish"
    assert calls and calls[0]["answer"].endswith("（已回读校验）")


@pytest.mark.anyio
async def test_execute_one_step_read_file_mutates_receipts(monkeypatch):
    from app.services.agent.loop import AgentLoopService, _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    service = AgentLoopService()
    run = AgentRun(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        goal="test",
        owner_user_id=uuid.uuid4(),
        status="running",
        max_steps=5,
    )
    attempt = AgentRunAttempt(
        id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1, status="running"
    )
    ctx = _AttemptContext(run=run, attempt=attempt)

    class FakeRepo:
        def __init__(self):
            self.add_steps = []

        async def add_step(self, **kw):
            self.add_steps.append(kw)

    repo = FakeRepo()
    graph_state = {"previous_observation": None, "web_enabled": True}
    runtime = {"owner_user_id": None, "is_super_admin": False}
    plan = {"thought_summary": "读取文件内容"}
    action = {"type": "read_file", "input": {"file_id": "f1"}}
    step_index = 2
    wf = {}

    observation = {"file_id": "f1", "sha256": "x", "bytes": 1}

    async def fake_stream(*args, **kwargs):
        return "thought", observation

    async def fake_persist_and_notify(*a, **k):
        return None

    monkeypatch.setattr(service, "_stream_visible_thought_with_tool_interleave", fake_stream)
    monkeypatch.setattr(service, "_record_observation", lambda *a, **k: None)
    monkeypatch.setattr(service, "_persist_and_notify", fake_persist_and_notify)

    out = await service._execute_one_step(
        repo, ctx, graph_state, runtime, plan, action, step_index, wf
    )

    assert out["step_index"] == step_index + 1
    assert out["previous_observation"] == observation
    assert wf["read_receipts"] == [
        {"file_id": "f1", "filename": None, "path": None, "bytes": 1, "sha256": "x", "source": None}
    ]
    assert wf["stage_actions"] == 1
    assert len(repo.add_steps) == 1


@pytest.mark.anyio
async def test_execute_one_step_finish_short_circuits(monkeypatch):
    from app.services.agent.loop import AgentLoopService, _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    service = AgentLoopService()
    run = AgentRun(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        goal="test",
        owner_user_id=uuid.uuid4(),
        status="running",
        max_steps=5,
    )
    attempt = AgentRunAttempt(
        id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1, status="running"
    )
    ctx = _AttemptContext(run=run, attempt=attempt)

    class FakeRepo:
        def __init__(self):
            self.add_steps = []

        async def add_step(self, **kw):
            self.add_steps.append(kw)

    repo = FakeRepo()
    graph_state = {"previous_observation": None, "web_enabled": True}
    runtime = {"owner_user_id": None, "is_super_admin": False}
    plan = {"thought_summary": "整理最终结论"}
    action = {"type": "finish", "input": {}}
    step_index = 3
    wf = {}

    async def fake_stream(*args, **kwargs):
        return "thought", {"final_answer": "答案"}

    monkeypatch.setattr(service, "_stream_visible_thought_with_tool_interleave", fake_stream)

    out = await service._execute_one_step(
        repo, ctx, graph_state, runtime, plan, action, step_index, wf
    )

    assert out["previous_observation"] == {"final_answer": "答案"}
    assert out["step_duration_seconds"] >= 0
    assert repo.add_steps == []
