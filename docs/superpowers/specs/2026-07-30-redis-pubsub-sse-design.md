# Redis Pub/Sub SSE Streaming Design

## Goal

Replace the current `pg_notify` → DB SELECT round-trip in the SSE hot path with
Redis Pub/Sub carrying complete event payloads, while PostgreSQL remains the
authoritative audit log persisted asynchronously (fire-and-forget). Achieve
sub-millisecond event delivery with independent Worker/API scaling.

## Motivation

The current `pg_notify` bridge (added 2026-07-30) sends only a lightweight signal
(`{run_id, seq}`), forcing the SSE generator to issue a redundant `SELECT` to
retrieve the event it just wrote. Every `answer_delta` incurs:

```
INSERT event (2ms) → pg_notify (0.5ms) → SELECT same event back (0.5ms) → SSE
```

Two problems: (1) the DB is hit twice for the same data, (2) the hot-path latency
floor is ~3 ms despite the event body being < 100 bytes for most deltas.

Redis Pub/Sub eliminates both: the Worker publishes the complete `EventItem` JSON
directly to a Redis channel, and every API subscriber receives it immediately with
no DB query. PostgreSQL persists the same event asynchronously, decoupled from the
streaming loop.

## Architecture

```
                         🔴 Hot path (Redis Pub/Sub, ~0.1 ms)
                         ─ ─ Cold path (async DB write, fire-and-forget)

┌─────────────────────┐     ┌──────────────┐     ┌─────────────────────┐
│     Worker 进程      │     │    Redis     │     │     API 进程         │
│                     │     │   Pub/Sub    │     │                     │
│ DeepSeek chunk      │     │              │     │ RedisSubscriber     │
│   │                 │     │              │     │   │                 │
│   ├─PUBLISH─────────▶─────▶ channel:     │────▶│   │ on_message()    │
│   │ (完整 EventItem) │     │ run:{id}    │     │   │                 │
│   │                 │     │              │     │   ▼                 │
│   └─asyncio.task───▶│     └──────────────┘     │ event_bus.publish() │
│     (INSERT DB)     │                           │   │                 │
│                     │                           │   ▼                 │
│                     │                           │ SSE 生成器          │
│                     │                           │ queue.get()        │
│                     │                           │ _encode_sse_event() │
│                     │                           │   │                 │
│                     │                           │   ▼                 │
│                     │                           │ 浏览器              │
└─────────────────────┘                           └─────────────────────┘
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Channel naming | `run:{run_id}` per active run | Isolates traffic; subscriber only receives events for runs currently streamed |
| Payload format | Full `EventItem` JSON | Eliminates DB round-trip; payload < 8 KB for 99% of events |
| Hot-path persistence | `asyncio.create_task` fire-and-forget | Delivery to browser must not wait for DB commit |
| Terminal-event persistence | Synchronous `await` | `answer_completed`, `run_succeeded` must be durable before marking terminal |
| Worker-to-Worker notification | `pg_notify('new_run')` | Unchanged; Worker wakes on new run via existing mechanism |
| Redis unavailable | Fallback to pg_notify + DB poll | SSE generator falls back gracefully (already implemented) |

### Event Bus Integration

The `RedisSubscriber` is a thin shim that receives a Redis message, deserializes
it to an `EventItem`, and calls `event_bus.publish(event_item)`:

```
Redis channel "run:{id}"  →  RedisSubscriber.on_message()
                                   │
                                   ▼
                            parse JSON → EventItem
                                   │
                                   ▼
                            event_bus.publish(EventItem)
                                   │
                                   ▼
                            SSE generator: queue.get()
                            (already handles EventItem directly, no code change needed)
```

### Async Persistence Strategy

```python
# loop.py: revised _stream_final_answer hot path
async for chunk in llm_client.stream_text(messages):
    event_item = EventItem(run_id=run_id, seq=seq, event_type="answer_delta", ...)

    # Hot: batch-publish to Redis via frame coalescing (~32 ms window)
    await redis_bridge.publish(f"run:{run_id}", event_item)

    # Cold: persist to PostgreSQL, fire-and-forget
    asyncio.create_task(_persist_event_to_db(event_item))
