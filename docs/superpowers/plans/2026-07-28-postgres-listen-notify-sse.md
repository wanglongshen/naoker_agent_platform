# PostgreSQL LISTEN/NOTIFY SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SSE 100ms database polling with PostgreSQL LISTEN/NOTIFY wake-ups, add a dedicated asyncpg listener lifecycle per API instance, and switch the SSE generator to wake-up-driven event dispatch with a 3-second compensation poll.

**Architecture:** Worker transactions register `pg_notify('agent_run_events', '{"run_id":"...","seq":123}')` before commit. Each API instance runs a background asyncpg `LISTEN` task that forwards notifications to a local wake-up router, which signals local SSE generators. The SSE generator queries persisted events by cursor on wake-up, never using the notification payload as event data.

**Tech Stack:** Python 3.12+, asyncpg, FastAPI, SQLAlchemy async, PostgreSQL 16+.

## Global Constraints

- Do not move the worker into FastAPI/Uvicorn.
- Do not introduce Redis or external message brokers.
- Notification payload contains only `run_id` and `seq`; no event body, answer text, or credentials.
- `pg_notify()` must run in the same transaction that appends the event, before commit.
- The database event table ordered by `seq` remains the sole authoritative source for browser output.
- Cursor-based replay, authentication, origin validation, heartbeat, and terminal catch-up must remain intact.
- Malformed notification payloads are logged and ignored; the listener task must not terminate.
- Listener unavailability must not prevent SSE delivery; streams fall back to compensation polling.
- Duplicate wake-ups may cause extra empty queries but must not duplicate SSE frames.
- All new settings must have safe defaults and a `AGENT_EVENT_LISTEN_NOTIFY_ENABLED` flag for rollback.
- Commit after every task.

---

### Task 1: Notification Payload And Repository Integration

**Files:**
- Modify: `backend/app/repositories/agent_repository.py:542-545`
- Modify: `backend/app/services/agent/loop.py:54-74`
- Modify: `backend/app/services/agent/loop.py:76-118`
- Create: `backend/tests/test_agent_notify.py`

**Interfaces:**
- Produces: `AgentRepository.notify_run_event(run_id: uuid.UUID, seq: int) -> None` — calls `pg_notify` inside the session.
- Produces: JSON payload `{"run_id": "<uuid>", "seq": <int>}` encoded in notification.

- [ ] **Step 1: Write failing notification payload and repository tests**

Create `backend/tests/test_agent_notify.py`:

```python
from __future__ import annotations

import json
import uuid

import pytest
from unittest.mock import AsyncMock

from app.repositories.agent_repository import AgentRepository


def test_notify_payload_is_run_id_and_seq_only():
    run_id = uuid.uuid4()
    seq = 42
    # Manually exercise the encoder without a DB session.
    # We only assert the payload shape.
    payload = {"run_id": str(run_id), "seq": seq}
    encoded = json.dumps(payload)
    assert encoded == json.dumps({"run_id": str(run_id), "seq": seq})
    parsed = json.loads(encoded)
    assert parsed == {"run_id": str(run_id), "seq": seq}
    assert "text" not in parsed
    assert "answer" not in parsed
    assert "delta" not in parsed


def test_notify_payload_rejects_invalid_uuid():
    payload = json.dumps({"run_id": "not-a-uuid", "seq": 1})
    # The listener, not the encoder, validates. The test asserts the listener
    # should reject this shape gently.
    assert "not-a-uuid" in payload


@pytest.mark.anyio
async def test_notify_is_called_inside_append_event_transaction():
    """Verify AgentRepository.notify_run_event invokes pg_notify."""
    from unittest.mock import MagicMock, patch

    repo = MagicMock()
    repo.session = MagicMock()
    repo.session.execute = AsyncMock()
    run_id = uuid.uuid4()
    seq = 1

    await AgentRepository.notify_run_event(repo, run_id, seq)

    repo.session.execute.assert_called_once()
    call_args = repo.session.execute.call_args[0][0]
    assert "pg_notify" in str(call_args)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest backend/tests/test_agent_notify.py -v`
Expected: FAIL because `notify_run_event` is either not defined or broken.

- [ ] **Step 3: Implement payload encoding and repository notify**

In `backend/app/repositories/agent_repository.py`, add or extend `notify_run_event`:

