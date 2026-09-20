from __future__ import annotations

from app.services.agent.langgraph_runner import workflow_to_state


def test_workflow_to_state_maps_field_names():
    from app.services.agent.loop import _RunWorkflowState

    st = _RunWorkflowState(stage="classify", stage_actions=2)
    out = workflow_to_state(st, attempt_ctx={"researched": True})
    assert out["workflow"]["stage"] == "classify"
    assert out["workflow"]["stage_actions"] == 2
    assert out["attempt_ctx"]["researched"] is True
