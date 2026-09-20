# Smooth Live Markdown And Static History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make only `running` Agent Runs stream character-level Markdown smoothly, render every historical or terminal answer immediately, and remove terminal full-page reload interruptions.

**Architecture:** The reducer remains the source of transport truth (`targetText`, sequence, stream generation, status, final result). A requestAnimationFrame scheduler owns visual `displayedText`, and only strict `running` status enables it. The backend SSE endpoint delivers in-process notifications immediately while retaining a 100 ms persisted-event compensation poll for Worker/API cross-process delivery.

**Tech Stack:** FastAPI, SQLAlchemy async, asyncio, Next.js 16, React 19, TypeScript, `react-markdown`, `remark-gfm`, Vitest, pytest.

## Global Constraints

- Implementation target is `C:\01_agent_loop`; `X:\01_agent_loop` is reference-only.
- Preserve character-level Markdown animation for all Runs whose normalized status is exactly `running`.
- Every non-running Run (`succeeded`, legacy `completed`, `failed`, `cancelled`, `queued`, `retry_wait`, `cancel_requested`, and unknown statuses) renders complete recovered text immediately.
- Do not change authentication, RBAC, provider/model selection, prompts, tool execution, sidebar/session-list layout, or raw HTML policy.
- Raw Markdown HTML remains disabled. Never add `rehype-raw`.
- Retain `X-Accel-Buffering: no`, ownership/origin checks, replay cursor semantics, and ordered event delivery.
- Active cross-process SSE compensation polling is exactly `100` ms; heartbeats remain no slower than 15 seconds.
- `displayedText` must remain a monotonic prefix of `targetText`; terminal text reaches full visibility within `250` ms.
- `C:\01_agent_loop` has no `.git`; do not attempt Git commits. Record changed files and command output in task reports.

---

### Task 1: Make SSE Notifications Immediate With Persisted-Event Compensation

**Files:**
- Modify: `C:\01_agent_loop\backend\app\api\agent_stream.py:27-259`
- Modify: `C:\01_agent_loop\backend\tests\test_agent_stream.py`

**Interfaces:**
- Consumes: `agent_event_bus.subscribe(run_id) -> tuple[str, asyncio.Queue[PersistedEvent]]`, persisted `AgentRunEvent.seq`.
- Produces: `_stream_persisted_run_events(run_id: UUID, after_seq: int | None)` delivers each event once in ascending sequence, wakes immediately for queue notifications, and polls persisted data every `0.1` seconds for cross-process events.

- [ ] **Step 1: Write failing immediate-notification tests**

Add a test that subscribes to a running stream, publishes a `PersistedEvent` through `agent_event_bus`, persists the corresponding `answer_delta`, and asserts the next emitted SSE frame is available before the configured `SSE_POLL_INTERVAL`.

```python
@pytest.mark.anyio
async def test_sse_delivers_event_bus_notification_without_waiting_for_poll(
    stream_db, ordinary_user, monkeypatch
):
    import app.api.agent_stream as asm

    monkeypatch.setattr(asm, "SSE_POLL_INTERVAL", 1.0)
    run_id = await create_running_run(stream_db, ordinary_user)
    stream = asm._stream_persisted_run_events(run_id, None)
    await anext(stream)  # Subscribe after any initial replay.
    event = await persist_answer_delta(stream_db, run_id, seq=2, delta="即时")
    await agent_event_bus.publish_after_commit(PersistedEvent(run_id=run_id, seq=event.seq))

    frame = await asyncio.wait_for(anext(stream), timeout=0.2)
    assert "event: answer_delta" in frame
    assert f"id: {event.seq}" in frame
```

Add a second test that has no queue publication, persists an event from the simulated Worker path, sets `SSE_POLL_INTERVAL = 0.01`, and asserts it arrives within 0.2 seconds. Add a third test that publishes two queue wake-ups for the same persisted event and asserts one event ID is emitted.

- [ ] **Step 2: Run the new tests and verify RED**

Run from `C:\01_agent_loop\backend`:

```powershell
python -m pytest tests/test_agent_stream.py -k "without_waiting_for_poll or cross_process or duplicate" -q
```