```

### Performance Optimizations

**1. Batch Publish with Frame Coalescing**

Instead of publishing each `answer_delta` individually (up to 60 Redis PUBLISH/s),
the `RedisBridge` accumulates events within a configurable time window (~32 ms,
2 rendering frames) and publishes a batch JSON array:

```
Individual (60 publishes/s):       Batch (2 publishes/s):
Worker → Redis: delta1 .01ms       Worker: delta1, delta2, delta3 accumulate
Worker → Redis: delta2 .01ms              ↓ 32ms window elapses
Worker → Redis: delta3 .01ms       Worker → Redis: [delta1, delta2, delta3] .01ms
```

The API subscriber receives the batch array, iterates, and publishes each event
to the EventBus individually. Frontend rendering is unaffected — `useTypingText`
still renders character-by-character at 20 ms/char.

**2. orjson Serialization**

Replace `json.dumps` with `orjson.dumps` for ~3-5x faster serialization:

```python
# Before
payload = json.dumps(event_dict, ensure_ascii=False).encode()

# After
payload = orjson.dumps(event_dict)  # Returns bytes, no encoding step
```

`orjson` is added to `requirements.txt`. All existing `json.dumps` calls in
the hot path are replaced.

**3. Redis Streams (Optional, Multi-Replica Only)**

When `AGENT_REDIS_STREAMS_ENABLED=True`, publish to a Redis Stream instead of
a Pub/Sub channel. Consumer Groups ensure each event is delivered exactly once
across multiple API replicas, preventing duplicate SSE emissions.

For single-process deployments (default), Pub/Sub is sufficient and faster.

### Configuration

```python
# core/config.py additions
REDIS_URL: str = "redis://localhost:6379/0"
    # Redis connection URL

AGENT_REDIS_PUBSUB_ENABLED: bool = True
    # True:  use Redis Pub/Sub for hot-path event delivery
    # False: fall back to pg_notify pipeline (legacy)

AGENT_REDIS_STREAMS_ENABLED: bool = False
    # True:  use Redis Streams + Consumer Groups (multi-replica)
    # False: use Redis Pub/Sub (single-process, default)

AGENT_REDIS_BATCH_WINDOW_MS: int = 32
    # Max window (ms) to accumulate events before publishing batch

AGENT_REDIS_BATCH_MAX_SIZE: int = 20
    # Max number of events to accumulate before publishing batch

AGENT_SYNC_PERSIST_EVENTS: bool = False
    # True:  await DB write in hot path (safer, slower)
    # False: fire-and-forget async DB write (faster, default)
```

### Files Changed

| File | Change | Impact |
|------|--------|--------|
| `backend/app/services/agent/redis_bridge.py` | **New.** `RedisBridge` class: connect, publish (batch-coalesced), subscribe, Streams (optional) | Core |
| `backend/app/services/agent/loop.py` | `_persist_and_notify`: publish to RedisBridge first, async DB second | Hot path |
| `backend/app/api/agent_stream.py` | Optional: direct Emit from EventBus EventItem (no DB catch-up needed when Redis active) | SSE |
| `backend/app/main.py` | `lifespan`: start `RedisBridge` subscriber, shutdown | Lifecycle |
| `backend/app/core/config.py` | Add 5 Redis + batch settings | Config |
| `backend/requirements.txt` | Add `redis[hiredis]`, `orjson` | Dependencies |

### Startup

```bash
# Start Redis (once)
redis-server

# Start API (Worker auto-starts inside lifespan if agent_worker_embedded=True)
uvicorn app.main:app --port 8000

# Or start Worker separately (production, multi-process)
python -m app.workers.agent_worker
```

### Latency Comparison

| Step | Before (pg_notify + DB round-trip) | After (Redis Pub/Sub) |
|------|-------------------------------------|----------------------|
| INSERT event | ~2 ms (hot path) | — (async) |
| pg_notify | ~0.5 ms | — |
| DB SELECT catch-up | ~0.5 ms | — |
| Redis publish | — | ~0.05 ms |
| Redis deliver to subscriber | — | ~0.05 ms |
| EventBus publish | ~0.01 ms | ~0.01 ms |
| SSE encode + TCP | ~1 ms | ~1 ms |
| **Pipeline overhead** | **~4 ms** | **~0.1 ms** |

### Crash Recovery

If Worker crashes mid-stream:

1. `AgentRunAttempt` lease expires.
2. Recovery Worker detects expired lease, reads last `answer_completed` or
   `answer_checkpoint` from DB.
3. Creates retry attempt with `not_before` backoff.
4. Lost fire-and-forget delta events (between last checkpoint and crash) are
   acceptable — the retry regenerates the answer.

### Risks

| Risk | Mitigation |
|------|-----------|
| Redis unavailable | Fallback to pg_notify pipeline (already coded in agent_stream.py EventNotify handler) |
| Redis message loss (no subscriber) | Retry-safe; browser reconnects with after_seq, SSE replays from DB |
| Firebase-and-forget DB write fails | Log warning; next checkpoint or terminal event persists full text |
| Redis connection exhaustion | Pool of connections managed by `redis.asyncio` |
