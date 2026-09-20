# Streaming Frame Coalescing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Reduce per-delta React setState and Markdown re-partitioning by coalescing SSE events per frame and caching Markdown state across identical prefixes.

**Architecture:** Two independent changes — SSE hook uses RAF to batch answerText updates; Markdown hook skips re-partitioning when the prefix hasn't grown.

## Global Constraints
- Do not change backend SSE delivery, event contract, or cursor semantics.
- `answerText` must reflect the latest received delta after at most one frame.
- Markdown partitioning must remain append-only; no data loss on prefix growth.
- All existing stream, reducer, and streaming-markdown tests remain green.
---

### Task 1: Coalesce answerText Updates Per Frame

**Files:** `frontend/src/hooks/use-run-event-stream.ts`, `frontend/src/hooks/use-run-event-stream.test.ts`

- [ ] **Step 1: Write failing test**

```ts
test("batches multiple answer deltas into one state update per frame", () => {
  // Fire 5 answer_delta events synchronously
  // Assert setState called exactly once per raf.flush()
  // Assert final answerText is the accumulated value
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/hooks/use-run-event-stream.test.ts -t "batches multiple"`
Expected: FAIL — each delta produces independent setState.

- [ ] **Step 3: Implement RAF coalescing**

Add to `useRunEventStream`:
```ts
const pendingAnswerRef = useRef<string | null>(null);
const rafPendingRef = useRef(false);

// In handleMessage, for answer_delta events only:
pendingAnswerRef.current = nextState.answerText;
if (!rafPendingRef.current) {
  rafPendingRef.current = true;
  requestAnimationFrame(() => {
    rafPendingRef.current = false;
    setState((s) => ({ ...s, answerText: pendingAnswerRef.current! }));
  });
}
// For non-answer events, call updateState immediately as before.
```

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/hooks/use-run-event-stream.test.ts src/lib/run-stream-reducer.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git commit -m "perf: coalesce answer text updates per animation frame"
```

---

### Task 2: Cache Markdown Partition Across Identical Prefixes

**Files:** `frontend/src/hooks/use-streaming-markdown.ts`, `frontend/src/hooks/use-streaming-markdown.test.ts`

- [ ] **Step 1: Write failing test**

```tsx
test("does not re-partition when displayedText prefix hasn't grown", () => {
  const { result, rerender } = renderHook(
    ({ text }) => useStreamingMarkdown(text, { resetKey: "s1" }),
    { initialProps: { text: "hello" } },
  );
  const v1 = result.current.tailVersion;
  // Same text, no growth
  rerender({ text: "hello" });
  expect(result.current.tailVersion).toBe(v1);
});
```

- [ ] **Step 2: Verify RED**

Run: `cd frontend; npx vitest --run src/hooks/use-streaming-markdown.test.ts -t "does not re-partition"`
Expected: FAIL — every render re-runs partition and tailVersion increments.

- [ ] **Step 3: Implement prefix caching**

```ts
const prevLenRef = useRef(0);
if (displayedText.length > prevLenRef.current) {
  prevLenRef.current = displayedText.length;
  stateRef.current = appendStreamingMarkdown(stateRef.current, displayedText);
  const snapshot = snapshotStreamingMarkdown(stateRef.current);
  snapshotRef.current = snapshot;
  // ... existing completedBlocks / tail publish logic
}
```

- [ ] **Step 4: Verify GREEN**

Run: `cd frontend; npx vitest --run src/hooks/use-streaming-markdown.test.ts src/lib/streaming-markdown.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git commit -m "perf: skip markdown re-partition on unchanged answer prefix"
```

---

### Task 3: Full Regression

- [ ] **Backend:** `python -m pytest tests/test_agent_stream.py tests/test_agent_loop.py -q` → all pass.
- [ ] **Frontend:** `npx vitest --run src/hooks/use-run-event-stream.test.ts src/lib/run-stream-reducer.test.ts src/hooks/use-streaming-markdown.test.ts src/lib/streaming-markdown.test.ts src/components/agent/agent-streaming.test.tsx` → all pass.
- [ ] **Build:** `npm run build` → compiled successfully.
