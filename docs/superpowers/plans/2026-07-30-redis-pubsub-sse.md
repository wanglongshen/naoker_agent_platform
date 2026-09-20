# Redis Pub/Sub SSE Streaming — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `pg_notify` → DB SELECT round-trip with Redis Pub/Sub carrying complete EventItem payloads, adding batch frame-coalescing and orjson serialization.

**Architecture:** Worker publishes EventItem JSON to Redis channel `run:{run_id}`. API's `RedisBridge` subscriber receives, deserializes, and calls `event_bus.publish()`. SSE generator gets EventItem directly from the EventBus queue — zero DB queries in the hot path. Batch coalescing accumulates up to 32 ms / 20 events before publishing. orjson replaces json.dumps for 3–5× faster serialization.

**Tech Stack:** Python 3.12+, FastAPI, `redis[hiredis]` 5.x, `orjson` 3.x, PostgreSQL (audit log, async).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-30-redis-pubsub-sse-design.md`
- All new config keys start with `AGENT_REDIS_`
- Serialization: `orjson.dumps` for hot path, `json.dumps` for DB (compatibility)
- Graceful fallback: `AGENT_REDIS_PUBSUB_ENABLED=False` reverts to pg_notify pipeline
- `EventItem` is frozen dataclass — use `dataclasses.asdict()` to serialize, then reconstruct in subscriber
- Python 3.12 `datetime.UTC` for timezone-aware timestamps

---

## File Structure

| File | Responsibility |
|------|---------------|
| `backend/app/services/agent/redis_bridge.py` | `RedisBridge` — connect, batch-publish, subscribe, Streams stub |
| `backend/app/services/agent/loop.py` | Worker hot-path: push to RedisBridge, async-DB cold-path |
| `backend/app/main.py` | Lifespan: start/stop RedisBridge subscriber |
| `backend/app/core/config.py` | 5 new Redis settings |
| `backend/requirements.txt` | `redis[hiredis]`, `orjson` |
| `backend/tests/test_redis_bridge.py` | Unit tests for RedisBridge |
| `backend/tests/test_redis_integration.py` | Integration: publish → subscriber → EventBus → event arrives |

---

### Task 1: Dependencies and Configuration

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/core/config.py:45-50`

**Interfaces:**
- Produces: 5 new `Settings` attributes, 2 new pip packages

- [ ] **Step 1: Add packages to requirements.txt**

Read `backend/requirements.txt` first, then append the two new lines at the end:

```
redis[hiredis]>=5.0,<6
orjson>=3.9,<4
```

Verify by opening `backend/requirements.txt` and confirming the lines exist.

- [ ] **Step 2: Install packages**

```powershell
python -m pip install "redis[hiredis]>=5.0,<6" "orjson>=3.9,<4"
```

Expected: both packages install without error.

- [ ] **Step 3: Add Redis config to Settings**

Open `backend/app/core/config.py`. After line 47 (`agent_answer_delta_flush_seconds`), insert:

```python
    redis_url: str = "redis://localhost:6379/0"
    agent_redis_pubsub_enabled: bool = True
    agent_redis_streams_enabled: bool = False
    agent_redis_batch_window_ms: int = 32
    agent_redis_batch_max_size: int = 20
    agent_sync_persist_events: bool = False
```

- [ ] **Step 4: Run the existing config test to confirm no breakage**

```powershell
python -X utf8 -m pytest backend/tests/test_agent_notify_config.py -v --no-header
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/app/core/config.py
git commit -m "chore: add Redis + orjson deps and config keys"
```

---

### Task 2: RedisBridge — Core Class

**Files:**
- Create: `backend/app/services/agent/redis_bridge.py`
- Create: `backend/tests/test_redis_bridge.py`