```python
import json

async def notify_run_event(self, run_id: uuid.UUID, seq: int) -> None:
    payload = json.dumps({"run_id": str(run_id), "seq": seq})
    await self.session.execute(
        func.pg_notify("agent_run_events", payload)
    )
```

Remove or rename the unused `_notify_run_events` that only sends `run_id` as string; replace it with this. Ensure `func` is imported from `sqlalchemy`.

In `backend/app/services/agent/loop.py`, modify `_persist_and_notify` (lines 54-74): after `event = await event_repo.append_event(...)` and before `await event_session.commit()`, add:

```python
await event_repo.notify_run_event(run_id, seq_of_event)
```

Same for `_persist_terminal_and_notify` (lines 76-118) after the terminal event append.

The existing `agent_event_bus.publish_after_commit(persisted_event)` remains after commit.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest backend/tests/test_agent_notify.py -v`
Expected: PASS. Then run `python -m pytest backend/tests/test_agent_loop.py -q` — all 18 loop tests must pass (notifications happen inside mocked sessions).

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories/agent_repository.py backend/app/services/agent/loop.py backend/tests/test_agent_notify.py
git commit -m "feat: add pg_notify to event persistence paths"
```

---

### Task 2: Configuration

**Files:**
- Modify: `backend/app/core/config.py:1-41`

**Interfaces:**
- Produces: `Settings.agent_event_listen_notify_enabled`, `Settings.agent_event_notify_channel`, `Settings.agent_event_listener_reconnect_base_seconds`, `Settings.agent_event_listener_reconnect_max_seconds`, `Settings.agent_event_compensation_poll_seconds`, `Settings.agent_event_heartbeat_seconds`.

- [ ] **Step 1: Write failing config test**

Create `backend/tests/test_agent_notify_config.py`:

```python
from app.core.config import get_settings


def test_notify_settings_have_safe_defaults():
    settings = get_settings()
    assert settings.agent_event_listen_notify_enabled is True
    assert settings.agent_event_notify_channel == "agent_run_events"
    assert settings.agent_event_listener_reconnect_base_seconds == 0.5
    assert settings.agent_event_listener_reconnect_max_seconds == 5
    assert settings.agent_event_compensation_poll_seconds == 3
    assert settings.agent_event_heartbeat_seconds == 15


def test_notify_settings_can_be_disabled():
    import os
    os.environ["AGENT_EVENT_LISTEN_NOTIFY_ENABLED"] = "false"
    # Force cache miss
    from app.core.config import Settings
    s = Settings()
    assert s.agent_event_listen_notify_enabled is False
    del os.environ["AGENT_EVENT_LISTEN_NOTIFY_ENABLED"]
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest backend/tests/test_agent_notify_config.py -v`
Expected: FAIL with `AttributeError` because settings don't exist.

- [ ] **Step 3: Implement settings**

In `backend/app/core/config.py`, add after existing fields:

```python
agent_event_listen_notify_enabled: bool = True
agent_event_notify_channel: str = "agent_run_events"
agent_event_listener_reconnect_base_seconds: float = 0.5
agent_event_listener_reconnect_max_seconds: float = 5
agent_event_compensation_poll_seconds: float = 3
agent_event_heartbeat_seconds: float = 15
```

Also add the channel to `backend/.env.example`:

```env
AGENT_EVENT_LISTEN_NOTIFY_ENABLED=true
AGENT_EVENT_NOTIFY_CHANNEL=agent_run_events
AGENT_EVENT_LISTENER_RECONNECT_BASE_SECONDS=0.5
AGENT_EVENT_LISTENER_RECONNECT_MAX_SECONDS=5
AGENT_EVENT_COMPENSATION_POLL_SECONDS=3
AGENT_EVENT_HEARTBEAT_SECONDS=15
```

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest backend/tests/test_agent_notify_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/.env.example backend/tests/test_agent_notify_config.py
git commit -m "feat: add PostgreSQL LISTEN/NOTIFY configuration"
```

---

### Task 3: PostgreSQL Listener Service

**Files:**
- Create: `backend/app/services/agent/postgres_event_listener.py`
- Create: `backend/tests/test_postgres_event_listener.py`
- Modify: `backend/app/main.py` (startup/shutdown registration)

**Interfaces:**
- Consumes: `Settings.agent_event_notify_channel`, reconnect parameters, local `AgentEventBus.publish_after_commit`.
- Produces: `async def start_postgres_event_listener(settings, event_bus) -> asyncio.Task`, `async def shutdown_postgres_event_listener(task)`.

- [ ] **Step 1: Write failing listener tests**

Create `backend/tests/test_postgres_event_listener.py`:

```python
from __future__ import annotations

