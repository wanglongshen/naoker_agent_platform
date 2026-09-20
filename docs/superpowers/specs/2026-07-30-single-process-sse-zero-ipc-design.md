# Single-Process SSE Streaming: Zero-IPC Event Bus Architecture

## Goal

Eliminate all inter-process communication (pg_notify, Redis, internal HTTP) from the SSE
hot path. Co-locate the Agent Worker as an asyncio background task within the FastAPI
process so that the in-process `EventBus` becomes the sole event delivery mechanism.
Persist events to PostgreSQL asynchronously (fire-and-forget) so that DB writes never
block streaming. Achieve sub-millisecond event delivery latency.

## Motivation

The current architecture runs the Agent Worker as a standalone OS process. Every
`answer_delta` event produced by the Worker must cross a process boundary to reach the
SSE generator inside the FastAPI process. The recently added `pg_notify` bridge brings
latency down to ~2 ms, but two inefficiencies remain:

1. **DB write-then-immediate-read**: the Worker INSERTs every delta into
   `agent_run_events` and the SSE generator immediately SELECTs the same row back.
   This double hit on the database is unnecessary for live streaming.

2. **IPC overhead**: even the lightweight `pg_notify` path involves a PostgreSQL
   callback, a queue dispatch, and an asyncpg listener round-trip (~0.5–1 ms).

By merging Worker and API into a single process, the in-memory `EventBus` carries
events directly from the loop to the SSE generator with zero IPC. DB persistence
becomes a non-blocking background operation (via `asyncio.create_task`), decoupled
from the streaming hot path.

## Current State

```
Worker process                         API process
─────────────────                     ─────────────────
DeepSeek chunk "量子"
  │
  ├─① INSERT agent_run_events  ──▶  PostgreSQL
  │
  ├─② pg_notify('agent_run_events')
  │   {run_id, seq:42}         ──▶  ──▶  PostgresEventListener
  │                                      │  EventNotify → EventBus
  │                                      ▼
  │                                  SSE generator wakes
  │                                    │
  └─③ event_bus.publish(EventItem)     │
     (Worker's EventBus — useless)      │
                                        ▼
                                   ④ SELECT FROM agent_run_events
                                      WHERE seq > last_seen_seq
                                        │
                                        ▼
                                   ⑤ _encode_sse_event → browser
```

- Steps ①+② = committed transaction (~2 ms)
- Step ④ = a redundant read (same data just inserted by ①)
- Step ③ = wasted (Worker and API have separate `EventBus` instances)

## Proposed Architecture

```
┌──────────────  Single FastAPI Process  ──────────────┐
│                                                       │
│  Agent Worker (asyncio Task, lifespan startup)        │
│    │                                                  │
│    │ DeepSeek chunk "量子"                             │
│    │                                                  │
│    ├─▶ HOT: event_bus.publish(EventItem)              │
│    │         │                                        │
│    │         ▼                                        │
│    │   SSE Generator: queue.get()  ← same EventBus!   │
│    │         │                                        │
│    │         ▼                                        │
│    │   _encode_sse_event() → browser (sub-millisecond)│
│    │                                                  │
│    └─▶ COLD: asyncio.create_task(                     │
│              persist_to_db(EventItem)                 │
│            )                                          │
│            │                                          │
│            ▼                                          │
│       PostgreSQL (async, never blocks the hot path)   │
│                                                       │
└───────────────────────────────────────────────────────┘
```

### Key Changes

| Component | Before | After |
|-----------|--------|-------|
| Event delivery | pg_notify → EventNotify → DB SELECT → SSE | `event_bus.publish(EventItem)` → SSE (direct) |
| DB persistence | Synchronous, in hot path (INSERT blocks streaming) | Asynchronous `create_task`, fire-and-forget |
| Worker startup | Separate terminal: `python -m app.workers.agent_worker` | Auto-launched in `main.py` lifespan |
| pg_notify | Core delivery mechanism | Kept as fallback only (configurable off) |
| PostgresEventListener | Always active in lifespan | Disabled by default |

### Event Bus: The Single Source

The `EventBus` (`backend/app/services/agent/event_bus.py`) becomes the universal
event router for the entire process:

```
event_bus.publish(EventItem)           # loop.py (Worker task)
    └── fan-out to all subscribers     # agent_stream.py (SSE consumers)
```

Since both the Worker task and the SSE generator live in the same asyncio event loop,
`queue.put_nowait()` followed by `queue.get()` completes in microseconds with no
serialization, no network, no database.

### Async Persistence: Fire-and-Forget

Current `_persist_and_notify` in `loop.py`:

```python
# Current: blocks on DB
event = await repo.append_event(run, attempt, event_type, payload, notify=True)
await repo.session.commit()          # ← blocks the hot path
await event_bus.publish(committed)
```

Proposed:

```python
# After: push first, persist later
await event_bus.publish(committed)   # ← hot path: immediate

asyncio.create_task(
    _persist_background(run, attempt, event_type, payload)
)                                     # ← cold path: async fire-and-forget
```

The `_persist_background` coroutine opens its own DB session, INSERTs the event,
commits, and handles errors silently (logging a warning). If it fails, the event
is already delivered to the browser — the only consequence is a gap in the DB
event log, which is acceptable for `answer_delta` fragments (recoverable via
the next `answer_checkpoint`).

### Worker Lifecycle

In `main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... seed RBAC ...

    # Start Agent Worker as a background asyncio Task
    worker = AgentWorker(worker_id=f"{socket.gethostname()}:{os.getpid()}", concurrency=3)
    worker_task = asyncio.create_task(worker.run(), name="agent-worker")

    yield

    # Graceful shutdown
    await worker.stop()
    try:
        await asyncio.wait_for(worker_task, timeout=settings.worker_shutdown_grace_seconds)
    except asyncio.TimeoutError:
        worker_task.cancel()
```

