# Conversation Stream Reliability And Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate duplicate visible thoughts, endless SSE reconnects, historical typing replay, slow live Markdown, unnecessary SSE DB queries, and tool timeline misalignment.

**Architecture:** Six focused changes across backend and frontend. Tasks A/B/C/D can run in parallel (Round 1). Task E depends on A+B+D. Task F depends on E.

**Tech Stack:** Python 3.12+/FastAPI/SQLAlchemy async, React 19/TypeScript/Vitest, `react-markdown`/`remark-gfm`.

## Global Constraints

- Do not change the provider chunk protocol or remove durable agent events.
- Do not introduce Redis or move the worker into FastAPI.
- Do not weaken Markdown URL safety, HTML safety, or visible-thought data protection.
- Preserve cursor-based replay, cross-process delivery, and compensation polling as correctness mechanisms.
- Share exact `isActivelyStreamingRun(status, isLiveRun)` predicate across all animation entry points.
- Completed Markdown blocks must retain stable DOM identity when only the active tail grows.
- Non-terminal visual reveal must never exceed 48 characters per frame.
- Commit after every task.

---

## Round 1 — Parallel (Tasks A, B, C, D)

### Task A: Visible Thought Resume Deduplication

**Files:**
- Modify: `backend/app/services/agent/loop.py:476-641`
- Create: `backend/tests/test_visible_thought_overlap.py`

**Interfaces:**
- Produces: `remove_visible_thought_overlap(previous_text: str, resumed_text: str) -> str`
- Produces: modified `_build_visible_thought_messages()` accepting `previous_visible_thought: str | None` and emitting strict non-repetition constraint.

- [ ] **Step 1: Write failing deduplication tests**

Create `backend/tests/test_visible_thought_overlap.py`:

```python
from __future__ import annotations
import pytest
from app.services.agent.loop import remove_visible_thought_overlap


def test_removes_repeated_prefix_when_long_enough():
    previous = "我已找到多个关于胡萝卜炒鸡蛋的食谱，接下来将整合成一份详细的图文教程。"
    resumed = previous + "接下来将为您汇总胡萝卜炒鸡蛋的详细教程。"

    result = remove_visible_thought_overlap(previous, resumed)
    assert result == "接下来将为您汇总胡萝卜炒鸡蛋的详细教程。"


def test_preserves_unrelated_resume_text():
    previous = "我会先搜索相关公开资料。"
    resumed = "搜索已得到多个来源，后续将整理成完整回答。"
    result = remove_visible_thought_overlap(previous, resumed)
    assert result == resumed


def test_uses_fallback_when_resume_is_fully_duplicated():
    previous = "搜索完成，正在整理。"
    result = remove_visible_thought_overlap(previous, previous, fallback_action_type="web_search")
    assert result is None or len(result) > 0


def test_ignores_short_overlap():
    previous = "搜索"
    resumed = "搜索已完成，整理中"
    result = remove_visible_thought_overlap(previous, resumed)
    assert result == resumed


def test_handles_whitespace_normalization():
    previous = "a very long visible thought that will be repeated"
    resumed = "a very long visible thought that will be repeated and then continued"
    # Under 12-char overlap threshold with these English strings; keep resumed
    result = remove_visible_thought_overlap(previous, resumed)
    assert len(result) > 0
```

- [ ] **Step 2: Verify RED**

Run: `cd backend; python -m pytest tests/test_visible_thought_overlap.py -v`
Expected: FAIL because `remove_visible_thought_overlap` does not exist.

- [ ] **Step 3: Implement overlap guard**

Add to `backend/app/services/agent/loop.py`:

```python
def remove_visible_thought_overlap(
    previous_text: str,
    resumed_text: str,
    *,
    fallback_action_type: str | None = None,
) -> str:
    MIN_OVERLAP_CHARS = 12
    MIN_OVERLAP_RATIO = 0.25

    prev_normalized = " ".join(previous_text.split())
    resumed_normalized = " ".join(resumed_text.split())

    if not prev_normalized or not resumed_normalized:
        return resumed_text

    overlap_length = 0
    for i in range(1, min(len(prev_normalized), len(resumed_normalized)) + 1):
        if resumed_normalized.startswith(prev_normalized[-i:]):
            overlap_length = i

    if overlap_length < MIN_OVERLAP_CHARS or (len(resumed_normalized) > 0 and overlap_length / len(resumed_normalized) < MIN_OVERLAP_RATIO):
        return resumed_text

    trimmed = resumed_text[overlap_length:].lstrip()
    if not trimmed:
        if fallback_action_type:
            return AgentLoopService()._visible_thought_fallback(fallback_action_type)
        return resumed_text
    return trimmed
```