Expected: the immediate-notification test fails because current code drains the queue and waits for a later persisted-event poll; compensation and duplicate tests may already pass.

- [ ] **Step 3: Extract one persisted-event fetch helper**

In `backend/app/api/agent_stream.py`, add a helper with this contract before `_stream_persisted_run_events`:

```python
async def _events_after(run_id: uuid.UUID, last_seen_seq: int | None) -> list[AgentRunEvent]:
    async with async_session_factory() as session:
        result = await session.execute(
            sa_select(AgentRunEvent)
            .where(
                AgentRunEvent.run_id == run_id,
                AgentRunEvent.seq > last_seen_seq if last_seen_seq is not None else True,
            )
            .order_by(AgentRunEvent.seq.asc())
            .limit(CATCH_UP_LIMIT)
        )
        return list(result.scalars().all())
```

Add `SSE_POLL_INTERVAL = 0.1` below `CATCH_UP_LIMIT`.

- [ ] **Step 4: Implement one ordered emit path for replay, notifications, poll, and terminal catch-up**

Inside `_stream_persisted_run_events`, replace repeated query/yield blocks with a nested async generator that calls `_events_after`, encodes events, and updates `last_seen_seq` only after yielding:

```python
async def emit_persisted_events():
    nonlocal last_seen_seq, last_sent_at
    for event in await _events_after(run_id, last_seen_seq):
        if last_seen_seq is not None and event.seq <= last_seen_seq:
            continue
        encoded = _encode_sse_event(event)
        if encoded is None:
            continue
        last_seen_seq = event.seq
        last_sent_at = asyncio.get_running_loop().time()
        yield encoded
```

Use it for initial replay, post-subscribe race catch-up, every queue wake-up, every `SSE_POLL_INTERVAL` timeout, and final terminal catch-up. Do not call `queue.get_nowait()` to discard notification records. A notification only wakes the loop; persisted events remain the authoritative payload.

Use this active-run wait:

```python
try:
    await asyncio.wait_for(queue.get(), timeout=SSE_POLL_INTERVAL)
except asyncio.TimeoutError:
    pass
async for frame in emit_persisted_events():
    yield frame
```

Keep the 15-second keepalive only when `last_sent_at` is stale.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_agent_stream.py -k "without_waiting_for_poll or cross_process or duplicate or replay or final_catch_up" -q
```

Expected: all selected tests pass, including existing replay and terminal catch-up tests.

- [ ] **Step 6: Run the complete stream suite**

Run:

```powershell
python -m pytest tests/test_agent_stream.py -q
```

Expected: all stream tests pass.

- [ ] **Step 7: Record verification instead of committing**

Write the changed files, RED/GREEN output, and stream ordering evidence to `C:\01_agent_loop\.superpowers\sdd\smooth-streaming-task-1-report.md`. Do not run Git commands.

### Task 2: Define Strict Active Status And Preserve Historical Answers

**Files:**
- Modify: `C:\01_agent_loop\frontend\src\components\agent\final-answer-panel.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\agent-streaming.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\lib\run-stream-reducer.ts`
- Modify: `C:\01_agent_loop\frontend\src\lib\run-stream-reducer.test.ts`

**Interfaces:**
- Consumes: `AgentRun.status`, `streamingAnswer`, `answerStreamId`, `run.result.final_answer`.
- Produces: `normalizeRunStatus(status: string): "running" | "terminal" | "inactive"` and `shouldAnimateFinalAnswer(run, streamingAnswer, answerStreamId): boolean` that enables animation only for `running`.

- [ ] **Step 1: Write failing rendered-history tests**

Add these component-level tests to `agent-streaming.test.tsx` using fake timers:

```tsx
test.each(["succeeded", "completed", "queued", "retry_wait", "cancel_requested", "failed", "cancelled", "unknown"]) (
  "%s historical answer renders complete text without typing replay",
  (status) => {
    vi.useFakeTimers();
    render(
      <FinalAnswerPanel
        run={makeRun({ status: status as AgentRunStatus, result: { final_answer: "完整历史答案" } })}
        streamingAnswer="完整历史答案"
        answerStreamId="historical-answer"
      />,
    );
    expect(screen.getByText("完整历史答案")).toBeVisible();
    act(() => vi.advanceTimersByTime(100));
    expect(screen.getByText("完整历史答案")).toBeVisible();
  },
);
```

Add a two-panel test that renders two distinct `running` Runs with growing stream text and asserts both predicates are true. Add a reducer test that initializes from persisted result and replayed answer events, then asserts a legacy `completed` status still exposes the full final text.

- [ ] **Step 2: Run the history tests and verify RED**

Run from `C:\01_agent_loop\frontend`:

```powershell
npm test -- --run src/components/agent/agent-streaming.test.tsx src/lib/run-stream-reducer.test.ts
```

Expected: `completed`, queued/retry, and unknown status cases fail because current logic treats every nonterminal status as animatable.

- [ ] **Step 3: Add explicit status normalization**

In `final-answer-panel.tsx`, replace the terminal-only helper with:

```tsx
type AnswerDisplayStatus = "running" | "terminal" | "inactive";

