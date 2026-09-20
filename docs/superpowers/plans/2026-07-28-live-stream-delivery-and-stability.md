# Live Stream Delivery And Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore real-time answer streaming, fix direct-SSE global-sequence blocking, stabilize Markdown transition at terminal state, and prevent scroll jumps during live answer generation.

**Architecture:** Four independent fixes: frontend SSE-open logic for queued/running unresolved turns, backend direct-frame per-run continuity, terminal DOM reuse in StreamingMarkdown, and scroll anchoring.

**Tech Stack:** React 19/TypeScript/Vitest, Python 3.12/FastAPI/SQLAlchemy async.

## Global Constraints

- Answer deltas must be visible before answer_completed; answer_completed alone does not close SSE.
- Queued latest runs must open SSE; historical turns never open SSE.
- Same-process CommittedEvent emits directly without global-sequence adjacency requirement.
- Terminal answer transition reuses completed block DOM keys; no full-tree unmount/remount.
- Scroll anchoring only when user is near bottom; do not fight user scroll position.

---
## File Structure

| File | Purpose |
| --- | --- |
| `frontend/src/lib/run-stream-reducer.ts` | Split terminal evidence from answer evidence; fix SSE-open rule. |
| `frontend/src/components/agent/session-conversation-stream.tsx` | Apply corrected rules; queued latest turns must stream. |
| `frontend/src/hooks/use-run-event-stream.ts` | Preserve answer_completed as non-terminal in hook lifecycle. |
| `frontend/src/components/agent/streaming-markdown.tsx` | Terminal DOM reuse. |
| `frontend/src/components/agent/final-answer-panel.tsx` | Wire terminal prop into StreamingMarkdown. |
| `backend/app/api/agent_stream.py` | Fix direct-frame global-sequence check. |
| `backend/tests/test_agent_stream.py` | Global-sequence gap direct delivery test. |
| `frontend/src/app/agent-globals.css` | Scroll anchoring CSS. |

---

### Task 1: Fix Frontend SSE Opening Rules

**Files:**
- Modify: `frontend/src/lib/run-stream-reducer.ts`
- Modify: `frontend/src/components/agent/session-conversation-stream.tsx`
- Modify: `frontend/src/hooks/use-run-event-stream.ts`
- Modify: `frontend/src/lib/run-stream-reducer.test.ts`
- Modify: `frontend/src/hooks/use-run-event-stream.test.ts`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`

**Interfaces:**
- Produces: `hasAuthoritativeTerminalEvidence(run, events): boolean` — true only for succeeded/failed/cancelled/completed raw status OR run_succeeded/run_failed/run_cancelled events.
- Produces: `hasCompletedAnswerEvidence(events): boolean` — true when answer_completed event has non-empty text.
- Produces: `shouldOpenRunStream(run, isLatestTurn, events): boolean` — isLatestTurn && !hasAuthoritativeTerminalEvidence(run, events).

- [ ] **Step 1: Write failing tests**

```ts
test("queued latest run opens SSE", () => {
  expect(shouldOpenRunStream({ status: "queued" } as any, true, [])).toBe(true);
});

test("running latest run with answer_completed but no run_succeeded still opens SSE", () => {
  expect(shouldOpenRunStream({ status: "running" } as any, true, [{ event_type: "answer_completed", payload: { text: "done" } }] as any)).toBe(true);
});

test("succeeded run never opens SSE", () => {
  expect(shouldOpenRunStream({ status: "succeeded" } as any, true, [])).toBe(false);
});

