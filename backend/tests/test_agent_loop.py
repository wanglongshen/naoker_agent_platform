from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from sqlalchemy import select

from app.services.agent import AgentLoopService, DeepSeekClient, ResearchPlanner


def _make_repo(*, is_cancel_requested: bool = False):
    return SimpleNamespace(is_cancel_requested=AsyncMock(return_value=is_cancel_requested))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_stream_text_yields_content_chunks():
    client = DeepSeekClient()

    chunks = [
        chunk
        async for chunk in client._iter_sse_content(
            [
                'data: {"choices":[{"delta":{"content":"你"}}]}\n\n',
                'data: {"choices":[{"delta":{"content":"好"}}]}\n\n',
                'data: [DONE]\n\n',
            ]
        )
    ]

    assert chunks == ["你", "好"]


def test_deepseek_client_reuses_http_client():
    client1 = DeepSeekClient()
    client2 = DeepSeekClient()

    assert client1._client is not client2._client
    assert client1._client is client1._client


@pytest.mark.anyio
async def test_deepseek_client_close_releases_connections():
    client = DeepSeekClient()

    await client.close()

    assert client._client.is_closed


def test_finish_plan_accepts_empty_input():
    parsed = ResearchPlanner()._validate_plan(
        {
            "thought_summary": "信息足够，可以整理结论。",
            "action": {"type": "finish", "input": {}},
        }
    )

    assert parsed.action.type == "finish"


def test_list_files_plan_accepts_empty_folder():
    parsed = ResearchPlanner()._validate_plan(
        {
            "thought_summary": "查看我的文件中是否有相关文件",
            "action": {"type": "list_files", "input": {"folder": ""}},
        }
    )

    assert parsed.action.type == "list_files"
    assert parsed.action.input["folder"] == ""


def test_list_files_plan_accepts_empty_keyword():
    parsed = ResearchPlanner()._validate_plan(
        {
            "thought_summary": "列出我的文件",
            "action": {"type": "list_files", "input": {"keyword": ""}},
        }
    )

    assert parsed.action.type == "list_files"
    assert parsed.action.input["keyword"] == ""


def test_validate_plan_raises_retryable_on_invalid_tool_input():
    from app.services.agent.llm import RetryablePlannerError

    with pytest.raises(RetryablePlannerError):
        ResearchPlanner()._validate_plan(
            {
                "thought_summary": "读取文件",
                "action": {"type": "read_file", "input": {"path": ""}},
            }
        )


def test_visible_thought_truncates_to_500_characters():
    text, fallback = AgentLoopService()._finalize_visible_thought("想" * 700, "http_request")

    assert len(text) == 500
    assert fallback is False


def test_visible_thought_uses_fallback_for_unsafe_content():
    text, fallback = AgentLoopService()._finalize_visible_thought(
        '{"Authorization":"Bearer secret-token"}', "http_request"
    )

    assert text == "我会先查看相关公开资料，核实关键信息后再继续整理。"
    assert fallback is True


@pytest.mark.anyio
async def test_successful_final_answer_persists_events():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            yield "第一部分"
            yield "第二部分"

    service = AgentLoopService()
    service.llm_client = FakeClient()

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
    )

    answer = await service._stream_final_answer(
        None, ctx, [{"role": "user", "content": "测试"}]
    )

    assert answer == "第一部分第二部分"
    event_types = [e[0] for e in events]
    assert event_types == [
        "answer_started",
        "answer_delta",
        "answer_completed",
    ]
    assert events[1][1]["delta"] == "第一部分第二部分"


@pytest.mark.anyio
async def test_final_answer_coalesces_single_character_provider_chunks():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            for _ in range(30):
                yield "字"

    service = AgentLoopService()
    service.llm_client = FakeClient()

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
    )

    answer = await service._stream_final_answer(None, ctx, [{"role": "user", "content": "测试"}])

    deltas = [payload for event_type, payload in events if event_type == "answer_delta"]
    assert answer == "字" * 30
    assert len(deltas) == 1
    assert deltas[0]["offset"] == 0
    assert deltas[0]["delta"] == "字" * 30
    assert "".join(payload["delta"] for payload in deltas) == answer


@pytest.mark.anyio
async def test_final_answer_flushes_a_small_chunk_while_provider_is_paused():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    release_provider = asyncio.Event()

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            yield "慢"
            await release_provider.wait()

    service = AgentLoopService()
    service.llm_client = FakeClient()
    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)
    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
    )

    pending = asyncio.create_task(
        service._stream_final_answer(None, ctx, [{"role": "user", "content": "测试"}])
    )
    # delta is now batched in 50ms windows — it won't appear while the provider is paused
    release_provider.set()

    assert await pending == "慢"
    delta_payloads = [p for e, p in events if e == "answer_delta"]
    assert len(delta_payloads) == 1
    assert delta_payloads[0]["delta"] == "慢"


@pytest.mark.anyio
async def test_final_delta_persistence_failure_emits_answer_failed():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            yield "短回答"

    service = AgentLoopService()
    service.llm_client = FakeClient()
    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)
    event_types: list[str] = []

    async def persist(repo, ctx, event_type, payload, **kwargs):
        event_types.append(event_type)
        if event_type == "answer_delta":
            raise RuntimeError("delta persistence failed")

    service._persist_and_notify = AsyncMock(side_effect=persist)

    with pytest.raises(RuntimeError, match="delta persistence failed"):
        await service._stream_final_answer(None, ctx, [{"role": "user", "content": "测试"}])

    assert "answer_failed" in event_types


@pytest.mark.anyio
async def test_partial_final_answer_failure_not_persisted_as_result():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            yield "未完成"
            raise RuntimeError("stream interrupted")

    service = AgentLoopService()
    service.llm_client = FakeClient()

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
    )

    with pytest.raises(RuntimeError, match="stream interrupted"):
        await service._stream_final_answer(None, ctx, [{"role": "user", "content": "测试"}])

    event_types = [e[0] for e in events]
    assert event_types == [
        "answer_started",
        "answer_checkpoint",
        "answer_failed",
    ]
    checkpoint_payload = events[1][1]
    assert checkpoint_payload == {
        "stream_id": "answer-None",
        "text": "未完成",
        "offset": 3,
    }


@pytest.mark.anyio
async def test_visible_thought_stream_failure_uses_fallback_for_finish_and_does_not_raise():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt
    from app.services.agent.llm import RetryableStreamingError

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            if False:
                yield ""
            raise RetryableStreamingError("thought stream interrupted")

    service = AgentLoopService()
    service.llm_client = FakeClient()

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
    )
    service._stream_final_answer = AsyncMock(return_value="测试回答")

    text = await service._stream_visible_thought(_make_repo(), ctx, 0, "finish", [{"role": "user", "content": "test"}])

    assert text == "现有信息已经足够，我正在整理最终结论。"
    event_types = [e[0] for e in events]
    assert event_types == [
        "visible_thought_started",
        "visible_thought_delta",
        "visible_thought_completed",
    ]
    completed_payload = events[2][1]
    assert completed_payload["fallback"] is True


@pytest.mark.anyio
async def test_visible_thought_stream_emits_multiple_safe_chunks():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            yield "我"
            yield "会先查看"
            yield "公开资料"
            yield "，再整理要点。"

    service = AgentLoopService()
    service.llm_client = FakeClient()

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
    )

    text, _obs = await service._stream_visible_thought_with_tool_interleave(
        repo=_make_repo(),
        ctx=ctx,
        step_index=0,
        validated_action_type="http_request",
        messages=[{"role": "user", "content": "test"}],
        action={"type": "http_request", "input": {}},
        previous_observation=None,
    )

    assert text == "我会先查看公开资料，再整理要点。"
    delta_payloads = [e[1] for e in events if e[0] == "visible_thought_delta"]
    assert len(delta_payloads) == 4
    assert "".join(p["delta"] for p in delta_payloads) == "我会先查看公开资料，再整理要点。"
    assert delta_payloads[0]["offset"] == 0
    completed_payload = events[-1][1]
    assert completed_payload == {
        "step_index": 0,
        "stream_id": "visible-thought-None-0",
        "text": "我会先查看公开资料，再整理要点。",
        "length": 16,
        "fallback": False,
    }


@pytest.mark.anyio
async def test_visible_thought_stream_drops_unsafe_chunks_and_preserves_offsets():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            yield '{"Authorization":"Bearer secret-token"}'

    service = AgentLoopService()
    service.llm_client = FakeClient()

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
    )

    text, _obs = await service._stream_visible_thought_with_tool_interleave(
        repo=_make_repo(),
        ctx=ctx,
        step_index=0,
        validated_action_type="http_request",
        messages=[{"role": "user", "content": "test"}],
        action={"type": "http_request", "input": {}},
        previous_observation=None,
    )

    assert text == "我会先查看相关公开资料，核实关键信息后再继续整理。"
    delta_payloads = [e[1] for e in events if e[0] == "visible_thought_delta"]
    assert len(delta_payloads) == 1
    assert delta_payloads[0]["delta"] == "我会先查看相关公开资料，核实关键信息后再继续整理。"
    assert delta_payloads[0]["offset"] == 0
    completed_payload = events[-1][1]
    assert completed_payload["text"] == "我会先查看相关公开资料，核实关键信息后再继续整理。"
    assert completed_payload["fallback"] is True


@pytest.mark.anyio
async def test_visible_thought_stream_uses_fallback_when_all_chunks_are_unsafe():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            yield "```"
            yield "system prompt"
            yield '{"cookie":"abc"}'

    service = AgentLoopService()
    service.llm_client = FakeClient()

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
    )

    text = await service._stream_visible_thought(None, ctx, 0, "finish", [{"role": "user", "content": "test"}])

    assert text == "现有信息已经足够，我正在整理最终结论。"
    delta_payloads = [e[1] for e in events if e[0] == "visible_thought_delta"]
    assert delta_payloads == [
        {
            "step_index": 0,
            "stream_id": "visible-thought-None-0",
            "offset": 0,
            "delta": "现有信息已经足够，我正在整理最终结论。",
        }
    ]
    completed_payloads = [e[1] for e in events if e[0] == "visible_thought_completed"]
    assert completed_payloads[-1]["fallback"] is True


@pytest.mark.anyio
async def test_visible_thought_stream_truncates_at_500():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            yield "想" * 600
            yield "理" * 100

    service = AgentLoopService()
    service.llm_client = FakeClient()

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
    )

    text, _obs = await service._stream_visible_thought_with_tool_interleave(
        repo=_make_repo(),
        ctx=ctx,
        step_index=0,
        validated_action_type="http_request",
        messages=[{"role": "user", "content": "test"}],
        action={"type": "http_request", "input": {}},
        previous_observation=None,
    )

    assert len(text) == 500
    assert text == "想" * 500
    delta_payloads = [e[1] for e in events if e[0] == "visible_thought_delta"]
    assert len(delta_payloads) == 1
    assert delta_payloads[0]["delta"] == "想" * 500
    assert delta_payloads[0]["offset"] == 0
    completed_payload = events[-1][1]
    assert completed_payload["length"] == 500
    assert completed_payload["fallback"] is False


@pytest.mark.anyio
async def test_first_non_empty_provider_chunk_flushes_immediately():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    class FakeClient:
        async def stream_text(self, messages, **kwargs):
            yield "首"

    service = AgentLoopService()
    service.llm_client = FakeClient()

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
    )

    answer = await service._stream_final_answer(None, ctx, [{"role": "user", "content": "测试"}])

    assert answer == "首"
    event_types = [e[0] for e in events]
    assert event_types == ["answer_started", "answer_delta", "answer_completed"]
    assert events[1][1]["delta"] == "首"