export function normalizeAnswerDisplayStatus(status: string): AnswerDisplayStatus {
  if (status === "running") return "running";
  if (["succeeded", "completed", "failed", "cancelled"].includes(status)) return "terminal";
  return "inactive";
}

export function shouldAnimateFinalAnswer(
  run: AgentRun,
  streamingAnswer: string,
  answerStreamId: string | null,
): boolean {
  return normalizeAnswerDisplayStatus(run.status) === "running" &&
    (Boolean(streamingAnswer) || Boolean(answerStreamId));
}
```

For non-running Runs choose the complete source in this order:

```tsx
const answerToRender = isActivelyStreaming
  ? streamedAnswer ?? finalAnswer
  : finalAnswer ?? streamedAnswer;
```

Pass `enabled: shouldAnimate` to the revised typing hook introduced in Task 3. Until Task 3 lands, keep the existing hook call but render `answerToRender` when `shouldAnimate` is false.

- [ ] **Step 4: Ensure terminal event precedence remains correct**

In `run-stream-reducer.ts`, keep `answer_completed` and `run_succeeded` result behavior. Add a pure helper if needed:

```ts
function finalAnswerFromPayload(payload: Record<string, unknown>): string | null {
  const answer = readText(payload, "final_answer") ?? readText(payload, "text");
  return answer?.trim() ? answer : null;
}
```

Use only non-empty terminal payload text to replace target text. Empty terminal payload must preserve current `answerText`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
npm test -- --run src/components/agent/agent-streaming.test.tsx src/lib/run-stream-reducer.test.ts
```

Expected: all historical, legacy-status, terminal-precedence, and multi-running tests pass.

- [ ] **Step 6: Record verification instead of committing**

Write the RED/GREEN transcript and changed files to `C:\01_agent_loop\.superpowers\sdd\smooth-streaming-task-2-report.md`.

### Task 3: Replace Timer Contention With One RAF Catch-Up Scheduler

**Files:**
- Modify: `C:\01_agent_loop\frontend\src\lib\typing-animation.ts`
- Modify: `C:\01_agent_loop\frontend\src\lib\typing-animation.test.ts`
- Modify: `C:\01_agent_loop\frontend\src\hooks\use-typing-text.ts`
- Modify: `C:\01_agent_loop\frontend\src\hooks\use-typing-text.test.ts`

**Interfaces:**
- Consumes: `targetText`, `enabled`, `resetKey`, `prefers-reduced-motion`.
- Produces: `advanceTypingAnimation(state, targetText, elapsedMs, frameMs)` with monotonic prefix output and `useTypingText(targetText, { enabled, resetKey })` with at most one RAF loop.

- [ ] **Step 1: Write failing pure scheduler tests**

Add tests that describe the required pure function behavior:

```ts
test("advances one character for a small backlog", () => {
  expect(advanceTypingAnimation({ displayedText: "你", elapsedMs: 0 }, "你好", 16, 16).displayedText)
    .toBe("你好");
});

test("accelerates while preserving a target prefix", () => {
  const next = advanceTypingAnimation(
    { displayedText: "", elapsedMs: 0 },
    "a".repeat(100),
    16,
    16,
  );
  expect(next.displayedText.length).toBeGreaterThan(1);
  expect("a".repeat(100).startsWith(next.displayedText)).toBe(true);
});

test("does not move backward when target grows", () => {
  const next = advanceTypingAnimation({ displayedText: "already", elapsedMs: 0 }, "already longer", 16, 16);
  expect(next.displayedText.startsWith("already")).toBe(true);
});
```