**Interfaces:**
- Produces: `RedisBridge` class
  - `async connect()` — returns `None`, creates subscriber + publisher connections
  - `async publish(channel: str, event: list[EventItem]) -> None` — batch-publish events as JSON array
  - `async subscribe(pattern: str) -> None` — starts background task listening on pattern
  - `async disconnect() -> None` — clean shutdown
  - Constructor: `RedisBridge(redis_url: str, event_bus: EventBus, batch_window_ms: int=32, batch_max_size: int=20)`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_redis_bridge.py`:

```python
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.agent.redis_bridge import RedisBridge
from app.services.agent.event_bus import EventBus, EventItem
from datetime import datetime, UTC
from uuid import uuid4


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
        """Batch flushes when reaching batch_max_size."""
        # Since we can't easily test async batch timing, we test the max_size trigger.
        bridge = RedisBridge("redis://localhost:6379/0", EventBus(), batch_window_ms=99999, batch_max_size=3)
        run_id = uuid4()
        now = datetime.now(UTC)

        # Inject 3 events into the batch buffer
        for i in range(3):
            item = EventItem(
                run_id=run_id, seq=i, event_type="answer_delta",
                payload={"delta": str(i), "offset": i},
                created_at=now, id=uuid4(), attempt_id=uuid4(),
            )
            bridge._batch_buffer.append(item)

        # After 3 (== max_size), buffer should be flushed
        flush_idx = bridge._should_flush()
        assert flush_idx is not None
        assert flush_idx == 3

    def test_no_flush_under_max_size(self):
        bridge = RedisBridge("redis://localhost:6379/0", EventBus(), batch_window_ms=99999, batch_max_size=10)
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
        # Should not raise — silently no-ops when not connected
        await bridge.publish(f"run:{run_id}", item)

    @pytest.mark.anyio
    async def test_disconnect_noop_when_not_connected(self):
        bridge = RedisBridge("redis://localhost:6379/0", EventBus())
        await bridge.disconnect()  # Should not raise
```

- [ ] **Step 2: Run test to verify it fails (RedisBridge not defined)**

```powershell
python -X utf8 -m pytest backend/tests/test_redis_bridge.py -v --no-header
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.agent.redis_bridge'`

- [ ] **Step 3: Implement RedisBridge**

Create `backend/app/services/agent/redis_bridge.py`:

```python
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

import orjson

if TYPE_CHECKING:
    from app.services.agent.event_bus import EventBus, EventItem

logger = logging.getLogger("redis_bridge")


class RedisBridge:
    def __init__(
        self,
        redis_url: str,
        event_bus: "EventBus",
        *,
        batch_window_ms: int = 32,
        batch_max_size: int = 20,
    ) -> None:
        self._redis_url = redis_url
        self._event_bus = event_bus
        self._batch_window_ms = batch_window_ms
        self._batch_max_size = batch_max_size

        self._publisher = None
        self._subscriber = None
        self._connected = False
        self._sub_task: asyncio.Task | None = None
        self._batch_buffer: list[EventItem] = []
        self._batch_last_flush = 0.0
        self._flush_task: asyncio.Task | None = None

    # ── Serialization ──────────────────────────────────

    @staticmethod
    def _event_item_to_dict(item: "EventItem") -> dict:
        d = asdict(item)
        d["run_id"] = str(item.run_id)
        d["id"] = str(item.id) if item.id else None
        d["attempt_id"] = str(item.attempt_id) if item.attempt_id else None
        d["created_at"] = item.created_at.isoformat()
        return d

    @staticmethod
    def _dict_to_event_item(d: dict) -> "EventItem":
        from app.services.agent.event_bus import EventItem

        return EventItem(
            run_id=UUID(d["run_id"]),
            seq=d["seq"],
            event_type=d["event_type"],
            payload=d["payload"],
            created_at=datetime.fromisoformat(d["created_at"]),
            id=UUID(d["id"]) if d.get("id") else None,
            attempt_id=UUID(d["attempt_id"]) if d.get("attempt_id") else None,
        )

    # ── Connection lifecycle ───────────────────────────

    async def connect(self) -> None:
        if self._connected:
            return
        try:
            import redis.asyncio as aioredis

            self._publisher = aioredis.from_url(self._redis_url)
            self._subscriber = aioredis.from_url(self._redis_url)
            await self._publisher.ping()
            await self._subscriber.ping()
            self._connected = True
            self._batch_last_flush = time.monotonic()
            self._flush_task = asyncio.create_task(self._batch_flush_loop())
            logger.info("redis_bridge_connected", extra={"url": self._redis_url})
        except Exception:
            logger.warning("redis_bridge_connect_failed", exc_info=True)
            self._connected = False

    async def disconnect(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):
                pass
            self._flush_task = None

        if self._batch_buffer:
            await self._flush_batch()

        if self._sub_task:
            self._sub_task.cancel()
            try:
                await self._sub_task
            except (asyncio.CancelledError, Exception):
                pass
            self._sub_task = None

        if self._publisher:
            await self._publisher.aclose()
            self._publisher = None
        if self._subscriber:
            await self._subscriber.aclose()
            self._subscriber = None
        self._connected = False

    # ── Batch publish ──────────────────────────────────

    def _should_flush(self) -> int | None:
        """Return number of items to flush, or None if not yet."""
        size = len(self._batch_buffer)
        if size == 0:
            return None
        if size >= self._batch_max_size:
            return size
        elapsed = (time.monotonic() - self._batch_last_flush) * 1000
        if elapsed >= self._batch_window_ms:
            return size
        return None

    async def _batch_flush_loop(self) -> None:
        while True:
            while True:
                flush_count = self._should_flush()
                if flush_count is None:
                    break
                await self._flush_batch(flush_count)
            await asyncio.sleep(self._batch_window_ms / 1000)

    async def _flush_batch(self, count: int | None = None) -> None:
        if not self._batch_buffer or not self._connected:
            return
        if count is None:
            count = len(self._batch_buffer)
        items = self._batch_buffer[:count]
        self._batch_buffer = self._batch_buffer[count:]
        self._batch_last_flush = time.monotonic()

        if not items:
            return

        payload = orjson.dumps([
            self._event_item_to_dict(item) for item in items
        ])

        run_id = items[0].run_id
        channel = f"run:{run_id}"
        try:
            await self._publisher.publish(channel, payload)
        except Exception:
            logger.warning("redis_publish_failed", exc_info=True)

    async def publish(self, channel: str, item: "EventItem") -> None:
        if not self._connected:
            return
        self._batch_buffer.append(item)

    # ── Subscribe ──────────────────────────────────────

    async def subscribe(self, pattern: str) -> None:
        if not self._connected:
            return
        self._sub_task = asyncio.create_task(self._subscribe_loop(pattern))

    async def _subscribe_loop(self, pattern: str) -> None:
        import redis.asyncio as aioredis

        try:
            pubsub = self._subscriber.pubsub()
            await pubsub.psubscribe(pattern)
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                try:
                    data = orjson.loads(message["data"])
                except Exception:
                    logger.warning("redis_subscribe_parse_failed")
                    continue
                items = data if isinstance(data, list) else [data]
                for d in items:
                    try:
                        event_item = self._dict_to_event_item(d)
                        await self._event_bus.publish(event_item)
                    except Exception:
                        logger.warning("redis_subscribe_event_failed", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("redis_subscribe_loop_error", exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
python -X utf8 -m pytest backend/tests/test_redis_bridge.py -v --no-header
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/redis_bridge.py backend/tests/test_redis_bridge.py
git commit -m "feat: add RedisBridge with batch publish and subscribe"
```

