from __future__ import annotations
import pytest
from app.services.agent import AgentLoopService
from app.services.agent.loop import _AttemptContext
from app.models.agent import AgentRun, AgentRunAttempt
import uuid


@pytest.mark.anyio
async def test_do_node_finalize_merges_save_answer_and_streams(monkeypatch, test_db):
    service = AgentLoopService()
    run = AgentRun(id=uuid.uuid4(), goal="写一份方案", owner_user_id=uuid.uuid4(), max_steps=5)
    attempt = AgentRunAttempt(id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1)
    ctx = _AttemptContext(run=run, attempt=attempt)
    runtime = {"service": service, "repo": None, "ctx": ctx, "owner_user_id": None, "is_super_admin": False}

    state = {
        "workflow": {"verified_save_receipts": []},
        "previous_observation": {"final_answer": "答案"},
        "wrote_file": True,
    }
    calls = []

    async def fake_completion(**kw):
        calls.append(kw)
        return None
    monkeypatch.setattr(service, "_persist_successful_completion", fake_completion)

    out = await service._do_node_finalize(state, runtime)
    assert out["terminal"]["action"] == "finish"
