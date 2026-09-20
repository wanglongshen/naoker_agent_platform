# Real-Time Answer Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate final-answer typewriter backlog so visible text tracks received model output by the next frame, render every active answer through SafeMarkdown without a plain-text fallback, make the first provider chunk immediate, and neutralize blue list markers.

**Architecture:** A new `useLiveAnswerText` hook replaces `useTypingText` for final answers, exposing the newest target atomically every frame with at most one pending RAF. `FinalAnswerPanel` always routes through `StreamingMarkdown` during active generation. Backend delta thresholds become named settings and honour an immediate first-chunk flush.

**Tech Stack:** React 19/TypeScript/Vitest, Python 3.12+/FastAPI/SQLAlchemy async, `react-markdown`/`remark-gfm`.

## Global Constraints

- Final answers must render through `SafeMarkdown` at every frame; no plain-text fallback during active generation.
- At most one pending RAF for final-answer presentation, at most one React state update per frame.
- Historical, terminal, non-live, and reduced-motion answers remain static.
- First non-empty provider chunk flushes immediately.
- Subsequent backend coalescing uses configurable thresholds.
- Cursor replay, checkpoint, direct same-process SSE, PostgreSQL notification, compensation polling, Markdown URL safety, and HTML safety remain intact.
- Commit after every task.

---

## File Structure

| File | Purpose |
| --- | --- |
| `frontend/src/hooks/use-live-answer-text.ts` | Real-time answer hook (no typewriter backlog). |
| `frontend/src/hooks/use-live-answer-text.test.ts` | RAF coalescing, latest-target exposure, reset tests. |
| `frontend/src/components/agent/final-answer-panel.tsx` | Wire `useLiveAnswerText` and always render `StreamingMarkdown`. |
| `frontend/src/app/agent-globals.css` | Neutral list marker color. |
| `frontend/src/components/agent/agent-streaming.test.tsx` | Integration tests. |
| `backend/app/core/config.py` | New delta threshold settings. |
| `backend/app/services/agent/loop.py` | First-chunk immediate flush + configurable thresholds. |
| `backend/tests/test_agent_loop.py` | First-chunk, threshold, completion-flush tests. |

---

### Task 1: Neutral List Markers (CSS)

**Files:**
- Modify: `frontend/src/app/agent-globals.css:1727-1730`

- [ ] **Step 1: Write failing color test**

Add to `frontend/src/components/agent/agent-streaming.test.tsx`:

```tsx
test("final-answer list markers inherit neutral text color", () => {
  const { container } = render(
    <FinalAnswerPanel
      run={makeRun({ status: "succeeded", result: { final_answer: "- 列表项\n- 另一项" } })}
      streamingAnswer="" answerStreamId={null}
    />,
  );
  const style = getComputedStyle(container.querySelector("li")!);
  // marker pseudo-element style is not directly accessible in jsdom.
  // Assert the rule is present in stylesheet instead.
  const sheets = Array.from(document.styleSheets);
  const ruleText = sheets.flatMap((s) => {
    try { return Array.from(s.cssRules).map((r) => r.cssText); }
    catch { return []; }
  }).find((t) => t.includes(".final-answer-prose li::marker"));
  expect(ruleText).toBeDefined();
  expect(ruleText).toContain("currentColor");
  expect(ruleText).not.toMatch(/#[0-9a-fA-F]{3,6}/);
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx -t "final-answer list markers"`
Expected: FAIL because `currentColor` is not present.

- [ ] **Step 3: Change marker color**

In `frontend/src/app/agent-globals.css`, change:

```css
.final-answer-prose li::marker {
  color: currentColor;
  font-weight: 700;
}
```

Do not alter any other final-answer-prose rules.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx -t "final-answer list markers"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/agent-globals.css frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "style: neutral answer list markers"
```

---

### Task 2: Real-Time Final-Answer Presentation

**Files:**
- Create: `frontend/src/hooks/use-live-answer-text.ts`
- Create: `frontend/src/hooks/use-live-answer-text.test.ts`
- Modify: `frontend/src/components/agent/final-answer-panel.tsx`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`