Add a test that terminal catch-up reaches the target by 250 ms of accumulated animation time and a test that reduced motion returns target text without scheduling.

- [ ] **Step 2: Run pure scheduler tests and verify RED**

Run:

```powershell
npm test -- --run src/lib/typing-animation.test.ts
```

Expected: acceleration, terminal deadline, and reduced-motion tests fail because current logic is timer-speed based and has no enabled/reduced-motion contract.

- [ ] **Step 3: Implement frame advancement tiers**

Replace fixed single-character progression with this deterministic policy in `typing-animation.ts`:

```ts
function charactersPerFrame(backlog: number, terminal: boolean): number {
  if (terminal) return Math.max(1, Math.ceil(backlog / 15));
  if (backlog > 160) return Math.max(8, Math.ceil(backlog / 20));
  if (backlog > 48) return 4;
  if (backlog > 12) return 2;
  return 1;
}
```

`advanceTypingAnimation` must reject a shorter/non-prefix target by returning the current text unchanged until a confirmed reset generation is supplied by the hook. Use elapsed time only to prevent advancing more than once for the same frame; do not retain `setTimeout` scheduling state.

- [ ] **Step 4: Implement a single RAF hook loop**

In `use-typing-text.ts`, replace the timeout effect with one RAF loop:

```tsx
export function useTypingText(
  targetText: string,
  { enabled = true, resetKey = null }: UseTypingTextOptions = {},
): string {
  const [displayedText, setDisplayedText] = useState(enabled ? "" : targetText);
  const frameRef = useRef<number | null>(null);
  const previousFrameRef = useRef<number | null>(null);
  // Reset only when resetKey changes. Cancel one existing frame in cleanup.
  // When !enabled or reduced motion is requested, synchronously converge to targetText.
  // Otherwise schedule exactly one requestAnimationFrame callback at a time.
}
```

Use `window.matchMedia("(prefers-reduced-motion: reduce)")` in an effect with a change listener. For terminal/non-running rendering, callers set `enabled=false`, which immediately returns target text.

- [ ] **Step 5: Write and run hook integration tests**

Use fake `requestAnimationFrame` in `use-typing-text.test.ts` to assert:

- only one pending frame exists after repeated target growth;
- displayed text grows monotonically;
- `enabled=false` exposes the complete target immediately;
- reset key clears only a confirmed new stream generation;
- unmount cancels the frame.

Run:

```powershell
npm test -- --run src/hooks/use-typing-text.test.ts src/lib/typing-animation.test.ts
```

Expected: all scheduler tests pass.

- [ ] **Step 6: Wire the scheduler to FinalAnswerPanel and verify active/history behavior**

Update the panel call:

```tsx
const renderedAnswer = useTypingText(answerToRender ?? "", {
  enabled: shouldAnimate,
  resetKey: shouldAnimate ? answerStreamId : null,
});
```

For non-active Runs render `answerToRender` rather than the hook result. For active Runs render the hook result.

Run:

```powershell
npm test -- --run src/components/agent/agent-streaming.test.tsx src/hooks/use-typing-text.test.ts src/lib/typing-animation.test.ts
```

Expected: complete history is immediate; active answer progresses; all scheduler tests pass.

- [ ] **Step 7: Record verification instead of committing**

Write test results and scheduler invariants to `C:\01_agent_loop\.superpowers\sdd\smooth-streaming-task-3-report.md`.

### Task 4: Reconcile Terminal State Without Unmounting The Conversation

