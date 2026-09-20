# Run Terminal Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure final answers, run state, attempt state, terminal events, and historical UI status remain consistent so completed conversations never show as thinking.

**Architecture:** Make terminal answer persistence atomic; isolate historical turns from SSE; derive non-live display state from safe terminal evidence; add idempotent repair for legacy interrupted runs.

**Tech Stack:** Python 3.12/FastAPI/SQLAlchemy/PostgreSQL, React 19/TypeScript/Vitest.

## Global Constraints

- Do not infer successful completion for a live running turn without canonical server confirmation.
- Successful completion transaction must contain result, attempt status, run status, terminal event, and terminal answer artifacts.
- Guarded terminal transition failure must append no terminal event and persist no final result.
- Historical turns never create EventSource.
- Repair command defaults to dry-run and never logs answer text.
- Commit after each task.

---

### Task 1: Atomic Successful Completion

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Modify: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Produces: terminal completion transaction that stores `answer_completed`, `step_completed`, `run_succeeded`, succeeded attempt/run states, and `run.result.final_answer` together.

- [ ] **Step 1: Write failing atomicity tests**

Add tests to `backend/tests/test_agent_loop.py`:

```python
@pytest.mark.anyio
async def test_success_terminal_persistence_sets_result_and_terminal_statuses_atomically():
    # Build a running run/attempt and invoke the successful terminal helper.
    # Assert persisted run.status and attempt.status are succeeded, result has
    # final_answer, and both answer_completed/run_succeeded events exist.
    ...

@pytest.mark.anyio
async def test_failed_terminal_guard_does_not_write_result_or_run_succeeded(monkeypatch):
    # Force mark_run_succeeded or attempt transition to return False.
    # Assert terminal helper raises and no result/run_succeeded is persisted.
    ...
```

- [ ] **Step 2: Verify RED**

Run: `cd backend; python -m pytest tests/test_agent_loop.py -k "atomic or terminal_guard" -v`
Expected: FAIL because answer completion is currently separate from terminal state and guard results are ignored.

- [ ] **Step 3: Implement atomic transaction**

Refactor the successful `finish` branch so it does not commit `answer_completed` independently before terminal persistence. Add a helper that in one `event_session` transaction:

```python
await event_repo.append_event(run, attempt, "answer_completed", {"stream_id": stream_id, "text": answer})
await event_repo.add_step(..., observation={"final_answer": answer}, status="success")
attempt_updated = await event_repo.transition_attempt_status(attempt, {"running"}, "succeeded", finished_at=now)
run_updated = await event_repo.mark_run_succeeded(run)
if not attempt_updated or not run_updated:
    raise AgentTerminalStateConflict()
run.result = {"final_answer": answer, "answer_format": "markdown", "completed_at": ..., "source_event_sequence": event.seq}
await event_repo.append_event(run, attempt, "run_succeeded", {"final_answer": answer})
await event_session.commit()
```

Publish the committed terminal event after commit. Store `event.seq`, not `inspect(event).identity[0]`, in `source_event_sequence`.

- [ ] **Step 4: Verify GREEN**

Run: `cd backend; python -m pytest tests/test_agent_loop.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
```

---

### Task 2: Historical Stream Isolation And Display State

**Files:**
- Modify: `frontend/src/components/agent/session-conversation-stream.tsx`
- Modify: `frontend/src/components/agent/detail-conversation.tsx`
- Modify: `frontend/src/hooks/use-run-event-stream.ts`
- Modify: `frontend/src/lib/run-stream-reducer.ts`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`
- Modify: `frontend/src/hooks/use-run-event-stream.test.ts`

**Interfaces:**
- Produces: `shouldOpenRunStream(run, isLatestTurn, hasTerminalEvidence): boolean`
- Produces: display-state derivation where non-live `answer_completed` history is completed/static.

- [ ] **Step 1: Write failing frontend tests**

```tsx
test("historical answer_completed turn is static completed and opens no EventSource", () => {
  // Historical run raw status running, events include answer_completed text.
  // Render conversation with a newer turn.
  // Expect no thinking label/timer and EventSource instances length 0 for it.
});

test("only latest running turn opens one EventSource", () => {
  // Two running snapshot turns; only latest has live stream enabled.
  // Expect one EventSource.
});

