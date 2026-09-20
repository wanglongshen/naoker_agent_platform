from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

SCENARIOS_FIXTURE = {
    "id": 1,
    "name": "fixture finish-only",
    "goal": "你好，介绍一下你自己",
    "settings": {"fast_path_enabled": False, "merged_plan_thought_enabled": False},
    "attachments": [],
}


def _install_fake_llm(monkeypatch, loop_module, *, patch_session_history: bool) -> None:
    # 测试库里可能留有录制 seed 的工作流文档（scripts.diff_seed），
    # 会激活阶段门禁使 finish-only 场景行为随 DB 状态漂移；本组测试只验证驱动，关掉文档注入。
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "workflow_docs_enabled", False)
    # test_alembic_config.py 会 cache_clear 掉 settings；loop 模块持有的旧对象也要 patch，
    # 否则全量套件运行顺序下这里关不干净（docs 会被真实加载）。
    monkeypatch.setattr(loop_module.settings, "workflow_docs_enabled", False)

    class FakeClient:
        async def stream_text(self, messages, usage_sink=None, **kwargs):
            for chunk in ["这是", "答案"]:
                yield chunk

        async def create_plan(self, messages):
            return {"action": {"type": "finish", "input": {}}, "thought_summary": "完成"}

        async def complete(self, messages):
            return "{}"

        async def close(self):
            return None

    monkeypatch.setattr(loop_module, "DeepSeekClient", FakeClient)

    async def fake_plan(*_a, **_k):
        return {"action": {"type": "finish", "input": {}}, "thought_summary": "完成"}

    monkeypatch.setattr(loop_module.AgentLoopService, "_stream_planning", fake_plan)

    if patch_session_history:

        async def fake_session_history(*_a, **_k):
            return []

        monkeypatch.setattr(
            loop_module.AgentLoopService, "_build_session_history", fake_session_history
        )


def test_scenarios_cover_ten_matrix_entries():
    from scripts.langgraph_differential import SCENARIOS

    assert len(SCENARIOS) == 10
    assert {s["id"] for s in SCENARIOS} == set(range(1, 11))
    assert all(s["goal"] for s in SCENARIOS)


@pytest.mark.anyio
async def test_run_scenario_captures_events_for_both_tracks(monkeypatch, test_db):
    """脚本化 FakeClient 跑 finish-only 场景：双轨事件流都非空且归一化后零差异。"""
    from scripts import langgraph_differential as mod
    from app.services.agent import loop as loop_module

    _install_fake_llm(monkeypatch, loop_module, patch_session_history=True)
    monkeypatch.setattr(mod, "_session_factory_override", test_db)

    events_old = await mod.run_scenario(SCENARIOS_FIXTURE, graph=False, recorder=None)
    events_graph = await mod.run_scenario(SCENARIOS_FIXTURE, graph=True, recorder=None)

    assert events_old, "old track must emit events"
    assert events_graph, "graph track must emit events"
    assert [e["event_type"] for e in events_old] == [e["event_type"] for e in events_graph]
    assert mod.diff_normalized(events_old, events_graph) == []


@pytest.mark.anyio
async def test_graph_track_survives_empty_session_history(monkeypatch, test_db):
    """不带 _build_session_history 补丁的真实 DB 路径：图轨必须在空历史下存活。

    回归测试：图轨曾对空 session_history 调用 list(None) 崩溃（loop.py:3196）。
    """
    from scripts import langgraph_differential as mod
    from app.services.agent import loop as loop_module

    _install_fake_llm(monkeypatch, loop_module, patch_session_history=False)
    monkeypatch.setattr(mod, "_session_factory_override", test_db)

    events = await mod.run_scenario(SCENARIOS_FIXTURE, graph=True, recorder=None)
    assert events