**Files:**
- Modify: `C:\01_agent_loop\frontend\src\hooks\use-run-event-stream.ts`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\sessions\[sessionId]\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\sessions\[sessionId]\page.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\hooks\use-run-event-stream.test.ts`
- Modify: `C:\01_agent_loop\frontend\src\lib\run-stream-reducer.ts`

**Interfaces:**
- Consumes: fully reduced terminal `AgentRun` from the stream hook.
- Produces: a background `reconcileSession()` that refreshes persisted state without page-level loading and a stale-source-safe event hook.

- [ ] **Step 1: Write failing terminal reconciliation tests**

Add a page test that dispatches `answer_completed`, then `run_succeeded`, and asserts the current conversation remains in the DOM with no page-level spinner. Add a test where reconciliation returns an older Run lacking `result.final_answer` and assert the displayed full answer remains. Add a test where reconciliation rejects and assert the answer remains with a scoped warning.

Add a hook test that dispatches a terminal event from a closed old EventSource after a Run switch and asserts state for the new Run does not change.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
npm test -- --run "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx" src/hooks/use-run-event-stream.test.ts
```

Expected: the spinner/no-unmount test fails because current terminal callback calls `loadSession()`, which sets `loading=true`; stale-source coverage may expose current closure behavior.

- [ ] **Step 3: Make answer completion non-terminal for page reconciliation**

In `run-stream-reducer.ts`, keep `answer_completed` text/result projection but do not force the Run status to `succeeded`. Only `run_succeeded` marks the Run terminal. The relevant result helper should preserve target text:

```ts
function setRunFinalAnswer(run: AgentRun | null, answerText: string, status?: AgentRunStatus): AgentRun | null {
  if (!run) return run;
  return {
    ...run,
    ...(status ? { status } : {}),
    result: { ...(run.result ?? {}), final_answer: answerText },
  };
}
```

Call it from `answer_completed` without `status`; call it from `run_succeeded` with `"succeeded"`.

- [ ] **Step 4: Add stale-source and background reconciliation guards**

At the first line of `handleMessage` in `use-run-event-stream.ts`, retain:

```ts
if (closed) return;
```

Notify `onTerminalState` only after a `run_succeeded`, `run_failed`, or `run_cancelled` reducer result, never after `answer_completed` alone.

In the session page, split initial `loadSession()` from terminal reconciliation:

```tsx
const reconcileSession = useCallback(async () => {
  const view = await loadAgentSessionView(sessionId);
  setTurns((current) => mergeTurnsKeepingRicherAnswer(current, view.turns));
  setWarnings(view.warnings);
}, [sessionId]);
```

`reconcileSession` must not call `setLoading(true)`. Define `mergeTurnsKeepingRicherAnswer` in the same page module: for identical run IDs, retain the Run object whose `result.final_answer` is non-empty or longer; preserve current events/steps when refreshed diagnostics are empty.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
npm test -- --run "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx" src/hooks/use-run-event-stream.test.ts src/lib/run-stream-reducer.test.ts
```

Expected: no full-page spinner at terminal answer completion, old source ignored, stale HTTP cannot erase final answer, and terminal reducer tests pass.

- [ ] **Step 6: Record verification instead of committing**

Write RED/GREEN output and merge behavior to `C:\01_agent_loop\.superpowers\sdd\smooth-streaming-task-4-report.md`.

### Task 5: Harden Markdown Presentation And Verify End-To-End Behavior

**Files:**
- Modify: `C:\01_agent_loop\frontend\src\components\agent\final-answer-panel.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\agent-streaming.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\agent-globals.css`

**Interfaces:**
- Consumes: complete or active `renderedAnswer` text, safe Markdown URL policy.
- Produces: safe GFM rendering with accessible answer semantics and browser-verifiable, immediate SSE behavior.

- [ ] **Step 1: Write failing Markdown contract tests**

Add tests for:

```tsx
test("renders complete historical GFM without animation", () => {
  render(<FinalAnswerPanel run={succeededRun} streamingAnswer="" answerStreamId={null} />);
  expect(screen.getByRole("heading", { name: "标题" })).toBeVisible();
  expect(screen.getByRole("table")).toBeVisible();
});