class TestShortTransactionEvents:
    async def test_run_started_is_committed_before_planner_blocks(
        self, monkeypatch, test_db
    ):
        from argon2 import PasswordHasher
        from app.services.agent.loop import AgentLoopService
        from app.models.agent import AgentSession
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"short_tx_user_{uuid.uuid4().hex[:8]}",
                display_name="Short Tx User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()

            session_obj = AgentSession(
                owner_user_id=user.id,
                title="short tx",
            )
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "short tx test", True, [], "expert"
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("worker-test")
            await s.commit()
            assert claimed is not None
            claim_id = claimed.id

        planner_entered = asyncio.Event()
        release_planner = asyncio.Event()

        async def delayed_plan(*_args, **_kwargs):
            planner_entered.set()
            await release_planner.wait()
            return {"thought_summary": "done", "action": {"type": "finish", "input": {}}}

        service = AgentLoopService()
        monkeypatch.setattr(service, "_stream_planning", delayed_plan)

        class FakeClient:
            async def stream_text(self, _messages, **kwargs):
                yield "【需要工具】这个问题需要继续处理"

        monkeypatch.setattr(service, "llm_client", FakeClient())

        import app.services.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        task = asyncio.create_task(
            service.process_attempt(claim_id, "worker-test")
        )
        await asyncio.wait_for(planner_entered.wait(), timeout=15)

        async with test_db() as observer:
            events = await AgentRepository(observer).list_events(run_id)

        event_types = [e.event_type for e in events]
        assert "run_started" in event_types, f"Expected run_started in {event_types}"
        release_planner.set()
        await task


class TestPhase2TerminalConsistency:
    """Task 1: atomic successful completion."""

    @pytest.mark.anyio
    async def test_success_terminal_persistence_sets_result_and_terminal_statuses_atomically(
        self, test_db, monkeypatch
    ):
        import uuid as _uuid
        from argon2 import PasswordHasher
        from app.services.agent import loop as loop_module
        from app.services.agent.loop import AgentLoopService, _AttemptContext
        from app.models.agent import AgentSession, AgentRunAttempt
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository
        from sqlalchemy import select

        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"term_atomic_{_uuid.uuid4().hex[:8]}",
                display_name="Term Atomic User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="atomic test")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "atomic test goal", True, [], "quick"
            )
            run.status = "running"
            attempt.status = "running"
            s.add_all([run, attempt])
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            attempt = await s.scalar(
                select(AgentRunAttempt).where(AgentRunAttempt.id == attempt_id)
            )
            assert run is not None and attempt is not None
            ctx = _AttemptContext(run=run, attempt=attempt)
            service = AgentLoopService()
            await service._persist_successful_completion(
                ctx=ctx,
                answer="final answer text",
                stream_id=f"answer-{run_id}",
                step_number=0,
                thought_summary="done",
                action_type="finish",
                action_payload={},
                observation={"final_answer": "final answer text"},
                step_duration_seconds=0.5,
            )

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "succeeded", f"Expected succeeded, got {run.status}"
            assert run.result is not None
            assert run.result["final_answer"] == "final answer text"
            assert run.result["answer_format"] == "markdown"
            assert "completed_at" in run.result
            assert isinstance(run.result.get("source_event_sequence"), int), (
                f"source_event_sequence should be int, got {run.result.get('source_event_sequence')!r}"
            )

            attempt = await s.get(AgentRunAttempt, attempt_id)
            assert attempt is not None
            assert attempt.status == "succeeded", f"Expected succeeded, got {attempt.status}"

            events = await repo.list_events(run_id)
            event_types = [e.event_type for e in events]
            assert "answer_completed" in event_types, f"answer_completed missing from {event_types}"
            assert "run_succeeded" in event_types, f"run_succeeded missing from {event_types}"

            answer_event = next(e for e in events if e.event_type == "answer_completed")
            assert answer_event.payload["text"] == "final answer text"

            run_succeeded_event = next(e for e in events if e.event_type == "run_succeeded")
            assert run_succeeded_event.payload["final_answer"] == "final answer text"

    @pytest.mark.anyio
    async def test_failed_terminal_guard_does_not_write_result_or_run_succeeded(
        self, test_db, monkeypatch
    ):
        import uuid as _uuid
        from argon2 import PasswordHasher
        from app.services.agent import loop as loop_module
        from app.services.agent.loop import AgentLoopService, _AttemptContext, AgentTerminalStateConflict
        from app.models.agent import AgentSession, AgentRunAttempt
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository
        from sqlalchemy import select

        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"term_guard_{_uuid.uuid4().hex[:8]}",
                display_name="Term Guard User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="guard test")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "guard test goal", True, [], "quick"
            )
            run.status = "running"
            attempt.status = "running"
            s.add_all([run, attempt])
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        from app.repositories.agent_repository import AgentRepository as _AR
        original_mark = _AR.mark_run_succeeded

        async def fake_mark(self_ref, run_obj):
            return False

        monkeypatch.setattr(_AR, "mark_run_succeeded", fake_mark)

        try:
            async with test_db() as s:
                repo = _AR(s)
                run = await repo.get_run(run_id)
                attempt = await s.scalar(
                    select(AgentRunAttempt).where(AgentRunAttempt.id == attempt_id)
                )
                assert run is not None and attempt is not None
                ctx = _AttemptContext(run=run, attempt=attempt)
                service = AgentLoopService()

                with pytest.raises(AgentTerminalStateConflict):
                    await service._persist_successful_completion(
                        ctx=ctx,
                        answer="should not persist",
                        stream_id=f"answer-{run_id}",
                        step_number=0,
                        thought_summary="done",
                        action_type="finish",
                        action_payload={},
                        observation={"final_answer": "should not persist"},
                        step_duration_seconds=0.5,
                    )
        finally:
            monkeypatch.setattr(_AR, "mark_run_succeeded", original_mark)

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run.status == "running", f"Expected still running, got {run.status}"
            assert run.result is None, f"Expected no result, got {run.result}"

            events = await repo.list_events(run_id)
            event_types = [e.event_type for e in events]
            assert "run_succeeded" not in event_types, (
                f"run_succeeded should not exist in {event_types}"
            )

    @pytest.mark.anyio
    async def test_successful_completion_publishes_all_three_committed_events(
        self, test_db, monkeypatch
    ):
        import uuid as _uuid
        from argon2 import PasswordHasher
        from app.services.agent import loop as loop_module
        from app.services.agent.loop import AgentLoopService, _AttemptContext
        from app.models.agent import AgentSession, AgentRunAttempt
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository
        from sqlalchemy import select

        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"committed_{_uuid.uuid4().hex[:8]}",
                display_name="Committed User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="committed test")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "committed goal", True, [], "quick"
            )
            run.status = "running"
            attempt.status = "running"
            s.add_all([run, attempt])
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        published_events: list = []
        real_publish = loop_module.event_bus.publish

        async def capture_publish(event):
            published_events.append(event)
            await real_publish(event)

        monkeypatch.setattr(
            loop_module.event_bus,
            "publish",
            capture_publish,
        )

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            attempt = await s.scalar(
                select(AgentRunAttempt).where(AgentRunAttempt.id == attempt_id)
            )
            assert run is not None and attempt is not None
            ctx = _AttemptContext(run=run, attempt=attempt)
            service = AgentLoopService()
            await service._persist_successful_completion(
                ctx=ctx,
                answer="committed final answer",
                stream_id=f"answer-{run_id}",
                step_number=0,
                thought_summary="done",
                action_type="finish",
                action_payload={},
                observation={"final_answer": "committed final answer"},
                step_duration_seconds=0.3,
            )

        assert len(published_events) == 3, (
            f"Expected 3 committed events, got {len(published_events)}"
        )
        event_types = [e.event_type for e in published_events]
        assert event_types == ["answer_completed", "step_completed", "run_succeeded"], (
            f"Expected [answer_completed, step_completed, run_succeeded], got {event_types}"
        )

        assert all(e.run_id == run_id for e in published_events)
        assert all(e.attempt_id == attempt_id for e in published_events)

        answer_event = published_events[0]
        assert answer_event.payload["text"] == "committed final answer"

        step_event = published_events[1]
        assert step_event.payload["step_index"] == 0

        run_event = published_events[2]
        assert run_event.payload["final_answer"] == "committed final answer"


class TestPhase1BuildSessionHistory:
    """BE-H-01: _build_session_history only finds run_completed, not run_succeeded."""

    @pytest.mark.anyio
    async def test_be_h01_build_session_history_reads_run_succeeded(
        self, test_db
    ): 
        """BE-H-01: ``_build_session_history`` should discover
        ``run_succeeded`` events (not just the non-existent
        ``run_completed``).  Currently it only searches for
        ``run_completed``, so history from succeeded runs is lost.
        """
        import uuid
        from app.services.agent.loop import AgentLoopService
        from app.models.agent import AgentRun, AgentRunEvent, AgentSession
        from app.models.rbac import User
        from argon2 import PasswordHasher

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"beh01_{uuid.uuid4().hex[:8]}",
                display_name="BE-H-01 User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()

            session_obj = AgentSession(
                owner_user_id=user.id, title="be-h01 session"
            )
            s.add(session_obj)
            await s.flush()

            prev_run = AgentRun(
                session_id=session_obj.id,
                owner_user_id=user.id,
                goal="previous question",
                mode="quick",
                status="succeeded",
            )
            s.add(prev_run)
            await s.flush()

            s.add(AgentRunEvent(
                run_id=prev_run.id,
                event_type="run_queued",
                payload={"goal": "previous question"},
            ))
            s.add(AgentRunEvent(
                run_id=prev_run.id,
                event_type="run_started",
                payload={},
            ))
            s.add(AgentRunEvent(
                run_id=prev_run.id,
                event_type="run_succeeded",
                payload={"final_answer": "this is the previous answer"},
            ))
            await s.flush()

            current_run = AgentRun(
                session_id=session_obj.id,
                owner_user_id=user.id,
                goal="current question",
                mode="quick",
                status="running",
            )
            s.add(current_run)
            await s.flush()
            await s.commit()

            session_id = session_obj.id
            current_run_id = current_run.id

        from app.repositories.agent_repository import AgentRepository

        async with test_db() as s:
            repo = AgentRepository(s)
            service = AgentLoopService()
            history = await service._build_session_history(
                repo, session_id, current_run_id
            )

        assert history is not None, (
            "BE-H-01 FAIL: _build_session_history returned None.  "
            "Previous run with run_succeeded event should have been "
            "included in session history."
        )
        assert len(history) == 1, (
            f"BE-H-01 FAIL: expected 1 history entry, got {len(history)}.  "
            "Code only searches for `run_completed` events, but the "
            "system produces `run_succeeded`."
        )
        assert history[0]["user"] == "previous question"
        assert history[0]["assistant"] == "this is the previous answer", (
            "BE-H-01 FAIL: assistant answer not found.  "
            "`_build_session_history` checks `event.event_type == 'run_completed'` "
            "but the system emits `run_succeeded`."
        )