**Interfaces:**
- Produces: `useLiveAnswerText(targetText: string, options: { enabled: boolean; resetKey: string | null }): string`

- [ ] **Step 1: Write failing hook tests**

Create `frontend/src/hooks/use-live-answer-text.test.ts`:

```tsx
import { act, renderHook } from "@testing-library/react";
import { describe, expect, test, vi, afterEach } from "vitest";
import { useLiveAnswerText } from "@/hooks/use-live-answer-text";

function installFakeRaf() {
  let nextId = 1;
  const frames = new Map<number, (ts: number) => void>();
  const raf = vi.fn((cb: (ts: number) => void) => { const id = nextId++; frames.set(id, cb); return id; });
  const caf = vi.fn((id: number) => frames.delete(id));
  vi.stubGlobal("requestAnimationFrame", raf);
  vi.stubGlobal("cancelAnimationFrame", caf);
  return {
    pendingCount: () => frames.size,
    runNextFrame(ts: number) {
      const [id, cb] = frames.entries().next().value ?? [];
      if (!id) return;
      frames.delete(id);
      cb(ts);
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("useLiveAnswerText", () => {
  test("renders target immediately when disabled", () => {
    const { result } = renderHook(() => useLiveAnswerText("full answer", { enabled: false, resetKey: "s1" }));
    expect(result.current).toBe("full answer");
  });

  test("exposes the latest target after one RAF frame", () => {
    const raf = installFakeRaf();
    const { result, rerender } = renderHook(
      ({ text }) => useLiveAnswerText(text, { enabled: true, resetKey: "s1" }),
      { initialProps: { text: "hello" } },
    );
    // Initial render starts with target (no backlog)
    expect(result.current).toBe("hello");

    rerender({ text: "hello world" });
    // Target changed but RAF hasn't fired yet; still at previous
    expect(result.current).toBe("hello");
    expect(raf.pendingCount()).toBe(1);

    act(() => raf.runNextFrame(16));
    expect(result.current).toBe("hello world");
    expect(raf.pendingCount()).toBe(0);
  });

  test("coalesces multiple target updates before a single frame", () => {
    const raf = installFakeRaf();
    const { result, rerender } = renderHook(
      ({ text }) => useLiveAnswerText(text, { enabled: true, resetKey: "s1" }),
      { initialProps: { text: "a" } },
    );
    expect(result.current).toBe("a");

    rerender({ text: "ab" });
    rerender({ text: "abc" });
    rerender({ text: "abcd" });
    expect(raf.pendingCount()).toBe(1);

    act(() => raf.runNextFrame(16));
    expect(result.current).toBe("abcd");
  });

  test("resets on stream generation change", () => {
    const raf = installFakeRaf();
    const { result, rerender } = renderHook(
      ({ text, resetKey }) => useLiveAnswerText(text, { enabled: true, resetKey }),
      { initialProps: { text: "old stream", resetKey: "one" } },
    );
    act(() => raf.runNextFrame(16));
    expect(result.current).toBe("old stream");

    rerender({ text: "new stream", resetKey: "two" });
    // On reset, render target immediately
    expect(result.current).toBe("new stream");
  });

  test("cleans up pending RAF on unmount", () => {
    const raf = installFakeRaf();
    const { unmount, rerender } = renderHook(
      ({ text }) => useLiveAnswerText(text, { enabled: true, resetKey: "s1" }),
      { initialProps: { text: "a" } },
    );
    rerender({ text: "ab" });
    unmount();
    expect(raf.pendingCount()).toBe(0);
  });
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/hooks/use-live-answer-text.test.ts`
Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement useLiveAnswerText**

Create `frontend/src/hooks/use-live-answer-text.ts`:

```ts
"use client";

import { useEffect, useRef, useState } from "react";

export function useLiveAnswerText(
  targetText: string,
  options: { enabled: boolean; resetKey: string | null },
): string {
  const { enabled, resetKey } = options;
  const [displayedText, setDisplayedText] = useState(enabled ? targetText : "");
  const pendingRef = useRef(false);
  const targetRef = useRef(targetText);
  const resetKeyRef = useRef(resetKey);

  useEffect(() => {
    if (resetKeyRef.current !== resetKey) {
      resetKeyRef.current = resetKey;
      pendingRef.current = false;
      targetRef.current = targetText;
      setDisplayedText(targetText);
      return;
    }
  }, [resetKey, targetText]);

  useEffect(() => {
    if (resetKeyRef.current !== resetKey) return;
    targetRef.current = targetText;
    if (!enabled) {
      setDisplayedText(targetText);
      return;
    }
    if (displayedText === targetText) return;
    if (pendingRef.current) return;
    pendingRef.current = true;
    const id = requestAnimationFrame(() => {
      pendingRef.current = false;
      setDisplayedText(targetRef.current);
    });
    return () => {
      cancelAnimationFrame(id);
      pendingRef.current = false;
    };
  }, [targetText, enabled, displayedText, resetKey]);

  return enabled ? displayedText : targetText;
}
```

- [ ] **Step 4: Wire into FinalAnswerPanel**

In `frontend/src/components/agent/final-answer-panel.tsx`:

1. Import `useLiveAnswerText` from `@/hooks/use-live-answer-text`.
2. Import `StreamingMarkdown` from `@/components/agent/streaming-markdown`.
3. Replace:

```tsx
const animatedAnswer = useTypingText(answerToRender ?? "", {
  enabled: shouldAnimate,
  resetKey: shouldAnimate ? answerStreamId : null,
});
const renderedAnswer = shouldAnimate ? animatedAnswer : answerToRender;
```

with:

```tsx
const liveAnswer = useLiveAnswerText(answerToRender ?? "", {
  enabled: shouldAnimate,
  resetKey: shouldAnimate ? answerStreamId : null,
});
const renderedAnswer = shouldAnimate ? liveAnswer : answerToRender;
```

4. In the active branch, replace the plain text div:

```tsx
{shouldAnimate ? (
  <div className="final-answer-streaming-text">{renderedAnswer}</div>
) : (
  <ReactMarkdown ...>{renderedAnswer}</ReactMarkdown>
)}
```

with always using `StreamingMarkdown`:

```tsx
{shouldAnimate ? (
  <StreamingMarkdown text={renderedAnswer} streamId={answerStreamId} />
) : (
  <ReactMarkdown ...>{renderedAnswer}</ReactMarkdown>
)}
```

5. Remove the now-unused `useTypingText` import from `final-answer-panel.tsx`.

6. Remove the obsolete CSS rule for `.final-answer-streaming-text` (line ~2603-2606 in agent-globals.css) since it is no longer used for final answers, but keep it if thought narrative still uses it. Check: thought narrative does not use this class, so remove it safely.

- [ ] **Step 5: Update integration tests**

Update the existing test `"keeps active streaming markdown as stable text until the answer is terminal"` in `agent-streaming.test.tsx`. This test was written for the previous plain-text-to-Markdown transition design. Now that active streaming always uses Markdown:

```tsx
test("streaming answer renders headings and completed blocks as Markdown before terminal", () => {
  const matchMedia = vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);
  try {
    render(
      <FinalAnswerPanel
        run={baseRun}
        streamingAnswer="# 标题\n\n完成的段落。\n\n活动"
        answerStreamId="live-md"
      />,
    );
    // Heading must be rendered as Markdown, not plain text
    expect(screen.getByRole("heading", { name: "标题" })).toBeVisible();
    // Completed paragraph visible
    expect(screen.getByText("完成的段落。")).toBeVisible();
    // Active tail also visible
    expect(screen.getByText("活动")).toBeVisible();
  } finally {
    matchMedia.mockRestore();
  }
});
```

