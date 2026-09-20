# Realtime SSE And Tavily Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver persisted Agent events to connected browsers within 250ms across separate Worker and API processes, make frontend development start directly in hot-reload mode, and configure the existing Tavily search provider.

**Architecture:** The existing EventSource protocol and persisted `AgentRunEvent` records remain unchanged. The API SSE generator will poll the persisted event table at 250ms intervals while the run is active, using the event bus only as an early wake-up optimization. The final answer reducer and 20ms-per-character typing animation remain unchanged. Tavily is configured only through the ignored backend environment file.

**Tech Stack:** FastAPI `StreamingResponse`, SQLAlchemy async, asyncio, Next.js 16, React 19, Vitest, pytest, httpx.

## Global Constraints

- Retain the existing EventSource URL, event schema, ownership check, origin validation, and replay behavior.
- Persisted SSE events must be emitted once in ascending `seq` order.
- Poll the database every `0.25` seconds while a run is active; keep `15` seconds only as the idle keepalive interval.
- Preserve `FinalAnswerPanel` and the current `20ms` per-character typing animation.
- Set the Tavily key only in ignored `backend/.env`; never add, print, assert, or commit it.
- Keep existing Tavily validation, bounded results, sanitization, and error handling.

---

### Task 1: Poll Persisted Events During Active SSE Runs

**Files:**
- Modify: `backend/app/api/agent_stream.py:27-29, 131-236`
- Modify: `backend/tests/test_agent_stream.py:293-309`

**Interfaces:**
- Consumes: `AgentRunEvent.run_id`, `AgentRunEvent.seq`, `agent_event_bus.subscribe(run_id) -> tuple[str, asyncio.Queue[PersistedEvent]]`.
- Produces: `_stream_persisted_run_events(run_id, after_seq)` async generator and `GET /api/agent/runs/{run_id}/stream` emit newly committed events without requiring an in-process bus publication, within `SSE_POLL_INTERVAL`.

- [ ] **Step 1: Write the failing stream-polling regression test**

Add an async unit test to `backend/tests/test_agent_stream.py` after `test_event_bus_broadcasts_same_event_to_all_subscribers`. It must call the extracted `_stream_persisted_run_events(run_id, after_seq)` generator directly, use `monkeypatch.setattr(asm, "SSE_POLL_INTERVAL", 0.01)`, persist an `answer_delta` event after the generator is subscribed, and assert that the next yielded SSE frame contains both `event: answer_delta` and its persisted `seq`. Wrap retrieving that frame with `asyncio.wait_for(..., timeout=0.2)`.


- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_agent_stream.py::TestAgentStream::test_sse_polls_persisted_events_when_worker_bus_is_a_different_process -q`

Expected: FAIL with an import error because `_stream_persisted_run_events` does not yet exist.

- [ ] **Step 3: Add a bounded active-run database poll interval**

In `backend/app/api/agent_stream.py`, add this constant directly below `CATCH_UP_LIMIT`:

```python
SSE_POLL_INTERVAL = 0.25
```

Extract the current body of `event_generator()` into `_stream_persisted_run_events(run_id: uuid.UUID, after_seq: int | None)`. The route-level generator delegates to it after authorization. Replace the active-run `queue.get()` wait with this short wait, retaining the following database query:

```python
                try:
                    await asyncio.wait_for(queue.get(), timeout=SSE_POLL_INTERVAL)
                except asyncio.TimeoutError:
                    pass
```

Before that wait, emit a keepalive only after 15 seconds without a sent event. Track `last_sent_at = asyncio.get_running_loop().time()` immediately before the loop. Set it after every yielded persisted event. Then add:

```python
                if asyncio.get_running_loop().time() - last_sent_at >= HEARTBEAT_INTERVAL:
                    yield ":keepalive\n\n"
                    last_sent_at = asyncio.get_running_loop().time()
```

This preserves keepalives while database polling detects Worker-written events in the next 250ms window.

- [ ] **Step 4: Run the focused stream test to verify it passes**

Run: `python -m pytest tests/test_agent_stream.py::TestAgentStream::test_sse_polls_persisted_events_when_worker_bus_is_a_different_process -q`

Expected: PASS.

- [ ] **Step 5: Run the complete stream suite**

Run: `python -m pytest tests/test_agent_stream.py -q`

Expected: PASS, including ordering, replay, authorization, terminal catch-up, and header checks.

- [ ] **Step 6: Commit the isolated SSE change**

```powershell
git add backend/app/api/agent_stream.py backend/tests/test_agent_stream.py
git commit -m "fix: poll persisted events for live SSE"
```

### Task 2: Restore Direct Hot-Reload Development Startup

**Files:**
- Modify: `frontend/package.json:5-12`
- Modify: `frontend/src/package-scripts.test.ts:5-15`
- Modify: `frontend/README.md:10-18, 95-101`

**Interfaces:**
- Consumes: Next command `next dev --webpack --no-server-fast-refresh` and existing `next build`, `next start` commands.
- Produces: `npm run dev` starts Next development mode directly; `npm run preview` is the explicit production build-and-start command.

- [ ] **Step 1: Write the failing package-script contract test**

Replace the assertions in `frontend/src/package-scripts.test.ts` with:

```typescript
    expect(packageJson.scripts.dev).toBe("next dev --webpack --no-server-fast-refresh");
    expect(packageJson.scripts.preview).toBe("npm run build && next start");
    expect(packageJson.scripts["dev:hot"]).toBeUndefined();