@pytest.mark.anyio
async def test_cleanup_stale_diff_runs_only_touches_diff_scenarios(test_db):
    """陈旧清理必须限定 diff-scenario-%：未终态 run/attempt 置 failed，其他会话不动。"""
    from scripts import langgraph_differential as mod
    from app.models.agent import AgentRun, AgentRunAttempt, AgentSession
    from app.models.rbac import User

    async with test_db() as session:
        user = User(username="cleanup_user", display_name="x", password_hash="hash")
        session.add(user)
        await session.flush()
        stale_session = AgentSession(owner_user_id=user.id, title="diff-scenario-99")
        other_session = AgentSession(owner_user_id=user.id, title="normal-session")
        session.add_all([stale_session, other_session])
        await session.flush()
        stale_run = AgentRun(
            session_id=stale_session.id, owner_user_id=user.id, goal="g", status="retry_wait"
        )
        other_run = AgentRun(
            session_id=other_session.id, owner_user_id=user.id, goal="g", status="queued"
        )
        session.add_all([stale_run, other_run])
        await session.flush()
        stale_attempt = AgentRunAttempt(run_id=stale_run.id, attempt_number=1, status="queued")
        other_attempt = AgentRunAttempt(run_id=other_run.id, attempt_number=1, status="queued")
        session.add_all([stale_attempt, other_attempt])
        await session.flush()
        ids = (
            stale_run.id,
            other_run.id,
            stale_attempt.id,
            other_attempt.id,
        )
        await session.commit()

    cleaned = await mod._cleanup_stale_diff_runs(test_db)
    assert cleaned == 1

    stale_run_id, other_run_id, stale_attempt_id, other_attempt_id = ids
    async with test_db() as session:
        assert (await session.get(AgentRun, stale_run_id)).status == "failed"
        stale_attempt_row = await session.get(AgentRunAttempt, stale_attempt_id)
        assert stale_attempt_row.status == "failed"
        assert stale_attempt_row.failure_code == "stale_cleanup"
        assert (await session.get(AgentRun, other_run_id)).status == "queued"
        assert (await session.get(AgentRunAttempt, other_attempt_id)).status == "queued"


@pytest.mark.anyio
async def test_setup_run_grants_positive_points(test_db):
    """录制用户必须预置正积分，否则成功 run 的扣费必失败（场景 10）。"""
    from scripts import langgraph_differential as mod
    from app.models.agent import AgentRun
    from app.models.points import UserPoints

    run_id = await mod._setup_run(test_db, SCENARIOS_FIXTURE)

    async with test_db() as session:
        run = await session.get(AgentRun, run_id)
        points = await session.get(UserPoints, run.owner_user_id)
        assert points is not None
        assert points.balance > 0


@pytest.mark.anyio
async def test_run_scenario_loops_until_run_terminal(monkeypatch, test_db):
    """attempt 1 可重试失败 → 脚本必须继续 claim attempt 2 直到 run 终态。"""
    from scripts import langgraph_differential as mod
    from app.core.config import get_settings
    from app.models.agent import AgentRun, AgentRunAttempt
    from app.repositories.agent_repository import AgentRepository
    from app.services.agent import loop as loop_module

    monkeypatch.setattr(get_settings(), "retry_backoff_base_seconds", 0.0)
    _install_fake_llm(monkeypatch, loop_module, patch_session_history=True)
    monkeypatch.setattr(mod, "_session_factory_override", test_db)

    calls = {"n": 0}

    async def fake_process_attempt(self, attempt_id, worker_id, **_kwargs):
        calls["n"] += 1
        async with test_db() as session:
            repo = AgentRepository(session)
            attempt = await session.get(AgentRunAttempt, attempt_id)
            run = await repo.get_run(attempt.run_id)
            now = datetime.now(UTC)
            if calls["n"] == 1:
                await repo.transition_attempt_status(
                    attempt, {"running"}, "failed", failure_code="boom", finished_at=now
                )
                await repo.schedule_retry_attempt(run, attempt, "boom")
            else:
                await repo.transition_attempt_status(
                    attempt, {"running"}, "succeeded", finished_at=now
                )
                run.status = "succeeded"
                session.add(run)
            await session.commit()

    monkeypatch.setattr(loop_module.AgentLoopService, "process_attempt", fake_process_attempt)

    events = await mod.run_scenario(SCENARIOS_FIXTURE, graph=False, recorder=None)

    assert calls["n"] == 2
    assert [event["event_type"] for event in events] == ["run_queued"]
    async with test_db() as session:
        run = await session.scalar(
            select(AgentRun).where(AgentRun.goal == SCENARIOS_FIXTURE["goal"])
        )
        assert run is not None
        assert run.status == "succeeded"


