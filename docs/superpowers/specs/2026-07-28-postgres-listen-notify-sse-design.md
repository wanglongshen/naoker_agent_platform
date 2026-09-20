# PostgreSQL LISTEN/NOTIFY SSE Design

## Goal

Replace the active agent-run SSE stream's normal 100 ms database polling path
with PostgreSQL `LISTEN/NOTIFY` wake-ups, while retaining the database event
log as the sole authoritative source and a low-frequency compensation poll for
failure recovery.

The design supports multiple independently deployed FastAPI API instances and
an independently deployed agent worker. It must not require sticky sessions,
Redis, or moving the worker into FastAPI.

## Current State

The worker persists each `AgentRunEvent` and publishes a process-local
`PersistedEvent(run_id, seq)` wake-up. The API SSE generator receives that
wake-up only when the worker and API share a process. In the normal deployed
topology, the independent worker cannot wake an API instance's in-memory bus.

`backend/app/api/agent_stream.py` therefore waits at most 100 ms, queries run
status, and queries the persisted event table repeatedly. This provides
cross-process correctness but introduces database load and event delivery
jitter.

The event table and `seq` cursor are already the authoritative replay
mechanism. PostgreSQL notification will optimize discovery only; it will never
carry the event body or replace cursor-based database reads.

## Architecture

Every API instance runs one dedicated PostgreSQL listener connection. Every
worker event transaction writes the event, registers a PostgreSQL notification
in that same transaction, and commits. PostgreSQL sends the notification only
after the transaction commits.

```text
Worker transaction
  -> append AgentRunEvent(run_id, seq)
  -> SELECT pg_notify('agent_run_events', payload)
  -> COMMIT
  -> PostgreSQL broadcasts notification
  -> each API instance listener receives {run_id, seq}
  -> local wake-up router signals only local SSE subscribers for run_id
  -> each SSE generator queries events where seq > last_seen_seq
  -> SSE emits ordered persisted events
```

The API instance that has no local SSE subscribers for a notified run does no
event-table lookup. An API instance that owns one or more subscribers performs
the normal cursor query for each awakened generator. Browser connections remain
independent and retain their own `last_seen_seq` cursor.

## Notification Contract

The configured PostgreSQL notification channel defaults to:

```text
agent_run_events
```

The payload is compact JSON:

```json
{"run_id":"8aaea3fd-50a3-4d92-9fd6-8b3d4b81ea3c","seq":123}
```

Rules:

- The payload contains only `run_id` and positive integer `seq`.
- It must not contain event bodies, answer text, user data, tool data,
  attachments, credentials, or error details.
- `pg_notify()` runs through the same database session and transaction that
  appends the event, before commit.
- A rollback must expose neither the event nor a usable notification.
- Notification order and duplicate delivery are not trusted for browser output.
  The event table ordered by `seq` remains authoritative.
- Malformed payloads are logged with safe metadata and ignored without ending
  the listener task.

## Event Persistence

All paths that append live events, including normal deltas, checkpoints,
failures, and terminal events, must use one shared repository-level operation:

```text
append event
-> register pg_notify(run_id, seq) in the current transaction
-> commit transaction
-> publish local process wake-up when applicable
```

The existing local `AgentEventBus` remains in place. It is a same-process
optimization and a local fan-out mechanism only. PostgreSQL notification makes
the same wake-up available to every API instance.

Duplicate wake-ups from a local worker and the PostgreSQL listener are valid.
They may produce an extra empty database query but cannot produce duplicate SSE
frames because the SSE cursor advances only after an event frame is emitted.

## Dedicated PostgreSQL Listener

Add an API-process service, for example
`backend/app/services/agent/postgres_event_listener.py`.

It owns a dedicated `asyncpg` connection rather than an SQLAlchemy pool
connection because `LISTEN` is session-scoped and must remain active for the
service lifetime.

Responsibilities:

- Open a dedicated asyncpg connection from the configured PostgreSQL URL.
- Execute `LISTEN <configured-channel>`.
- Parse and validate notification payloads.
- Forward valid `PersistedEvent(run_id, seq)` hints to the local wake-up router.
- Reconnect after disconnects with bounded exponential backoff.
- Expose listener health through structured logs and in-process state.
- Stop reconnecting, unlisten, and close the connection during FastAPI shutdown.

Lifecycle:

```text
FastAPI startup
  -> create listener background task
  -> connect and LISTEN

connection failure
  -> mark degraded
  -> reconnect after 0.5 s, 1 s, 2 s, 4 s, then cap at 5 s

FastAPI shutdown
  -> signal stop
  -> cancel or await listener task
  -> UNLISTEN and close connection
```

Listener availability is an optimization. An unavailable listener must not
make the API unhealthy or prevent SSE replay; streams continue with
compensation polling.

## Local Wake-Up Router

The existing `AgentEventBus` keeps a mapping from `run_id` to local subscriber
queues. It gains or reuses a safe method that publishes a lightweight
`PersistedEvent(run_id, seq)` to local queues.

The PostgreSQL listener invokes this method after accepting a notification.
The worker still invokes it directly after its local commit where applicable.

Requirements:

- Fan out only to local subscribers of the notified run.
- Do not block writers on slow clients.
- Preserve existing bounded queue behavior and slow-subscriber removal.
- Do not serialize event payloads into local queues.
- Do not need global deduplication; cursor-based event reads provide output
  idempotence.

## SSE Generator

`backend/app/api/agent_stream.py` keeps all existing replay, cursor validation,
event ordering, encoding, authentication, origin validation, heartbeat, and
terminal catch-up behavior.

The active loop changes from frequent status/event polling to wake-up-driven
event reads:

```text
1. Replay persisted events after the requested cursor.
2. Subscribe local queue for run_id.
3. Replay once more to close the subscribe race.
4. Wait for one of:
   - local wake-up queue item;
   - compensation-poll deadline;
   - heartbeat deadline.
5. On local wake-up, read and emit every persisted event after cursor.
6. On compensation deadline, read events and current run status.
7. On heartbeat deadline, emit ':keepalive'.
8. After a terminal event or confirmed terminal status, perform final catch-up
   and close the stream.
```

Normal PostgreSQL notification delivery must not wait for the compensation
deadline. The notification is only a signal; the generator always queries the
database before emitting frames.

`last_seen_seq` advances only after a valid frame has been generated and yielded
from the persisted event. A duplicate, stale, malformed, or out-of-order
wake-up cannot skip an event or duplicate a browser-visible event.

Run status reads occur after event wake-ups and at compensation deadlines, not
every 100 ms. A terminal event remains sufficient to trigger final catch-up and
stream closure.

## Failure and Recovery

| Condition | Required behavior |
| --- | --- |
| Invalid notification payload | Log safe metadata, ignore, keep listening. |
| Listener disconnect | Reconnect with bounded exponential backoff; SSE relies on compensation polling meanwhile. |
| Notification lost | Compensation poll reads events after cursor and sends them. |
| Listener starts late | Initial replay and compensation polling preserve delivery. |
| Duplicate local and PostgreSQL wake-up | At most an extra empty event query; no duplicate SSE frame. |
| Queue full | Preserve current slow-subscriber handling; EventSource reconnects and replays from cursor. |
| Worker transaction rollback | No committed event and no browser-visible output. |
| Terminal notification lost | Compensation poll or EventSource reconnect obtains terminal event; final catch-up closes stream. |
| PostgreSQL notification unavailable | Emit listener-degraded telemetry; retain compensation-poll SSE operation. |

## Configuration

Add the following settings with these defaults:

```env
AGENT_EVENT_LISTEN_NOTIFY_ENABLED=true
AGENT_EVENT_NOTIFY_CHANNEL=agent_run_events
AGENT_EVENT_LISTENER_RECONNECT_BASE_SECONDS=0.5
AGENT_EVENT_LISTENER_RECONNECT_MAX_SECONDS=5
AGENT_EVENT_COMPENSATION_POLL_SECONDS=3
AGENT_EVENT_HEARTBEAT_SECONDS=15
```