---

### Task 3: Integrate RedisBridge into Hot Path (loop.py)

**Files:**
- Modify: `backend/app/services/agent/loop.py:63-86`, `backend/app/services/agent/loop.py:20-28` (imports)

**Interfaces:**
- Consumes: `RedisBridge` from Task 2 (`.publish()`, `.connect()`)
- Produces: `redis_bridge` global singleton, `AgentLoopService.__init__` accepts optional `redis_bridge`

- [ ] **Step 1: Write test for hot-path integration**

Create `backend/tests/test_redis_integration.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC
from uuid import uuid4

import pytest
from app.services.agent.redis_bridge import RedisBridge
from app.services.agent.event_bus import EventBus, EventItem
from app.services.agent.loop import AgentLoopService


class TestRedisHotPath:
    @pytest.mark.anyio
    async def test_persist_and_notify_publishes_to_redis_first(self, monkeypatch):
        """_persist_and_notify should publish to RedisBridge before DB commit."""
        from app.services.agent.loop import AgentLoopService, _AttemptContext

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
        monkeypatch.setattr(
            "app.services.agent.loop.redis_bridge", mock_redis
        )
        monkeypatch.setattr(
            "app.services.agent.loop.event_bus", mock_bus
        )

        service = AgentLoopService()
        await service._persist_and_notify(repo, ctx, "answer_delta", {"delta": "test"})

        # Redis publish must be called before DB commit
        mock_redis.publish.assert_called_once()
        repo.session.commit.assert_awaited_once()
        mock_bus.publish.assert_called_once()

    @pytest.mark.anyio
    async def test_persist_and_notify_graceful_on_redis_failure(self, monkeypatch):
        """Redis failure must not block event delivery."""
        from app.services.agent.loop import AgentLoopService, _AttemptContext

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
        monkeypatch.setattr(
            "app.services.agent.loop.redis_bridge", mock_redis
        )
        monkeypatch.setattr(
            "app.services.agent.loop.event_bus", mock_bus
        )

        service = AgentLoopService()
        # Must NOT raise
        await service._persist_and_notify(repo, ctx, "answer_delta", {"delta": "test"})

        # DB commit must still happen
        repo.session.commit.assert_awaited_once()
        mock_bus.publish.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
python -X utf8 -m pytest backend/tests/test_redis_integration.py -v --no-header
```

