from __future__ import annotations

import uuid

import pytest

from app.models.agent import AgentRun, AgentRunAttempt
from app.services.agent import AgentLoopService
from app.services.agent.langgraph_runner import LangGraphRunner, build_state
from app.services.agent.loop import _AttemptContext


async def _nop(*_a, **_k):
    return None


def _make_ctx(goal: str, *, max_steps: int = 5) -> _AttemptContext:
    run = AgentRun(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        goal=goal,
        owner_user_id=uuid.uuid4(),
        status="running",
        network_enabled=False,
        max_steps=max_steps,
    )
    attempt = AgentRunAttempt(
        id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1, status="running"
    )
    return _AttemptContext(run=run, attempt=attempt)


@pytest.mark.anyio
async def test_fidelity_reports_zero_diff_when_frames_identical():
    from app.services.agent.langgraph_runner import diff_event_streams
    a = [{"event_type": "x", "payload": {"a": 1}}]
    b = [{"event_type": "x", "payload": {"a": 1}}]
    assert diff_event_streams(a, b) == []


@pytest.mark.anyio
async def test_graph_plan_goal_matches_old_attachment_format(monkeypatch):
    """T8 deferred item 1: attachments entering GraphState keep the old-track shape
    ({"name", "content"} from _read_attachment_context) and are rendered into the
    planner goal with the same 附件：<name>\\n<content> blocks as the old while-loop."""
    service = AgentLoopService()
    ctx = _make_ctx("总结附件")

    class FakeRepo:
        def __init__(self):
            self.session = type("S", (), {"commit": None})()

        async def is_cancel_requested(self, _run_id):
            return False

        async def transition_attempt_status(self, *_a, **_k):
            return None

    repo = FakeRepo()
    monkeypatch.setattr("app.services.agent.loop.settings.workflow_docs_enabled", False)

    attachment = {
        "name": "brief.md",
        "content": "[用户上传的附件，内容如下]\n目标人群：宝妈",
    }

    async def fake_read_attachments(*_a, **_k):
        return [dict(attachment)]

    async def fake_session_history(*_a, **_k):
        return []

    captured = {}

    async def fake_plan(_repo, _ctx, messages, _step_index):
        captured["user_message"] = messages[1]["content"]
        return {"action": {"type": "finish", "input": {}}, "thought_summary": "完成"}

    async def fake_merged(*_a, **_k):
        return None

    async def fake_stream(*_a, **_k):
        return "thought", {"final_answer": "答案"}

    completed = []

    async def fake_completion(**kw):
        completed.append(kw)

    monkeypatch.setattr(service, "_read_attachment_context", fake_read_attachments)
    monkeypatch.setattr(service, "_stream_planning", fake_plan)
    monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)
    monkeypatch.setattr(service, "_stream_visible_thought_with_tool_interleave", fake_stream)
    monkeypatch.setattr(service, "_persist_and_notify", _nop)
    monkeypatch.setattr(service, "_commit_repo", _nop)
    monkeypatch.setattr(service, "_build_session_history", fake_session_history)
    monkeypatch.setattr(service, "_advance_workflow_stage", _nop)
    monkeypatch.setattr(service, "_run_policy", lambda _run, max_steps: (False, max_steps))
    monkeypatch.setattr(service, "_enforce_answer_truthfulness", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "_persist_successful_completion", fake_completion)
    monkeypatch.setattr(service, "_has_save_intent", lambda _g: False)

    await service._do_process_attempt_graph(repo, ctx, None, False)

    assert completed, "finish path must reach persist_successful_completion"
    expected_goal = (
        "总结附件\n\n以下是用户提供的附件内容：\n"
        "附件：brief.md\n[用户上传的附件，内容如下]\n目标人群：宝妈"
    )
    assert captured["user_message"].startswith(f"当前目标：{expected_goal}\n")


@pytest.mark.anyio
async def test_plan_node_commits_repo_before_planning(monkeypatch):
    """T8 deferred item 2: the old while-loop commits the session immediately before
    building planner messages (loop.py:2394). The graph plan node must do the same,
    with the same single repo argument."""
    service = AgentLoopService()
    ctx = _make_ctx("写一份方案")
    repo = object()
    runtime = {
        "service": service,
        "repo": repo,
        "ctx": ctx,
        "owner_user_id": None,
        "is_super_admin": False,
    }

    order = []

    async def fake_commit(committed_repo):
        order.append(("commit", committed_repo))

    async def fake_plan(_repo, _ctx, _messages, _step_index):
        order.append(("plan", None))
        return {"action": {"type": "finish", "input": {}}, "thought_summary": "完成"}

    async def fake_merged(*_a, **_k):
        return None

    monkeypatch.setattr(service, "_commit_repo", fake_commit)
    monkeypatch.setattr(service, "_prepare_quality_injection", _nop)
    monkeypatch.setattr(service, "_stream_planning", fake_plan)
    monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)
    monkeypatch.setattr(service, "_persist_and_notify", _nop)

    state = {
        "workflow": {},
        "step_index": 0,
        "previous_observation": None,
        "wrote_file": False,
        "web_enabled": False,
        "effective_max_steps": 5,
    }
    out = await service._do_node_plan(state, runtime)

    assert order == [("commit", repo), ("plan", None)], (
        "graph plan node must commit the repo before planning, like the old track"
    )
    assert out["pending_action"]["action"]["type"] == "finish"


@pytest.mark.anyio
async def test_graph_threads_pre_generated_thought_into_execute(monkeypatch):
    """T8 deferred item 3: a thought pre-generated by the merged plan stream must
    survive the GraphState round-trip and reach the execute node's visible-thought
    stream (event/answer path), exactly like the old while-loop passes it through."""
    service = AgentLoopService()
    ctx = _make_ctx("测试目标")

    class FakeRepo:
        def __init__(self):
            self.steps = []

        async def add_step(self, **kw):
            self.steps.append(kw)

    repo = FakeRepo()
    runner = LangGraphRunner(service, repo, ctx, None, False)

    async def fake_plan_one_step(*_a, **_k):
        return (
            {
                "action": {"type": "read_file", "input": {"file_id": "f1"}},
                "thought_summary": "读取文件",
            },
            "预生成的可见说明",
        )

    captured = {}

    async def fake_stream(*_a, **k):
        captured["pre_generated_thought"] = k.get("pre_generated_thought")
        return "预生成的可见说明", {"file_id": "f1", "sha256": "x", "bytes": 1}

    monkeypatch.setattr(service, "_plan_one_step", fake_plan_one_step)
    monkeypatch.setattr(service, "_stream_visible_thought_with_tool_interleave", fake_stream)
    monkeypatch.setattr(service, "_persist_and_notify", _nop)
    monkeypatch.setattr(service, "_record_observation", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "_commit_repo", _nop)

    state = build_state()
    state.update(
        {"step_index": 0, "workflow": {}, "web_enabled": True, "effective_max_steps": 5}
    )
    await runner.compile().ainvoke(state)

    assert captured.get("pre_generated_thought") == "预生成的可见说明"
    assert repo.steps, "execute node must have run for a non-finish action"