Modify `_build_visible_thought_messages` to accept `previous_visible_thought: str | None` and append the non-repetition constraint when provided.

In the resume stream path (around line 522-641), pass `previous_visible_thought=finalized_text` and apply `remove_visible_thought_overlap` to the final resume text before persisting.

- [ ] **Step 4: Verify GREEN**

Run: `cd backend; python -m pytest tests/test_visible_thought_overlap.py -v`
Expected: PASS.
Run: `cd backend; python -m pytest tests/test_agent_loop.py -q`
Expected: all 18 pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_visible_thought_overlap.py
git commit -m "feat: prevent visible thought repetition after tool resume"
```

---

### Task B: Historical Animation Static Rendering

**Files:**
- Modify: `frontend/src/components/agent/thought-narrative.tsx`
- Modify: `frontend/src/components/agent/final-answer-panel.tsx`
- Modify: `frontend/src/components/agent/session-conversation-stream.tsx`
- Create: `frontend/src/lib/animation-eligibility.ts`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`

**Interfaces:**
- Produces: `isActivelyStreamingRun(status: string, isLiveRun: boolean): boolean`
- Consumes: `isLiveRun: boolean` passed from session-conversation-stream and detail-conversation.

- [ ] **Step 1: Write failing tests**

Add to `frontend/src/components/agent/agent-streaming.test.tsx`:

```tsx
describe("Historical animation prevention", () => {
  test("queued historical run renders reasoning statically without typing animation", () => {
    const raf = installFakeRaf();
    const { container } = render(
      <ThoughtNarrative run={{ ...baseRun, status: "queued" }} steps={[]} events={[
        { id: "e1", run_id: "run-1", attempt_id: null, seq: 1, event_type: "visible_thought_started", payload: { step_index: 0, stream_id: "thought-1" }, created_at: "2026-01-01T00:00:00Z" },
        { id: "e2", run_id: "run-1", attempt_id: null, seq: 2, event_type: "visible_thought_completed", payload: { step_index: 0, stream_id: "thought-1", text: "历史思考内容" }, created_at: "2026-01-01T00:00:01Z" },
      ]} isLiveRun={false} />
    );
    expect(screen.getByText("历史思考内容")).toBeVisible();
    expect(raf.pendingCount()).toBe(0);
  });

  test("non-live running run renders reasoning statically", () => {
    const { container } = render(
      <ThoughtNarrative run={baseRun} steps={[]} events={[
        { id: "e1", run_id: "run-1", attempt_id: null, seq: 1, event_type: "visible_thought_started", payload: { step_index: 0, stream_id: "thought-1" }, created_at: "2026-01-01T00:00:00Z" },
        { id: "e2", run_id: "run-1", attempt_id: null, seq: 2, event_type: "visible_thought_delta", payload: { step_index: 0, stream_id: "thought-1", offset: 0, delta: "正在思考" }, created_at: "2026-01-01T00:00:01Z" },
      ]} isLiveRun={false} />
    );
    expect(screen.getByText("正在思考")).toBeVisible();
    const animated = container.querySelector('[class*="thought-narrative-item-streaming"]');
    expect(animated).toBeNull();
  });
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx -t "Historical animation prevention"`
Expected: FAIL because `isLiveRun` prop does not exist and queued runs animate.

- [ ] **Step 3: Implement shared eligibility and static rendering**

Create `frontend/src/lib/animation-eligibility.ts`:

```ts
export function isActivelyStreamingRun(status: string, isLiveRun: boolean): boolean {
  return isLiveRun && status === "running";
}
```

In `thought-narrative.tsx`:
- Accept `isLiveRun: boolean` prop.
- Replace `isThinking` logic at line 97 with `isActivelyStreamingRun(run.status, isLiveRun)`.
- In `StreamingReasoningBlock`, pass `enabled={isActive}` to `useTypingText`. Only the active+unfinished block should animate.

