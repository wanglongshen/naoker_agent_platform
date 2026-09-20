# Incremental Streaming Markdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render Markdown while an answer streams without reparsing completed answer content on every animation frame, while allowing bounded high-backlog catch-up that does not create long main-thread tasks.

**Architecture:** The answer transport reducer continues to accept every `answer_delta` in order. `useTypingText` remains the single RAF-driven presentation scheduler, but uses capped adaptive reveal counts. A new append-only Markdown partitioner turns the displayed prefix into immutable completed Markdown blocks plus one active Markdown tail. Completed blocks render through memoized `ReactMarkdown` and never reparse unless the stream generation resets; only the active tail is reparsed at a bounded cadence. On terminal state, the existing full-document Markdown renderer remains the canonical final render.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, `react-markdown`, `remark-gfm`, `requestAnimationFrame`.

## Global Constraints

- Preserve every currently supported terminal Markdown feature: GFM tables, fenced code, task lists, safe links, focusable table scroll, and focusable code scroll.
- During `running`, Markdown must be visible in completed blocks and the active tail; do not revert to plain-text-only streaming.
- Never run a character-by-character loop to catch up a large backlog.
- Each animation frame may perform at most one string slice and one displayed-text state update.
- Every non-terminal reveal count must be capped at 48 characters per frame.
- The active Markdown tail must be reparsed no more frequently than every 80 ms while it has changed.
- Completed Markdown blocks must retain stable keys and must not reparse when a later delta only changes the active tail.
- Never render raw HTML; retain `skipHtml` and the current `classifyHref` policy.
- Answer delta events must remain available for diagnostics, but answer-only deltas must not cause the thought narrative to rebuild.
- Reset all incremental state only when `answerStreamId` changes or displayed text ceases to extend the previous source.
- Do not modify the backend chunk contract in this work.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `frontend/src/lib/streaming-markdown.ts` | Append-only Markdown block partitioner and tail snapshot model. |
| `frontend/src/lib/streaming-markdown.test.ts` | Pure partitioner behavior, fenced code, table/list boundaries, resets, and append-only invariants. |
| `frontend/src/lib/typing-animation.ts` | Bounded adaptive per-frame reveal policy. |
| `frontend/src/lib/typing-animation.test.ts` | Exact per-frame caps for normal, large, and terminal backlog. |
| `frontend/src/hooks/use-streaming-markdown.ts` | React adapter that incrementally feeds displayed answer text into the partitioner and throttles the active-tail render version. |
| `frontend/src/hooks/use-streaming-markdown.test.ts` | Hook lifecycle, 80 ms tail throttle, reset, and stable completed-block references. |
| `frontend/src/components/agent/streaming-markdown.tsx` | Memoized completed Markdown blocks and active-tail Markdown renderer sharing the existing safe component map. |
| `frontend/src/components/agent/final-answer-panel.tsx` | Replaces active plain text with `StreamingMarkdown`; keeps terminal full-document render unchanged. |
| `frontend/src/components/agent/agent-streaming.test.tsx` | Integration tests for live headings/lists/code, stable completed DOM, terminal safety, and no active plain-text fallback. |
| `frontend/src/lib/run-stream-reducer.ts` | Adds a narrative-only event collection or revision so answer deltas do not invalidate thought rendering. |
| `frontend/src/components/agent/detail-conversation.tsx` | Passes narrative-only event data to `ThoughtNarrative`. |
| `frontend/src/lib/run-stream-reducer.test.ts` | Verifies answer deltas preserve diagnostics but do not advance narrative revision. |

---

### Task 1: Bounded Adaptive Reveal Policy

**Files:**
- Modify: `frontend/src/lib/typing-animation.ts:6-42`
- Modify: `frontend/src/lib/typing-animation.test.ts:1-48`

**Interfaces:**
- Produces: `advanceTypingAnimation(...)` that reveals at most 48 characters per non-terminal frame and still returns an answer prefix.
- Consumes: Existing `TypingAnimationState` and terminal catch-up contract.

- [ ] **Step 1: Write failing large-backlog tests**

Add to `frontend/src/lib/typing-animation.test.ts`:

```ts
test("reveals a bounded 48 characters for an extreme non-terminal backlog", () => {
  const target = "a".repeat(10_000);
  const next = advanceTypingAnimation({ displayedText: "", elapsedMs: 0 }, target, 16, 16);

  expect(next.displayedText).toHaveLength(48);
  expect(target.startsWith(next.displayedText)).toBe(true);
});

test("never performs a terminal catch-up larger than the remaining target", () => {
  const target = "a".repeat(1_000);
  const next = advanceTypingAnimation({ displayedText: "a".repeat(990), elapsedMs: 0 }, target, 16, 16, true);

  expect(next.displayedText).toBe(target);
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/lib/typing-animation.test.ts`

Expected: the 10,000-character test fails because the current non-terminal cap is eight characters.

- [ ] **Step 3: Implement the bounded adaptive policy**

Replace `charactersPerFrame` with:

```ts
function charactersPerFrame(backlog: number, terminal: boolean): number {
  if (terminal) return Math.max(1, Math.ceil(backlog / 12));
  if (backlog > 2_000) return 48;
  if (backlog > 1_000) return 32;
  if (backlog > 400) return 24;
  if (backlog > 160) return 16;
  if (backlog > 48) return 8;
  if (backlog > 12) return 4;
  return 1;
}
```

Keep the existing single `targetText.slice(...)` operation. Do not add a loop over characters.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/lib/typing-animation.test.ts src/hooks/use-typing-text.test.ts`

Expected: all tests pass; no frame reveals more than 48 non-terminal characters.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/typing-animation.ts frontend/src/lib/typing-animation.test.ts
```

---

### Task 2: Append-Only Markdown Partitioner

**Files:**
- Create: `frontend/src/lib/streaming-markdown.ts`
- Create: `frontend/src/lib/streaming-markdown.test.ts`

**Interfaces:**
- Produces:

```ts
export type StreamingMarkdownState = {
  source: string;
  completedBlocks: readonly string[];
  activeTail: string;
  pendingLine: string;
  fence: "`" | "~" | null;
};

export type StreamingMarkdownSnapshot = {
  completedBlocks: readonly string[];
  activeTail: string;
};

export function createStreamingMarkdownState(): StreamingMarkdownState;
export function appendStreamingMarkdown(
  state: StreamingMarkdownState,
  source: string,
): StreamingMarkdownState;
export function snapshotStreamingMarkdown(
  state: StreamingMarkdownState,
): StreamingMarkdownSnapshot;
```

- [ ] **Step 1: Write failing partitioner tests**

Create `frontend/src/lib/streaming-markdown.test.ts`:

```ts
import { describe, expect, test } from "vitest";
import {
  appendStreamingMarkdown,
  createStreamingMarkdownState,
  snapshotStreamingMarkdown,
} from "@/lib/streaming-markdown";

