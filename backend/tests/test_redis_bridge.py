import asyncio
from datetime import datetime, UTC
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.services.agent.event_bus import EventBus, EventItem
from app.services.agent.redis_bridge import RedisBridge


class TestRedisBridgeSerialize:
    def test_serialize_event_item_to_dict(self):
        run_id = uuid4()
        now = datetime.now(UTC)
        item = EventItem(
            run_id=run_id, seq=42, event_type="answer_delta",
            payload={"delta": "test", "offset": 0},
            created_at=now, id=uuid4(), attempt_id=uuid4(),
        )
        d = RedisBridge._event_item_to_dict(item)
        assert d["run_id"] == str(run_id)
        assert d["seq"] == 42
        assert d["event_type"] == "answer_delta"
        assert d["payload"]["delta"] == "test"

    def test_deserialize_dict_to_event_item(self):
        run_id = uuid4()
        now = datetime.now(UTC)
        d = {
            "run_id": str(run_id), "seq": 42, "event_type": "answer_delta",
            "payload": {"delta": "test", "offset": 0},
            "created_at": now.isoformat(), "id": str(uuid4()),
            "attempt_id": str(uuid4()),
        }
        item = RedisBridge._dict_to_event_item(d)
        assert item.run_id == run_id
        assert item.seq == 42
        assert item.event_type == "answer_delta"
        assert item.payload["delta"] == "test"

    def test_serialize_round_trip(self):
        run_id = uuid4()
        now = datetime.now(UTC)
        item = EventItem(
            run_id=run_id, seq=42, event_type="answer_delta",
            payload={"delta": "test", "offset": 0},
            created_at=now, id=uuid4(), attempt_id=uuid4(),
        )
        d = RedisBridge._event_item_to_dict(item)
        restored = RedisBridge._dict_to_event_item(d)
        assert restored.run_id == item.run_id
        assert restored.seq == item.seq
        assert restored.event_type == item.event_type
        assert restored.payload == item.payload
        assert restored.created_at == item.created_at


class TestRedisBridgeBatch:
    def test_flush_on_max_size(self):
        bridge = RedisBridge("redis://localhost:6379/0", EventBus(), batch_window_ms=99999, batch_max_size=3)
        import time
        bridge._batch_last_flush = time.monotonic()
        run_id = uuid4()
        now = datetime.now(UTC)

        for i in range(3):
            item = EventItem(
                run_id=run_id, seq=i, event_type="answer_delta",
                payload={"delta": str(i), "offset": i},
                created_at=now, id=uuid4(), attempt_id=uuid4(),
            )
            bridge._batch_buffer.append(item)

        flush_idx = bridge._should_flush()
        assert flush_idx is not None
        assert flush_idx == 3

    def test_no_flush_under_max_size(self):
        bridge = RedisBridge("redis://localhost:6379/0", EventBus(), batch_window_ms=99999, batch_max_size=10)
        import time
        bridge._batch_last_flush = time.monotonic()
        run_id = uuid4()
        now = datetime.now(UTC)
        for i in range(3):
            item = EventItem(
                run_id=run_id, seq=i, event_type="answer_delta",
                payload={"delta": str(i), "offset": i},
                created_at=now, id=uuid4(), attempt_id=uuid4(),
            )
            bridge._batch_buffer.append(item)
        assert bridge._should_flush() is None


class TestRedisBridgeGracefulDegradation:
    @pytest.mark.anyio
    async def test_publish_noop_when_not_connected(self):
        bridge = RedisBridge("redis://localhost:6379/0", EventBus())
        run_id = uuid4()
        now = datetime.now(UTC)
        item = EventItem(
            run_id=run_id, seq=42, event_type="answer_delta",
            payload={"delta": "test", "offset": 0},
            created_at=now, id=uuid4(), attempt_id=uuid4(),
        )
        await bridge.publish(f"run:{run_id}", item)

    @pytest.mark.anyio
    async def test_disconnect_noop_when_not_connected(self):
        bridge = RedisBridge("redis://localhost:6379/0", EventBus())
        await bridge.disconnect()


class FakeBridge:
    def __init__(self, **kwargs):
        self.connected = False
        self.subscribed = False
        self.disconnected = False

    async def connect(self):
        self.connected = True

    async def subscribe(self, pattern):
        self.subscribed = True

    async def disconnect(self):
        self.disconnected = True


class TestInitShutdownBridge:
    async def test_init_redis_bridge_disabled_returns_none(self, monkeypatch):
        import app.services.agent.loop as loop_module

        monkeypatch.setattr(loop_module.settings, "agent_redis_pubsub_enabled", False)
        assert await loop_module.init_redis_bridge() is None

    async def test_init_redis_bridge_connects_and_sets_global(self, monkeypatch):
        import app.services.agent.loop as loop_module

        monkeypatch.setattr(loop_module.settings, "agent_redis_pubsub_enabled", True)
        monkeypatch.setattr(loop_module, "RedisBridge", FakeBridge)
        bridge = None
        try:
            bridge = await loop_module.init_redis_bridge()
            assert bridge is not None
            assert bridge.connected is True
            assert bridge.subscribed is True
            assert loop_module.redis_bridge is bridge
            assert loop_module.agent_loop_service.redis_bridge is bridge
        finally:
            await loop_module.shutdown_redis_bridge()
            assert bridge is not None
            assert bridge.disconnected is True
            assert loop_module.redis_bridge is None

    async def test_init_redis_bridge_worker_mode_skips_subscribe(self, monkeypatch):
        import app.services.agent.loop as loop_module

        monkeypatch.setattr(loop_module.settings, "agent_redis_pubsub_enabled", True)
        monkeypatch.setattr(loop_module, "RedisBridge", FakeBridge)
        bridge = None
        try:
            bridge = await loop_module.init_redis_bridge(subscribe=False)
            assert bridge is not None
            assert bridge.subscribed is False
        finally:
            await loop_module.shutdown_redis_bridge()
            assert bridge is not None
            assert bridge.disconnected is True