test("does not render unsafe markdown links", () => {
  render(<FinalAnswerPanel run={runningRun} streamingAnswer="[bad](javascript:alert(1))" />);
  expect(screen.queryByRole("link", { name: "bad" })).toHaveAttribute("href", "");
});
```

Add tests for external `https` links opening with `target="_blank" rel="noreferrer noopener"`, internal `/agent` links with no new target, raw HTML omission, `aria-live="polite"` stream region, and `aria-labelledby`/accessible answer section.

- [ ] **Step 2: Run Markdown tests and verify RED**

Run:

```powershell
npm test -- --run src/components/agent/agent-streaming.test.tsx
```

Expected: internal link policy and answer accessibility tests fail because current renderer sends every link to a new tab and has no explicit section/stream semantics.

- [ ] **Step 3: Implement one safe URL and link-policy helper**

Add pure helpers in `final-answer-panel.tsx`:

```tsx
function safeHref(href: string | undefined): string {
  if (!href) return "";
  if (href.startsWith("/") && !href.startsWith("//")) return href;
  if (href.startsWith("#")) return href;
  try {
    const url = new URL(href);
    return ["http:", "https:", "mailto:"].includes(url.protocol) ? href : "";
  } catch {
    return "";
  }
}

function isExternalHref(href: string): boolean {
  return href.startsWith("http:") || href.startsWith("https:") || href.startsWith("mailto:");
}
```

Render external anchors with new-tab protection and an `aria-label` suffix. Render internal and fragment anchors without `target`. Retain `skipHtml`.

Wrap answer content in:

```tsx
<section className="final-answer-panel" aria-labelledby={`answer-heading-${run.id}`}>
  <h2 id={`answer-heading-${run.id}`} className="sr-only">最终回答</h2>
  <div className="final-answer-prose" aria-live={shouldAnimate ? "polite" : "off"}>
```

- [ ] **Step 4: Add Markdown presentation CSS**

In `agent-globals.css`, add styles for `h4`, `h5`, `h6`, `.final-answer-prose a:focus-visible`, and scroll wrappers:

```css
.final-answer-prose h4,
.final-answer-prose h5,
.final-answer-prose h6 { margin: 1.2em 0 0.55em; line-height: 1.35; }
.final-answer-prose a:focus-visible { outline: 2px solid var(--agent-accent); outline-offset: 3px; }
.final-answer-prose pre,
.final-answer-prose .table-scroll { overflow-x: auto; }
```

Use the existing table wrapper pattern or provide a `components.table` renderer that wraps tables in `<div className="table-scroll" tabIndex={0}>` while preserving native table semantics.

- [ ] **Step 5: Run Markdown tests and verify GREEN**

Run:

```powershell
npm test -- --run src/components/agent/agent-streaming.test.tsx
```

Expected: GFM, link-policy, HTML omission, and accessibility tests pass.

- [ ] **Step 6: Run full automated verification**

Run in parallel:

```powershell
cd C:\01_agent_loop\frontend
npm test -- --run
npm run build
```

```powershell
cd C:\01_agent_loop\backend
python -m pytest tests/test_agent_api.py tests/test_agent_stream.py tests/test_agent_loop.py tests/test_agent_tools.py tests/test_agent_worker.py -q
```

Expected: frontend suite and build pass. Document any existing unrelated backend failures separately with test names and stack traces.

- [ ] **Step 7: Execute real Edge acceptance**

Use Microsoft Edge with a clean profile. Do not use Quark for acceptance.

1. Start API, Worker, and `npm run dev` from `C:\01_agent_loop`.
2. Load one completed session; assert initial DOM contains full final answer with no incremental changes for 500 ms.
3. Submit a long answer task. Record SSE frame timestamps and DOM text lengths. Assert at least two increasing lengths occur before terminal status.
4. At terminal, assert no full-page spinner/remount and final DOM text equals persisted final answer.
5. Reload that completed session and repeat immediate-history assertion.
6. Disconnect after two `answer_delta` frames, restore connectivity, and assert no duplicate/backward/reset text.
7. Capture desktop and mobile Markdown fixtures containing headings, nested lists, table, code, quote, safe/unsafe links, and raw HTML.

Acceptance evidence must include Run ID, timestamps, event sequences, DOM lengths, browser console, and screenshots. Never record secrets or answer content from private production data.

- [ ] **Step 8: Record final verification instead of committing**

Write automated output, browser evidence, changed files, residual risks, and rollback observations to `C:\01_agent_loop\.superpowers\sdd\smooth-streaming-task-5-report.md`.