@pytest.mark.anyio
async def test_replay_mode_replaces_web_tools_with_fixed_payloads(monkeypatch, test_db):
    """回放模式：web_search 被固定返回替换，真实实现不被调用。"""
    from scripts import langgraph_differential as mod
    from app.services.agent import loop as loop_module
    from app.services.agent.tool_executor import ToolExecutor

    _install_fake_llm(monkeypatch, loop_module, patch_session_history=True)
    monkeypatch.setattr(mod, "_session_factory_override", test_db)

    plans = {"n": 0}

    async def fake_plan(*_a, **_k):
        plans["n"] += 1
        if plans["n"] == 1:
            return {
                "action": {
                    "type": "web_search",
                    "input": {"query": "差分回放固定查询", "max_results": 3},
                },
                "thought_summary": "先搜索",
            }
        return {"action": {"type": "finish", "input": {}}, "thought_summary": "完成"}

    monkeypatch.setattr(loop_module.AgentLoopService, "_stream_planning", fake_plan)

    # 固定策略：多步可用（全量套件运行顺序下 max_steps 可能被外部状态影响，
    # 导致首个动作被强制 finish，web 工具不会执行）。
    monkeypatch.setattr(
        loop_module.AgentLoopService,
        "_run_policy",
        lambda self, run, max_steps: (True, 5),
    )

    real_calls = {"n": 0}

    async def forbidden_real_web_search(self, payload):
        real_calls["n"] += 1
        raise AssertionError("replay 模式不得调用真实 _web_search")

    monkeypatch.setattr(ToolExecutor, "_web_search", forbidden_real_web_search)

    events = await mod.run_scenario(
        SCENARIOS_FIXTURE, graph=False, recorder=None, replay=True
    )

    observations = [
        event["payload"]["observation"]
        for event in events
        if event["event_type"] == "tool_completed"
        and event["payload"].get("action_type") == "web_search"
    ]
    assert observations == [mod.REPLAY_WEB_STUB_PAYLOADS["web_search"]]
    assert real_calls["n"] == 0
    assert ToolExecutor._web_search is forbidden_real_web_search


@pytest.mark.anyio
async def test_scenario_fault_injection_forces_retryable_failure(monkeypatch, test_db):
    """场景 7 注入 web_search 必失败：注入语义 + 3 次 attempt 耗尽 → run_failed。"""
    from scripts import langgraph_differential as mod
    from app.core.config import get_settings
    from app.models.agent import AgentRun
    from app.services.agent import loop as loop_module
    from app.services.agent.tool_executor import RetryableToolError, ToolExecutor

    settings = get_settings()
    monkeypatch.setattr(settings, "retry_backoff_base_seconds", 0.0)
    monkeypatch.setattr(settings, "merged_plan_thought_enabled", False)
    monkeypatch.setattr(settings, "fast_path_enabled", False)
    _install_fake_llm(monkeypatch, loop_module, patch_session_history=True)
    monkeypatch.setattr(mod, "_session_factory_override", test_db)

    fault_scenario = mod.SCENARIOS[6]
    assert fault_scenario["fault"]["mode"] == "retryable"
    assert "web_search" in fault_scenario["fault"]["tools"]

    async def fake_plan(*_a, **_k):
        return {
            "action": {
                "type": "web_search",
                "input": {"query": "年度营销方案调研", "max_results": 3},
            },
            "thought_summary": "先搜索",
        }

    monkeypatch.setattr(loop_module.AgentLoopService, "_stream_planning", fake_plan)

    with mod._fault_injection(fault_scenario["fault"]):
        with pytest.raises(RetryableToolError):
            await ToolExecutor().execute({"type": "web_search", "input": {"query": "x"}})

    events = await mod.run_scenario(fault_scenario, graph=False, recorder=None)

    event_types = [event["event_type"] for event in events]
    assert event_types.count("run_retry_scheduled") == 2
    assert "run_failed" in event_types
    async with test_db() as session:
        run = await session.scalar(
            select(AgentRun).where(AgentRun.goal == fault_scenario["goal"])
        )
        assert run is not None
        assert run.status == "failed"
