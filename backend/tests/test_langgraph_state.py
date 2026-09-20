from __future__ import annotations
from app.services.agent.langgraph_runner import build_state


def test_build_state_has_required_keys():
    s = build_state()
    assert "workflow" in s
    assert "attempt_ctx" in s
    assert "step_index" in s
    assert "wrote_file" in s
    assert "step_journal" in s
    assert "_gate_retry" in s
    assert "_retryable" in s
    assert "step_duration_seconds" in s