Single-command startup:

```bash
# Before (3 terminals)
uvicorn app.main:app              # terminal 1: API
python -m app.workers.agent_worker # terminal 2: Worker
python -m app.workers.agent_maintenance # terminal 3: Maintenance

# After (1 terminal)
uvicorn app.main:app              # API + Worker auto-starts inside lifespan
```

Maintenance worker can stay separate (daily cleanup, low frequency).

### PG Notify Fallback

Keep the `pg_notify` bridge as an optional fallback channel. When
`agent_event_listen_notify_enabled=True`, the listener still runs and publishes
`EventNotify` into the `EventBus`. The SSE generator already handles `EventNotify`
gracefully. This provides:

- **Development**: single-process with EventBus only (no PG listener needed)
- **Production (multi-replica)**: enable PG listener on each API replica for
  notifications from maintenance tasks or other replicas

### Delta Persistence Strategy

| Event Type | Hot Path | Persistence |
|-----------|----------|-------------|
| `answer_delta` | EventBus → SSE immediate | `create_task` fire-and-forget |
| `answer_checkpoint` | EventBus → SSE immediate | `create_task` fire-and-forget |
| `answer_completed` | EventBus → SSE immediate | `await` (must succeed before run_succeeded) |
| `run_succeeded` | EventBus → SSE immediate | `await` (terminal event, must be durable) |
| `plan_created`, `step_completed`, `tool_*` | EventBus → SSE immediate | `create_task` fire-and-forget |
| `visible_thought_*` | EventBus → SSE immediate | `create_task` fire-and-forget |

Terminal events (`answer_completed`, `run_succeeded`, `run_failed`) use `await`
persistence because downstream consumers (session history builder, audit,
reconciliation) depend on their presence in the DB.

### Crash Recovery

If the Worker task crashes mid-stream:

1. The `AgentRunAttempt` lease expires.
2. A new Worker task (or the restarted process) detects the expired lease via
   `_recover_expired()`.
3. `answer_checkpoint` records (written every 256 chars / 0.4 s) provide the
   latest known answer state.
4. A retry attempt is created with `not_before` backoff.

Edge case: the last few `answer_delta` chunks (between the last checkpoint and
the crash) are lost. The retry picks up from the last checkpoint. Maximum data
loss: 255 characters (the worst-case window between checkpoints).

### Configuration

```python
# New settings in core/config.py
agent_sync_persist_events: bool = False
    # True:  await DB persistence in hot path (safer, current behavior)
    # False: fire-and-forget async persistence (faster, proposed)

agent_worker_embedded: bool = True
    # True:  start worker as asyncio task in lifespan
    # False: worker must be started separately (legacy mode)

agent_event_listen_notify_enabled: bool = False
    # True:  enable PG listener (for multi-replica deployments)
    # False: rely on EventBus only (single-process, default)
```

### Latency Comparison

| | Before (separate process + pg_notify) | After (single process + EventBus) |
|---|---|---|
| LLM chunk | ~16 ms | ~16 ms |
| Worker → EventBus | N/A (cross-process) | ~0.01 ms |
| IPC (pg_notify) | ~0.5 ms | — |
| DB INSERT (hot path) | ~2 ms | — (async) |
| DB SELECT (SSE catch-up) | ~0.5 ms | — |
| SSE encode + TCP | ~1 ms | ~1 ms |
| Frontend render | ~16 ms | ~16 ms |
| **Total pipeline overhead** | **~4 ms** | **~1 ms** |

### Files Changed

| File | Change |
|------|--------|
| `backend/app/main.py` | `lifespan`: start `AgentWorker` as asyncio task, shutdown |
| `backend/app/services/agent/loop.py` | `_persist_and_notify`: publish first, persist async. Terminal events: await persist |
| `backend/app/api/agent_stream.py` | Remove `EventNotify` handling (no longer needed for fast path; keep for pg_notify fallback) |
| `backend/app/core/config.py` | Add `agent_sync_persist_events`, `agent_worker_embedded` |
| `backend/app/workers/agent_worker.py` | Entry point remains for standalone mode, `AgentWorker.stop()` made async-safe for lifecycle |

### Migration Path

1. **Phase 1** (this spec): Add `_persist_background` + `agent_sync_persist_events` flag.
   Default `agent_sync_persist_events=True` (current behavior, safe).
   Add `agent_worker_embedded` flag, default `False`.

2. **Phase 2** (test in dev): Set `agent_sync_persist_events=False`,
   `agent_worker_embedded=True`. Run full test suite. Validate streaming latency.

3. **Phase 3** (production): Flip defaults. Remove standalone Worker startup from
   deployment scripts.

### Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Worker crash loses last deltas | Checkpoint every 256 chars → max loss 255 chars; retry mechanism handles |
| EventBus queue overflow (1000 items) | Full queues unsubscribe subscriber; SSE reconnects with `after_seq` |
| Database connection exhaustion | Fire-and-forget tasks use same pool; pool_size=20 should suffice for 3 concurrent attempts |
| Async DB write fails silently | Log warning; next checkpoint or completed event will fill the gap |
| CPU-bound LLM inference blocks asyncio | DeepSeek API is network I/O (asyncio native); tool execution (calculator) is fast; `http_request` is async |

### Non-Goals

- Multi-replica API deployment (pg_notify fallback preserved but not in fast path)
- Horizontal Worker scaling (single-process embeds one Worker by design; for scale-out,
  run multiple process replicas each with `agent_worker_concurrency=1`)
- Eliminating PostgreSQL entirely (event log remains authoritative source for audit,
  reconciliation, and replay)