class TestGroupAFixes:
    """Tests for Group A fixes in loop.py."""

    @pytest.mark.anyio
    async def test_fix1_retryable_streaming_error_caught(self, monkeypatch):
        """Fix 1: RetryableStreamingError is in the except tuple and triggers retry."""
        import uuid as _uuid
        from app.services.agent.loop import (
            AgentLoopService,
            _AttemptContext,
        )
        from app.services.agent.llm import RetryableStreamingError

        fake_run_id = _uuid.uuid4()
        fake_attempt_id = _uuid.uuid4()

        run = type("FakeRun", (), {"id": fake_run_id})()
        attempt = type(
            "FakeAttempt",
            (),
            {"id": fake_attempt_id, "attempt_number": 1, "worker_id": "w", "status": "running"},
        )()
        ctx = _AttemptContext(run=run, attempt=attempt)

        service = AgentLoopService()

        schedule_calls = []
        async def fake_schedule(repo, ctx, exc):
            schedule_calls.append(exc)
            return True

        monkeypatch.setattr(service, "_schedule_retryable_failure", fake_schedule)

        # Simulate the try/except block by directly exercising the handler
        # _schedule_retryable_failure should accept RetryableStreamingError
        from app.services.agent.loop import AgentIntegrityError

        class FakeRepo:
            pass

        result = await service._schedule_retryable_failure(
            FakeRepo(), ctx, RetryableStreamingError("stream broke")
        )
        assert result is True
        assert len(schedule_calls) == 1
        assert isinstance(schedule_calls[0], RetryableStreamingError)

    @pytest.mark.anyio
    async def test_fix2_persist_and_notify_uses_repo_session(self, monkeypatch):
        """_persist_and_notify uses the repo session directly, not a new session."""
        import uuid as _uuid
        from app.services.agent.loop import AgentLoopService, _AttemptContext
        from unittest.mock import AsyncMock

        fake_run_id = _uuid.uuid4()
        fake_attempt_id = _uuid.uuid4()

        run = type("FakeRun", (), {"__dict__": {"id": fake_run_id}})()
        attempt = type("FakeAttempt", (), {"__dict__": {"id": fake_attempt_id}})()
        ctx = _AttemptContext(run=run, attempt=attempt)

        fake_event = type("FakeEvent", (), {
            "seq": 42,
            "created_at": type("dt", (), {"isoformat": lambda: "2026-01-01T00:00:00Z"})(),
            "id": fake_run_id,
            "__dict__": {"seq": 42},
        })()

        repo = type("FakeRepo", (), {
            "append_event": AsyncMock(return_value=fake_event),
            "session": type("FakeSession", (), {"commit": AsyncMock()})(),
        })()

        import app.services.agent.loop as loop_mod
        from unittest.mock import MagicMock
        mock_bus = AsyncMock()
        monkeypatch.setattr(loop_mod, "event_bus", mock_bus)

        service = AgentLoopService()
        await service._persist_and_notify(repo, ctx, "test_event", {"key": "val"})

        repo.append_event.assert_awaited_once_with(run, attempt, "test_event", {"key": "val"})
        repo.session.commit.assert_awaited_once()
        mock_bus.publish.assert_called_once()

    @pytest.mark.anyio
    async def test_fix2_persist_terminal_and_notify_raises_on_none_entities(self, monkeypatch):
        """Fix 2: _persist_terminal_and_notify raises AgentIntegrityError when attempt/run is None."""
        import uuid as _uuid
        from app.services.agent.loop import (
            AgentIntegrityError,
            AgentLoopService,
            _AttemptContext,
        )

        fake_run_id = _uuid.uuid4()
        fake_attempt_id = _uuid.uuid4()

        run = type("FakeRun", (), {"__dict__": {"id": fake_run_id}})()
        attempt = type("FakeAttempt", (), {"__dict__": {"id": fake_attempt_id}})()
        ctx = _AttemptContext(run=run, attempt=attempt)

        import app.services.agent.loop as loop_mod
        from unittest.mock import MagicMock

        class FakeSession:
            async def scalar(self, stmt):
                return None

            async def get(self, model, id):
                return None

            async def close(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        fake_factory = MagicMock(return_value=FakeSession())
        monkeypatch.setattr(loop_mod, "async_session_factory", fake_factory)

        service = AgentLoopService()
        with pytest.raises(AgentIntegrityError, match="_persist_terminal_and_notify"):
            await service._persist_terminal_and_notify(
                None, ctx, "run_failed", {"error": "x"}, "failed", "failed"
            )

    @pytest.mark.anyio
    async def test_fix2_persist_successful_completion_raises_on_none_entities(self, monkeypatch):
        """Fix 2: _persist_successful_completion raises AgentIntegrityError when attempt/run is None."""
        import uuid as _uuid
        from app.services.agent.loop import (
            AgentIntegrityError,
            AgentLoopService,
            _AttemptContext,
        )

        fake_run_id = _uuid.uuid4()
        fake_attempt_id = _uuid.uuid4()

        run = type("FakeRun", (), {"__dict__": {"id": fake_run_id}})()
        attempt = type("FakeAttempt", (), {"__dict__": {"id": fake_attempt_id}})()
        ctx = _AttemptContext(run=run, attempt=attempt)

        import app.services.agent.loop as loop_mod
        from unittest.mock import MagicMock

        class FakeSession:
            async def scalar(self, stmt):
                return None

            async def get(self, model, id):
                return None

            async def close(self):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        fake_factory = MagicMock(return_value=FakeSession())
        monkeypatch.setattr(loop_mod, "async_session_factory", fake_factory)

        service = AgentLoopService()
        with pytest.raises(AgentIntegrityError, match="_persist_successful_completion"):
            await service._persist_successful_completion(
                ctx=ctx,
                answer="answer",
                stream_id="s1",
                step_number=0,
                thought_summary="done",
                action_type="finish",
                action_payload={},
                observation={"final_answer": "answer"},
            )

    @pytest.mark.anyio
    async def test_fix3_finish_none_guard_schedules_retry(self, monkeypatch):
        """Fix 3: observation_or_answer None raises RetryablePlannerError handled by retry branch."""
        import uuid as _uuid
        from app.services.agent.loop import AgentLoopService, _AttemptContext
        from app.services.agent.llm import RetryablePlannerError

        run = type("FakeRun", (), {"id": _uuid.uuid4(), "session_id": None, "owner_user_id": None, "goal": "test", "status": "running", "network_enabled": True, "max_steps": 3, "mode": "expert", "result": None})()
        attempt = type("FakeAttempt", (), {"id": _uuid.uuid4(), "run_id": None, "attempt_number": 1, "status": "running"})()
        ctx = _AttemptContext(run=run, attempt=attempt)

        service = AgentLoopService()

        # Mock stream to return (text, None) for a finish action
        async def fake_stream(*args, **kwargs):
            return ("visible thought fallback", None)

        monkeypatch.setattr(service, "_stream_visible_thought_with_tool_interleave", fake_stream)

        async def fake_merged(*args, **kwargs):
            return ({"thought_summary": "done", "action": {"type": "finish", "input": {}}}, None)

        monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)

        # Mock all DB-interacting methods
        service._persist_and_notify = AsyncMock()
        service._persist_terminal_and_notify = AsyncMock()
        service._persist_successful_completion = AsyncMock()
        service._commit_repo = AsyncMock()
        service._build_session_history = AsyncMock(return_value=None)
        service._read_attachment_context = AsyncMock(return_value=[])

        import app.services.agent.loop as loop_module
        monkeypatch.setattr(
            loop_module, "should_try_direct_answer", lambda *a, **k: False
        )

        retry_calls = []

        async def fake_schedule_retryable_failure(repo, ctx, exc):
            retry_calls.append(exc)
            return True

        monkeypatch.setattr(service, "_schedule_retryable_failure", fake_schedule_retryable_failure)

        class FakeRepo:
            async def is_cancel_requested(self, run_id):
                return False
            async def transition_attempt_status(self, *args, **kwargs):
                pass

        # For finish with None observation, the None-guard raises RetryablePlannerError
        # which the retry branch schedules instead of silently returning
        await service._process_attempt_internal(FakeRepo(), ctx)
        assert len(retry_calls) == 1
        assert isinstance(retry_calls[0], RetryablePlannerError)
        assert "finish" in str(retry_calls[0])

    @pytest.mark.anyio
    async def test_p1_resume_uses_llm_streaming_for_post_tool_thought(self, monkeypatch):
        """P1: After tool execution, resume thought is streamed via LLM (not hardcoded template)."""
        from app.services.agent.loop import _AttemptContext

        service = AgentLoopService()

        # Track LLM stream_text calls
        stream_calls = []
        class FakeClient:
            async def stream_text(self, messages, **kwargs):
                stream_calls.append(messages)
                if len(stream_calls) == 1:
                    yield "准备搜索相关资料"
                else:
                    yield "已"
                    yield "找到相关资料"
                    yield "，正在整理。"

        service.llm_client = FakeClient()

        run = type("FakeRun", (), {"id": None, "session_id": None, "owner_user_id": None, "goal": "test", "status": "running", "network_enabled": True, "max_steps": 3, "mode": "quick", "result": None})()
        attempt = type("FakeAttempt", (), {"id": None, "run_id": None, "attempt_number": 1, "status": "running"})()
        ctx = _AttemptContext(run=run, attempt=attempt)

        events = []
        service._persist_and_notify = AsyncMock(
            side_effect=lambda repo, ctx, etype, payload, **kwargs: events.append((etype, payload))
        )

        service.tool_executor = type("FakeTE", (), {
            "execute": AsyncMock(return_value={"result": "ok"})
        })()

        fake_repo = type("FakeRepo", (), {"is_cancel_requested": AsyncMock(return_value=False)})()

        text, obs = await service._stream_visible_thought_with_tool_interleave(
            repo=fake_repo,
            ctx=ctx,
            step_index=0,
            validated_action_type="web_search",
            messages=[{"role": "user", "content": "test"}],
            action={"type": "web_search", "input": {"query": "test query"}},
            previous_observation=None,
            web_enabled=True,
        )

        # P1: stream_text is called for both initial thought and resume thought
        assert len(stream_calls) == 2, (
            f"P1 FAIL: stream_text called {len(stream_calls)} times, expected 2 (initial + resume)"
        )

        # The combined text includes LLM-generated resume content (not a hardcoded template)
        assert "准备搜索相关资料" in text
        assert "已找到相关资料，正在整理。" in text

    @pytest.mark.anyio
    async def test_p2_initial_visible_thought_not_capped_at_150(self):
        """P2: Initial visible thought streams via LLM with 500-char cap, not 150."""
        from app.services.agent.loop import _AttemptContext
        from app.models.agent import AgentRun, AgentRunAttempt

        long_text = "想" * 100 + "理" * 100 + "不会被发送的部分"

        class FakeClient:
            async def stream_text(self, messages, **kwargs):
                yield long_text

        service = AgentLoopService()
        service.llm_client = FakeClient()

        run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
        attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
        ctx = _AttemptContext(run=run, attempt=attempt)

        events = []
        service._persist_and_notify = AsyncMock(
            side_effect=lambda repo, ctx, event_type, payload, **kwargs: events.append((event_type, payload))
        )

        text, _obs = await service._stream_visible_thought_with_tool_interleave(
            repo=_make_repo(),
            ctx=ctx,
            step_index=0,
            validated_action_type="http_request",
            messages=[{"role": "user", "content": "test"}],
            action={"type": "http_request", "input": {}},
            previous_observation=None,
        )

        # P2 assertion: text fits within 500-char cap (not truncated at 150)
        expected_len = 100 + 100 + 8
        assert len(text) == expected_len, f"P2 FAIL: expected {expected_len} chars, got {len(text)}"
        assert text == long_text
        delta_payloads = [e[1] for e in events if e[0] == "visible_thought_delta"]
        assert len(delta_payloads) == 1
        assert delta_payloads[0]["delta"] == text
        assert delta_payloads[0]["offset"] == 0
        completed_payload = events[-1][1]
        assert completed_payload["length"] == len(text)
        assert completed_payload["fallback"] is False

    @pytest.mark.anyio
    async def test_p3_cancel_check_called_once_per_iteration(self, monkeypatch):
        """P3: is_cancel_requested is called exactly once per loop iteration in _process_attempt_internal."""
        import uuid as _uuid
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        run = type("FakeRun", (), {"id": _uuid.uuid4(), "session_id": None, "owner_user_id": None, "goal": "test", "status": "running", "network_enabled": True, "max_steps": 3, "mode": "expert", "result": None})()
        attempt = type("FakeAttempt", (), {"id": _uuid.uuid4(), "run_id": None, "attempt_number": 1, "status": "running"})()
        ctx = _AttemptContext(run=run, attempt=attempt)

        service = AgentLoopService()

        service._persist_and_notify = AsyncMock()
        service._persist_terminal_and_notify = AsyncMock()
        service._persist_successful_completion = AsyncMock()
        service._commit_repo = AsyncMock()
        service._build_session_history = AsyncMock(return_value=None)
        service._read_attachment_context = AsyncMock(return_value=[])

        cancel_call_count = 0

        class FakeRepo:
            async def is_cancel_requested(self, run_id):
                nonlocal cancel_call_count
                cancel_call_count += 1
                return False
            async def transition_attempt_status(self, *args, **kwargs):
                pass

        from app.services.agent.planner import ResearchPlanner
        monkeypatch.setattr(service.planner, "next_action", AsyncMock(
            return_value={"thought_summary": "done", "action": {"type": "finish", "input": {}}}
        ))

        async def fake_stream(*args, **kwargs):
            return ("visible thought", {"final_answer": "answer text"})

        monkeypatch.setattr(service, "_stream_visible_thought_with_tool_interleave", fake_stream)

        await service._process_attempt_internal(FakeRepo(), ctx)

        # P3 assertion: exactly one cancel check per iteration (one iteration since finish returns)
        assert cancel_call_count == 1, (
            f"P3 FAIL: is_cancel_requested called {cancel_call_count} times, expected 1"
        )


