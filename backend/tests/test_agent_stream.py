import uuid
from datetime import datetime, timezone

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.agent import AgentRun, AgentRunEvent, AgentSession
from app.models.base import Base
from app.models.rbac import User

settings = get_settings()

TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture
async def stream_db(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as s:
        await seed_rbac(s)
        await s.commit()

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    import app.api.agent_stream as asm
    original_factory = asm.async_session_factory
    asm.async_session_factory = session_factory

    app.dependency_overrides[get_db] = override_get_db

    yield session_factory

    asm.async_session_factory = original_factory
    app.dependency_overrides.clear()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def ordinary_user(stream_db):
    async with stream_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"ordinary_{uuid.uuid4().hex[:8]}",
            display_name="Ordinary User",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


async def create_running_run(stream_db, ordinary_user) -> uuid.UUID:
    async with stream_db() as session:
        session_obj = AgentSession(owner_user_id=ordinary_user.id, title="stream")
        session.add(session_obj)
        await session.flush()
        run = AgentRun(
            session_id=session_obj.id,
            owner_user_id=ordinary_user.id,
            goal="stream goal",
            mode="quick",
            status="running",
        )
        session.add(run)
        await session.commit()
        return run.id


async def persist_answer_delta(stream_db, run_id: uuid.UUID, *, delta: str) -> int:
    async with stream_db() as session:
        event = AgentRunEvent(
            run_id=run_id,
            event_type="answer_delta",
            payload={"delta": delta},
        )
        session.add(event)
        await session.flush()
        from sqlalchemy import select as sa_select

        seq = await session.scalar(
            sa_select(AgentRunEvent.seq).where(AgentRunEvent.id == event.id)
        )
        await session.commit()
        assert seq is not None
        return seq


@pytest.fixture
async def ordinary_client(stream_db, ordinary_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={"username": ordinary_user.username, "password": "Password123"},
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def admin_client(stream_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={
                "username": settings.initial_admin_username,
                "password": settings.initial_admin_password,
            },
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def terminal_run_with_events(stream_db, ordinary_user):
    async with stream_db() as s:
        session_obj = AgentSession(
            owner_user_id=ordinary_user.id, title="Test Session"
        )
        s.add(session_obj)
        await s.flush()

        run = AgentRun(
            session_id=session_obj.id,
            owner_user_id=ordinary_user.id,
            goal="Test goal",
            mode="quick",
            status="succeeded",
        )
        s.add(run)
        await s.flush()

        for i, event_type in enumerate(
            ["run_queued", "run_started", "thought_start", "thought_end", "run_succeeded"],
            start=1,
        ):
            event = AgentRunEvent(
                run_id=run.id,
                event_type=event_type,
                payload={"step": i, "data": f"event_{i}"},
            )
            s.add(event)
            await s.flush()

        await s.commit()
        return run


class TestAgentStream:

    async def test_failure_event_is_replayable(self, ordinary_client, stream_db, ordinary_user):
        async with stream_db() as s:
            session_obj = AgentSession(owner_user_id=ordinary_user.id, title="failed")
            s.add(session_obj)
            await s.flush()
            run = AgentRun(
                session_id=session_obj.id,
                owner_user_id=ordinary_user.id,
                goal="failed goal",
                mode="quick",
                status="failed",
            )
            s.add(run)
            await s.flush()
            s.add(
                AgentRunEvent(
                    run_id=run.id,
                    event_type="run_failed",
                    payload={"error": "worker_unhandled_error"},
                )
            )
            await s.commit()
            run_id = run.id

        response = await ordinary_client.get(
            f"/api/agent/runs/{run_id}/events?after_seq=0",
            headers={"Origin": TEST_ORIGIN},
        )

        assert response.status_code == 200
        events = response.json()["data"]["items"]
        assert events[-1]["event_type"] == "run_failed"
        assert events[-1]["payload"] == {"error": "worker_unhandled_error"}

    async def test_sse_replays_only_owned_events_after_last_event_id(
        self, ordinary_client, terminal_run_with_events, stream_db
    ):
        async with stream_db() as s:
            from sqlalchemy import select as sa_select
            from app.models.agent import AgentRunEvent
            result = await s.execute(
                sa_select(AgentRunEvent.seq)
                .where(AgentRunEvent.run_id == terminal_run_with_events.id)
                .order_by(AgentRunEvent.seq.asc())
            )
            seqs = [row[0] for row in result.all()]

        first_seq = seqs[0]
        second_seq = seqs[1]
        last_seq = seqs[-1]

        response = await ordinary_client.get(
            f"/api/agent/runs/{terminal_run_with_events.id}/stream",
            headers={"Last-Event-ID": str(first_seq), "Origin": TEST_ORIGIN},
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert f"id: {first_seq}" not in content
        assert f"id: {second_seq}" in content
        assert f"id: {last_seq}" in content

    async def test_sse_replays_every_event_beyond_catch_up_limit(
        self, ordinary_client, ordinary_user, stream_db
    ):
        import app.api.agent_stream as asm
        from sqlalchemy import select as sa_select

        async with stream_db() as s:
            session_obj = AgentSession(owner_user_id=ordinary_user.id, title="large replay")
            s.add(session_obj)
            await s.flush()
            run = AgentRun(
                session_id=session_obj.id,
                owner_user_id=ordinary_user.id,
                goal="large replay goal",
                mode="quick",
                status="succeeded",
            )
            s.add(run)
            await s.flush()

            total_events = asm.CATCH_UP_LIMIT * 2
            for i in range(total_events):
                s.add(
                    AgentRunEvent(
                        run_id=run.id,
                        event_type="answer_delta",
                        payload={"delta": str(i)},
                    )
                )
            await s.flush()
            result = await s.execute(
                sa_select(AgentRunEvent.seq)
                .where(AgentRunEvent.run_id == run.id)
                .order_by(AgentRunEvent.seq.asc())
            )
            expected_seqs = list(result.scalars())
            await s.commit()

        response = await ordinary_client.get(
            f"/api/agent/runs/{run.id}/stream?after_seq={expected_seqs[0] - 1}",
            headers={"Origin": TEST_ORIGIN},
        )

        assert response.status_code == 200
        emitted_seqs = [
            int(line[4:])
            for line in response.text.split("\n")
            if line.startswith("id: ")
        ]
        assert emitted_seqs == expected_seqs
        assert emitted_seqs[-1] == expected_seqs[-1]

    async def test_terminal_catch_up_loops_beyond_single_page(
        self, ordinary_client, ordinary_user, stream_db, monkeypatch
    ):
        import app.api.agent_stream as asm
        from sqlalchemy import select as sa_select

        async with stream_db() as s:
            session_obj = AgentSession(
                owner_user_id=ordinary_user.id, title="paged terminal"
            )
            s.add(session_obj)
            await s.flush()
            run = AgentRun(
                session_id=session_obj.id,
                owner_user_id=ordinary_user.id,
                goal="paged terminal goal",
                mode="quick",
                status="succeeded",
            )
            s.add(run)
            await s.flush()
            for i in range(5):
                s.add(
                    AgentRunEvent(
                        run_id=run.id,
                        event_type="answer_delta",
                        payload={"delta": str(i)},
                    )
                )
            await s.flush()
            result = await s.execute(
                sa_select(AgentRunEvent.seq)
                .where(AgentRunEvent.run_id == run.id)
                .order_by(AgentRunEvent.seq.asc())
            )
            expected_seqs = list(result.scalars())
            await s.commit()

        real_events_after = asm._events_after

        async def small_pages(run_id, after_seq, limit=2):
            return await real_events_after(run_id, after_seq, limit=limit)

        monkeypatch.setattr(asm, "_events_after", small_pages)

        response = await ordinary_client.get(
            f"/api/agent/runs/{run.id}/stream?after_seq={expected_seqs[0] - 1}",
            headers={"Origin": TEST_ORIGIN},
        )

        assert response.status_code == 200
        emitted_seqs = [
            int(line[4:])
            for line in response.text.split("\n")
            if line.startswith("id: ")
        ]
        assert emitted_seqs == expected_seqs

    async def test_foreign_sse_is_404_before_stream_body(
        self, admin_client, terminal_run_with_events
    ):
        response = await admin_client.get(
            f"/api/agent/runs/{terminal_run_with_events.id}/stream",
            headers={"Origin": TEST_ORIGIN},
        )
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body["code"] == "RESOURCE_NOT_FOUND"

    async def test_sse_rejects_attacker_suffix_origin_for_owned_run(
        self, ordinary_client, terminal_run_with_events
    ):
        response = await ordinary_client.get(
            f"/api/agent/runs/{terminal_run_with_events.id}/stream",
            headers={"Origin": "http://localhost:3000.evil"},
        )

        assert response.status_code == 403
        assert response.json()["code"] == "CSRF_VALIDATION_FAILED"

    async def test_event_ordering_is_correct_by_seq(
        self, ordinary_client, terminal_run_with_events
    ):
        response = await ordinary_client.get(
            f"/api/agent/runs/{terminal_run_with_events.id}/stream",
            headers={"Origin": TEST_ORIGIN},
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")

        seqs = []
        for line in content.split("\n"):
            if line.startswith("id: "):
                seqs.append(int(line[4:]))

        assert seqs == sorted(seqs)
        assert len(seqs) >= 3

    async def test_final_catch_up_on_terminal_status(
        self, ordinary_client, terminal_run_with_events
    ):
        response = await ordinary_client.get(
            f"/api/agent/runs/{terminal_run_with_events.id}/stream",
            headers={"Origin": TEST_ORIGIN},
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "event: run_succeeded" in content

    async def test_sse_replays_all_events_when_no_cursor(
        self, ordinary_client, terminal_run_with_events
    ):
        response = await ordinary_client.get(
            f"/api/agent/runs/{terminal_run_with_events.id}/stream",
            headers={"Origin": TEST_ORIGIN},
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "id: 1" in content
        assert "id: 2" in content

    async def test_invalid_cursor_returns_400_before_stream(
        self, ordinary_client, terminal_run_with_events
    ):
        response = await ordinary_client.get(
            f"/api/agent/runs/{terminal_run_with_events.id}/stream?after_seq=abc",
            headers={"Origin": TEST_ORIGIN},
        )
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body["code"] == "INVALID_CURSOR"

    async def test_sse_unauthenticated_returns_401(
        self, stream_db, terminal_run_with_events
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
            headers={"Origin": TEST_ORIGIN},
        ) as ac:
            response = await ac.get(
                f"/api/agent/runs/{terminal_run_with_events.id}/stream",
            )
            assert response.status_code == 401
            assert response.headers["content-type"].startswith("application/json")

    async def test_sse_content_type_and_headers(
        self, ordinary_client, terminal_run_with_events
    ):
        response = await ordinary_client.get(
            f"/api/agent/runs/{terminal_run_with_events.id}/stream",
            headers={"Origin": TEST_ORIGIN},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"

    async def test_sse_streams_all_events_for_running_run(
        self, ordinary_client, stream_db, ordinary_user
    ):
        async with stream_db() as s:
            session_obj = AgentSession(owner_user_id=ordinary_user.id, title="streaming")
            s.add(session_obj)
            await s.flush()
            run = AgentRun(
                session_id=session_obj.id,
                owner_user_id=ordinary_user.id,
                goal="streaming goal",
                mode="quick",
                status="succeeded",
            )
            s.add(run)
            await s.flush()
            run_id = run.id

            for event_type in ["run_queued", "run_started", "answer_delta", "run_succeeded"]:
                s.add(AgentRunEvent(
                    run_id=run_id,
                    event_type=event_type,
                    payload={"test": True},
                ))
            await s.commit()

        response = await ordinary_client.get(
            f"/api/agent/runs/{run_id}/stream",
            headers={"Origin": TEST_ORIGIN},
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "event: answer_delta" in content
        assert "event: run_succeeded" in content

    async def test_event_bus_broadcasts_same_event_to_all_subscribers(self):
        from app.services.agent.event_bus import EventBus, EventItem

        bus = EventBus(max_queue_size=4)
        run_id = uuid.uuid4()
        subscriber_a, queue_a = await bus.subscribe(run_id)
        subscriber_b, queue_b = await bus.subscribe(run_id)

        event = EventItem(run_id=run_id, seq=1, event_type="test", payload={}, created_at=datetime.now(timezone.utc))
        await bus.publish(event)

        assert (await queue_a.get()).seq == 1
        assert (await queue_b.get()).seq == 1

        await bus.unsubscribe(run_id, subscriber_a)
        await bus.unsubscribe(run_id, subscriber_b)

    async def test_sse_event_includes_type_and_timestamp_aliases(
        self, ordinary_client, terminal_run_with_events, stream_db
    ):
        import json

        async with stream_db() as s:
            from sqlalchemy import select as sa_select
            from app.models.agent import AgentRunEvent
            result = await s.execute(
                sa_select(AgentRunEvent.seq)
                .where(AgentRunEvent.run_id == terminal_run_with_events.id)
                .order_by(AgentRunEvent.seq.asc())
            )
            seqs = [row[0] for row in result.all()]

        first_seq = seqs[0]

        response = await ordinary_client.get(
            f"/api/agent/runs/{terminal_run_with_events.id}/stream",
            headers={"Origin": TEST_ORIGIN},
        )
        assert response.status_code == 200

        content = response.content.decode("utf-8")
        data_blocks = []
        for line in content.split("\n"):
            if line.startswith("data: "):
                data_blocks.append(json.loads(line[6:]))

        first_event = data_blocks[0]
        assert first_event["seq"] == first_seq
        assert first_event["event_type"] == "run_queued"
        assert "created_at" in first_event
        assert first_event["id"] is not None