```

Rename the test to `uses direct hot reload for development and an explicit production preview`.

- [ ] **Step 2: Run the contract test to verify it fails**

Run: `npm test -- --run src/package-scripts.test.ts`

Expected: FAIL because `dev` currently builds before starting and `preview` is absent.

- [ ] **Step 3: Implement the package-script contract and document the preview command**

Set the `scripts` block entries in `frontend/package.json` to:

```json
"dev": "next dev --webpack --no-server-fast-refresh",
"preview": "npm run build && next start",
"build": "next build",
"start": "next start"
```

Remove `dev:hot`. In `frontend/README.md`, keep `npm run dev` under Quick Start and add this production-preview section after Build:

```markdown
## Production Preview

```powershell
npm run preview
```
```

- [ ] **Step 4: Run the contract test to verify it passes**

Run: `npm test -- --run src/package-scripts.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit the isolated startup change**

```powershell
git add frontend/package.json frontend/src/package-scripts.test.ts frontend/README.md
git commit -m "chore: restore direct frontend development startup"
```

### Task 3: Configure Existing Tavily Search And Verify It Safely

**Files:**
- Modify: `backend/.env` (ignored, never stage)
- Test: `backend/tests/test_agent_tools.py:223-268`

**Interfaces:**
- Consumes: `Settings.tavily_api_key`, `ToolExecutor.execute({"type": "web_search", "input": {"query": str, "max_results": int}})`.
- Produces: the existing `web_search` action uses Tavily when network mode is enabled and `TAVILY_API_KEY` is set.

- [ ] **Step 1: Strengthen the existing mocked Tavily contract test**

In `test_web_search_returns_bounded_safe_results`, define a capture list immediately before `FakeClient` and record the created client:

```python
    created_clients = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.request_body = None
            self.request_headers = None
            created_clients.append(self)
```

Add this assertion after the existing result assertions:

```python
    assert created_clients[0].request_headers == {"Authorization": "Bearer super-secret"}
```

- [ ] **Step 2: Run the focused authenticated-search tests**

Run: `python -m pytest tests/test_agent_tools.py::test_web_search_returns_bounded_safe_results -q`

Expected: PASS because the existing implementation already sends Tavily authorization; this documents and protects established behavior without modifying production code.

- [ ] **Step 3: Verify the existing implementation satisfies the authenticated-search contract**

No production code change is expected: `ToolExecutor._web_search` already sends `Authorization: Bearer {settings.tavily_api_key}`, bounds results, and sanitizes returned URLs and content. Run the focused test after correcting its fake-client capture.

Run: `python -m pytest tests/test_agent_tools.py::test_web_search_returns_bounded_safe_results tests/test_agent_tools.py::test_web_search_reports_missing_key_without_secret -q`

Expected: PASS.

- [ ] **Step 4: Configure the user-provided key locally without exposing it**

This is an explicit user-approved configuration exception to test-first development. Append this line to the ignored `backend/.env` using the supplied value, without printing the file or staging it:

```text
TAVILY_API_KEY=<supplied user secret>
```

Restart the backend API and Agent Worker so their cached settings read the configured environment. Do not include this value in command output, source files, tests, commits, or completion messages.

- [ ] **Step 5: Run the tool test module**

Run: `python -m pytest tests/test_agent_tools.py -q`

Expected: PASS.

- [ ] **Step 6: Commit only the test change, if one was needed**

```powershell
git add backend/tests/test_agent_tools.py
git commit -m "test: verify Tavily search authorization"
```

Do not stage `backend/.env`.

### Task 4: End-To-End Regression Verification

**Files:**
- Verify only: `backend/app/api/agent_stream.py`
- Verify only: `frontend/src/hooks/use-run-event-stream.ts`
- Verify only: `frontend/src/components/agent/final-answer-panel.tsx`

**Interfaces:**
- Consumes: current SSE endpoint, browser EventSource hook, `answer_delta` reducer behavior, and `useTypingText` default `20ms` speed.
- Produces: evidence that real-time events stream, the final answer animates at the retained rate, startup scripts have the intended behavior, and backend search tests pass.

- [ ] **Step 1: Run all backend Agent tests**

Run: `python -m pytest tests/test_agent_api.py tests/test_agent_stream.py tests/test_agent_loop.py tests/test_agent_tools.py tests/test_agent_worker.py -q`

Expected: PASS.

- [ ] **Step 2: Run all frontend tests and production build**

Run: `npm test -- --run`

Expected: PASS.

Run: `npm run build`

Expected: successful Next production build.

- [ ] **Step 3: Manually verify an active run in the browser**

Start API, Worker, and `npm run dev`. Create a new Agent run with network enabled. In browser DevTools Network, verify `GET /api/agent/runs/{id}/stream` remains open and receives `answer_delta` frames before terminal events. Confirm the answer text visibly appears incrementally with the existing typing animation. Submit a research request and confirm a `web_search` tool event completes without `tavily_api_key_not_configured`.

- [ ] **Step 4: Review the worktree and commit verification artifacts only when changed**

Run: `git status --short` and `git diff --check`.

Do not stage generated files, local `.env` files, or unrelated user changes. If no tracked verification artifacts changed, leave the worktree clean and do not create an empty commit.
