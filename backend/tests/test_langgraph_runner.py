from __future__ import annotations
import pytest
from app.services.agent.langgraph_runner import LangGraphRunner, route_after_plan


@pytest.mark.anyio
async def test_runner_compiles():
    runner = LangGraphRunner(service=None, repo=None, ctx=None, owner_user_id=None, is_super_admin=False)
    compiled = runner.compile()
    assert compiled is not None


def test_route_after_plan_stops_on_retryable_and_terminal():
    """plan 节点返回 _retryable / terminal 时不得进 execute（否则抛 execute before plan）。"""
    assert route_after_plan({"_retryable": True, "pending_action": None}) == "end"
    assert route_after_plan({"terminal": {"action": "failed"}, "pending_action": None}) == "end"
    assert route_after_plan({"_gate_retry": True}) == "end"
    assert route_after_plan({"pending_action": {"action": {"type": "web_search"}}}) == "execute"
