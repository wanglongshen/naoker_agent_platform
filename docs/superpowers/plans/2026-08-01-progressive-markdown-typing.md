# Progressive Markdown Rendering During Typing

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While the answer types out character-by-character, the already-typed portion renders as Markdown (headings, lists, quotes progressively; tables/code blocks appear when structurally complete).

**Architecture:** Replace `StreamingTail`'s span `textContent` update (plain text) with a throttled React state render through `ReactMarkdown`. Keep the rAF typing loop and `stateRef` untouched; every 2nd frame pushes the partial text into React state, which renders `<ReactMarkdown>{partialText}</ReactMarkdown>`. Cursor moves outside the markdown. Terminal transition becomes visually seamless (markdown already rendered).

**Tech Stack:** TypeScript, React, react-markdown + remark-gfm

## Global Constraints

- Typing speed stays 20ms/char (`TYPING_SPEED_MS`)
- `advanceTypingAnimation` / `typing-animation.ts` NOT modified
- `onComplete` must fire when typing finishes (existing `animateTerminal` flow depends on it)
- Outer wrapper keeps `className="streaming-tail"` (3 tests depend on it)
- Reuse existing `mdComponents` and `CompletedBlock` from `progressive-markdown.tsx`
- Tests must pass (62/62 agent-streaming)

---

### Task 1: StreamingTail renders partial text as Markdown (throttled to 30fps)

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx`

**Interfaces:**
- Consumes: `targetText: string`, `onComplete?: () => void` (unchanged props)
- Produces: `<ReactMarkdown>` of the typed portion every 2nd frame; `onComplete` fires once typing reaches target

- [ ] **Step 1: Write the failing test**

In `frontend/src/components/agent/agent-streaming.test.tsx`, add a new test inside the `FinalAnswerPanel` describe block (after the existing streaming tests, around line 195). It uses the existing `installFakeRaf` helper (already defined at the bottom of the file):

```tsx
test("streaming answer renders typed markdown progressively as headings", async () => {
  const raf = installFakeRaf();
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);
  try {
    render(
      <FinalAnswerPanel
        run={baseRun}
        streamingAnswer={`# 标题

内容`}
        answerStreamId="live-md-progressive"
      />,
    );
    act(() => {
      for (let i = 1; i <= 8; i += 1) {
        raf.runNextFrame(i * 16);
      }
    });
    expect(screen.getByRole("heading", { name: "标题" })).toBeVisible();
  } finally {
    raf.restore?.();
    vi.restoreAllMocks();
  }
});
```

Note: `installFakeRaf` returns `{ pendingCount, runNextFrame }` per the existing helper; if it has a `restore` method use it, otherwise the stub persists per-test (match the pattern used by other tests in this file that call `installFakeRaf`).

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -t "renders typed markdown progressively" -v
```

Expected: FAIL — heading role not found because StreamingTail renders plain text via `textContent`.

- [ ] **Step 3: Rewrite StreamingTail to render via ReactMarkdown**

In `frontend/src/components/agent/progressive-markdown.tsx`, replace the entire `StreamingTail` component (currently lines 52-99) with:

```typescript
function StreamingTail({ targetText, onComplete }: { targetText: string; onComplete?: () => void }) {
  const stateRef = useRef<TypingAnimationState>(createTypingAnimationState());
  const targetRef = useRef(targetText);
  const rafRef = useRef<number>(0);
  const lastTimeRef = useRef<number | null>(null);
  const frameCounterRef = useRef(0);
  const [displayed, setDisplayed] = useState("");

  useEffect(() => {
    targetRef.current = targetText;

    if (!targetText) {
      stateRef.current = createTypingAnimationState();
      setDisplayed("");
      return;
    }

    function tick(now: number) {
      const elapsed = lastTimeRef.current !== null ? now - lastTimeRef.current : TYPING_SPEED_MS;
      lastTimeRef.current = now;
      const next = advanceTypingAnimation(
        stateRef.current,
        targetRef.current,
        elapsed,
        TYPING_SPEED_MS,
      );
      stateRef.current = next;

      frameCounterRef.current += 1;
      if (frameCounterRef.current % 2 === 0) {
        setDisplayed(next.displayedText);
      }

      if (next.displayedText !== targetRef.current) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setDisplayed(next.displayedText);
        if (onComplete) onComplete();
      }
    }

    rafRef.current = requestAnimationFrame(tick);

    return () => cancelAnimationFrame(rafRef.current);
  }, [targetText]);

  return (
    <span className="streaming-tail">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={mdComponents}>
        {displayed}
      </ReactMarkdown>
      <span className="streaming-cursor">|</span>
    </span>
  );
}
```

Key changes:
- `spanRef` removed; typed text now lives in React state `displayed`
- `setDisplayed` called every 2nd frame (30fps throttle) + once on completion
- Renders `<ReactMarkdown>` of the partial text using the same `mdComponents` as `CompletedBlock`
- Cursor `|` sits after the markdown as a sibling
- `onComplete` fires when typing reaches the end (unchanged contract)

- [ ] **Step 4: Run the new test to verify it passes**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -t "renders typed markdown progressively" -v
```

Expected: PASS — after 8 frames the heading role exists.

- [ ] **Step 5: Run full agent-streaming suite**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: 62 existing + 1 new = 63 tests pass. If any fail (e.g., tests asserting on plain-text content or rAF-driven state), fix the TEST ONLY if it asserts the old plain-text behavior — otherwise fix the component.

- [ ] **Step 6: Run full frontend suite**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
```

Expected: No new failures (13 pre-existing failures in unrelated files unchanged).

- [ ] **Step 7: Build check**

```bash
cd C:\01_agent_loop_pro\frontend && npx next build
```

Expected: Compiled successfully.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "feat: progressive markdown rendering during typing (30fps throttled)"
```
