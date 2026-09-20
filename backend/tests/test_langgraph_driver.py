from __future__ import annotations
import uuid

import pytest

from app.services.agent.langgraph_runner import LangGraphRunner


@pytest.mark.anyio
async def test_do_process_attempt_graph_runs_a_single_finish_step(monkeypatch):
    """Driver level: a finish plan should go through execute->finalize and produce a terminal."""
    from app.services.agent.loop import AgentLoopService, _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    service = AgentLoopService()
    run = AgentRun(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        goal="写一份方案",
        owner_user_id=uuid.uuid4(),
        status="running",
        network_enabled=False,
        max_steps=5,
    )
    attempt = AgentRunAttempt(
        id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1, status="running"
    )
    ctx = _AttemptContext(run=run, attempt=attempt)

    class FakeRepo:
        def __init__(self):
            self.session = type("S", (), {"commit": None})()

        async def is_cancel_requested(self, _run_id):
            return False

        async def get_run(self, _run_id):
            return run

        async def transition_attempt_status(self, *_a, **_k):
            return None

    repo = FakeRepo()
    monkeypatch.setattr("app.services.agent.loop.settings.workflow_docs_enabled", False)

    async def fake_persist_and_notify(*a, **k):
        return None

    async def fake_nop_async(*a, **k):
        return None

    monkeypatch.setattr(service, "_persist_and_notify", fake_persist_and_notify)
    monkeypatch.setattr(service, "_commit_repo", fake_nop_async)

    async def fake_session_history(*_a, **_k):
        return []

    monkeypatch.setattr(service, "_build_session_history", fake_session_history)
    monkeypatch.setattr(service, "_run_policy", lambda _run, max_steps: (False, max_steps))
    monkeypatch.setattr(service, "_advance_workflow_stage", fake_nop_async)

    async def fake_read_attachments(*_a, **_k):
        return []

    monkeypatch.setattr(service, "_read_attachment_context", fake_read_attachments)

    async def fake_plan(*_a, **_k):
        return {"action": {"type": "finish", "input": {}}, "thought_summary": "完成"}

    monkeypatch.setattr(service, "_stream_planning", fake_plan)

    async def fake_merged(*_a, **_k):
        return None

    monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)

    async def fake_stream(*_a, **_k):
        return "thought", {"final_answer": "答案"}

    monkeypatch.setattr(service, "_stream_visible_thought_with_tool_interleave", fake_stream)
    monkeypatch.setattr(service, "_enforce_answer_truthfulness", lambda _a, _r: None)
    completed = []

    async def fake_completion(**kw):
        completed.append(kw)
        return None

    monkeypatch.setattr(service, "_persist_successful_completion", fake_completion)
    monkeypatch.setattr(service, "_has_save_intent", lambda _g: False)

    # Run the driver; a finish plan should flow plan->execute->finalize, producing
    # a successful completion, NOT just pass vacuously.
    await service._do_process_attempt_graph(repo, ctx, None, False)

    assert completed, "finalize/persist_successful_completion must be reached for a finish plan"


@pytest.mark.anyio
async def test_graph_retries_gate_without_raising(monkeypatch):
    """A correctable gate plan must route plan->end (not plan->execute) and return
    _gate_retry in the merged result, without execute raising 'execute before plan'."""
    from app.services.agent.loop import AgentLoopService, _AttemptContext, RetryablePlannerError
    from app.models.agent import AgentRun, AgentRunAttempt

    service = AgentLoopService()
    run = AgentRun(
        id=uuid.uuid4(), session_id=uuid.uuid4(), goal="g", owner_user_id=uuid.uuid4(),
        status="running", network_enabled=False, max_steps=5,
    )
    attempt = AgentRunAttempt(id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)
    runner = LangGraphRunner(service, None, ctx, None, False)

    async def fake_plan_raises(*_a, **_k):
        raise RetryablePlannerError("invalid_tool_result: 需按禁选动作处理")

    monkeypatch.setattr(service, "_stream_planning", fake_plan_raises)
    monkeypatch.setattr(service, "_is_correctable_workflow_error", lambda exc: True)
    monkeypatch.setattr("app.services.agent.loop.settings.merged_plan_thought_enabled", False)
    monkeypatch.setattr(service, "_persist_and_notify", lambda *a, **k: None)

    state = {
        "workflow": {}, "attempt_ctx": {}, "step_index": 0, "previous_observation": None,
        "wrote_file": False, "step_journal": [], "web_enabled": False, "effective_max_steps": 5,
        "session_history": [], "attachments": [], "terminal": None, "pending_action": None,
        "pre_generated_thought": None, "_gate_retry": False, "_retryable": False,
        "step_duration_seconds": 0.0,
    }
    result = await runner.compile().ainvoke(state)
    assert result.get("_gate_retry") is True, "gate retry must survive the graph round-trip"
    assert result.get("step_index") == 1


@pytest.mark.anyio
async def test_enforce_gate_retries_not_fail(monkeypatch):
    """C1: a correctable gate raised by _enforce_stage_gate must route to _gate_retry
    (replan), NOT propagate and fail the attempt."""
    from app.services.agent.loop import AgentLoopService, _AttemptContext, RetryablePlannerError
    from app.models.agent import AgentRun, AgentRunAttempt

    service = AgentLoopService()
    run = AgentRun(
        id=uuid.uuid4(), session_id=uuid.uuid4(), goal="写一份方案", owner_user_id=uuid.uuid4(),
        status="running", network_enabled=False, max_steps=5,
    )
    attempt = AgentRunAttempt(id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)
    runner = LangGraphRunner(service, None, ctx, None, False)

    async def fake_plan(*_a, **_k):
        return {"action": {"type": "write_file", "input": {"path": "方案.md", "content": "x"}},
                "thought_summary": "写文件"}

    monkeypatch.setattr(service, "_stream_planning", fake_plan)
    monkeypatch.setattr("app.services.agent.loop.settings.merged_plan_thought_enabled", False)
    monkeypatch.setattr(service, "_persist_and_notify", lambda *a, **k: None)
    # force _enforce_stage_gate to raise a correctable gate error
    monkeypatch.setattr(
        service, "_enforce_stage_gate",
        lambda plan, run_id: (_ for _ in ()).throw(RetryablePlannerError("stage_gate: 当前阶段不允许该动作")),
    )

    state = {
        "workflow": {}, "attempt_ctx": {}, "step_index": 0, "previous_observation": None,
        "wrote_file": False, "step_journal": [], "web_enabled": False, "effective_max_steps": 5,
        "session_history": [], "attachments": [], "terminal": None, "pending_action": None,
        "pre_generated_thought": None, "_gate_retry": False, "_retryable": False,
        "step_duration_seconds": 0.0,
    }
    result = await runner.compile().ainvoke(state)
    assert result.get("_gate_retry") is True, "enforce gate must route to _gate_retry, not fail"
    assert result.get("terminal") is None