describe("streaming markdown partitioner", () => {
  test("freezes a paragraph after a blank line and keeps later text in the tail", () => {
    const first = appendStreamingMarkdown(createStreamingMarkdownState(), "# 标题\n\n第一段\n\n第二");
    const snapshot = snapshotStreamingMarkdown(first);

    expect(snapshot.completedBlocks).toEqual(["# 标题\n\n", "第一段\n\n"]);
    expect(snapshot.activeTail).toBe("第二");
  });

  test("does not freeze a fenced code block until its closing fence arrives", () => {
    const partial = appendStreamingMarkdown(createStreamingMarkdownState(), "```ts\nconst value = 1;\n");
    expect(snapshotStreamingMarkdown(partial)).toEqual({ completedBlocks: [], activeTail: "```ts\nconst value = 1;\n" });

    const completed = appendStreamingMarkdown(partial, "```\n\n下一段");
    expect(snapshotStreamingMarkdown(completed)).toEqual({
      completedBlocks: ["```ts\nconst value = 1;\n```\n"],
      activeTail: "\n下一段",
    });
  });

  test("preserves prior completed block references when only the tail grows", () => {
    const first = appendStreamingMarkdown(createStreamingMarkdownState(), "完成段落\n\n尾");
    const before = snapshotStreamingMarkdown(first);
    const second = appendStreamingMarkdown(first, "完成段落\n\n尾部继续");
    const after = snapshotStreamingMarkdown(second);

    expect(after.completedBlocks).toBe(before.completedBlocks);
    expect(after.activeTail).toBe("尾部继续");
  });

  test("rebuilds safely when a new source is not an extension of the prior source", () => {
    const prior = appendStreamingMarkdown(createStreamingMarkdownState(), "旧内容\n\n尾部");
    const reset = appendStreamingMarkdown(prior, "新内容");

    expect(snapshotStreamingMarkdown(reset)).toEqual({ completedBlocks: [], activeTail: "新内容" });
  });
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/lib/streaming-markdown.test.ts`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement line-based append-only partitioning**

Create `frontend/src/lib/streaming-markdown.ts` with these rules:

1. If `source` does not start with `state.source`, reset to `createStreamingMarkdownState()` and process all source text.
2. Process only `source.slice(state.source.length)` character data.
3. Accumulate unfinished characters in `pendingLine`; commit a line only after `\n` arrives.
4. A blank line outside a fenced code block seals the current block into `completedBlocks`.
5. A line whose trimmed start begins with three or more matching backticks or tildes toggles the fence state. A closing fence seals the fenced block immediately; keep a following blank line for the next active tail.
6. Do not mutate `completedBlocks`; create a new array only when a new block seals. Return the existing array reference when only `activeTail` changes.
7. `snapshotStreamingMarkdown()` returns the completed blocks and a tail formed from the current unsealed block plus `pendingLine`.

Implement helpers with these exact signatures:

```ts
function fenceMarker(line: string): "`" | "~" | null;
function isClosingFence(line: string, fence: "`" | "~"): boolean;
function appendCommittedLine(state: StreamingMarkdownState, line: string): StreamingMarkdownState;
```

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/lib/streaming-markdown.test.ts`

Expected: all four tests pass.

- [ ] **Step 5: Extend coverage for GFM-safe boundaries**

Add these tests before committing:

```ts
test("keeps a table in the active tail until a blank line seals it", () => {
  const state = appendStreamingMarkdown(
    createStreamingMarkdownState(),
    "| 名称 | 值 |\n| --- | --- |\n| 韭菜 | 300g |\n\n下一段",
  );
  expect(snapshotStreamingMarkdown(state)).toEqual({
    completedBlocks: ["| 名称 | 值 |\n| --- | --- |\n| 韭菜 | 300g |\n\n"],
    activeTail: "下一段",
  });
});

test("keeps an unfinished list in the active tail", () => {
  const state = appendStreamingMarkdown(createStreamingMarkdownState(), "- 鸡蛋\n- 韭菜");
  expect(snapshotStreamingMarkdown(state)).toEqual({ completedBlocks: [], activeTail: "- 鸡蛋\n- 韭菜" });
});
```

Run: `cd frontend; npx vitest --run src/lib/streaming-markdown.test.ts`

Expected: all six tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/streaming-markdown.ts frontend/src/lib/streaming-markdown.test.ts
```

---

### Task 3: Throttled Streaming Markdown Hook

**Files:**
- Create: `frontend/src/hooks/use-streaming-markdown.ts`
- Create: `frontend/src/hooks/use-streaming-markdown.test.ts`

**Interfaces:**
- Consumes: `appendStreamingMarkdown`, `createStreamingMarkdownState`, `snapshotStreamingMarkdown` from Task 2.
- Produces:

```ts
export type StreamingMarkdownView = {
  completedBlocks: readonly string[];
  activeTail: string;
  tailVersion: number;
};

export function useStreamingMarkdown(
  displayedText: string,
  options: { resetKey: string | null; tailIntervalMs?: number },
): StreamingMarkdownView;
```

- [ ] **Step 1: Write failing hook tests**

Create `frontend/src/hooks/use-streaming-markdown.test.ts`:

```tsx
import { act, renderHook } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { useStreamingMarkdown } from "@/hooks/use-streaming-markdown";

describe("useStreamingMarkdown", () => {
  test("returns completed Markdown blocks immediately while throttling only the active tail version", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ text }) => useStreamingMarkdown(text, { resetKey: "stream-1", tailIntervalMs: 80 }),
      { initialProps: { text: "# 标题\n\n第一段\n\n尾" } },
    );

    expect(result.current.completedBlocks).toEqual(["# 标题\n\n", "第一段\n\n"]);
    const firstTailVersion = result.current.tailVersion;

    rerender({ text: "# 标题\n\n第一段\n\n尾部继续" });
    expect(result.current.activeTail).toBe("尾");
    expect(result.current.tailVersion).toBe(firstTailVersion);

    act(() => vi.advanceTimersByTime(80));
    expect(result.current.activeTail).toBe("尾部继续");
    expect(result.current.tailVersion).toBe(firstTailVersion + 1);
    vi.useRealTimers();
  });

  test("resets completed blocks when resetKey changes", () => {
    const { result, rerender } = renderHook(
      ({ text, resetKey }) => useStreamingMarkdown(text, { resetKey }),
      { initialProps: { text: "旧段\n\n旧尾", resetKey: "one" } },
    );

    rerender({ text: "新尾", resetKey: "two" });
    expect(result.current.completedBlocks).toEqual([]);
    expect(result.current.activeTail).toBe("新尾");
  });
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/hooks/use-streaming-markdown.test.ts`

Expected: FAIL because the hook does not exist.

- [ ] **Step 3: Implement the hook**

Implement these behaviors:

1. Keep the append-only `StreamingMarkdownState` in a ref.
2. On `resetKey` change, reset the partitioner and cancel any tail timer.
3. Feed every new `displayedText` immediately to the partitioner so completed blocks become available in the same React update.
4. Publish completed block changes immediately.
5. If only `activeTail` changed, queue a single `setTimeout` for the remaining duration until 80ms since the last published tail. Do not queue more than one timer.
6. A tail timer publishes the latest partitioner snapshot, not a stale captured tail.
7. On unmount, cancel the timer.

Use `tailIntervalMs = 80` by default. Do not use `requestAnimationFrame` here; RAF already controls displayed text changes, while this hook independently bounds Markdown parsing frequency.

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/hooks/use-streaming-markdown.test.ts`