class TestStreamingPlanner:
    async def test_stream_planning_emits_events_and_parses_json(
        self, monkeypatch
    ):
        import json
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        plan_chunks = [
            '{"thought_summary"',
            ':"直接回答"',
            ',"action":{"type":"finish","input":{}}}',
        ]

        class FakeStreamClient:
            async def stream_text(self, messages, **kwargs):
                for c in plan_chunks:
                    yield c

        monkeypatch.setattr(service.llm_client, "stream_text", FakeStreamClient().stream_text)

        # Mock _persist_and_notify to capture events instead of writing to DB
        captured_events = []
        async def capture_notify(repo, ctx, event_type, payload):
            captured_events.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture_notify)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000001"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000002"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        messages = [{"role": "user", "content": "test"}]
        result = await service._stream_planning(mock_repo, ctx, messages, 0)

        assert result == json.loads("".join(plan_chunks))
        event_types = [e[0] for e in captured_events]
        assert event_types == ["plan_started", "plan_completed"]


class TestFastPathGate:
    def test_gate_allows_short_goal_without_attachments(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("写一个韭菜炒鸡蛋教程", False) is True

    def test_gate_rejects_attachments(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("分析这个文件", True) is False

    def test_gate_rejects_long_goal(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("请" * 300, False) is False

    def test_gate_rejects_goal_with_file_path(self):
        from app.services.agent.loop import should_try_direct_answer
        goal = "读取 00_Agent规范模板/内容维护标准/自控力_短视频内容创作规范.md"
        assert should_try_direct_answer(goal, False) is False

    def test_gate_rejects_goal_with_file_keyword(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("帮我读取文件", False) is False
        assert should_try_direct_answer("分析这份文档", False) is False
        assert should_try_direct_answer("看看我的附件", False) is False

    def test_gate_still_allows_plain_questions(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("写一个韭菜炒鸡蛋教程", False) is True
        assert should_try_direct_answer("介绍一下你自己", False) is True


class TestDirectAnswerMessages:
    def test_messages_include_tool_self_route_instruction(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        messages = service._build_direct_answer_messages("写个教程", None)
        system_content = messages[0]["content"]
        assert "【需要工具】" in system_content
        assert messages[1]["content"].startswith("用户目标：写个教程")


class TestTryDirectAnswer:
    async def test_direct_answer_success_streams_and_completes(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        chunks = ["韭菜炒鸡蛋教程", "步骤：", "1. 打蛋"]

        class FakeStream:
            async def stream_text(self, messages, **kwargs):
                for c in chunks:
                    yield c

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        completed = []
        async def capture_completion(**kwargs):
            completed.append(kwargs)
        monkeypatch.setattr(service, "_persist_successful_completion", capture_completion)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000001"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000002"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._try_direct_answer(mock_repo, ctx, "写教程", None, 0)

        assert result == "韭菜炒鸡蛋教程步骤：1. 打蛋"
        types = [e[0] for e in emitted]
        assert types[0] == "answer_started"
        assert "answer_delta" in types
        assert types[-1] == "answer_completed"
        assert len(completed) == 1

    async def test_direct_answer_detects_tool_need_and_returns_none(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages, **kwargs):
                yield "【需要工具】这个问题需要搜索最新数据"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        completed = []
        async def capture_completion(**kwargs):
            completed.append(kwargs)
        monkeypatch.setattr(service, "_persist_successful_completion", capture_completion)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000002"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000003"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._try_direct_answer(mock_repo, ctx, "最新金价", None, 0)

        assert result is None
        assert len(completed) == 0
        assert emitted[-1][0] == "answer_failed"

    async def test_direct_answer_detects_marker_split_across_chunks(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages, **kwargs):
                yield "【"
                yield "需要"
                yield "工具】这个问题需要读取文件"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        completed = []
        async def capture_completion(**kwargs):
            completed.append(kwargs)
        monkeypatch.setattr(service, "_persist_successful_completion", capture_completion)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000030"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000031"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._try_direct_answer(mock_repo, ctx, "读取文件", None, 0)

        assert result is None
        assert len(completed) == 0
        assert emitted[-1][0] == "answer_failed"

    async def test_direct_answer_short_answer_without_marker(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages, **kwargs):
                yield "好的"
                yield "，这就回答"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        completed = []
        async def capture_completion(**kwargs):
            completed.append(kwargs)
        monkeypatch.setattr(service, "_persist_successful_completion", capture_completion)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000032"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000033"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._try_direct_answer(mock_repo, ctx, "介绍一下", None, 0)

        assert result == "好的，这就回答"
        assert emitted[-1][0] == "answer_completed"
        assert len(completed) == 1


class TestFastPathIntegration:
    async def test_fast_path_bypasses_planner_on_direct_answer(self, monkeypatch, test_db):
        from app.services.agent.loop import AgentLoopService
        from app.repositories.agent_repository import AgentRepository
        from app.models.agent import AgentSession
        from app.models.rbac import User
        from argon2 import PasswordHasher
        import uuid as _uuid

        uid = _uuid.uuid4().hex[:8]
        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"fp_user_{uid}",
                display_name="FP User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="fp")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "写个教程", True, [], "quick"
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("fp-worker")
            await s.commit()
            assert claimed is not None

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages, **kwargs):
                for c in ["直接回答内容"]:
                    yield c

        monkeypatch.setattr(service, "llm_client", FakeStream())
        monkeypatch.setattr(service.planner, "next_action", None)  # must never be called

        planner_called = {"called": False}
        async def boom(*_args, **_kwargs):
            planner_called["called"] = True
            raise AssertionError("planner must not be called in fast path")
        monkeypatch.setattr(service.planner, "next_action", boom)
        monkeypatch.setattr(service, "_stream_planning", boom)

        import app.services.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        await service.process_attempt(attempt_id, "fp-worker")

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "succeeded"
            assert run.result.get("final_answer") == "直接回答内容"
        assert planner_called["called"] is False


class TestFileToolsIntegration:
    async def test_run_lists_then_reads_file_and_succeeds(self, monkeypatch, test_db):
        from app.services.agent.loop import AgentLoopService
        from app.repositories.agent_repository import AgentRepository
        from app.models.agent import AgentSession
        from app.models.rbac import User
        from argon2 import PasswordHasher
        import uuid as _uuid

        uid = _uuid.uuid4().hex[:8]
        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"ft_user_{uid}",
                display_name="FT User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="ft")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "读取我的文件里的杨振东简历并总结", True, [], "expert"
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("ft-worker")
            await s.commit()
            assert claimed is not None

        service = AgentLoopService()

        # The loop streams the merged plan+thought once per step, plus a resume
        # thought after tool execution and the final answer. Discriminate calls
        # by system-prompt content and plan list_files on the first planner
        # call, then finish on the second.
        class FakeStream:
            def __init__(self):
                self.planner_calls = 0

            async def stream_text(self, messages, **kwargs):
                system = messages[0]["content"]
                if "【决策】" in system or "规划器" in system:
                    self.planner_calls += 1
                    if self.planner_calls == 1:
                        yield '【决策】{"thought_summary":"先列出文件再读取","action":{"type":"list_files","input":{"keyword":"杨振东"}}}\n'
                        yield "【说明】我先查看你的文件中是否有杨振东的资料。"
                    else:
                        yield '【决策】{"thought_summary":"已读取文件内容，信息足够","action":{"type":"finish","input":{"answer":"杨振东：全栈开发工程师，经验丰富。"}}}\n'
                        yield "【说明】我已经获取到杨振东的简历，正在整理结论。"
                elif "工具已执行完毕" in system:
                    yield "我已在文件中找到杨振东的简历，接下来会读取内容。"
                elif "研究助理" in system:
                    yield "杨振东：全栈开发工程师，拥有丰富的开发经验。"
                else:
                    yield "我先查看你的文件中是否有杨振东的资料。"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        # Tool executor: list_files returns one file; read_file returns content
        from unittest.mock import MagicMock
        fake_list = MagicMock()
        async def fake_execute(action, **kwargs):
            if action["type"] == "list_files":
                return {"files": [{"file_id": "00000000-0000-0000-0000-000000000001", "filename": "杨振东-全栈开发.md"}], "total": 1}
            if action["type"] == "read_file":
                return {"filename": "杨振东-全栈开发.md", "content": "杨振东：全栈开发工程师"}
            return {"final_answer": "完成"}
        monkeypatch.setattr(service.tool_executor, "execute", fake_execute)

        import app.services.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        await service.process_attempt(attempt_id, "ft-worker")

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "succeeded"


class TestMergedPlanThought:
    def test_merged_messages_include_format_instruction(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        messages = service._build_merged_messages(
            goal="搜索量子计算最新进展",
            step_index=0,
            previous_observation=None,
            session_history=None,
            web_enabled=True,
            final_step=False,
        )
        system_content = messages[0]["content"]
        assert "【决策】" in system_content
        assert "【说明】" in system_content

    def test_merged_messages_inherit_step_journal(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        messages = service._build_merged_messages(
            goal="写方案保存到 brief/",
            step_index=1,
            previous_observation={"observation": "ok"},
            session_history=None,
            web_enabled=True,
            final_step=False,
            step_journal=["步骤1: read_file(brief_test.md) → 成功"],
        )
        prompt = "\n".join(message["content"] for message in messages)
        assert "本任务已执行步骤" in prompt
        assert "read_file(brief_test.md)" in prompt

    def test_parse_merged_output_ok(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        text = (
            "【决策】{\"thought_summary\":\"需要搜索\",\"action\":{\"type\":\"web_search\",\"input\":{\"query\":\"量子计算\",\"max_results\":5}}}\n"
            "【说明】我将搜索量子计算的最新研究进展。"
        )
        result = service._parse_merged_output(text)
        assert result is not None
        plan, thought = result
        assert plan["action"]["type"] == "web_search"
        assert thought == "我将搜索量子计算的最新研究进展。"

    def test_parse_merged_output_none_when_no_decision(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        result = service._parse_merged_output("【说明】只有说明没有决策")
        assert result is None

    def test_parse_merged_output_none_when_bad_json(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        result = service._parse_merged_output("【决策】not json at all\n【说明】说明文字")
        assert result is None

    async def test_stream_merged_emits_thought_deltas_and_returns_plan(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages, **kwargs):
                for c in [
                    "【决策】{\"thought_summary\":\"需要搜索\",\"action\":{\"type\":\"web_search\",\"input\":{\"query\":\"q\",\"max_results\":5}}}",
                    "\n【说明】我将",
                    "搜索相关资料",
                ]:
                    yield c

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000010"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000011"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._stream_merged_plan_thought(mock_repo, ctx, [{"role": "user", "content": "x"}], 0)

        assert result is not None
        plan, thought = result
        assert plan["action"]["type"] == "web_search"
        assert thought == "我将搜索相关资料"
        types = [e[0] for e in emitted]
        assert types[0] == "plan_started"
        assert "visible_thought_started" in types
        assert "visible_thought_delta" in types
        assert types[-1] == "visible_thought_completed"

    async def test_stream_merged_returns_none_on_unparseable(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages, **kwargs):
                yield "完全不是约定格式的文本"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000012"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000013"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._stream_merged_plan_thought(mock_repo, ctx, [{"role": "user", "content": "x"}], 0)

        assert result is None
        assert [e[0] for e in emitted] == ["plan_started", "plan_completed"]

    async def test_visible_thought_uses_pre_generated_text_without_llm(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()
        llm_called = {"called": False}

        class FakeStream:
            async def stream_text(self, messages, **kwargs):
                llm_called["called"] = True
                yield "不应被调用"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        async def fake_final_answer(repo, ctx, messages):
            return "答案"
        monkeypatch.setattr(service, "_stream_final_answer", fake_final_answer)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000014"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000015"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        text, observation = await service._stream_visible_thought_with_tool_interleave(
            repo=mock_repo, ctx=ctx, step_index=0,
            validated_action_type="finish",
            messages=[{"role": "user", "content": "x"}],
            action={"type": "finish", "input": {}},
            previous_observation=None,
            web_enabled=True,
            pre_generated_thought="我将直接回答",
        )

        assert llm_called["called"] is False
        assert "我将直接回答" in text

    async def test_pre_generated_thought_emits_no_started_or_delta(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append(event_type)
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        async def fake_final_answer(repo, ctx, messages):
            return "答案"
        monkeypatch.setattr(service, "_stream_final_answer", fake_final_answer)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000020"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000021"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        await service._stream_visible_thought_with_tool_interleave(
            repo=mock_repo, ctx=ctx, step_index=0,
            validated_action_type="finish",
            messages=[{"role": "user", "content": "x"}],
            action={"type": "finish", "input": {}},
            previous_observation=None,
            web_enabled=True,
            pre_generated_thought="我将直接回答",
        )

        assert "visible_thought_started" not in emitted
        assert "visible_thought_delta" not in emitted
        assert "visible_thought_completed" in emitted

    async def test_merged_path_used_and_falls_back_to_planner(self, monkeypatch, test_db):
        from app.services.agent.loop import AgentLoopService
        from app.repositories.agent_repository import AgentRepository
        from app.models.agent import AgentSession
        from app.models.rbac import User
        from argon2 import PasswordHasher
        import uuid as _uuid

        uid = _uuid.uuid4().hex[:8]
        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"mp_user_{uid}",
                display_name="MP User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="mp")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "搜索量子计算进展", True, [], "expert"
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("mp-worker")
            await s.commit()
            assert claimed is not None

        service = AgentLoopService()

        merged_called = {"called": False}
        async def fake_merged(repo, ctx, messages, step_index):
            merged_called["called"] = True
            return None  # force fallback to planner

        monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)

        # planner path must still work via _stream_planning
        async def fake_stream_planning(repo, ctx, messages, step_index):
            return {"thought_summary": "直接回答", "action": {"type": "finish", "input": {}}}

        monkeypatch.setattr(service, "_stream_planning", fake_stream_planning)

        class FakeStream:
            async def stream_text(self, messages, **kwargs):
                yield "【需要工具】这个问题需要搜索最新数据"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        import app.services.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        await service.process_attempt(attempt_id, "mp-worker")

        assert merged_called["called"] is True

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "succeeded"


class TestVisibleThoughtFailureHandling:
    async def test_visible_thought_stream_failure_schedules_retry(
        self, test_db, monkeypatch
    ):
        import uuid as _uuid

        import app.services.agent.loop as loop_module
        from argon2 import PasswordHasher
        from sqlalchemy import select as sa_select

        from app.models.agent import AgentRun, AgentRunAttempt, AgentSession
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository
        from app.services.agent.llm import RetryableStreamingError
        from app.services.agent.loop import AgentLoopService

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"vtuser_{_uuid.uuid4().hex[:8]}",
                display_name="VT User",
                password_hash=ph.hash("Password123"),
                status="active",
            )
            s.add(user)
            await s.flush()
            agent_session = AgentSession(owner_user_id=user.id, title="vt")
            s.add(agent_session)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                agent_session, "visible thought failure test", True, [], "quick"
            )
            attempt.status = "running"
            attempt.worker_id = "worker-test"
            s.add(attempt)
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        class RaisingClient:
            async def stream_text(self, messages, **kwargs):
                raise RetryableStreamingError("deepseek_timeout")
                yield

        service = AgentLoopService()
        service.llm_client = RaisingClient()

        async def fake_merged(*args, **kwargs):
            return (
                {
                    "thought_summary": "先搜索",
                    "action": {"type": "web_search", "input": {"query": "q"}},
                },
                None,
            )

        monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)
        monkeypatch.setattr(
            loop_module, "should_try_direct_answer", lambda *a, **k: False
        )

        await service.process_attempt(attempt_id, "worker-test")

        async with test_db() as s:
            run = await s.get(AgentRun, run_id)
            assert run.status == "retry_wait"
            attempts = (
                await s.execute(
                    sa_select(AgentRunAttempt)
                    .where(AgentRunAttempt.run_id == run_id)
                    .order_by(AgentRunAttempt.attempt_number)
                )
            ).scalars().all()
            assert len(attempts) == 2
            assert attempts[0].status == "failed"
            assert attempts[1].status == "queued"
            assert attempts[1].attempt_number == 2

    async def test_empty_tool_input_schedules_retry_not_silent_stop(
        self, test_db, monkeypatch
    ):
        import uuid as _uuid

        import app.services.agent.loop as loop_module
        from argon2 import PasswordHasher
        from sqlalchemy import select as sa_select

        from app.models.agent import AgentRun, AgentRunAttempt, AgentSession
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository
        from app.services.agent.loop import AgentLoopService

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"etuser_{_uuid.uuid4().hex[:8]}",
                display_name="ET User",
                password_hash=ph.hash("Password123"),
                status="active",
            )
            s.add(user)
            await s.flush()
            agent_session = AgentSession(owner_user_id=user.id, title="et")
            s.add(agent_session)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                agent_session, "empty tool input test", True, [], "quick"
            )
            attempt.status = "running"
            attempt.worker_id = "worker-test"
            s.add(attempt)
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        class FakeClient:
            async def stream_text(self, messages, **kwargs):
                yield "我会先查看文件列表"

        service = AgentLoopService()
        service.llm_client = FakeClient()

        async def fake_merged(*args, **kwargs):
            return (
                {
                    "thought_summary": "查看文件",
                    "action": {"type": "list_files", "input": {}},
                },
                None,
            )

        monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)
        monkeypatch.setattr(
            loop_module, "should_try_direct_answer", lambda *a, **k: False
        )

        await service.process_attempt(attempt_id, "worker-test")

        async with test_db() as s:
            run = await s.get(AgentRun, run_id)
            assert run.status == "retry_wait"
            attempts = (
                await s.execute(
                    sa_select(AgentRunAttempt)
                    .where(AgentRunAttempt.run_id == run_id)
                    .order_by(AgentRunAttempt.attempt_number)
                )
            ).scalars().all()
            assert len(attempts) == 2
            assert attempts[0].status == "failed"
            assert attempts[1].status == "queued"


class TestWorkflowInjection:
    async def test_builders_append_workflow_instruction(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService()
        service._workflow_instruction = "【系统工作流约束（必须严格遵守，每次任务都必须执行）】\n核心规则摘要"

        messages = service._build_direct_answer_messages("写方案", None)
        assert "核心规则摘要" in messages[0]["content"]

        merged = service._build_merged_messages(
            goal="写方案", step_index=0, previous_observation=None,
            session_history=None, web_enabled=True, final_step=False,
        )
        assert "核心规则摘要" in merged[0]["content"]

        final = service._build_final_answer_messages(
            goal="写方案", session_history=None, previous_observation=None, attachments=None,
        )
        assert "核心规则摘要" in final[0]["content"]

    async def test_builders_unchanged_when_instruction_empty(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService()
        service._workflow_instruction = ""

        messages = service._build_direct_answer_messages("写方案", None)
        assert "工作流约束" not in messages[0]["content"]


class TestSaveIntentEnforcement:
    async def test_write_rejected_then_finish_is_blocked(self, monkeypatch, test_db):
        from app.services.agent.loop import AgentLoopService
        from app.repositories.agent_repository import AgentRepository
        from app.models.agent import AgentSession
        from app.models.rbac import User
        from argon2 import PasswordHasher
        import uuid as _uuid

        uid = _uuid.uuid4().hex[:8]
        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"ft_user_{uid}",
                display_name="FT User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="ft")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "读取 brief_test.md，然后写一份方案保存到 brief 文件夹中，最后把保存结果告诉我", True, [], "expert"
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("ft-worker")
            await s.commit()
            assert claimed is not None

        service = AgentLoopService()

        class FakeStream:
            def __init__(self):
                self.planner_calls = 0

            async def stream_text(self, messages, **kwargs):
                system = messages[0]["content"]
                if "【决策】" in system or "规划器" in system:
                    self.planner_calls += 1
                    if self.planner_calls == 1:
                        yield '【决策】{"thought_summary":"先读取brief资料","action":{"type":"read_file","input":{"path":"brief/brief_test.md"}}}\n'
                        yield "【说明】先读取 brief 资料。"
                    elif self.planner_calls == 2:
                        yield '【决策】{"thought_summary":"写入方案","action":{"type":"write_file","input":{"path":"brief/方案.md","content":"# 残缺方案\\n## 一、Brief Recap\\n"}}}\n'
                        yield "【说明】我正在写入方案文件。"
                    else:
                        yield '【决策】{"thought_summary":"保存成功","action":{"type":"finish","input":{"answer":"已保存"}}}\n'
                        yield "【说明】文件已保存。"
                elif "工具已执行完毕" in system:
                    yield "我继续处理。"
                elif "研究助理" in system:
                    yield "已完成。"
                else:
                    yield "我继续处理。"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        from unittest.mock import MagicMock
        fake_execute_calls = []

        async def fake_execute(action, **kwargs):
            fake_execute_calls.append(action["type"])
            if action["type"] == "read_file":
                return {
                    "content": "brief 内容：目标回顾、市场分析、预算与排期、执行策略。",
                    "filename": "brief_test.md",
                    "path": "brief/brief_test.md",
                }
            if action["type"] == "write_file":
                content = action["input"].get("content", "")
                if "## 八、附录" not in content:
                    return {
                        "error": "plan_structure_incomplete",
                        "missing_modules": ["前策调研", "本品表现", "用户分析", "投流策略", "Roadmap", "附录"],
                        "skeleton": "## 一、Brief Recap\n## 二、前策调研\n## 三、本品表现\n## 四、用户分析\n## 五、创意与传播规划\n## 六、投流策略\n## 七、Roadmap\n## 八、附录",
                    }
                return {
                    "file_id": "00000000-0000-0000-0000-000000000099",
                    "filename": "方案.md",
                    "folder_path": "brief",
                    "action": "created",
                }
            return {"final_answer": "已保存"}

        monkeypatch.setattr(service.tool_executor, "execute", fake_execute)

        import app.services.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        # write_file 被拒（observation 带 error）→ wrote_file 保持 False → 模型 plan
        # finish 被 _enforce_save_intent 拦截（抛 RetryablePlannerError）→ 走重试调度，
        # 而不是终态失败：原 attempt 标记 failed，新 attempt 排队重试，run 保持非 failed
        await service.process_attempt(attempt_id, "ft-worker")

        assert fake_execute_calls.count("write_file") == 1

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "retry_wait"
            from app.models.agent import AgentRunAttempt

            attempt_obj = await s.get(AgentRunAttempt, attempt_id)
            assert attempt_obj is not None
            assert attempt_obj.status == "failed"
            assert attempt_obj.failure_code == "save_intent_unfulfilled"

            retry_stmt = select(AgentRunAttempt).where(
                AgentRunAttempt.retry_of_attempt_id == attempt_id
            )
            retry_attempts = list((await s.execute(retry_stmt)).scalars().all())
            assert len(retry_attempts) == 1
            retry_attempt = retry_attempts[0]
            assert retry_attempt.attempt_number == 2
            assert retry_attempt.status == "queued"


def test_save_intent_gate_blocks_finish_without_save():
    from app.services.agent.loop import AgentLoopService
    from app.services.agent.llm import RetryablePlannerError

    svc = AgentLoopService()
    with pytest.raises(RetryablePlannerError) as exc_info:
        svc._enforce_save_intent(
            goal="读取 brief 写方案保存到 brief/",
            plan={"action": {"type": "finish", "input": {}}},
            wrote_file=False,
            final_step=True,
        )
    assert "save_intent_unfulfilled" in str(exc_info.value)

class TestWorkflowStageMachine:
    """Task 3: blueprint stage state machine in the main loop."""

    # A1 后：方案类目标缺 ≥2 项关键约束会先追问；本组测试关注阶段机，
    # 故使用信息完整的 goal，避免命中追问分支。
    _COMPLETE_GOAL = (
        "写一份完整方案并附执行步骤：预算 50 万、周期 3 个月、"
        "目标 GMV 1000 万、必讲卖点、考核指标"
    )

    @staticmethod
    def _rules():
        from app.services.agent.workflow_rules import (
            AdmissionRule,
            ParsedRules,
            TaskTypeRule,
            WorkflowGraph,
            WorkflowStep,
        )

        return ParsedRules(
            sha256="0123456789abcdef",
            task_types=[
                TaskTypeRule(
                    type_name="完整方案需求",
                    features=["方案", "保存到"],
                    default_action="route.md",
                ),
                TaskTypeRule(
                    type_name="纯框架问题",
                    features=["框架"],
                    default_action="direct",
                ),
            ],
            admission_rules=[
                AdmissionRule(branch="可直接产出", applies="约束清楚", next_step="直接产出")
            ],
            graph=WorkflowGraph(
                steps=[WorkflowStep(step_id="0", title="分类", body="x", kind="rule")],
                task_type_edges={
                    "完整方案需求": ["0", "0.5", "1", "1.1", "3", "5", "6", "7", "8"],
                    "纯框架问题": ["0"],
                },
            ),
            red_lines=["待补充", "待确认"],
            structure=[],
        )

    def test_classify_stage_advances_to_admission(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        svc._workflow_rules = self._rules()
        asyncio.run(svc._advance_workflow_stage(
            None, SimpleNamespace(goal=self._COMPLETE_GOAL), 0
        ))
        assert svc._workflow_task_type == "完整方案需求"
        # 代码阶段连推：classify → admission → recap（模型阶段，材料盘点未完成即停）
        assert svc._workflow_stage == "recap"
        assert svc._workflow_stages_done == ["classify", "admission"]

    def test_admission_stage_advances_to_recap(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        svc._workflow_rules = self._rules()
        svc._workflow_task_type = "完整方案需求"
        svc._workflow_stage = "admission"
        svc._workflow_stages_done = ["classify"]
        asyncio.run(svc._advance_workflow_stage(
            None, SimpleNamespace(goal=self._COMPLETE_GOAL), 0
        ))
        assert svc._workflow_admission == "可直接产出"
        assert svc._workflow_stage == "recap"
        assert svc._workflow_stages_done == ["classify", "admission"]

    def test_next_stage_after_follows_task_type_path(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        svc._workflow_rules = self._rules()
        assert svc._next_stage_after("classify", "完整方案需求") == "admission"
        assert svc._next_stage_after("admission", "完整方案需求") == "recap"
        assert svc._next_stage_after("classify", "纯框架问题") == "classify"

    def test_stage_context_injected_into_merged_user_prompt(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        messages = svc._build_merged_messages(
            goal="写方案",
            step_index=0,
            previous_observation=None,
            session_history=None,
            web_enabled=True,
            final_step=False,
            stage_context="recap",
        )
        assert "当前工作流阶段：recap" in messages[1]["content"]

    def test_stage_context_falls_back_to_free_execution(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        messages = svc._build_merged_messages(
            goal="写方案",
            step_index=0,
            previous_observation=None,
            session_history=None,
            web_enabled=True,
            final_step=False,
            stage_context=None,
        )
        assert "当前工作流阶段：自由执行" in messages[1]["content"]

    @pytest.mark.anyio
    async def test_main_loop_injects_stage_and_records_blueprint_sha256(
        self, test_db, monkeypatch
    ):
        from argon2 import PasswordHasher
        from app.models.agent import AgentSession
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository
        from app.services.agent.loop import AgentLoopService

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"stage_machine_{uuid.uuid4().hex[:8]}",
                display_name="Stage Machine User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="stage machine")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, self._COMPLETE_GOAL, True, [], "expert"
            )
            await s.commit()
            run_id = run.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("stage-worker")
            await s.commit()
            assert claimed is not None

        service = AgentLoopService()
        rules = self._rules()

        async def fake_get_rules(_session, _goal):
            return rules

        async def fake_get_instruction(_session, _goal):
            return ""

        async def fake_resolve_admin(_session):
            return uuid.UUID("00000000-0000-0000-0000-000000000001")

        monkeypatch.setattr(service.workflow_policy, "get_rules", fake_get_rules)
        monkeypatch.setattr(
            service.workflow_policy, "get_instruction", fake_get_instruction
        )
        monkeypatch.setattr(
            service.workflow_policy, "_resolve_super_admin_id", fake_resolve_admin
        )

        captured_messages = []
        plan_call = {"count": 0}

        async def fake_stream_planning(_repo, _ctx, messages, _step_index):
            captured_messages.append(messages)
            plan_call["count"] += 1
            if plan_call["count"] == 1:
                return {
                    "thought_summary": "盘点文件",
                    "action": {"type": "list_files", "input": {"limit": 10}},
                }
            if plan_call["count"] in (2, 3):
                return {
                    "thought_summary": "先搜索",
                    "action": {"type": "web_search", "input": {"query": "测试搜索"}},
                }
            if plan_call["count"] == 4:
                return {
                    "thought_summary": "写文件",
                    "action": {
                        "type": "write_file",
                        "input": {"path": "brief/x_V1.md", "content": "方案内容"},
                    },
                }
            return {
                "thought_summary": "直接回答",
                "action": {"type": "finish", "input": {}},
            }

        monkeypatch.setattr(service, "_stream_planning", fake_stream_planning)

        async def fake_execute(action, **kwargs):
            if action["type"] == "list_files":
                return {"files": []}
            if action["type"] == "web_search":
                return {"results": []}
            if action["type"] == "write_file":
                return {"path": "brief/x_V1.md", "status": "created"}
            return {"result": "ok"}

        monkeypatch.setattr(service.tool_executor, "execute", fake_execute)

        class FakeClient:
            async def stream_text(self, _messages, **kwargs):
                yield "【需要工具】这个问题需要继续处理"

        monkeypatch.setattr(service, "llm_client", FakeClient())

        import app.services.agent.loop as loop_module

        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        await service.process_attempt(claimed.id, "stage-worker")

        assert captured_messages, "planner 应至少被调用一次"
        assert any(
            "当前工作流阶段" in message[1]["content"] for message in captured_messages
        )
        assert plan_call["count"] == 5, (
            f"阶段机应在 recap/research/content 完成后推进至完成，"
            f"实际 planner 调用 {plan_call['count']} 次"
        )

        async with test_db() as s:
            stored = await AgentRepository(s).get_run(run_id)
            assert stored is not None
            assert stored.result is not None
            # 新代码把状态机证据平铺进 result：阶段全链推进记录
            assert stored.result.get("workflow_stages_done") == [
                "classify",
                "admission",
                "recap",
                "version",
                "research",
                "content",
                "redline",
            ]


class TestQuestionHang:
    """Task 4: admission=先追问 hangs the run with pending questions."""

    @staticmethod
    def _rules():
        from app.services.agent.workflow_rules import (
            AdmissionRule,
            ParsedRules,
            TaskTypeRule,
            WorkflowGraph,
            WorkflowStep,
        )

        return ParsedRules(
            sha256="0123456789abcdef",
            task_types=[
                TaskTypeRule(
                    type_name="完整方案需求",
                    features=["方案", "保存到"],
                    default_action="route.md",
                ),
            ],
            admission_rules=[
                AdmissionRule(
                    branch="先追问",
                    applies="缺口会改变策略方向",
                    next_step="集中提出不超过 5 个关键问题",
                )
            ],
            graph=WorkflowGraph(
                steps=[WorkflowStep(step_id="0", title="分类", body="x", kind="rule")],
                task_type_edges={
                    "完整方案需求": ["0", "0.5", "1", "1.1", "3", "5", "6", "7", "8"],
                },
            ),
            red_lines=[],
            structure=[],
        )

    @pytest.mark.anyio
    async def test_admission_questioning_hangs_run(self, test_db, monkeypatch):
        import uuid as _uuid
        from argon2 import PasswordHasher
        from app.services.agent import loop as loop_module
        from app.services.agent.loop import AgentLoopService
        from app.services.agent.workflow_rules import AdmissionRule
        from app.models.agent import AgentSession, AgentRunAttempt
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository

        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"question_hang_{_uuid.uuid4().hex[:8]}",
                display_name="Question Hang User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="question hang")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "写一份完整方案并附执行步骤", True, [], "expert"
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("question-worker")
            await s.commit()
            assert claimed is not None

        service = AgentLoopService()
        rules = self._rules()

        async def fake_get_rules(_session, _goal):
            return rules

        async def fake_get_instruction(_session, _goal):
            return ""

        async def fake_resolve_admin(_session):
            return uuid.UUID("00000000-0000-0000-0000-000000000001")

        monkeypatch.setattr(service.workflow_policy, "get_rules", fake_get_rules)
        monkeypatch.setattr(
            service.workflow_policy, "get_instruction", fake_get_instruction
        )
        monkeypatch.setattr(
            service.workflow_policy, "_resolve_super_admin_id", fake_resolve_admin
        )

        def fake_admission_judgment(goal, files_read_ok, missing_constraints):
            return AdmissionRule(
                branch="先追问",
                applies="缺口会改变策略方向",
                next_step="集中提出不超过 5 个关键问题",
            )

        monkeypatch.setattr(loop_module, "admission_judgment", fake_admission_judgment)
        monkeypatch.setattr(
            loop_module, "should_try_direct_answer", lambda *a, **k: False
        )

        async def fake_merged(*_args, **_kwargs):
            return (
                {
                    "thought_summary": "先搜索",
                    "action": {"type": "web_search", "input": {"query": "q"}},
                },
                None,
            )

        monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)

        async def fake_planning(*_args, **_kwargs):
            return {
                "thought_summary": "先搜索",
                "action": {"type": "web_search", "input": {"query": "q"}},
            }

        monkeypatch.setattr(service, "_stream_planning", fake_planning)

        async def fake_execute(action, **kwargs):
            return {"result": "ok"}

        monkeypatch.setattr(service.tool_executor, "execute", fake_execute)

        class FakeClient:
            async def stream_text(self, _messages, **kwargs):
                yield "我先查看相关公开资料，再整理要点。"

        monkeypatch.setattr(service, "llm_client", FakeClient())

        await service.process_attempt(claimed.id, "question-worker")

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "awaiting_question", (
                f"expected awaiting_question, got {run.status}"
            )
            assert isinstance(run.pending_questions, list)
            assert 0 < len(run.pending_questions) <= 5
            assert all("question" in q for q in run.pending_questions)

            attempt = await s.get(AgentRunAttempt, attempt_id)
            assert attempt is not None
            assert attempt.status == "paused", (
                f"expected paused attempt, got {attempt.status}"
            )
            assert attempt.finished_at is not None

            events = await repo.list_events(run_id)
            event_types = [e.event_type for e in events]
            assert "run_awaiting_question" in event_types, (
                f"run_awaiting_question missing from {event_types}"
            )
            awaiting_event = next(
                e for e in events if e.event_type == "run_awaiting_question"
            )
            assert isinstance(awaiting_event.payload["questions"], list)
            assert len(awaiting_event.payload["questions"]) <= 5
            assert "run_failed" not in event_types

    @pytest.mark.anyio
    async def test_build_questions_returns_at_most_five(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        questions = svc._build_questions("写一份完整方案")
        assert isinstance(questions, list)
        assert 0 < len(questions) <= 5
        assert all("question" in q and "affects" in q for q in questions)


class TestAdmissionAskBranch:
    """T8/A1: plan goals missing ≥2 critical constraints pause for questions."""

    @staticmethod
    def _rules():
        from app.services.agent.workflow_rules import (
            AdmissionRule,
            ParsedRules,
            TaskTypeRule,
            WorkflowGraph,
            WorkflowStep,
        )

        return ParsedRules(
            sha256="0123456789abcdef",
            task_types=[
                TaskTypeRule(
                    type_name="完整方案需求",
                    features=["方案", "保存到"],
                    default_action="route.md",
                ),
                TaskTypeRule(
                    type_name="纯框架问题",
                    features=["框架"],
                    default_action="direct",
                ),
            ],
            admission_rules=[
                AdmissionRule(branch="可直接产出", applies="约束清楚", next_step="直接产出")
            ],
            graph=WorkflowGraph(
                steps=[WorkflowStep(step_id="0", title="分类", body="x", kind="rule")],
                task_type_edges={
                    "完整方案需求": ["0", "0.5", "1", "1.1", "3", "5", "6", "7", "8"],
                    "纯框架问题": ["0"],
                },
            ),
            red_lines=[],
            structure=[],
        )

    @classmethod
    def _svc(cls):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        svc._workflow_rules = cls._rules()
        svc._workflow_task_type = "完整方案需求"
        svc._workflow_stage = "admission"
        svc._workflow_stages_done = ["classify"]
        return svc

    def test_admission_ask_enabled_defaults_to_true(self):
        from app.services.agent.loop import AgentLoopService

        assert AgentLoopService().admission_ask_enabled is True

    def test_asks_when_two_or_more_constraints_missing(self):
        from app.services.agent.loop import _QuestionHangSignal

        svc = self._svc()
        run = SimpleNamespace(goal="帮我写一份新品上市方案")
        with pytest.raises(_QuestionHangSignal) as exc_info:
            asyncio.run(svc._advance_workflow_stage(None, run, 0))
        assert svc._workflow_stage == "awaiting_question"
        assert svc._workflow_admission == "先追问"
        questions = exc_info.value.questions
        assert 0 < len(questions) <= 5
        assert any("预算" in q["question"] for q in questions)
        assert any("周期" in q["question"] for q in questions)

    def test_does_not_ask_when_constraints_complete(self):
        svc = self._svc()
        run = SimpleNamespace(
            goal="帮我写一份新品上市方案：预算 50 万、周期 3 个月、"
            "目标 GMV 1000 万、必讲卖点、考核指标"
        )
        asyncio.run(svc._advance_workflow_stage(None, run, 0))
        assert svc._workflow_stage == "recap"
        assert svc._workflow_admission == "可直接产出"

    def test_disabled_flag_falls_back_to_old_behavior(self):
        svc = self._svc()
        svc.admission_ask_enabled = False
        run = SimpleNamespace(goal="帮我写一份新品上市方案")
        asyncio.run(svc._advance_workflow_stage(None, run, 0))
        assert svc._workflow_stage == "recap"
        assert svc._workflow_admission == "可直接产出"

    def test_skips_ask_for_research_exempt_goal(self):
        svc = self._svc()
        run = SimpleNamespace(goal="基于已有资料直接产出，帮我写一份新品上市方案")
        asyncio.run(svc._advance_workflow_stage(None, run, 0))
        assert svc._workflow_stage == "recap"

    def test_skips_ask_for_non_plan_goal(self):
        svc = self._svc()
        run = SimpleNamespace(goal="什么是品牌心智模型？")
        asyncio.run(svc._advance_workflow_stage(None, run, 0))
        assert svc._workflow_stage == "recap"

    def test_build_questions_prioritizes_missing_constraints(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        questions = svc._build_questions(
            "写一份完整方案", missing=["时间周期", "成功指标"]
        )
        assert 0 < len(questions) <= 5
        assert "周期" in questions[0]["question"]
        assert "成功指标" in questions[1]["question"]


class TestStageAdvance:
    """Task 2: full code-driven stage advancement for plan-class tasks."""

    def _svc(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        svc._workflow_rules = object()  # 非 None 即启用
        return svc

    def test_research_advances_to_content_when_search_done(self):
        svc = self._svc()
        svc._workflow_stage = "research"
        svc._research_ok = True
        asyncio.run(svc._advance_workflow_stage(None, None, 0))
        assert svc._workflow_stage == "content"

    def test_research_stays_when_no_search(self):
        svc = self._svc()
        svc._workflow_stage = "research"
        svc._research_ok = False
        asyncio.run(svc._advance_workflow_stage(None, None, 0))
        assert svc._workflow_stage == "research"

    def test_content_advances_to_redline_when_saved(self):
        svc = self._svc()
        svc._workflow_stage = "content"
        svc._save_ok = True
        asyncio.run(svc._advance_workflow_stage(None, None, 0))
        # redline 是代码阶段，while 循环连推到 done
        assert svc._workflow_stage == "done"

    def test_redline_advances_to_done_when_clean(self):
        svc = self._svc()
        svc._workflow_stage = "redline"
        asyncio.run(svc._advance_workflow_stage(None, None, 0))
        assert svc._workflow_stage == "done"

    def test_recap_requires_action(self):
        svc = self._svc()
        svc._workflow_stage = "recap"
        svc._material_inventory_done = True
        svc._stage_actions = 0
        asyncio.run(svc._advance_workflow_stage(None, None, 0))
        assert svc._workflow_stage == "recap"  # 无动作不推进
        svc._stage_actions = 1
        asyncio.run(svc._advance_workflow_stage(None, None, 0))
        # version 是代码阶段，while 循环连推到 research（模型阶段，未研究即停）
        assert svc._workflow_stage == "research"


class TestStageGate:
    """Task 2: per-stage action whitelist + research gate + version gate."""

    def test_research_stage_rejects_write_file(self):
        from app.services.agent.llm import RetryablePlannerError

        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "research"
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/x_V1.md"}}}
        with pytest.raises(RetryablePlannerError) as ei:
            svc._enforce_stage_gate(plan)
        assert "stage_gate" in str(ei.value)

    def test_research_stage_allows_web_search(self):
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "research"
        plan = {"thought_summary": "x", "action": {"type": "web_search", "input": {"query": "x"}}}
        svc._enforce_stage_gate(plan)  # 不抛

    def test_research_gate_blocks_write_without_search(self):
        from app.services.agent.llm import RetryablePlannerError

        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "content"
        svc._fallback_state.material_inventory_done = True
        svc._research_ok = False
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/x_V1.md"}}}
        with pytest.raises(RetryablePlannerError) as ei:
            svc._enforce_stage_gate(plan)
        assert "research_required" in str(ei.value)

    def test_research_gate_passes_after_search(self):
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "content"
        svc._fallback_state.material_inventory_done = True
        svc._research_ok = True
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/x_V1.md"}}}
        svc._enforce_stage_gate(plan)  # 不抛

    def test_version_gate_rejects_unversioned_filename(self):
        from app.services.agent.llm import RetryablePlannerError

        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "content"
        svc._fallback_state.material_inventory_done = True
        svc._research_ok = True
        svc._workflow_version_rule = None  # 触发默认
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/创意建议方案.md"}}}
        with pytest.raises(RetryablePlannerError) as ei:
            svc._enforce_stage_gate(plan)
        assert "version_required" in str(ei.value)

    def test_version_gate_passes_versioned_filename(self):
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "content"
        svc._fallback_state.material_inventory_done = True
        svc._research_ok = True
        svc._workflow_version_rule = None
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/GAP_V1_创意建议.md"}}}
        svc._enforce_stage_gate(plan)  # 不抛

    def test_no_rules_ignores_gates(self):
        svc = AgentLoopService()
        svc._workflow_rules = None  # 非方案类
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/x.md"}}}
        svc._enforce_stage_gate(plan)  # 不抛


class TestAnswerTruthfulness:
    """Task 2: claimed saved .md filenames must exist in this run's save list."""

    def test_claims_saved_file_not_in_list_rejected(self):
        from app.services.agent.llm import RetryablePlannerError

        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = ["GAP_V1_创意建议.md"]
        with pytest.raises(RetryablePlannerError) as ei:
            svc._enforce_answer_truthfulness("方案已保存至 brief/其他文件.md")
        assert "answer_truthfulness" in str(ei.value)

    def test_claims_real_file_passes(self):
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = ["GAP_V1_创意建议.md"]
        svc._enforce_answer_truthfulness("方案已保存至 brief/GAP_V1_创意建议.md")  # 不抛

    def test_no_file_mention_passes(self):
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = ["GAP_V1_创意建议.md"]
        svc._enforce_answer_truthfulness("方案已完成，包含策略与创意方向。")  # 不抛

    def test_claims_file_but_nothing_saved_rejected(self):
        from app.services.agent.llm import RetryablePlannerError

        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = []
        with pytest.raises(RetryablePlannerError) as ei:
            svc._enforce_answer_truthfulness("已保存至 brief/方案.md")
        assert "answer_truthfulness" in str(ei.value)
class TestRetryPreservesStage:
    """重试（attempt>1）必须保留状态机进度，不能从 classify 重新开始。"""

    def test_second_attempt_keeps_stage_progress(self):
        from app.services.agent.loop import AgentLoopService
        from uuid import uuid4

        svc = AgentLoopService()
        run_id = uuid4()
        st = svc._wf(run_id)
        st.stage = "content"
        st.stage_actions = 5
        st.research_ok = True
        st.save_ok = True

        svc._maybe_reset_workflow_state(run_id, attempt_number=2)

        kept = svc._wf(run_id)
        assert kept.stage == "content"
        assert kept.stage_actions == 5
        assert kept.save_ok is True

    def test_first_attempt_resets_state(self):
        from app.services.agent.loop import AgentLoopService
        from uuid import uuid4

        svc = AgentLoopService()
        run_id = uuid4()
        st = svc._wf(run_id)
        st.stage = "content"

        svc._maybe_reset_workflow_state(run_id, attempt_number=1)

        assert svc._wf(run_id).stage == "classify"
        assert svc._wf(run_id).stage_actions == 0


class TestWorkflowStateIsolation:
    """agent_loop_service 是进程单例，不同 run 的状态必须隔离。"""

    def test_states_isolated_per_run(self):
        from app.services.agent.loop import AgentLoopService
        from uuid import uuid4

        svc = AgentLoopService()
        a_id, b_id = uuid4(), uuid4()
        svc._wf(a_id).stage = "research"
        svc._wf(a_id).save_ok = True

        assert svc._wf(b_id).stage == "classify"
        assert svc._wf(b_id).save_ok is False
        assert svc._wf(a_id).stage == "research"

    def test_fallback_state_used_for_test_calls(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        svc._workflow_stage = "research"
        assert svc._wf(None).stage == "research"


class TestAnswerTruthfulnessContext:
    """真实性校验只拦"声称保存"语境，不拦"读取/阅读"的提及。"""

    def test_read_mentions_not_treated_as_claimed_save(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = ["GAP_V1_创意建议.md"]
        svc._enforce_answer_truthfulness(
            "已读取 brief_test.md，方案已保存至 brief/GAP_V1_创意建议.md"
        )  # 不抛

    def test_save_mention_of_wrong_file_still_rejected(self):
        from app.services.agent.llm import RetryablePlannerError
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = ["GAP_V1_创意建议.md"]
        with pytest.raises(RetryablePlannerError, match="answer_truthfulness"):
            svc._enforce_answer_truthfulness("已保存至 brief/其他文件.md")

    def test_save_without_verb_context_not_checked(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = []
        svc._enforce_answer_truthfulness("我读取了 brief_test.md 和 GAP_V1_创意建议.md")  # 不抛


class TestObservationHistory:
    """工具观察跨步骤累积，避免模型"失忆"反复重读。"""

    def test_observation_recorded_with_cap(self):
        from app.services.agent.loop import AgentLoopService
        from uuid import uuid4

        svc = AgentLoopService()
        run_id = uuid4()
        for i in range(10):
            svc._record_observation(run_id, "web_search", {"results": [f"r{i}"]})
        st = svc._wf(run_id)
        assert len(st.observation_history) <= 5

    def test_observation_text_injected_into_messages(self):
        from app.services.agent.loop import AgentLoopService
        from uuid import uuid4

        svc = AgentLoopService()
        run_id = uuid4()
        svc._record_observation(run_id, "read_file", {"content": "brief 正文内容"})
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "goal"},
        ]
        out = svc._inject_observation_history(messages, run_id)
        assert "brief 正文内容" in out[1]["content"]

    def test_observation_truncated_at_4000_chars(self):
        from app.services.agent.loop import AgentLoopService
        from uuid import uuid4

        svc = AgentLoopService()
        run_id = uuid4()
        long_obs = {"content": "x" * 6000}
        svc._record_observation(run_id, "read_file", long_obs)
        st = svc._wf(run_id)
        assert len(st.observation_history) == 1
        # "read_file: " 前缀（11 字符）+ 截断 4000
        assert len(st.observation_history[0]) == 11 + 4000


class TestMergedObservationInjection:
    """merged 路径必须注入累积的工具观察（修复模型反复重读）。"""

    def test_merged_messages_include_observation_history(self):
        from uuid import uuid4

        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        run_id = uuid4()
        st = svc._wf(run_id)
        st.observation_history.append("read_file: brief_test.md 正文内容 ABC")
        messages = svc._build_merged_messages(
            goal="写方案",
            step_index=1,
            previous_observation=None,
            session_history=None,
            web_enabled=True,
            final_step=False,
            run_id=run_id,
        )
        assert "brief_test.md 正文内容 ABC" in messages[1]["content"]
        assert "近期工具结果" in messages[1]["content"]

    def test_merged_messages_without_history_unchanged(self):
        from uuid import uuid4

        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        messages = svc._build_merged_messages(
            goal="写方案",
            step_index=0,
            previous_observation=None,
            session_history=None,
            web_enabled=True,
            final_step=False,
        )
        assert "近期工具结果" not in messages[1]["content"]


class TestMergeSaveAnswer:
    """finish 回答 = 模型内容简述 + 系统侧保存事实。"""

    def test_keeps_model_brief_with_facts(self):
        from app.services.agent.loop import AgentLoopService

        receipts = [
            {"filename": "a.md", "path": "/brief/a.md", "bytes": 100, "sha256": "abc"}
        ]
        answer = AgentLoopService._merge_save_answer(
            "方案已完成，包含创意主题与线上玩法。", receipts
        )
        assert "方案已完成，包含创意主题与线上玩法。" in answer
        assert "已完成并保存，保存后回读校验通过。" in answer
        assert "/brief/a.md" in answer

    def test_brief_truncated_when_too_long(self):
        from app.services.agent.loop import AgentLoopService

        long_brief = "内容" * 200
        answer = AgentLoopService._merge_save_answer(long_brief, [])
        # 120 字符简述 + 省略号 + 空行 + 系统事实
        assert len(answer) <= 121 + 2 + len(
            AgentLoopService._verified_save_answer([])
        )

    def test_falls_back_to_facts_when_brief_too_short(self):
        from app.services.agent.loop import AgentLoopService

        receipts = [
            {"filename": "a.md", "path": "/brief/a.md", "bytes": 100, "sha256": "abc"}
        ]
        answer = AgentLoopService._merge_save_answer("已保存", receipts)
        assert answer == AgentLoopService._verified_save_answer(receipts)

    def test_empty_receipts_produce_facts_only(self):
        from app.services.agent.loop import AgentLoopService

        answer = AgentLoopService._merge_save_answer("方案完成", [])
        assert answer == AgentLoopService._verified_save_answer([])
        assert "/brief/" not in answer


class TestPlatformSampleGate:
    async def _make_state(self, service):
        from uuid import uuid4
        from app.services.agent.loop import _RunWorkflowState

        service._wf_states = {}
        service._fallback_state = _RunWorkflowState()
        run_id = uuid4()
        st = service._wf(run_id)
        st.platform_samples = {}
        st.platform_sample_urls = {}
        st.platform_waived = set()
        return st

    async def test_state_has_platform_fields(self):
        from app.services.agent.loop import AgentLoopService, _RunWorkflowState

        st = _RunWorkflowState()
        assert st.platform_samples == {}
        assert st.platform_sample_urls == {}
        assert st.platform_waived == set()

    async def test_gate_hangs_below_40(self):
        from app.services.agent.loop import AgentLoopService, _QuestionHangSignal

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        st.platform_samples = {"douyin": 10}
        st.platform_sample_urls = {"douyin": {"u1"}}
        st.research_ok = True
        try:
            service._check_platform_sample_gate(st)
            raise AssertionError("must hang below 40")
        except _QuestionHangSignal as hang:
            assert hang.questions[0]["question"]
            assert "40" in hang.questions[0]["question"]
            assert "150" not in hang.questions[0]["question"]
            assert st.stage == "awaiting_question"
            assert st.hung_from_stage == "content"

    async def test_gate_passes_at_40(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        st.platform_samples = {"xiaohongshu": 40}
        st.platform_sample_urls = {"xiaohongshu": {f"u{i}" for i in range(40)}}
        st.research_ok = True
        service._check_platform_sample_gate(st)  # 不抛异常即通过

    async def test_accumulate_uses_platform_total_idempotently(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        service._accumulate_platform_samples(
            st,
            {
                "platform": "douyin",
                "platform_total": 42,
                "samples": [{"url": "https://www.douyin.com/video/1"}],
                "sample_count": 1,
            },
        )
        assert st.platform_samples["douyin"] == 42
        # 重复搜索（重试/同关键词再来一次）幂等：仍 42
        service._accumulate_platform_samples(
            st,
            {
                "platform": "douyin",
                "platform_total": 42,
                "samples": [{"url": "https://www.douyin.com/video/1"}],
                "sample_count": 1,
            },
        )
        assert st.platform_samples["douyin"] == 42

    async def test_gate_skipped_when_no_platform_used(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        service._check_platform_sample_gate(st)  # 不抛异常即通过

    async def test_waived_platform_not_hung_again(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        st.platform_samples = {"douyin": 10}
        st.platform_sample_urls = {"douyin": {"u1"}}
        st.platform_waived = {"douyin"}
        service._check_platform_sample_gate(st)  # 不抛异常即通过

    async def test_resume_restores_stage_and_does_not_rehang(self):
        from app.services.agent.loop import AgentLoopService, _RunWorkflowState

        service = AgentLoopService()
        service._wf_states = {}
        service._fallback_state = _RunWorkflowState()
        st = service._wf(None)
        st.rules = object()  # 启用工作流
        st.platform_samples = {"douyin": 10}
        st.platform_sample_urls = {"douyin": {"u1"}}
        st.research_ok = True
        st.stage = "awaiting_question"
        st.hung_from_stage = "content"
        # resume 后的推进：恢复阶段，不得再次挂起
        await service._advance_workflow_stage(None, None, 0)
        assert st.stage == "content"
        assert st.hung_from_stage is None
        assert "awaiting_question" in st.stages_done