test("live answer_completed remains active until authoritative terminal state", () => {
  // Live run gets answer_completed alone.
  // Expect active status and reconciliation behavior, not immediate success.
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx src/hooks/use-run-event-stream.test.ts`
Expected: FAIL because historical turns are currently routed through the stream hook and `answer_completed` preserves raw running status.

- [ ] **Step 3: Implement stream isolation**

Add:

```ts
export function hasTerminalEvidence(events: AgentRunEvent[]): boolean {
  return events.some((event) => ["run_succeeded", "run_completed", "run_failed", "run_cancelled", "answer_completed"].includes(event.event_type));
}

export function shouldOpenRunStream(run: AgentRun, isLatestTurn: boolean, terminalEvidence: boolean): boolean {
  return isLatestTurn && run.status === "running" && !terminalEvidence;
}
```

Use the rule in `SessionConversationStream` before invoking/enabling `useRunEventStream`. For non-live turns, render a static reduced state initialized from historical events. Do not create EventSource or reconnect timers.

For non-live turn display only, derive `succeeded` when an `answer_completed` event has text or a `run_succeeded` event has final_answer. Keep the underlying raw status unchanged for audit diagnostics. For a live turn, retain current behavior until terminal reconciliation.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx src/hooks/use-run-event-stream.test.ts src/lib/run-stream-reducer.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent/session-conversation-stream.tsx frontend/src/components/agent/detail-conversation.tsx frontend/src/hooks/use-run-event-stream.ts frontend/src/lib/run-stream-reducer.ts frontend/src/components/agent/agent-streaming.test.tsx frontend/src/hooks/use-run-event-stream.test.ts
```

---

### Task 3: API Evidence And Result Sequence Repair

**Files:**
- Modify: `backend/app/api/agent.py`
- Modify: `backend/app/schemas/agent.py`
- Modify: `backend/tests/test_agent_api.py`
- Modify: `backend/app/services/agent/loop.py` if source event sequence remains UUID-based

- [ ] **Step 1: Write failing API evidence test**

```python
async def test_run_response_labels_answer_completed_projection_as_terminal_evidence(client, ...):
    # running raw run + answer_completed text event
    # GET run response retains running status and returns terminal_evidence="answer_completed_event"
    ...
```

- [ ] **Step 2: Verify RED**

Run: `cd backend; python -m pytest tests/test_agent_api.py -k terminal_evidence -v`
Expected: FAIL because response has no terminal evidence field.

- [ ] **Step 3: Implement safe evidence field**

Add optional response field:

```python
terminal_evidence: Literal["persisted_terminal", "run_succeeded_event", "answer_completed_event", "none"]
```

Rules:

- terminal raw status -> `persisted_terminal`
- run_succeeded event -> `run_succeeded_event`
- answer_completed text -> `answer_completed_event`
- otherwise -> `none`

Keep raw status unchanged. Ensure `source_event_sequence` writes event `seq` integer in terminal persistence.

- [ ] **Step 4: Verify GREEN**

Run: `cd backend; python -m pytest tests/test_agent_api.py -k "terminal_evidence or result" -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/agent.py backend/app/schemas/agent.py backend/tests/test_agent_api.py backend/app/services/agent/loop.py
```

---

### Task 4: Worker Recovery Events And Legacy Repair Script

**Files:**
- Modify: `backend/app/repositories/agent_repository.py`
- Modify: `backend/app/services/agent/worker.py`
- Create: `backend/scripts/reconcile_completed_agent_runs.py`
- Create: `backend/tests/test_reconcile_completed_agent_runs.py`
- Modify: `backend/tests/test_agent_worker.py`

**Interfaces:**
- Produces: `AgentRepository.reconcile_completed_answer_run(run_id) -> bool`
- Produces script CLI: `python scripts/reconcile_completed_agent_runs.py [--apply]`

- [ ] **Step 1: Write failing repair tests**

```python
async def test_reconciles_expired_running_attempt_with_completed_answer(test_db):
    # running run/attempt with expired lease, answer_completed(text), no run_succeeded
    # invoke reconciliation
    # assert succeeded run/attempt/result/run_succeeded event

async def test_reconciliation_is_idempotent(test_db):
    # invoke twice; only one run_succeeded event exists
```

- [ ] **Step 2: Verify RED**

Run: `cd backend; python -m pytest tests/test_reconcile_completed_agent_runs.py -v`
Expected: FAIL because repository method/script does not exist.

- [ ] **Step 3: Implement repository reconciliation**

Eligibility:

```text
run.status in running/queued/retry_wait
current attempt exists and lease expired or unowned
answer_completed event with non-empty text exists
run_succeeded event does not exist
```

In one transaction:

```text
transition attempt -> succeeded
run -> succeeded
run.result = final answer + source event seq
append run_succeeded
commit
post-commit publish
```

The repository method returns false for non-eligible rows and never logs answer text.

- [ ] **Step 4: Implement dry-run script**

`reconcile_completed_agent_runs.py`:

```text
no flags -> enumerate eligible run IDs and print count only
--apply -> reconcile each eligible ID in its own transaction
print run_id, old status, source sequence, action; never answer text
```

- [ ] **Step 5: Verify GREEN**

Run: `cd backend; python -m pytest tests/test_reconcile_completed_agent_runs.py tests/test_agent_worker.py -q`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/repositories/agent_repository.py backend/app/services/agent/worker.py backend/scripts/reconcile_completed_agent_runs.py backend/tests/test_reconcile_completed_agent_runs.py backend/tests/test_agent_worker.py
```

---

### Task 5: Full Regression Verification

- [ ] **Step 1: Backend**

Run: `cd backend; python -m pytest tests/test_agent_loop.py tests/test_agent_stream.py tests/test_agent_api.py tests/test_agent_worker.py tests/test_reconcile_completed_agent_runs.py -q`
Expected: all pass.

- [ ] **Step 2: Frontend**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx src/hooks/use-run-event-stream.test.ts src/lib/run-stream-reducer.test.ts`
Expected: all pass.

- [ ] **Step 3: Build**

Run: `cd frontend; npm run build`
Expected: TypeScript clean and production build succeeds.

- [ ] **Step 4: Validate repair command dry-run**

Run: `cd backend; python scripts/reconcile_completed_agent_runs.py`
Expected: exits 0, performs no writes, prints only safe counts/IDs.

- [ ] **Step 5: Commit if clean**

Run: `git diff --check; git status --short`