Expected: both tests pass with no pending timer after unmount.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/use-streaming-markdown.ts frontend/src/hooks/use-streaming-markdown.test.ts
```

---

### Task 4: Memoized Live Markdown Renderer

**Files:**
- Create: `frontend/src/components/agent/streaming-markdown.tsx`
- Modify: `frontend/src/components/agent/final-answer-panel.tsx:30-123`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`
- Modify: `frontend/src/app/agent-globals.css:2603-2606`

**Interfaces:**
- Consumes: `useStreamingMarkdown(displayedText, { resetKey })` from Task 3.
- Produces:

```tsx
export function StreamingMarkdown({ text, streamId }: {
  text: string;
  streamId: string | null;
}): React.ReactElement;
```

- [ ] **Step 1: Write failing integration tests**

Add to `frontend/src/components/agent/agent-streaming.test.tsx`:

```tsx
test("renders a completed streaming heading as Markdown before the answer terminates", () => {
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);

  render(
    <FinalAnswerPanel
      run={baseRun}
      streamingAnswer="# 韭菜炒鸡蛋\n\n第一步已经完成。\n\n正在"
      answerStreamId="live-markdown"
    />,
  );

  expect(screen.getByRole("heading", { name: "韭菜炒鸡蛋" })).toBeVisible();
  expect(screen.getByText("第一步已经完成。")).toBeVisible();
  expect(screen.getByText("正在")).toBeVisible();
});

test("keeps completed streaming markdown blocks mounted while the tail grows", () => {
  const matchMedia = vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);
  const { rerender } = render(
    <FinalAnswerPanel run={baseRun} streamingAnswer="# 标题\n\n稳定段落\n\n尾" answerStreamId="live-markdown" />,
  );
  const heading = screen.getByRole("heading", { name: "标题" });

  rerender(
    <FinalAnswerPanel run={baseRun} streamingAnswer="# 标题\n\n稳定段落\n\n尾部继续" answerStreamId="live-markdown" />,
  );

  expect(screen.getByRole("heading", { name: "标题" })).toBe(heading);
  matchMedia.mockRestore();
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/components/agent/agent-streaming.test.tsx -t "streaming heading|completed streaming markdown"`