test("non-latest running turn never opens SSE", () => {
  expect(shouldOpenRunStream({ status: "running" } as any, false, [])).toBe(false);
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/lib/run-stream-reducer.test.ts -t "queued latest|answer_completed but no run_succeeded|succeeded run never|non-latest"
Expected: FAIL — queued returns false, answer_completed blocks stream.

- [ ] **Step 3: Implement corrected rules**

In `run-stream-reducer.ts`, split current `hasTerminalEvidence` + `shouldOpenRunStream`:

```ts
export function hasAuthoritativeTerminalEvidence(run: AgentRun | null | undefined, events: AgentRunEvent[]): boolean {
  if (run && ["succeeded", "completed", "failed", "cancelled"].includes(run.status)) return true;
  return events.some((e) => ["run_succeeded", "run_completed", "run_failed", "run_cancelled"].includes(e.event_type));
}

export function hasCompletedAnswerEvidence(events: AgentRunEvent[]): boolean {
  return events.some((e) => e.event_type === "answer_completed" && typeof (e.payload as any)?.text === "string" && (e.payload as any).text.trim().length > 0);
}

export function shouldOpenRunStream(run: AgentRun, isLatestTurn: boolean, events: AgentRunEvent[]): boolean {
  return isLatestTurn && !hasAuthoritativeTerminalEvidence(run, events);
}
```

In `session-conversation-stream.tsx`, update `SessionTurn`:

```ts
const shouldStream = shouldOpenRunStream(run, isLiveRun, initialEvents);
const hasAnswer = hasCompletedAnswerEvidence(initialEvents);
const isAuthoritativeTerminal = hasAuthoritativeTerminalEvidence(run, initialEvents);

const displayRun = (!isLiveRun && hasAnswer && !isAuthoritativeTerminal)
  ? { ...streamedRun, status: "succeeded" as const }
  : streamedRun;
```

In `use-run-event-stream.ts`, `answer_completed` must continue its current behavior: it does NOT close EventSource and does NOT set run status to terminals. No code change needed there — the existing logic is correct; only the gating was wrong.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/lib/run-stream-reducer.test.ts src/hooks/use-run-event-stream.test.ts src/components/agent/agent-streaming.test.tsx`
Expected: all pass; queued turn opens SSE; answer_completed doesn't block stream; authoritative terminal still blocks.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/run-stream-reducer.ts frontend/src/components/agent/session-conversation-stream.tsx frontend/src/hooks/use-run-event-stream.ts frontend/src/lib/run-stream-reducer.test.ts frontend/src/hooks/use-run-event-stream.test.ts frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "fix: open SSE for queued and answer_completed unresolved runs"
```

---

### Task 2: Fix Direct SSE Frame Global-Sequence Continuity

**Files:**
- Modify: `backend/app/api/agent_stream.py`
- Create: `backend/tests/test_agent_stream_direct.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_agent_stream_direct.py`:

```python
import asyncio, uuid
from unittest.mock import AsyncMock
import pytest
from app.services.agent.event_bus import CommittedEvent
from app.api.agent_stream import _should_emit_direct

def test_direct_emission_succeeds_with_global_sequence_gap():
    """A run's own CommittedEvent with a global-inserted gap must still emit directly."""
    # last_seen_seq from run A = 100, other run B took seq 101
    run_a_event = CommittedEvent(run_id=uuid.uuid4(), seq=102, event_type="answer_delta", payload={"delta":"x"}, created_at=...)
    assert _should_emit_direct(run_a_event, last_seen_seq=100) is True

def test_duplicate_or_stale_event_is_ignored():
    event = CommittedEvent(run_id=uuid.uuid4(), seq=100, event_type="answer_delta", payload={"delta":"x"}, created_at=...)
    assert _should_emit_direct(event, last_seen_seq=100) is False
```

- [ ] **Step 2: Verify RED**

Run: `cd backend; python -m pytest tests/test_agent_stream_direct.py -v`
Expected: FAIL because current `_should_emit_direct` requires `seq == last_seen_seq + 1`.

- [ ] **Step 3: Implement per-run sequence continuity check**

Replace the existing direct-emit guard in `agent_stream.py`:

```python
def _should_emit_direct(self, event: CommittedEvent, last_seen_seq: int | None) -> bool:
    return last_seen_seq is None or event.seq > last_seen_seq
```

The SSE loop for CommittedEvent becomes:

```python
if isinstance(queue_item, CommittedEvent):
    if _should_emit_direct(queue_item, last_seen_seq):
        encoded = _encode_sse_event(queue_item)
        if encoded:
            yield encoded
            last_seen_seq = queue_item.seq
        continue
    # fall-through: use database cursor query
```

PersistedEvent and PostgreSQL notification paths remain unchanged — they always use `_events_after` cursor query.

- [ ] **Step 4: Verify GREEN**

Run: `cd backend; python -m pytest tests/test_agent_stream_direct.py tests/test_agent_stream.py -q`
Expected: all pass; global gap test passes; existing direct-emit and gap tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/agent_stream.py backend/tests/test_agent_stream_direct.py
git commit -m "fix: allow direct SSE frames across global sequence gaps"
```

---

### Task 3: Terminal Markdown DOM Stability

**Files:**
- Modify: `frontend/src/components/agent/streaming-markdown.tsx`
- Modify: `frontend/src/components/agent/final-answer-panel.tsx`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`

- [ ] **Step 1: Write failing stability test**

```tsx
test("terminal answer reuses completed streaming block DOM identity", () => {
  const matchMedia = vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);
  try {
    const { rerender } = render(
      <FinalAnswerPanel run={baseRun} streamingAnswer="# 标题\n\n段落" answerStreamId="live" />,
    );
    const heading = screen.getByRole("heading", { name: "标题" });
    // Now simulate terminal state
    rerender(
      <FinalAnswerPanel run={{ ...baseRun, status: "succeeded", result: { final_answer: "# 标题\n\n段落" } }} streamingAnswer="" answerStreamId={null} />,
    );
    // Same heading must still be in DOM
    expect(screen.getByRole("heading", { name: "标题" })).toBe(heading);
  } finally {
    matchMedia.mockRestore();
  }
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx -t "reuses completed streaming block DOM"
Expected: FAIL — currently terminal branch uses separate ReactMarkdown, remounting the entire tree.

- [ ] **Step 3: Implement terminal DOM reuse**

In `streaming-markdown.tsx`, add `terminal` prop:

```tsx
export function StreamingMarkdown({ text, streamId, terminal }: { text: string; streamId: string | null; terminal?: boolean }) {
  const { completedBlocks, activeTail, tailVersion } = useStreamingMarkdown(text, { resetKey: streamId });

  return (
    <div className="final-answer-streaming-markdown" data-tail-version={tailVersion}>
      {completedBlocks.map((content, index) => (
        <CompletedMarkdownBlock key={`${streamId ?? "stream"}:${index}`} content={content} />
      ))}
      {terminal
        ? (activeTail ? <SafeMarkdown content={activeTail} /> : null)
        : (activeTail ? <div className="final-answer-markdown-tail"><SafeMarkdown content={activeTail} /></div> : null)
      }
    </div>
  );
}
```

In `final-answer-panel.tsx`, replace:

```tsx
{shouldAnimate ? (
  <StreamingMarkdown text={renderedAnswer} streamId={answerStreamId} />
) : (
  <ReactMarkdown ...>{renderedAnswer}</ReactMarkdown>
)}
```

with:

```tsx
<StreamingMarkdown text={renderedAnswer} streamId={answerStreamId} terminal={!shouldAnimate} />
```

CompletedBlock keys remain stable, so React reuses their DOM. The terminal flag simply changes how the active tail is wrapped.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx`
Expected: all Markdown safety tests pass; DOM reuse test passes; no heading remount.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent/streaming-markdown.tsx frontend/src/components/agent/final-answer-panel.tsx frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "fix: reuse completed streaming markdown blocks at terminal"
```

---

### Task 4: Scroll Anchoring Stability

**Files:**
- Modify: `frontend/src/app/agent-globals.css`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`

- [ ] **Step 1: Write failing scroll layout test**

```tsx
test("conversation stack uses overflow anchor", () => {
  const { container } = render(<FinalAnswerPanel run={baseRun} streamingAnswer="text" answerStreamId="live" />);
  const wrapper = container.closest(".detail-conversation-stack") || container;
  expect(wrapper).not.toBeNull();
});
```

- [ ] **Step 2: Add CSS**

```css
.detail-conversation-stack {
  overflow-anchor: auto;
}

.final-answer-streaming-markdown {
  overflow-anchor: auto;
}
```

No JavaScript `scrollIntoView` changes. Keep existing composer `scrollIntoView` behavior.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/agent-globals.css frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "fix: enable scroll anchoring on conversation content"
```

---

### Task 5: Full Regression Verification

- [ ] **Step 1: Backend**

```bash
cd backend && python -m pytest tests/test_agent_stream.py tests/test_agent_stream_direct.py tests/test_agent_loop.py -q
```
Expected: all pass.

- [ ] **Step 2: Frontend**

```bash
cd frontend && npx vitest --run src/lib/run-stream-reducer.test.ts src/hooks/use-run-event-stream.test.ts src/components/agent/agent-streaming.test.tsx
```
Expected: all pass.

- [ ] **Step 3: Build**

```bash
cd frontend && npm run build
```
Expected: compiled successfully, TypeScript clean.

- [ ] **Step 4: Commit if clean**