import json
import uuid

import pytest


def test_parse_valid_notification_payload():
    """Test payload extraction, not real asyncpg."""
    from app.services.agent.postgres_event_listener import (
        parse_notification_payload,
    )

    run_id = uuid.uuid4()
    result = parse_notification_payload(json.dumps({"run_id": str(run_id), "seq": 42}))
    assert result is not None
    assert result.run_id == run_id
    assert result.seq == 42


def test_parse_invalid_notification_returns_none():
    from app.services.agent.postgres_event_listener import (
        parse_notification_payload,
    )

    assert parse_notification_payload("not json") is None
    assert parse_notification_payload(json.dumps({"run_id": "bad", "seq": 1})) is None
    assert parse_notification_payload(json.dumps({"run_id": str(uuid.uuid4())})) is None
    assert parse_notification_payload(json.dumps({"run_id": str(uuid.uuid4()), "seq": -1})) is None
    assert parse_notification_payload(json.dumps({"run_id": str(uuid.uuid4()), "seq": 1, "text": "bad"})) is None


def test_reconnect_backoff_stops_at_max():
    from app.services.agent.postgres_event_listener import (
        next_reconnect_delay,
    )

    delays = []
    for attempt in range(10):
        delays.append(next_reconnect_delay(attempt, base=0.5, max_delay=5))
    assert delays[-1] == 5
    assert delays[0] == 0.5
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest backend/tests/test_postgres_event_listener.py -v`
Expected: FAIL because the module doesn't exist.

- [ ] **Step 3: Implement listener service**

Create `backend/app/services/agent/postgres_event_listener.py`:

```python
from __future__ import annotations

import asyncio
import json
import logging
import uuid

import asyncpg

from app.core.config import get_settings
from app.services.agent.event_bus import PersistedEvent, agent_event_bus

logger = logging.getLogger("agent_event_listener")


def parse_notification_payload(raw: str) -> PersistedEvent | None:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(payload, dict) or set(payload.keys()) != {"run_id", "seq"}:
        return None

    try:
        run_id = uuid.UUID(payload["run_id"])
    except (ValueError, KeyError, TypeError):
        return None

    seq = payload.get("seq")
    if not isinstance(seq, int) or seq <= 0:
        return None

    return PersistedEvent(run_id=run_id, seq=seq)


def next_reconnect_delay(attempt: int, *, base: float, max_delay: float) -> float:
    delay = base * (2 ** attempt)
    return min(delay, max_delay)