- [ ] **Step 6: Verify GREEN**

Run: `cd frontend; npx vitest --run src/hooks/use-live-answer-text.test.ts src/components/agent/agent-streaming.test.tsx`
Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/use-live-answer-text.ts frontend/src/hooks/use-live-answer-text.test.ts frontend/src/components/agent/final-answer-panel.tsx frontend/src/app/agent-globals.css frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "feat: real-time final-answer presentation with always-on Markdown"
```

---

### Task 3: Configurable Backend First-Chunk Immediate + Shorter Coalesce

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/agent/loop.py` (around `_stream_final_answer`)
- Modify: `backend/tests/test_agent_loop.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_agent_loop.py`:

```python
@pytest.mark.anyio
async def test_first_non_empty_provider_chunk_flushes_immediately():
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    class FakeClient:
        async def stream_text(self, messages):
            yield "首"

    service = AgentLoopService()
    service.llm_client = FakeClient()

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    events: list[tuple[str, dict]] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload: events.append((event_type, payload))
    )

    answer = await service._stream_final_answer(None, ctx, [{"role": "user", "content": "测试"}])

    assert answer == "首"
    event_types = [e[0] for e in events]
    assert event_types == ["answer_started", "answer_delta", "answer_completed"]
    assert events[1][1]["delta"] == "首"
```

- [ ] **Step 2: Verify RED**

Run: `cd backend; python -m pytest tests/test_agent_loop.py -k "first_non_empty" -v`
Expected: FAIL because first chunk is buffered until 24 characters or 50ms.

- [ ] **Step 3: Implement configurable first-delta and shorter coalesce**

In `backend/app/core/config.py`, add:

```python
agent_answer_delta_flush_characters: int = 48
agent_answer_delta_flush_seconds: float = 0.025
```

In `backend/app/services/agent/loop.py`, in `_stream_final_answer`:

Replace hard-coded values with settings:

```python
delta_flush_characters = settings.agent_answer_delta_flush_characters
delta_flush_seconds = settings.agent_answer_delta_flush_seconds
```

After `answer = ""` and before the first provider chunk, add:

```python
first_chunk_flushed = False
```

In the provider-chunk loop, after appending to `pending_delta`:

```python
if not first_chunk_flushed:
    await flush_delta()
    first_chunk_flushed = True
    continue
```

This ensures the first non-empty chunk is persisted and notified immediately, before the normal coalescing logic runs on subsequent chunks.

- [ ] **Step 4: Verify GREEN**

Run: `cd backend; python -m pytest tests/test_agent_loop.py -q`
Expected: all 18+ tests pass, including new first-chunk test and existing coalesce test.

- [ ] **Step 5: Update `.env.example`**

Add to `backend/.env.example`:

```env
AGENT_ANSWER_DELTA_FLUSH_CHARACTERS=48
AGENT_ANSWER_DELTA_FLUSH_SECONDS=0.025
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/app/services/agent/loop.py backend/tests/test_agent_loop.py backend/.env.example
git commit -m "perf: immediate first answer delta and shorter backend coalesce"
```

---

### Task 4: Full Regression Verification

- [ ] **Step 1: Run backend tests**

```bash
cd backend && python -m pytest tests/test_agent_loop.py tests/test_agent_stream.py tests/test_visible_thought_overlap.py -q
```
Expected: all pass.

- [ ] **Step 2: Run frontend stream/markdown/animation tests**

```bash
cd frontend && npx vitest --run src/hooks/use-live-answer-text.test.ts src/components/agent/agent-streaming.test.tsx src/hooks/use-streaming-markdown.test.ts src/hooks/use-typing-text.test.ts src/lib/typing-animation.test.ts src/lib/streaming-markdown.test.ts
```
Expected: all pass.

- [ ] **Step 3: Production build**

```bash
cd frontend && npm run build
```
Expected: compiled successfully, TypeScript clean.

- [ ] **Step 4: Commit if clean**

```bash
git status --short
git diff --check
```