Expected: FAIL because active streaming uses `.final-answer-streaming-text` plain text and has no live heading.

- [ ] **Step 3: Extract shared safe Markdown components**

In `final-answer-panel.tsx`, move the existing `ReactMarkdown` `components` map into an exported constant or reusable `SafeMarkdown` component in `streaming-markdown.tsx`.

The shared renderer must preserve this behavior exactly:

```tsx
<ReactMarkdown
  remarkPlugins={[remarkGfm]}
  skipHtml
  components={{
    a: ({ href, children, node: _node, ...props }) => {
      const { href: safeHref, external } = classifyHref(href);
      return (
        <a href={safeHref} {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})} {...props}>
          {children}
          {external ? <span className="sr-only">（在新标签页中打开）</span> : null}
        </a>
      );
    },
    table: ({ children, ...props }) => <div className="table-scroll" tabIndex={0}><table {...props}>{children}</table></div>,
    pre: ({ children, node: _node, ...props }) => <div className="code-scroll" tabIndex={0}><pre {...props}>{children}</pre></div>,
  }}
>
  {content}
</ReactMarkdown>
```

`classifyHref` must move with the shared renderer or remain exported from a narrowly named module; do not duplicate URL security logic.

- [ ] **Step 4: Implement `StreamingMarkdown`**

Create `streaming-markdown.tsx`:

```tsx
"use client";

import React from "react";
import { useStreamingMarkdown } from "@/hooks/use-streaming-markdown";

const CompletedMarkdownBlock = React.memo(function CompletedMarkdownBlock({ content }: { content: string }) {
  return <SafeMarkdown content={content} />;
});

export function StreamingMarkdown({ text, streamId }: { text: string; streamId: string | null }) {
  const { completedBlocks, activeTail, tailVersion } = useStreamingMarkdown(text, { resetKey: streamId });

  return (
    <div className="final-answer-streaming-markdown" data-tail-version={tailVersion}>
      {completedBlocks.map((content, index) => (
        <CompletedMarkdownBlock key={`${streamId ?? "stream"}:${index}`} content={content} />
      ))}
      {activeTail ? <div className="final-answer-markdown-tail"><SafeMarkdown content={activeTail} /></div> : null}
    </div>
  );
}
```

Use block index only because completed blocks are append-only for a stream generation. The `streamId` prefix guarantees a new generation does not reuse old DOM.

Replace only this active branch in `final-answer-panel.tsx`:

```tsx
<div className="final-answer-streaming-text">{renderedAnswer}</div>
```

with:

```tsx
<StreamingMarkdown text={renderedAnswer} streamId={answerStreamId} />
```

Do not change the non-active terminal `ReactMarkdown` branch.

- [ ] **Step 5: Add CSS that limits active-tail layout scope**

Replace `.final-answer-streaming-text` with:

```css
.final-answer-streaming-markdown {
  overflow-wrap: anywhere;
}

.final-answer-markdown-tail {
  contain: layout style;
  overflow-wrap: anywhere;
}
```

Do not use `contain: paint`, because active content must remain visible even when it expands outside an internal paint boundary.

- [ ] **Step 6: Verify GREEN and safety regression**

Run:

```bash
cd frontend
npx vitest --run src/components/agent/agent-streaming.test.tsx
```

Expected: all current Markdown safety tests pass, live streaming heading tests pass, and no raw HTML or unsafe link regression appears.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/agent/streaming-markdown.tsx frontend/src/components/agent/final-answer-panel.tsx frontend/src/components/agent/agent-streaming.test.tsx frontend/src/app/agent-globals.css
```

---

### Task 5: Isolate Thought Narrative From Answer Delta Churn

**Files:**
- Modify: `frontend/src/lib/run-stream-reducer.ts:125-345`
- Modify: `frontend/src/lib/run-stream-reducer.test.ts`
- Modify: `frontend/src/components/agent/detail-conversation.tsx`
- Modify: `frontend/src/components/agent/session-conversation-stream.tsx` if it passes the full event list to `ThoughtNarrative`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx` if integration expectations require adjustment

