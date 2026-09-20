# Agent Worker Runtime Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make queued Agent runs execute reliably, surface provider/runtime failures immediately, stream committed execution events to the Session UI, and prevent live attempts from being incorrectly recovered as expired.

**Architecture:** The independent `agent_worker` remains the only executor. Each state transition and emitted event is committed as a short transaction before it is published to the event bus; no database transaction remains open while awaiting DeepSeek, web tools, or streamed chunks. Worker orchestration owns claims, full-lifetime concurrency permits, lease renewal, structured failure finalization, and logs; the Agent loop owns planner/tool/answer domain events but receives a per-attempt event publisher rather than a shared pending-event list.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, PostgreSQL, asyncpg, httpx, Pydantic, pytest, Next.js 16, React 19, TypeScript, Vitest, EventSource.

## Global Constraints

- Do not move the Worker into FastAPI/Uvicorn. The canonical executable remains `python -m app.workers.agent_worker`.
- Do not log `DEEPSEEK_API_KEY`, authorization headers, request bodies, attachment text, system prompts, or raw model responses.
- Preserve immutable attempts and events. A retry creates an attempt; it never deletes prior history.
- Every terminal execution path emits a durable terminal event: `run_succeeded`, `run_failed`, or `run_cancelled`.
- A lease expiry is only for abandoned Worker processes. An exception from a live Worker must become `run_failed` immediately, with a sanitized failure code.
- Do not hold an `AsyncSession` transaction open across any external await: DeepSeek request/stream, Tavily request, HTTP tool request, content extraction, or retry delay.
- The Session UI continues using the Agent Loop source presentation structure. Status synchronization may change data loading, not the right-side layout.
- Tests must prove failure states with fake clients; no test may call DeepSeek or expose real secrets.

---

## Confirmed Runtime Evidence

The actual failure is not an absent key or absent Worker:

```text
DEEPSEEK_API_KEY configured: True
Worker process: python -m app.workers.agent_worker (PID 26352)

Run 5a473d4b... Attempt 1: lease_expired
Run 5a473d4b... Attempt 2: lease_expired
Run 5a473d4b... Attempt 3: lease_expired_no_retry
Only persisted event: run_queued
```

Current causes in `backend/app/services/agent/worker.py` and `backend/app/services/agent/loop.py`:

1. `_process_attempt_with_renewal()` swallows exceptions with `except Exception: pass`.
2. `_renew_lease_until_finished()` swallows renewal errors with `except Exception: pass`.
3. `process_attempt()` keeps one session transaction open from `run_started` through planner, thought stream, tool, answer stream, and terminal transition.
4. `transition_attempt_status()` updates the attempt before external calls, so the long transaction holds a row lock. The renewal transaction blocks on that lock and cannot extend `lease_expires_at`.
5. `_pending_events` is a mutable singleton field on `AgentLoopService`; parallel attempts share and clear the same list.
6. `_claim_and_execute()` releases its semaphore immediately after spawning the execution task; its configured concurrency is not an execution limit.
7. `SessionDetailPage` only loads REST run state on mount/after a user sends a message. It depends on SSE for later state, so a missing terminal event leaves the original `queued` display visible.

## File Map

| File | Responsibility after repair |
|---|---|
| `backend/app/services/agent/worker.py` | Claim loop, full-lifetime concurrency, lease renewal, logs, immediate failure finalization |
| `backend/app/services/agent/loop.py` | Per-attempt domain loop, no shared event buffer, no long transaction across external I/O |
| `backend/app/repositories/agent_repository.py` | Atomic state/event helpers and sanitized failure finalization |
| `backend/app/services/agent/event_bus.py` | Publish already-committed event references only |
| `backend/app/services/agent/llm.py` | Normalize provider exceptions into safe retryable/non-retryable categories |
| `backend/app/core/config.py` | Validate runtime Agent settings without disclosing secrets |
| `backend/app/workers/agent_worker.py` | Worker startup validation and structured startup/error logging |
| `backend/tests/test_agent_worker.py` | Lease, semaphore, exception and recovery tests |
| `backend/tests/test_agent_loop.py` | Per-event commit/publish and terminal event tests |
| `backend/tests/test_agent_stream.py` | Stream replay of failure and terminal events |
| `frontend/src/hooks/use-run-event-stream.ts` | Terminal state refresh fallback when stream ends/retries exhaust |
| `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx` | Refresh current Session state after terminal stream status changes without changing layout |
| `frontend/src/hooks/use-run-event-stream.test.ts` | Failed/closed/reconnect status tests |
| `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx` | Page refresh of final run status after stream terminal transition |
| `README.md` | Separate API/Worker commands, environment prerequisites, diagnostics and key-rotation note |