The enabled flag allows immediate operational fallback. When false, the API
does not start the listener and SSE uses the compensation polling path. The
fallback does not alter cursor, event, or browser protocol semantics.

## Observability

Add safe structured logs and metrics. They must not record answer text,
prompts, attachments, tool payloads, cookies, JWTs, or secrets.

Required measurements:

- listener connected/degraded state;
- listener reconnect count;
- notifications received and invalid notifications rejected;
- local SSE wake-ups by source: local bus, PostgreSQL notification, or
  compensation poll;
- notification-to-SSE-frame latency;
- event-commit-to-SSE-frame latency;
- compensation-poll count and recovery count;
- listener queue overflow or slow-subscriber removal count.

Permitted log dimensions are `run_id`, `seq`, `event_type`, API instance ID,
wake-up source, listener state, and latency values.

## Testing

### Unit Tests

- Notification payload encoder emits only valid `run_id` and `seq` fields.
- Invalid JSON, invalid UUID, missing fields, and invalid sequence values are
  rejected without ending the listener.
- Local wake-up routing signals only subscribers for the notified run.
- Duplicate wake-ups do not duplicate emitted SSE frames.
- Listener startup, shutdown, reconnect backoff, and degraded state are
  deterministic with injected connection factories and clocks.
- SSE queue wake-up emits events without waiting for the compensation timeout.
- Compensation polling restores event delivery without a notification.
- Terminal events trigger final catch-up and closure.

### PostgreSQL Integration Tests

Use the real test PostgreSQL database and independent connections:

1. Start an API listener and an SSE generator.
2. From an independent transaction, append an event and register `NOTIFY`.
3. Assert a correctly ordered SSE frame arrives in less than 200 ms.
4. Confirm a rolled-back transaction produces no frame.
5. Simulate listener disconnect, append an event, and verify compensation poll
   delivery within its configured bound.
6. Restore listener and verify notification-driven delivery resumes.
7. Run two listener instances; ensure both receive PostgreSQL notification but
   only instances with local subscribers query and emit events.
8. Verify contiguous events are delivered strictly by sequence with no gaps or
   duplicates across duplicate wake-ups, replay, and reconnect.

### Performance Acceptance

| Scenario | Acceptance criterion |
| --- | --- |
| Healthy local PostgreSQL notification path | P95 commit-to-frame latency below 100 ms in integration environment. |
| Normal active SSE delivery | No dependence on 100 ms polling. |
| Idle active SSE connection | Event/status database reads occur only at the 3 s compensation cadence, plus heartbeat-independent work. |
| 100 idle active SSE connections | Removes the prior approximate 2,000 status/event reads per second. |
| Listener unavailable | Events remain correct and arrive within reconnect time plus compensation-poll bound. |
| Replay and reconnect | Strict sequence order, no duplicates, no omissions. |

## Rollout

1. Deploy with `AGENT_EVENT_LISTEN_NOTIFY_ENABLED=false` and validate that the
   code path preserves existing polling behavior.
2. Enable the listener in one API instance and observe listener state,
   notification-to-frame latency, compensation recovery rate, and reconnects.
3. Enable on all API instances.
4. Keep the 3 s compensation poll permanently as a correctness mechanism.
5. If production behavior regresses, disable the flag and return immediately to
   compensation-poll operation without migrating data or changing browser
   protocol.

## Out of Scope

- Moving the worker into FastAPI/Uvicorn.
- Adding Redis or another external message broker.
- Sending event bodies or answer text through `NOTIFY` payloads.
- Removing the persisted `AgentRunEvent` log or cursor replay.
- Requiring sticky sessions.
- Changing the browser EventSource protocol or frontend reducer semantics.
- Altering Markdown or animation behavior as part of this transport change.