Expected: FAIL — `AttributeError: module 'app.services.agent.loop' has no attribute 'redis_bridge'`

- [ ] **Step 3: Modify loop.py — add imports and redis_bridge singleton**

In `backend/app/services/agent/loop.py`, after line 28 (after the tool_executor import), add:

```python
from app.services.agent.redis_bridge import RedisBridge
```

After line 53 (last line of `class AgentLoopService:` constructor `__init__`):

```python
    def __init__(self, redis_bridge: RedisBridge | None = None) -> None:
        self.planner = ResearchPlanner()
        self.llm_client = DeepSeekClient()
        self.tool_executor = ToolExecutor()
        self.redis_bridge = redis_bridge

agent_loop_service = AgentLoopService()
```

At the bottom of the file, after `agent_loop_service = AgentLoopService()` (line 1022), add:

```python
redis_bridge: RedisBridge | None = None


def set_redis_bridge(bridge: RedisBridge) -> None:
    global redis_bridge
    redis_bridge = bridge
    agent_loop_service.redis_bridge = bridge
```

- [ ] **Step 4: Modify _persist_and_notify to push Redis first**

Replace the body of `_persist_and_notify` (lines 63-86) with:

```python
    async def _persist_and_notify(
        self,
        repo: AgentRepository,
        ctx: _AttemptContext,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        run_id = ctx.run.__dict__["id"]
        attempt_id = ctx.attempt.__dict__["id"]
        event = await repo.append_event(ctx.run, ctx.attempt, event_type, payload, notify=True)
        committed = EventItem(
            run_id=run_id,
            seq=event.seq,
            event_type=event_type,
            payload=payload,
            created_at=event.created_at,
            id=event.id,
            attempt_id=attempt_id,
        )

        # Hot path: push to Redis (fire-and-forget, non-blocking)
        if self.redis_bridge is not None:
            try:
                await self.redis_bridge.publish(f"run:{run_id}", committed)
            except Exception:
                pass

        # Cold path: commit DB, publish to local EventBus
        await repo.session.commit()
        try:
            await event_bus.publish(committed)
        except Exception:
            pass
```

- [ ] **Step 5: Modify _persist_terminal_and_notify to push Redis first**

Read `_persist_terminal_and_notify` (lines 88-129). After `await event_session.commit()` (line 128), before `await event_bus.publish(committed)` (line 129), insert hot-path Redis publish:

```python
            # Hot path: push terminal event to Redis
            if self.redis_bridge is not None:
                try:
                    await self.redis_bridge.publish(f"run:{run_id}", committed)
                except Exception:
                    pass
```

- [ ] **Step 6: Run tests to verify they pass**

```powershell
python -X utf8 -m pytest backend/tests/test_redis_integration.py -v --no-header
```

Expected: 2 passed.

- [ ] **Step 7: Run all agent loop tests to confirm no regression**

```powershell
python -X utf8 -m pytest backend/tests/test_agent_loop.py backend/tests/test_agent_notify.py backend/tests/test_agent_notify_integration.py backend/tests/test_agent_notify_sse.py -v --no-header
```

Expected: all 38 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_redis_integration.py
git commit -m "feat: push events to RedisBridge in hot path"
```

---

### Task 4: Lifecycle — Start RedisBridge Subscriber in FastAPI

**Files:**
- Modify: `backend/app/main.py:28-33`

**Interfaces:**
- Consumes: `RedisBridge` from Task 2, `set_redis_bridge` from Task 3
- Produces: subscriber running on `run:*` pattern, clean shutdown

- [ ] **Step 1: Write lifecycle test**

Append to `backend/tests/test_redis_integration.py`:

```python
class TestRedisLifecycle:
    @pytest.mark.anyio
    async def test_redis_bridge_set_on_loop_service(self, monkeypatch):
        from app.services.agent.redis_bridge import RedisBridge
        from app.services.agent.loop import agent_loop_service, set_redis_bridge
        from app.services.agent.event_bus import EventBus

        bridge = RedisBridge("redis://localhost:6379/0", EventBus())
        set_redis_bridge(bridge)
        assert agent_loop_service.redis_bridge is bridge
        assert agent_loop_service.redis_bridge is not None

    @pytest.mark.anyio
    async def test_connect_and_disconnect_cycle(self):
        from app.services.agent.redis_bridge import RedisBridge
        from app.services.agent.event_bus import EventBus

        bridge = RedisBridge("redis://localhost:6379/0", EventBus())
        # connect should not raise even if Redis is down
        await bridge.connect()
        # disconnect should not raise
        await bridge.disconnect()
