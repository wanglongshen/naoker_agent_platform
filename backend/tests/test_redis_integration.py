import asyncio
from unittest.mock import AsyncMock
from datetime import datetime, UTC
from uuid import uuid4

import pytest
from app.services.agent.redis_bridge import RedisBridge
from app.services.agent.event_bus import EventBus, EventItem
from app.services.agent.loop import AgentLoopService, _AttemptContext, set_redis_bridge, agent_loop_service


class TestRedisHotPath:
    @pytest.mark.anyio
    async def test_persist_and_notify_publishes_to_redis_first(self, monkeypatch):
        fake_run_id = uuid4()
        fake_attempt_id = uuid4()
        run = type("FakeRun", (), {"__dict__": {"id": fake_run_id}})()
        attempt = type("FakeAttempt", (), {"__dict__": {"id": fake_attempt_id}})()
        ctx = _AttemptContext(run=run, attempt=attempt)

        fake_event = type("FakeEvent", (), {
            "seq": 42,
            "created_at": datetime.now(UTC),
            "id": fake_run_id,
            "__dict__": {"seq": 42},
        })()

        repo = type("FakeRepo", (), {
            "append_event": AsyncMock(return_value=fake_event),
            "session": type("FakeSession", (), {"commit": AsyncMock()})(),
        })()

        mock_redis = AsyncMock()
        mock_bus = AsyncMock()
        monkeypatch.setattr("app.services.agent.loop.redis_bridge", mock_redis)
        monkeypatch.setattr("app.services.agent.loop.event_bus", mock_bus)

        service = AgentLoopService()
        service.redis_bridge = mock_redis
        await service._persist_and_notify(repo, ctx, "answer_delta", {"delta": "test"})

        mock_redis.publish.assert_called_once()
        repo.session.commit.assert_awaited_once()
        mock_bus.publish.assert_called_once()

    @pytest.mark.anyio
    async def test_persist_and_notify_graceful_on_redis_failure(self, monkeypatch):
        fake_run_id = uuid4()
        fake_attempt_id = uuid4()
        run = type("FakeRun", (), {"__dict__": {"id": fake_run_id}})()
        attempt = type("FakeAttempt", (), {"__dict__": {"id": fake_attempt_id}})()
        ctx = _AttemptContext(run=run, attempt=attempt)

        fake_event = type("FakeEvent", (), {
            "seq": 42,
            "created_at": datetime.now(UTC),
            "id": fake_run_id,
            "__dict__": {"seq": 42},
        })()

        repo = type("FakeRepo", (), {
            "append_event": AsyncMock(return_value=fake_event),
            "session": type("FakeSession", (), {"commit": AsyncMock()})(),
        })()

        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = Exception("Redis down")
        mock_bus = AsyncMock()
        monkeypatch.setattr("app.services.agent.loop.redis_bridge", mock_redis)
        monkeypatch.setattr("app.services.agent.loop.event_bus", mock_bus)

        service = AgentLoopService()
        service.redis_bridge = mock_redis
        await service._persist_and_notify(repo, ctx, "answer_delta", {"delta": "test"})

        repo.session.commit.assert_awaited_once()
        mock_bus.publish.assert_called_once()