### Task 1: Make Worker failures observable and terminal immediately

**Files:**
- Modify: `backend/app/services/agent/worker.py`
- Modify: `backend/app/repositories/agent_repository.py`
- Modify: `backend/app/services/agent/loop.py`
- Modify: `backend/tests/test_agent_worker.py`
- Modify: `backend/tests/test_agent_loop.py`

**Interfaces:**

```python
async def AgentRepository.fail_attempt_and_run(
    self,
    attempt_id: UUID,
    worker_id: str,
    failure_code: str,
) -> PersistedEvent | None:
    """Atomically fail the claimed live attempt/run and persist run_failed."""

def classify_agent_failure(exc: BaseException) -> str:
    """Return a stable safe code; never include raw provider content or secrets."""
```

- [ ] **Step 1: Add failing Worker exception test**

```python
async def test_worker_exception_marks_claimed_run_failed_and_persists_event(
    monkeypatch, test_db, queued_run_and_attempt
):
    worker = make_worker(test_db, worker_id="worker-test", concurrency=1)

    async def explode(*_args, **_kwargs):
        raise RuntimeError("provider exploded with secret=should-not-persist")

    monkeypatch.setattr(agent_loop_service, "process_attempt", explode)

    assert await worker._claim_and_execute() is True
    await worker.wait_for_all_tasks()

    async with test_db() as session:
        run = await session.get(AgentRun, queued_run_and_attempt[0].id)
        attempts = await AgentRepository(session).list_attempts(run.id)
        events = await AgentRepository(session).list_events(run.id)

    assert run.status == "failed"
    assert attempts[-1].status == "failed"
    assert attempts[-1].failure_code == "worker_unhandled_error"
    assert events[-1].event_type == "run_failed"
    assert events[-1].payload == {"error": "worker_unhandled_error"}
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_agent_worker.py -k worker_exception_marks_claimed -v`  
Expected: FAIL because `_process_attempt_with_renewal()` catches and discards the exception; the attempt remains `running` until recovery.

- [ ] **Step 3: Add a short-transaction terminal failure repository method**

```python
async def fail_attempt_and_run(self, attempt_id: UUID, worker_id: str, failure_code: str) -> AgentRunEvent | None:
    attempt = await self.session.scalar(
        select(AgentRunAttempt).where(
            AgentRunAttempt.id == attempt_id,
            AgentRunAttempt.worker_id == worker_id,
            AgentRunAttempt.status == "running",
        ).with_for_update()
    )
    if attempt is None:
        return None

    run = await self.session.get(AgentRun, attempt.run_id, with_for_update=True)
    if run is None or run.status in {"succeeded", "failed", "cancelled"}:
        return None

    now = datetime.now(UTC)
    attempt.status = "failed"
    attempt.failure_code = failure_code
    attempt.finished_at = now
    run.status = "failed"
    run.updated_at = now
    event = AgentRunEvent(
        run_id=run.id,
        attempt_id=attempt.id,
        event_type="run_failed",
        payload={"error": failure_code},
    )
    self.session.add(event)
    await self.session.flush()
    return event
```

Commit the worker session, then publish `PersistedEvent(run_id=event.run_id, seq=event.seq)` only after the commit succeeds.

- [ ] **Step 4: Replace silent catch blocks with safe logs and terminal handling**

```python
logger = logging.getLogger("agent_worker")

async def _process_attempt_with_renewal(self, attempt_id: UUID) -> None:
    renewal_task = asyncio.create_task(self._renew_lease_until_finished(attempt_id))
    try:
        await agent_loop_service.process_attempt(attempt_id, self.worker_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.error(
            "agent_attempt_unhandled",
            extra={
                "attempt_id": str(attempt_id),
                "worker_id": self.worker_id,
                "failure_code": "worker_unhandled_error",
                "exception_type": type(exc).__name__,
            },
        )
        await self._mark_unhandled_attempt_failure(attempt_id)
    finally:
        renewal_task.cancel()
        with suppress(asyncio.CancelledError):
            await renewal_task
```

`_mark_unhandled_attempt_failure()` opens its own session, calls `fail_attempt_and_run(attempt_id, worker_id, "worker_unhandled_error")`, commits, then publishes the returned event. It must not include `str(exc)` in a database event, log message, log stack trace, or log `extra` fields.