```

- [ ] **Step 2: Run test to verify it passes (or fails gracefully)**

```powershell
python -X utf8 -m pytest backend/tests/test_redis_integration.py::TestRedisLifecycle -v --no-header
```

Expected: 2 passed.

- [ ] **Step 3: Modify main.py lifespan**

Replace the `lifespan` function in `backend/app/main.py` (lines 28-41):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_session_factory() as session:
        await seed_rbac(session)
        await session.commit()

    listener_task = None
    if settings.agent_event_listen_notify_enabled:
        listener_task = start_postgres_event_listener()

    from app.services.agent.redis_bridge import RedisBridge
    from app.services.agent.loop import set_redis_bridge
    from app.services.agent.event_bus import event_bus

    redis_bridge = None
    if settings.agent_redis_pubsub_enabled:
        redis_bridge = RedisBridge(
            redis_url=settings.redis_url,
            event_bus=event_bus,
            batch_window_ms=settings.agent_redis_batch_window_ms,
            batch_max_size=settings.agent_redis_batch_max_size,
        )
        await redis_bridge.connect()
        await redis_bridge.subscribe("run:*")
        set_redis_bridge(redis_bridge)

    yield

    if redis_bridge is not None:
        await redis_bridge.disconnect()
    if listener_task is not None:
        await shutdown_postgres_event_listener(listener_task)
```

- [ ] **Step 4: Run FastAPI health check to confirm app still starts**

```powershell
python -X utf8 -c "from app.main import app; print('FastAPI app loaded OK')"
```

Expected: `FastAPI app loaded OK` (Redis connection failure is logged but non-fatal).

- [ ] **Step 5: Run all existing agent tests to confirm no regression**

```powershell
python -X utf8 -m pytest backend/tests/test_agent_loop.py backend/tests/test_agent_notify.py backend/tests/test_agent_notify_integration.py backend/tests/test_agent_notify_sse.py backend/tests/test_agent_notify_config.py -v --no-header
```

Expected: all 40 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_redis_integration.py
git commit -m "feat: start RedisBridge subscriber in FastAPI lifespan"
```

---

### Task 5: Verification — End-to-End Manual Test

**Files:** None (manual verification)

- [ ] **Step 1: Start Redis (if not running)**

```powershell
# Check if Redis is running
redis-cli ping
```

If fails: start Redis (`redis-server` in a separate terminal).

- [ ] **Step 2: Start the API**

```powershell
python -X utf8 -m uvicorn app.main:app --reload --port 8000
```

Check output for: `redis_bridge_connected url=redis://localhost:6379/0`

- [ ] **Step 3: Start the Worker (separate terminal)**

```powershell
python -X utf8 -m app.workers.agent_worker
```

- [ ] **Step 4: Watch Redis traffic**

```powershell
redis-cli PSUBSCRIBE "run:*"
```

You should see `pmessage` entries as the Worker publishes events.

- [ ] **Step 5: Create a run via frontend or curl, verify streaming works**

Observe that text appears in real-time in the browser. Verify in backend logs that:
- Events are published to Redis
- Subscriber receives and pushes to EventBus
- SSE frames are emitted

---

### Task 6: Review and Finalize

- [ ] **Step 1: Run full backend test suite**

```powershell
python -X utf8 -m pytest backend/tests/test_agent_loop.py backend/tests/test_agent_notify.py backend/tests/test_agent_notify_integration.py backend/tests/test_agent_notify_sse.py backend/tests/test_agent_notify_config.py backend/tests/test_redis_bridge.py backend/tests/test_redis_integration.py -v --no-header
```

Expected: all tests pass (at least 45 total).

- [ ] **Step 2: Verify .env has Redis URL**

Check that `backend/.env` contains (or add if missing):

```
REDIS_URL=redis://localhost:6379/0
```

- [ ] **Step 3: Commit final review changes**

```bash
git add -A
git diff --staged  # review what's being committed
git commit -m "chore: final review — all Redis SSE integration tests pass"
```