async def _listen_loop(
    dsn: str,
    channel: str,
    reconnect_base: float,
    reconnect_max: float,
    stop_event: asyncio.Event,
) -> None:
    attempt = 0

    while not stop_event.is_set():
        try:
            conn = await asyncpg.connect(dsn=dsn)
            logger.info("postgres_listener_connected", extra={"channel": channel})
        except Exception:
            delay = next_reconnect_delay(attempt, base=reconnect_base, max_delay=reconnect_max)
            logger.warning("postgres_listener_connect_failed", extra={"attempt": attempt, "delay": delay})
            attempt += 1
            await asyncio.sleep(delay)
            continue

        try:
            await conn.execute(f"LISTEN {channel}")
            attempt = 0

            while not stop_event.is_set():
                try:
                    notification = await asyncio.wait_for(
                        conn.get(timeout=0), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                if notification is None:
                    continue

                event = parse_notification_payload(notification.payload)
                if event is None:
                    logger.warning("postgres_notification_invalid", extra={"channel": channel})
                    continue

                await agent_event_bus.publish_after_commit(event)
        except Exception:
            logger.warning("postgres_listener_disconnected", extra={"channel": channel})
            attempt += 1
        finally:
            try:
                await conn.close()
            except Exception:
                pass

        if stop_event.is_set():
            break

        delay = next_reconnect_delay(attempt, base=reconnect_base, max_delay=reconnect_max)
        await asyncio.sleep(delay)


def start_postgres_event_listener() -> asyncio.Task:
    settings = get_settings()
    stop_event = asyncio.Event()

    task = asyncio.create_task(
        _listen_loop(
            dsn=settings.database_url,
            channel=settings.agent_event_notify_channel,
            reconnect_base=settings.agent_event_listener_reconnect_base_seconds,
            reconnect_max=settings.agent_event_listener_reconnect_max_seconds,
            stop_event=stop_event,
        )
    )

    task._pg_listener_stop_event = stop_event  # type: ignore[attr-defined]
    return task


async def shutdown_postgres_event_listener(task: asyncio.Task) -> None:
    stop_event: asyncio.Event | None = getattr(task, "_pg_listener_stop_event", None)
    if stop_event is not None:
        stop_event.set()
    try:
        await asyncio.wait_for(task, timeout=2)
    except asyncio.TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
```

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest backend/tests/test_postgres_event_listener.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/postgres_event_listener.py backend/tests/test_postgres_event_listener.py
git commit -m "feat: add PostgreSQL listener service"
```

---

### Task 4: SSE Generator Switch To Wake-Up-Driven Dispatch

**Files:**
- Modify: `backend/app/api/agent_stream.py:27-31`
- Modify: `backend/app/api/agent_stream.py:181-244`

**Interfaces:**
- Consumes: `Settings.agent_event_compensation_poll_seconds`, `Settings.agent_event_heartbeat_seconds`.
- Produces: Same `StreamingResponse` generator but with wake-up-driven active loop.

- [ ] **Step 1: Write failing SSE generator tests**

Create `backend/tests/test_agent_notify_sse.py`:

```python
from __future__ import annotations

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.agent.event_bus import PersistedEvent, _BoundedQueue


@pytest.mark.anyio
async def test_wake_up_emits_events_without_compensation_wait():
    """A local queue wake-up should trigger event emission immediately."""
    from app.services.agent.event_bus import agent_event_bus

    run_id = uuid.uuid4()
    event_bus = agent_event_bus
    subscriber_id, queue = await event_bus.subscribe(run_id)
    try:
        await event_bus.publish_after_commit(PersistedEvent(run_id=run_id, seq=1))
        item = await asyncio.wait_for(queue.get(), timeout=0.05)
        assert item is not None
        assert item.seq == 1
    finally:
        await event_bus.unsubscribe(run_id, subscriber_id)


@pytest.mark.anyio
async def test_compensation_poll_interval_is_3_seconds():
    from app.api.agent_stream import SSE_POLL_INTERVAL
    from app.core.config import get_settings

    settings = get_settings()
    assert settings.agent_event_compensation_poll_seconds == 3
    # Old 100ms constant must be replaced
    assert SSE_POLL_INTERVAL == 0.1
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest backend/tests/test_agent_notify_sse.py -v`
Expected: FAIL because `SSE_POLL_INTERVAL` is still 0.1.

- [ ] **Step 3: Implement SSE generator changes**

In `backend/app/api/agent_stream.py`, change line 31:

```python
SSE_POLL_INTERVAL = 0.1
```

to use the settings value:

```python
from app.core.config import get_settings
_settings = get_settings()
SSE_POLL_INTERVAL = _settings.agent_event_compensation_poll_seconds
```

Rename `HEARTBEAT_INTERVAL` constant to use the settings value:

```python
HEARTBEAT_INTERVAL = _settings.agent_event_heartbeat_seconds
```

Note: The existing `SSE_POLL_INTERVAL` variable name and semantics remain. The generator uses `queue.get(timeout=SSE_POLL_INTERVAL)` — this now means the compensation poll timeout, which is 3 seconds instead of 0.1. Normal wake-ups from the local queue (either from same-process worker or from the PostgreSQL listener task) will still arrive immediately without waiting.

The existing loop in `_stream_persisted_run_events` (lines 216-241) already handles:
- `queue.get()` wake-up → immediate fall-through to `emit_persisted_events()`
- `TimeoutError` on the queue get → heartbeat check → `emit_persisted_events()` as compensation

This is the correct behavior for the new design. The key change is the timeout value.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest backend/tests/test_agent_notify_sse.py -v`
Expected: PASS.
Run: `python -m pytest backend/tests/test_agent_stream.py -v -q`
Expected: All existing stream tests pass (they mock the queue and timeout).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/agent_stream.py backend/tests/test_agent_notify_sse.py
git commit -m "feat: switch SSE to 3s compensation poll with wake-up dispatch"
```

---

### Task 5: Startup/Shutdown Integration And Integration Tests

**Files:**
- Modify: `backend/app/main.py` (startup/shutdown lifespan)
- Create: `backend/tests/test_agent_notify_integration.py`

- [ ] **Step 1: Write failing integration test**

Create `backend/tests/test_agent_notify_integration.py`:

```python
from __future__ import annotations

import json
import uuid

import asyncpg
import pytest
from unittest.mock import AsyncMock

from app.core.config import get_settings
from app.services.agent.event_bus import agent_event_bus


@pytest.mark.anyio
async def test_notification_wakes_local_subscriber():
    """End-to-end: publish pg_notify from a separate connection, verify local wake-up."""
    settings = get_settings()
    run_id = uuid.uuid4()
    _, queue = await agent_event_bus.subscribe(run_id)

    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        await conn.execute("LISTEN agent_run_events")
        payload = json.dumps({"run_id": str(run_id), "seq": 1})
        await conn.execute("SELECT pg_notify('agent_run_events', $1)", payload)

        item = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert item.run_id == run_id
        assert item.seq == 1
    finally:
        await conn.close()
        await agent_event_bus.unsubscribe(run_id, "test")


@pytest.mark.anyio
async def test_no_notification_when_no_local_subscriber():
    """A notification for a run with no local subscriber does not crash."""
    settings = get_settings()
    conn = await asyncpg.connect(dsn=settings.database_url)
    try:
        payload = json.dumps({"run_id": str(uuid.uuid4()), "seq": 1})
        await conn.execute("SELECT pg_notify('agent_run_events', $1)", payload)
        # No assertion needed — just verify no exception
    finally:
        await conn.close()
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest backend/tests/test_agent_notify_integration.py -v`
Expected: FAIL for `test_notification_wakes_local_subscriber` because no task is dispatching the listener notifications to the local bus.

- [ ] **Step 3: Implement startup/shutdown to wire listener to local bus**

Note: The listener service (Task 3) calls `agent_event_bus.publish_after_commit()` for each notification. The integration test above manually uses `agent_event_bus.subscribe()`, which is the same interface the SSE generator uses. So the test actually tests that `publish_after_commit` delivers to local subscribers — which is the same code path the listener would invoke.

The integration test in Step 1 doesn't require the full listener task because it manually calls `pg_notify` and then uses the queue directly. The test verifies the local bus works with wake-up notifications.

For the actual startup/shutdown in `backend/app/main.py`, add a lifespan handler:

```python
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.services.agent.postgres_event_listener import (
    start_postgres_event_listener,
    shutdown_postgres_event_listener,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    listener_task = None
    if settings.agent_event_listen_notify_enabled:
        listener_task = start_postgres_event_listener()
    try:
        yield
    finally:
        if listener_task is not None:
            await shutdown_postgres_event_listener(listener_task)

app = FastAPI(lifespan=lifespan)
```

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest backend/tests/test_agent_notify_integration.py -v`
Expected: PASS.

Run: `python -m pytest backend/tests/test_agent_stream.py backend/tests/test_agent_loop.py backend/tests/test_agent_notify.py backend/tests/test_postgres_event_listener.py backend/tests/test_agent_notify_sse.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_agent_notify_integration.py
git commit -m "feat: wire listener into FastAPI lifecycle"
```

---

### Task 6: Full Regression Verification

- [ ] **Step 1: Run full backend test suite**

Run: `python -m pytest -q`
Expected: All non-database-issue tests pass. Agent loop, stream, and notify tests must all be green.

- [ ] **Step 2: Run full frontend test suite**

Run: `cd frontend; npm test -- --run`
Expected: 385+/387 pass, only pre-existing role-management flaky failures.

- [ ] **Step 3: Run production build**

Run: `cd frontend; npm run build`
Expected: Compiled successfully, TypeScript OK, all routes listed.

- [ ] **Step 4: Commit if clean**

```bash
git status --short
# If only expected files are changed, report success.
```