**Interfaces:**
- Produces `RunStreamState.narrativeEvents: AgentRunEvent[]` containing only events used to construct thought/tool narrative blocks.
- `RunStreamState.events` remains the full event history for diagnostics and replay displays.

- [ ] **Step 1: Write failing reducer test**

Add to `frontend/src/lib/run-stream-reducer.test.ts`:

```ts
test("keeps narrative events referentially stable for answer deltas", () => {
  const started = reduceRunStream(initialState, {
    type: "visible_thought_started",
    seq: 1,
    payload: { step_index: 0, stream_id: "thought-1" },
  });
  const narrativeEvents = started.narrativeEvents;

  const afterAnswer = reduceRunStream(started, {
    type: "answer_delta",
    seq: 2,
    payload: { stream_id: "answer-1", offset: 0, delta: "实时答案" },
  });

  expect(afterAnswer.events).toHaveLength(2);
  expect(afterAnswer.narrativeEvents).toBe(narrativeEvents);
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/lib/run-stream-reducer.test.ts`

Expected: FAIL because `narrativeEvents` does not exist.

- [ ] **Step 3: Implement event separation**

1. Add `narrativeEvents` to `RunStreamState` and initialize it from historical events after filtering out all event types whose names start with `answer_`.
2. Add:

```ts
function isNarrativeEvent(event: StreamEvent): boolean {
  return !event.type.startsWith("answer_");
}
```

3. In `reduceRunStream`, keep `events: appendEvent(...)` for every event.
4. Only append to `narrativeEvents` when `isNarrativeEvent(event)` is true. For every answer event, preserve the exact existing `narrativeEvents` array reference.
5. Change only `ThoughtNarrative` callers to pass `streamState.narrativeEvents`; diagnostics components must continue receiving `streamState.events`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
cd frontend
npx vitest --run src/lib/run-stream-reducer.test.ts src/components/agent/agent-streaming.test.tsx src/hooks/use-run-event-stream.test.ts
```

Expected: all pass; answer deltas remain in diagnostics and no longer invalidate thought narrative inputs.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/run-stream-reducer.ts frontend/src/lib/run-stream-reducer.test.ts frontend/src/components/agent/detail-conversation.tsx frontend/src/components/agent/session-conversation-stream.tsx frontend/src/components/agent/agent-streaming.test.tsx
```

---

### Task 6: End-To-End Performance Regression Coverage

**Files:**
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`
- Modify: `frontend/src/hooks/use-typing-text.test.ts`
- Modify: `frontend/src/hooks/use-streaming-markdown.test.ts`

- [ ] **Step 1: Add large-answer behavior tests**

Add a FinalAnswerPanel test using a 100 KB answer with at least one sealed heading/paragraph block and a growing tail. Assert:

```tsx
expect(screen.getByRole("heading", { name: "长答案标题" })).toBeVisible();
expect(container.querySelectorAll(".final-answer-streaming-markdown > *").length).toBeGreaterThan(1);
```

Add an animation test that advances a 10,000-character target for ten RAF frames and asserts each captured length increase is at most 48.

Add a hook test with ten rapid tail updates before 80ms and assert one tail version increment after advancing fake time by 80ms.

- [ ] **Step 2: Run tests to verify the intended bounds**

Run:

```bash
cd frontend
npx vitest --run src/lib/typing-animation.test.ts src/hooks/use-typing-text.test.ts src/hooks/use-streaming-markdown.test.ts src/components/agent/agent-streaming.test.tsx
```

Expected: all pass and no test depends on arbitrary real-time sleeps.

- [ ] **Step 3: Run full frontend verification**

Run:

```bash
cd frontend
npm test -- --run
npm run build
```

Expected: production build completes. If unrelated known flaky role-management tests fail, rerun their file once and report both results separately; do not weaken their assertions as part of this feature.

- [ ] **Step 4: Review diff and commit**

Run:

```bash
git diff --check
```

Expected: no whitespace errors and no generated files staged.

Commit:

```bash
git add frontend/src/components/agent/agent-streaming.test.tsx frontend/src/hooks/use-typing-text.test.ts frontend/src/hooks/use-streaming-markdown.test.ts
```