- [ ] **Step 5: Add failure classification tests**

```python
@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (httpx.TimeoutException("timeout"), "deepseek_timeout"),
        (httpx.HTTPStatusError("unauthorized", request=REQUEST, response=RESPONSE_401), "deepseek_auth_error"),
        (ValueError("invalid json"), "planner_invalid_response"),
        (RuntimeError("any internal exception"), "worker_unhandled_error"),
    ],
)
def test_classify_agent_failure_returns_safe_stable_code(exc, expected):
    assert classify_agent_failure(exc) == expected
```

- [ ] **Step 6: Verify GREEN**

Run: `python -m pytest tests/test_agent_worker.py tests/test_agent_loop.py -k "worker_exception or classify_agent_failure" -v`  
Expected: PASS; no live worker exception turns into `lease_expired`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/agent/worker.py backend/app/repositories/agent_repository.py backend/app/services/agent/loop.py backend/tests/test_agent_worker.py backend/tests/test_agent_loop.py
```

### Task 2: Commit each execution event before external I/O and publish after commit

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Modify: `backend/app/services/agent/event_bus.py`
- Modify: `backend/tests/test_agent_loop.py`
- Modify: `backend/tests/test_agent_stream.py`
- Source reference: `X:\01_agent_loop\backend\app\services\agent_loop.py:41-46,674-862`

**Interfaces:**

```python
class AttemptEventPublisher:
    def __init__(self, attempt_id: UUID, worker_id: str) -> None:
        self.attempt_id = attempt_id
        self.worker_id = worker_id

    async def persist_and_publish(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> AgentRunEvent:
        """Commit one event before notifying stream subscribers."""
```

- [ ] **Step 1: Add failing event visibility test**

```python
async def test_run_started_is_committed_before_planner_waits(monkeypatch, test_db, queued_run_and_attempt):
    planner_entered = asyncio.Event()
    release_planner = asyncio.Event()

    async def delayed_plan(*_args, **_kwargs):
        planner_entered.set()
        await release_planner.wait()
        return {"thought_summary": "完成", "action": {"type": "finish", "input": {}}}

    monkeypatch.setattr(agent_loop_service.planner, "next_action", delayed_plan)
    task = asyncio.create_task(agent_loop_service.process_attempt(queued_run_and_attempt[1].id, "worker-test"))
    await planner_entered.wait()

    async with test_db() as observer:
        events = await AgentRepository(observer).list_events(queued_run_and_attempt[0].id)

    assert [event.event_type for event in events] == ["run_queued", "run_started"]
    release_planner.set()
    await task
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_agent_loop.py -k run_started_is_committed -v`  
Expected: FAIL because `process_attempt()` retains its one transaction while awaiting the planner, so another session sees only `run_queued`.

- [ ] **Step 3: Remove the singleton `_pending_events` buffer**

Delete `self._pending_events` from `AgentLoopService`. It is not safe because one singleton service may process multiple attempts concurrently. Do not replace it with another service-global mutable list.

- [ ] **Step 4: Implement short event/state transactions**

Create a local helper that opens a session per committed transition:

```python
async def _with_attempt_transaction(
    attempt_id: UUID,
    worker_id: str,
    operation: Callable[[AgentRepository, _AttemptContext], Awaitable[AgentRunEvent | None]],
) -> AgentRunEvent | None:
    async with async_session_factory() as session:
        repo = AgentRepository(session)
        attempt = await session.scalar(
            select(AgentRunAttempt).where(
                AgentRunAttempt.id == attempt_id,
                AgentRunAttempt.worker_id == worker_id,
                AgentRunAttempt.status == "running",
            )
        )
        if attempt is None:
            return None
        run = await session.get(AgentRun, attempt.run_id)
        if run is None:
            return None
        event = await operation(repo, _AttemptContext(run=run, attempt=attempt))
        await session.commit()
    if event is not None:
        await agent_event_bus.publish_after_commit(PersistedEvent(run_id=event.run_id, seq=event.seq))
    return event
```

Use it for `run_started`, every `plan_created`, visible-thought stream event, tool event, step completion, retry scheduled, terminal success/failure/cancel event, and answer checkpoints. External calls consume immutable local snapshots and happen outside this helper.

- [ ] **Step 5: Preserve source event order and terminal semantics**

The committed sequence must remain:

```text
run_started
plan_created
visible_thought_started / visible_thought_delta / visible_thought_completed
tool_started / tool_completed              (only for tool actions)
step_completed                             (only after completed tool/final answer)
answer_started / answer_delta / answer_checkpoint / answer_completed
run_succeeded                              (only after final answer)
```

On a non-retryable exception after `run_started`, persist only a safe `run_failed` terminal event. On retryable failures, persist the failed attempt/retry attempt and `run_retry_scheduled` in a single committed transaction.

- [ ] **Step 6: Add stream replay tests**

```python
async def test_failure_event_is_replayable_after_worker_exception(client, failed_owned_run):
    response = await client.get(f"/api/agent/runs/{failed_owned_run.id}/events?after_seq=0")
    events = response.json()["data"]["items"]
    assert events[-1]["event_type"] == "run_failed"
    assert events[-1]["payload"] == {"error": "worker_unhandled_error"}
```

- [ ] **Step 7: Verify GREEN**

Run: `python -m pytest tests/test_agent_loop.py tests/test_agent_stream.py -v`  
Expected: PASS; observers and SSE replay see `run_started` before a blocked planner returns, and every terminal failure has an event.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/agent/loop.py backend/app/services/agent/event_bus.py backend/tests/test_agent_loop.py backend/tests/test_agent_stream.py
```

### Task 3: Make lease renewal and concurrency match live execution

**Files:**
- Modify: `backend/app/services/agent/worker.py`
- Modify: `backend/app/repositories/agent_repository.py`
- Modify: `backend/tests/test_agent_worker.py`

**Interfaces:**

```python
async def AgentWorker._execute_claimed_attempt(self, attempt_id: UUID) -> None:
    """Hold one semaphore permit until process_attempt and lease renewal have both stopped."""

async def AgentWorker._renew_lease_until_finished(self, attempt_id: UUID) -> None:
    """Log renewal failures and exit only after a terminal/missing/non-owned attempt."""
```

- [ ] **Step 1: Add failing concurrency and renewal tests**

```python
async def test_worker_holds_concurrency_permit_until_attempt_finishes(monkeypatch, test_db, two_queued_attempts):
    worker = make_worker(test_db, worker_id="worker-test", concurrency=1)
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def delayed_process(attempt_id, _worker_id):
        first_started.set()
        await release_first.wait()

    monkeypatch.setattr(agent_loop_service, "process_attempt", delayed_process)
    assert await worker._claim_and_execute() is True
    await first_started.wait()
    assert await worker._claim_and_execute() is False
    release_first.set()
    await worker.wait_for_all_tasks()

async def test_renewal_failure_is_logged_and_attempt_is_not_silently_expired(monkeypatch, caplog, worker):
    monkeypatch.setattr(AgentRepository, "renew_lease", AsyncMock(side_effect=RuntimeError("db unavailable")))
    renewal = asyncio.create_task(worker._renew_lease_until_finished(ATTEMPT_ID))
    await wait_until(lambda: "agent_lease_renewal_failed" in caplog.text)
    renewal.cancel()
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_agent_worker.py -k "holds_concurrency or renewal_failure" -v`  
Expected: FAIL because `_claim_and_execute()` releases its permit before the spawned task executes and renewal swallows the database exception.

- [ ] **Step 3: Move semaphore acquisition into the execution task**

```python
async def _claim_and_execute(self) -> bool:
    if self._semaphore.locked():
        return False
    async with self._session_factory() as session:
        attempt = await AgentRepository(session).claim_next_attempt(self.worker_id)
        await session.commit()
    if attempt is None:
        return False
    task = asyncio.create_task(self._execute_claimed_attempt(attempt.id))
    self._tasks.add(task)
    task.add_done_callback(self._tasks.discard)
    return True

async def _execute_claimed_attempt(self, attempt_id: UUID) -> None:
    async with self._semaphore:
        await self._process_attempt_with_renewal(attempt_id)
```

Do not use `Semaphore.locked()` as an atomic reservation. Add a `self._inflight_claims` counter guarded by an `asyncio.Lock`, or acquire the permit before claiming and transfer it to the task in a `try/finally`, so a rapid polling loop cannot claim more attempts than capacity.

- [ ] **Step 4: Make renewal failures observable and bounded**

```python
except asyncio.CancelledError:
    raise
except Exception:
    logger.exception("agent_lease_renewal_failed", extra={"attempt_id": str(attempt_id), "worker_id": self.worker_id})
    return
```

When renewal returns false because the attempt became terminal, return normally. When a renewal database error occurs, log it and immediately invoke `_mark_unhandled_attempt_failure()` rather than allowing a live run to wait for expiry.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/test_agent_worker.py -v`  
Expected: PASS; live execution holds capacity, renewal errors are visible, and live exceptions do not become lease expiry records.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/worker.py backend/app/repositories/agent_repository.py backend/tests/test_agent_worker.py
```

### Task 4: Classify DeepSeek failures and validate Worker startup

**Files:**
- Modify: `backend/app/services/agent/llm.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/workers/agent_worker.py`
- Modify: `backend/tests/test_agent_loop.py`
- Create: `backend/tests/test_agent_worker_startup.py`
- Modify: `backend/.env.example`

**Interfaces:**

```python
class ProviderConfigurationError(Exception): pass
class ProviderAuthenticationError(Exception): pass
class ProviderResponseError(Exception): pass

def validate_agent_worker_settings(settings: Settings) -> None:
    """Reject missing/placeholder DeepSeek configuration before the polling loop starts."""
```

- [ ] **Step 1: Add failing startup validation tests**

```python
def test_worker_rejects_missing_deepseek_key():
    settings = Settings.model_construct(deepseek_api_key=None, deepseek_base_url="https://api.deepseek.com", deepseek_model="deepseek-chat")
    with pytest.raises(ProviderConfigurationError, match="DEEPSEEK_API_KEY"):
        validate_agent_worker_settings(settings)

def test_worker_rejects_example_deepseek_key():
    settings = Settings.model_construct(deepseek_api_key="sk-your-deepseek-api-key", deepseek_base_url="https://api.deepseek.com", deepseek_model="deepseek-chat")
    with pytest.raises(ProviderConfigurationError, match="DEEPSEEK_API_KEY"):
        validate_agent_worker_settings(settings)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_agent_worker_startup.py -v`  
Expected: FAIL because Worker starts and later fails silently for missing or placeholder credentials.

- [ ] **Step 3: Normalize provider errors without persisting secrets**

```python
if response.status_code in {401, 403}:
    raise ProviderAuthenticationError("deepseek_auth_error")
if response.status_code in {400, 404, 422}:
    raise ProviderResponseError("deepseek_request_rejected")
if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
    raise RetryablePlannerError(f"deepseek_retryable_status:{response.status_code}")
```

Use the same classification for stream setup. Do not call `response.text`, include it in exceptions, or log request headers.

- [ ] **Step 4: Validate startup before entering `worker.run()`**

```python
async def main() -> None:
    settings = get_settings()
    validate_agent_worker_settings(settings)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    logger.info("agent_worker_started", extra={"worker_id": worker_id, "model": settings.deepseek_model})
    await AgentWorker(worker_id=worker_id, concurrency=settings.worker_concurrency).run()
```

The startup log may include worker ID, model, concurrency, poll interval and base URL hostname. It must not include key text.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/test_agent_worker_startup.py tests/test_agent_loop.py -k "provider or startup" -v`  
Expected: PASS; invalid credentials fail clearly at startup and 401 provider errors become `deepseek_auth_error` terminal records.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/llm.py backend/app/core/config.py backend/app/workers/agent_worker.py backend/tests/test_agent_loop.py backend/tests/test_agent_worker_startup.py backend/.env.example
```

### Task 5: Synchronize terminal Worker state to the Session UI

**Files:**
- Modify: `frontend/src/hooks/use-run-event-stream.ts`
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`
- Modify: `frontend/src/hooks/use-run-event-stream.test.ts`
- Create: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx`

**Interfaces:**

```ts
type UseRunEventStreamOptions = {
  runId: string;
  initialEvents: AgentRunEvent[];
  initialRun: AgentRun | null;
  onTerminalState?: (run: AgentRun) => void;
};
```

- [ ] **Step 1: Write failing frontend terminal sync tests**

```tsx
it("calls onTerminalState after a replayed run_failed event", async () => {
  const onTerminalState = vi.fn();
  renderHook(() => useRunEventStream({ runId: "run-1", initialEvents: [], initialRun: runningRun, onTerminalState }));
  emitEventSourceEvent("run_failed", failedEvent);
  await waitFor(() => expect(onTerminalState).toHaveBeenCalledWith(expect.objectContaining({ status: "failed" })));
});

it("reloads session data after the latest active run becomes terminal", async () => {
  render(<SessionDetailPage />);
  emitEventSourceEvent("run_failed", failedEvent);
  await waitFor(() => expect(agentApi.getSessionRuns).toHaveBeenCalledTimes(2));
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm test -- --run src/hooks/use-run-event-stream.test.ts "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx"`  
Expected: FAIL because the hook updates only local state and the page never re-fetches run status after mount.

- [ ] **Step 3: Add one terminal callback to the existing hook**

After `reduceRunStream()` produces a terminal run status, call `onTerminalState` exactly once for each run ID/status pair. Do not add polling or change the Agent Loop layout.

```ts
if (nextState.run && isTerminalAgentRunStatus(nextState.run.status)) {
  options.onTerminalState?.(nextState.run);
}
```

Use a ref containing the last notified `${runId}:${status}` to avoid duplicate reloads from replay/reconnect.

- [ ] **Step 4: Refresh only the owning Session after terminal state**

Pass an `onTerminalState` callback from the Session conversation turn to `SessionDetailPage`. It calls the existing `loadSession()` once after `succeeded`, `failed`, or `cancelled`. The callback must not alter source Agent Loop DOM structure or add a status dashboard.

- [ ] **Step 5: Verify GREEN**

Run: `npm test -- --run src/hooks/use-run-event-stream.test.ts "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx"; npm run build`  
Expected: PASS; UI changes from queued/running to failed/succeeded without a browser refresh, while preserving the copied Agent Loop right-side layout.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/use-run-event-stream.ts frontend/src/hooks/use-run-event-stream.test.ts "frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx" "frontend/src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx"
```

### Task 6: Operational diagnostics, secure key rotation, and final verification

**Files:**
- Modify: `README.md`
- Modify: `backend/.env.example`
- Create: `backend/scripts/agent_worker_health.py`
- Create: `backend/tests/test_agent_worker_health.py`

**Interfaces:**

```text
python -m app.workers.agent_worker
python backend/scripts/agent_worker_health.py
```

- [ ] **Step 1: Write failing health diagnostic tests**

```python
def test_worker_health_reports_counts_without_secrets(monkeypatch, capsys):
    monkeypatch.setattr(health, "load_counts", lambda: {"queued": 2, "running": 1, "expired": 0})
    health.main()
    output = capsys.readouterr().out
    assert "queued=2" in output
    assert "running=1" in output
    assert "sk-" not in output
```

- [ ] **Step 2: Run test and verify RED**

Run: `python -m pytest tests/test_agent_worker_health.py -v`  
Expected: FAIL because no worker-health command exists.

- [ ] **Step 3: Implement read-only operational health command**

It reports only:

```text
worker_configured=true|false
queued_attempts=N
running_attempts=N
expired_leases=N
failed_attempts_last_hour=N
```

It validates provider key presence only as a boolean, never prints it. It uses a short async database session and returns exit code 1 when configuration is invalid or expired leases exist.

- [ ] **Step 4: Update operator documentation**

Add a dedicated Agent troubleshooting section:

```text
1. Rotate any DeepSeek key exposed in an editor, screenshot, terminal, issue, or chat.
2. Put the replacement only in backend/.env as DEEPSEEK_API_KEY.
3. Restart agent_worker after changing backend/.env; Uvicorn restart is insufficient.
4. Start API and Worker separately.
5. Run the worker health command before creating a new run.
6. Inspect structured Worker logs by attempt ID; do not use database lease expiration as a normal failure signal.
```

- [ ] **Step 5: Run final verification**

Run from `backend`:

```powershell
alembic upgrade head
python -m pytest -q
python scripts/agent_worker_health.py
```

Run from `frontend`:

```powershell
npm test -- --run
npm run build
```

Expected: all tests pass; Worker health returns zero expired leases; build exits 0.

- [ ] **Step 6: Commit**

```bash
git add README.md backend/.env.example backend/scripts/agent_worker_health.py backend/tests/test_agent_worker_health.py
```

## Plan Self-Review

| Required repair | Covered task |
|---|---|
| Reveal actual Worker exceptions | Task 1 |
| Mark exception attempts failed immediately with a durable event | Task 1 |
| Avoid transaction/row lock blocking lease renewal | Task 2 |
| Commit and publish live events before/after external calls | Task 2 |
| Remove shared `_pending_events` race | Task 2 |
| Hold Worker concurrency permit through execution | Task 3 |
| Make renewal failures visible and terminal | Task 3 |
| Validate key configuration and classify provider errors | Task 4 |
| Refresh stale Session UI after terminal SSE state | Task 5 |
| Provide secure operations/health diagnostics | Task 6 |

No feature layout changes are planned. The Session right-side content remains the directly copied Agent Loop structure. No placeholder items remain; all state transitions, method signatures, test assertions, commands, and files are explicit.