In `session-conversation-stream.tsx`:
- Compute `isLiveRun` for the latest active turn.
- Pass `isLiveRun={isLiveRun}` to both `ThoughtNarrative` and `FinalAnswerPanel`.

In `final-answer-panel.tsx`:
- Accept `isLiveRun` (optional, defaults to true for backward compatibility).
- Use `isActivelyStreamingRun` for `shouldAnimate` decisions.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx`
Expected: all 56+ tests pass; new historical tests pass; live active reasoning still animates.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/animation-eligibility.ts frontend/src/components/agent/thought-narrative.tsx frontend/src/components/agent/final-answer-panel.tsx frontend/src/components/agent/session-conversation-stream.tsx frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "fix: render historical conversations statically"
```

---

### Task C: Tool Timeline Alignment

**Files:**
- Modify: `frontend/src/app/agent-globals.css:1464-1487`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`

- [ ] **Step 1: Write failing style contract test**

Add to `agent-streaming.test.tsx`:

```tsx
test("tool record icon shares timeline axis with reasoning marker", () => {
  const events = [
    { id: "e1", run_id: "run-1", attempt_id: null, seq: 1, event_type: "visible_thought_completed", payload: { step_index: 0, stream_id: "t1", text: "思考" }, created_at: "2026-01-01T00:00:00Z" },
    { id: "e2", run_id: "run-1", attempt_id: null, seq: 2, event_type: "tool_started", payload: { step_index: 0, action_type: "web_search" }, created_at: "2026-01-01T00:00:01Z" },
  ];
  const { container } = render(<ThoughtNarrative run={baseRun} steps={[]} events={events} isLiveRun={false} />);

  const toolRecord = container.querySelector(".thought-tool-record") as HTMLElement | null;
  const toolIcon = container.querySelector(".thought-tool-record-icon") as HTMLElement | null;
  expect(toolRecord).not.toBeNull();
  expect(toolIcon).not.toBeNull();
  const recordStyle = getComputedStyle(toolRecord!);
  const iconStyle = getComputedStyle(toolIcon!);
  expect(recordStyle.position).toBe("relative");
  expect(iconStyle.position).toBe("absolute");
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx -t "tool record icon shares timeline axis"`
Expected: FAIL because current positioning is not `absolute`/`relative`.

- [ ] **Step 3: Implement alignment CSS**

In `frontend/src/app/agent-globals.css`, update tool record styles:

```css
.thought-tool-record {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 12px;
  border: 1px solid var(--agent-border);
  border-radius: 12px;
  background: var(--agent-panel);
  position: relative;
}

.thought-tool-record-icon {
  position: absolute;
  left: -28px;
  top: 7px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
}
```

Keep existing `thought-tool-record-main`, `thought-tool-record-label`, and other child styles unchanged.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx`
Expected: style contract test passes; no visual regression test failures.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/agent-globals.css frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "fix: align tool call icon with reasoning timeline axis"
```

---

### Task D: Faster Live Markdown Tail And Reveal Speed

**Files:**
- Modify: `frontend/src/hooks/use-streaming-markdown.ts`
- Modify: `frontend/src/hooks/use-streaming-markdown.test.ts`
- Modify: `frontend/src/lib/typing-animation.ts`
- Modify: `frontend/src/lib/typing-animation.test.ts`

- [ ] **Step 1: Write failing speed and cadence tests**

Add to `frontend/src/lib/typing-animation.test.ts`:

```ts
test("reveals two characters for a backlog of ten", () => {
  const target = "a".repeat(10);
  const next = advanceTypingAnimation({ displayedText: "", elapsedMs: 0 }, target, 16, 16);
  expect(next.displayedText).toHaveLength(2);
});
```

Add to `frontend/src/hooks/use-streaming-markdown.test.ts`:

```tsx
test("publishes a short active tail within a frame, not 80ms", () => {
  vi.useFakeTimers();
  const { result, rerender } = renderHook(
    ({ text }) => useStreamingMarkdown(text, { resetKey: "stream-1", tailIntervalMs: 16 }),
    { initialProps: { text: "# 标题\n\n段落" } },
  );
  expect(result.current.completedBlocks).toEqual(["# 标题\n\n"]);
  const initialVersion = result.current.tailVersion;

  rerender({ text: "# 标题\n\n段落续" });
  act(() => vi.advanceTimersByTime(16));
  // Tail should have updated within 16ms, not waiting 80ms
  expect(result.current.tailVersion).toBe(initialVersion + 1);
  vi.useRealTimers();
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/lib/typing-animation.test.ts src/hooks/use-streaming-markdown.test.ts`
Expected: FAIL — reveal count is still 1 for backlog of 10, and tail timer is still 80ms default.

- [ ] **Step 3: Implement faster reveal and tail cadence**

In `frontend/src/lib/typing-animation.ts`, update `charactersPerFrame`:

```ts
function charactersPerFrame(backlog: number, terminal: boolean): number {
  if (terminal) return Math.max(1, Math.ceil(backlog / 12));
  if (backlog > 1_000) return 48;
  if (backlog > 400) return 32;
  if (backlog > 160) return 20;
  if (backlog > 48) return 12;
  if (backlog > 12) return 6;
  return 2;
}
```

In `frontend/src/hooks/use-streaming-markdown.ts`, replace the fixed 80ms timer with an adaptive RAF-based publisher:

```ts
const tailIntervalMs = options.tailIntervalMs ?? 16;

function computedTailInterval(size: number): number {
  if (size > 8_000) return 64;
  if (size > 2_000) return 32;
  return 16;
}
```

Use `setTimeout` with the computed interval instead of a fixed 80ms. Keep the single-timer invariant.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/lib/typing-animation.test.ts src/hooks/use-typing-text.test.ts src/hooks/use-streaming-markdown.test.ts src/lib/streaming-markdown.test.ts`
Expected: all pass; 2 chars/frame for small backlog; tail interval adaptive.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/typing-animation.ts frontend/src/lib/typing-animation.test.ts frontend/src/hooks/use-streaming-markdown.ts frontend/src/hooks/use-streaming-markdown.test.ts
git commit -m "perf: faster text reveal and adaptive markdown tail cadence"
```

---

## Round 2 — Sequential (Task E depends on A + B + D)

### Task E: SSE Terminal Reconciliation And Reconnect Fix

**Files:**
- Modify: `frontend/src/hooks/use-run-event-stream.ts`
- Modify: `frontend/src/lib/run-stream-reducer.ts`
- Modify: `frontend/src/lib/agent-api.ts`
- Modify: `frontend/src/hooks/use-run-event-stream.test.ts`
- Modify: `frontend/src/lib/run-stream-reducer.test.ts`
- Modify: `backend/app/api/agent_stream.py`
- Modify: `backend/tests/test_agent_stream.py`

- [ ] **Step 1: Write failing reconciliation tests**

Add to `frontend/src/hooks/use-run-event-stream.test.ts`:

```ts
test("reconciles terminal run state after SSE closes with answer completed", async () => {
  // Simulate: answer_completed received but no run_succeeded
  MockEventSource.instances = [];
  const { result } = renderHook(() =>
    useRunEventStream({
      runId: "run-1",
      initialEvents: [],
      initialRun: { id: "run-1", status: "running" } as any,
    })
  );

  const source = MockEventSource.instances[0];
  source.dispatchEvent("answer_completed", JSON.stringify({
    seq: 1, type: "answer_completed", run_id: "run-1", timestamp: "", payload: { text: "完整答案" },
  }));
  source.dispatchEvent("open", "");

  // Simulate SSE clean close - the server returns 200 with no more events
  act(() => { source.readyState = EventSource.CLOSED; source.onerror?.({} as Event); });

  // After reconciliation, the run should be terminal and EventSource closed
  await waitFor(() => expect(result.current.connection).toBe("closed"));
  expect(result.current.run?.status).toBe("succeeded");
}, 10000);
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/hooks/use-run-event-stream.test.ts -t "reconciles terminal run state"`
Expected: FAIL because no reconciliation exists.

- [ ] **Step 3: Implement terminal reconciliation**

In `frontend/src/lib/agent-api.ts`, ensure `getRun` is exported (should already exist).

In `frontend/src/hooks/use-run-event-stream.ts`:

Add a single-flight reconciliation:

```ts
const reconcilingRef = useRef(false);

async function reconcileTerminalRun(runId: string) {
  if (reconcilingRef.current) return;
  reconcilingRef.current = true;
  try {
    const run = await agentApi.getRun(runId);
    if (!run || !isTerminalAgentRunStatus(run.status)) return;
    setState((current) => ({
      ...current,
      run: run.result?.final_answer
        ? { ...run, result: { ...current.run?.result, ...run.result } }
        : { ...current.run, status: run.status },
      answerText: current.answerText || run.result?.final_answer || "",
      connection: "closed",
    }));
    if (source) { source.close(); source = null; closed = true; }
    clearReconnectTimer();
    if (run.status && lastNotifiedRef.current !== `${run.id}:${run.status}`) {
      lastNotifiedRef.current = `${run.id}:${run.status}`;
      onTerminalStateRef.current?.(run);
    }
  } catch {
    // Keep local state; reconnect will try again
  } finally {
    reconcilingRef.current = false;
  }
}
```

Trigger it from the `onerror` handler when the local state is still non-terminal and there are no pending reconnect attempts.

Backend: In `agent_stream.py`, after the final catch-up, if the status is terminal but no terminal event was emitted, log a structured warning. Do not invent events.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/hooks/use-run-event-stream.test.ts`
Expected: reconciliation test passes; all existing stream tests pass.
Run: `cd backend; python -m pytest tests/test_agent_stream.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/use-run-event-stream.ts frontend/src/lib/run-stream-reducer.ts frontend/src/lib/agent-api.ts frontend/src/hooks/use-run-event-stream.test.ts frontend/src/lib/run-stream-reducer.test.ts backend/app/api/agent_stream.py backend/tests/test_agent_stream.py
git commit -m "fix: reconcile terminal run after missing terminal SSE event"
```

---

## Round 3 — Sequential (Task F depends on E)

### Task F: Same-Process Direct SSE Event Frames

**Files:**
- Modify: `backend/app/services/agent/event_bus.py`
- Modify: `backend/app/services/agent/loop.py:54-75`
- Modify: `backend/app/api/agent_stream.py:181-244`
- Modify: `backend/tests/test_agent_stream.py`

- [ ] **Step 1: Write failing direct-event tests**

Add to `backend/tests/test_agent_stream.py`:

```python
async def test_direct_committed_event_skips_database_query_when_contiguous():
    """Same-process committed event with seq == last_seen + 1 should not query DB."""
    ...
```

- [ ] **Step 2: Verify RED**

Run: `cd backend; python -m pytest tests/test_agent_stream.py -k direct_committed_event -v`
Expected: FAIL.

- [ ] **Step 3: Implement CommittedEvent and direct path**

In `event_bus.py`, add `CommittedEvent` dataclass. The existing `publish_after_commit` method gains a new `Publishable = PersistedEvent | CommittedEvent` union. Same-process worker paths publish `CommittedEvent` after commit.

In `agent_stream.py`, the active loop can directly encode a `CommittedEvent` when `event.seq == last_seen_seq + 1`. For gaps, duplicate, or `PersistedEvent`, use the existing `_events_after` query.

- [ ] **Step 4: Verify GREEN**

Run: `cd backend; python -m pytest tests/test_agent_stream.py tests/test_agent_loop.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/event_bus.py backend/app/services/agent/loop.py backend/app/api/agent_stream.py backend/tests/test_agent_stream.py
git commit -m "perf: direct same-process committed SSE event frames"
```

---

## Round 4 — Final Verification (Task G)

### Task G: Full Regression And Performance Coverage

- [ ] **Step 1: Run full backend suite**

```bash
cd backend
python -m pytest -q
```

Expected: test_agent_loop, test_agent_stream, test_visible_thought_overlap, test_agent_notify, test_postgres_event_listener, test_agent_notify_integration all pass.

- [ ] **Step 2: Run full frontend suite**

```bash
cd frontend
npm test -- --run
```

Expected: 385+/387 pass; streaming, animation, markdown, reducer, and thought narrative tests all green.

- [ ] **Step 3: Run production build**

```bash
cd frontend
npm run build
```

Expected: compiled successfully, TypeScript clean, all routes listed.

- [ ] **Step 4: Commit if clean**

```bash
git status --short
git diff --check
```
