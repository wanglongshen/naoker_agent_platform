from __future__ import annotations
import uuid
import pytest
from app.services.agent import AgentLoopService
from app.services.agent.loop import _AttemptContext
from app.models.agent import AgentRun, AgentRunAttempt
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """与外部状态解耦，并保证 patch 打中真实执行路径。

    - 关掉 workflow docs：测试库可能被差分脚本 seed 了文档，会让计划类 goal 走进
      蓝图加载路径（repo=None 时 AttributeError）。
    - 关掉 merged/fast path：本组测试 mock 的是 `_stream_planning`。
    - 必须 patch loop 模块持有的 settings 对象——`test_alembic_config.py` 会调用
      `get_settings.cache_clear()`，此后 `get_settings()` 返回新对象，而 loop 模块里的
      引用仍是旧对象（只 patch get_settings() 会打不中，导致测试打真实 LLM）。
    """
    from app.services.agent import loop as loop_module

    monkeypatch.setattr(loop_module.settings, "workflow_docs_enabled", False)
    monkeypatch.setattr(loop_module.settings, "merged_plan_thought_enabled", False)
    monkeypatch.setattr(loop_module.settings, "fast_path_enabled", False)


@pytest.mark.anyio
async def test_plan_node_builds_action(monkeypatch, test_db):
    # 关闭 merged-plan-thought 分支：plan 节点在仓库为 None（无 DB）时仅走 _stream_planning，
    # 与测试意图（mock _stream_planning 产出 plan dict）一致。见 task 8 报告中的计划缺陷 2。
    monkeypatch.setattr(get_settings(), "merged_plan_thought_enabled", False)
    service = AgentLoopService()
    run = AgentRun(id=uuid.uuid4(), goal="写一份方案", owner_user_id=uuid.uuid4(), max_steps=5, session_id=uuid.uuid4())
    attempt = AgentRunAttempt(id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1)
    ctx = _AttemptContext(run=run, attempt=attempt)
    runtime = {"service": service, "repo": None, "ctx": ctx, "owner_user_id": None, "is_super_admin": False}

    async def fake_persist_and_notify(*a, **k):
        return None

    async def fake_plan(repo, ctx, messages, step_index):
        return {"action": {"type": "write_file", "input": {"path": "a.md", "content": "x"}},
                "thought_summary": "写文件"}
    monkeypatch.setattr(service, "_stream_planning", fake_plan)
    monkeypatch.setattr(service, "_persist_and_notify", fake_persist_and_notify)

    state = {"step_index": 0, "previous_observation": None, "workflow": {}, "wrote_file": False}
    out = await service._do_node_plan(state, runtime)
    assert out["pending_action"]["action"]["type"] == "write_file"


@pytest.mark.anyio
async def test_plan_node_schedules_attempt_retry_on_non_correctable_planner_error(monkeypatch, test_db):
    """非门禁类 RetryablePlannerError 应与旧轨一致：能重试则调度 attempt 重试（返回 _retryable），不向上抛。"""
    from app.services.agent.loop import RetryablePlannerError

    monkeypatch.setattr(get_settings(), "merged_plan_thought_enabled", False)
    service = AgentLoopService()
    run = AgentRun(id=uuid.uuid4(), goal="写一份方案", owner_user_id=uuid.uuid4(), max_steps=5, session_id=uuid.uuid4())
    attempt = AgentRunAttempt(id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1)
    ctx = _AttemptContext(run=run, attempt=attempt)
    runtime = {"service": service, "repo": None, "ctx": ctx, "owner_user_id": None, "is_super_admin": False}

    async def fake_persist_and_notify(*a, **k):
        return None

    async def fake_plan(repo, ctx_, messages, step_index):
        raise RetryablePlannerError("invalid_tool_input: boom")

    scheduled = {}

    async def fake_schedule(repo, ctx_, exc):
        scheduled["exc"] = exc
        return True

    monkeypatch.setattr(service, "_stream_planning", fake_plan)
    monkeypatch.setattr(service, "_persist_and_notify", fake_persist_and_notify)
    monkeypatch.setattr(service, "_schedule_retryable_failure", fake_schedule)

    state = {"step_index": 0, "previous_observation": None, "workflow": {}, "wrote_file": False}
    out = await service._do_node_plan(state, runtime)
    assert out.get("_retryable") is True
    assert "invalid_tool_input" in str(scheduled["exc"])


@pytest.mark.anyio
async def test_plan_node_persists_run_failed_when_retry_not_possible(monkeypatch, test_db):
    """重试不可用（attempt 用尽）时，plan 节点应落 run_failed 终态并返回 terminal，而不是向上抛。"""
    from app.services.agent.loop import RetryablePlannerError

    monkeypatch.setattr(get_settings(), "merged_plan_thought_enabled", False)
    service = AgentLoopService()
    run = AgentRun(id=uuid.uuid4(), goal="写一份方案", owner_user_id=uuid.uuid4(), max_steps=5, session_id=uuid.uuid4())
    attempt = AgentRunAttempt(id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1)
    ctx = _AttemptContext(run=run, attempt=attempt)
    runtime = {"service": service, "repo": None, "ctx": ctx, "owner_user_id": None, "is_super_admin": False}

    async def fake_persist_and_notify(*a, **k):
        return None

    async def fake_plan(repo, ctx_, messages, step_index):
        raise RetryablePlannerError("invalid_tool_input: boom")

    async def fake_schedule(repo, ctx_, exc):
        return False

    terminals = []

    async def fake_terminal(repo, ctx_, event_type, payload, *a, **k):
        terminals.append((event_type, payload))

    monkeypatch.setattr(service, "_stream_planning", fake_plan)
    monkeypatch.setattr(service, "_persist_and_notify", fake_persist_and_notify)
    monkeypatch.setattr(service, "_schedule_retryable_failure", fake_schedule)
    monkeypatch.setattr(service, "_persist_terminal_and_notify", fake_terminal)

    state = {"step_index": 0, "previous_observation": None, "workflow": {}, "wrote_file": False}
    out = await service._do_node_plan(state, runtime)
    assert out.get("terminal", {}).get("action") == "failed"
    assert terminals and terminals[0][0] == "run_failed"
