# Continue-Typing Through Terminal Transition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the run completes mid-typing, `StreamingTail` keeps typing the remaining text (no "后半段砰一下全出"), then switches to `CompletedBlock` — without re-typing from scratch, and without animating historical answers.

**Architecture:** `ProgressiveMarkdown` uses unified JSX so `StreamingTail` NEVER unmounts on the terminal transition (typing state preserved). New `animateOnTerminal` prop (from the existing `wasLiveStreamed` flag) gates whether terminal answers type-to-completion (`true` for live runs this session) or render instantly (`false` for historical). `StreamingTail` gains an `onComplete` callback that flips `typedComplete`, which swaps in `CompletedBlock`.

**Tech Stack:** TypeScript, React

## Global Constraints

- NO re-type from scratch (StreamingTail must stay mounted — unified JSX)
- NO `animateTerminal`-era remount bug: same component slot across streaming→terminal
- Historical runs (page load, `wasLiveStreamed=false`) render instantly
- Thinking area unchanged
- Tests must pass (64 agent-streaming)

---

### Task 1: Continue typing through terminal, instant for historical

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx`
- Modify: `frontend/src/components/agent/final-answer-panel.tsx`
- Test: `frontend/src/components/agent/agent-streaming.test.tsx`

**Interfaces:**
- Consumes: `text: string`, `terminal: boolean`, `animateOnTerminal: boolean` (new prop on ProgressiveMarkdown); `wasLiveStreamed: boolean` (existing prop on FinalAnswerPanel)
- Produces: `StreamingTail` gains `onComplete?: () => void`; `typedComplete` state swaps in `CompletedBlock` after typing finishes

- [ ] **Step 1: Write the failing tests**

Add two tests to `frontend/src/components/agent/agent-streaming.test.tsx` (inside the `FinalAnswerPanel` describe block):

```tsx
test("terminal transition does not pop the remaining answer — typewriter continues", async () => {
  const raf = installFakeRaf();
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);
  try {
    const { rerender } = render(
      <FinalAnswerPanel
        run={baseRun}
        streamingAnswer={`# 标题

${"a".repeat(200)}`}
        answerStreamId="live-continue"
      />,
    );
    act(() => {
      for (let i = 1; i <= 8; i += 1) {
        raf.runNextFrame(i * 16);
      }
    });

    rerender(
      <FinalAnswerPanel
        run={{ ...baseRun, status: "succeeded", result: { final_answer: `# 标题\n\n${"a".repeat(200)}` } }}
        streamingAnswer=""
        answerStreamId={null}
        wasLiveStreamed={true}
      />,
    );

    expect(document.querySelector(".streaming-tail")).not.toBeNull();
  } finally {
    vi.restoreAllMocks();
  }
});

test("historical terminal run renders instantly without typewriter", () => {
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);

  const { container } = render(
    <FinalAnswerPanel
      run={makeRun({ status: "succeeded", result: { final_answer: `# 标题\n\n段落` } })}
      streamingAnswer=""
      answerStreamId={null}
    />,
  );

  expect(container.querySelector(".streaming-tail")).toBeNull();
  expect(screen.getByRole("heading", { name: "标题" })).toBeVisible();
});
```

Note: check `FinalAnswerPanel`'s existing prop `wasLiveStreamed` is already accepted (it is — added earlier); `makeRun` and `baseRun` are defined at the top of the test file.

- [ ] **Step 2: Run tests to verify they FAIL**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -t "terminal transition does not pop|historical terminal run renders instantly" -v
```

Expected: Both FAIL (terminal flips to `CompletedBlock` immediately — `.streaming-tail` gone in test 1; historical passes test 2's heading assertion BUT check which failed — if only test 1 fails, confirm test 2's `.streaming-tail` assertion also fails against current code, meaning test 2 is a valid guard for the historical-instant requirement).

- [ ] **Step 3: Add `onComplete` to `StreamingTail`**

In `frontend/src/components/agent/progressive-markdown.tsx`, change the `StreamingTail` signature and completion branch:

```typescript
function StreamingTail({ targetText, onComplete }: { targetText: string; onComplete?: () => void }) {
```

In the `tick` function, change the else branch:

```typescript
      if (next.displayedText !== targetRef.current) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setDisplayed(next.displayedText);
        if (onComplete) onComplete();
      }
```

- [ ] **Step 4: Rewrite `ProgressiveMarkdown` with unified JSX**

Replace the `ProgressiveMarkdown` function body:

```typescript
export default function ProgressiveMarkdown({ text, terminal, animateOnTerminal = false }: { text: string; terminal: boolean; animateOnTerminal?: boolean }) {
  const [typedComplete, setTypedComplete] = useState(false);

  useEffect(() => {
    setTypedComplete(false);
  }, [text, terminal]);

  const { completed, active } = useMemo(() => {
    if (!text) return { completed: [] as string[], active: "" };
    if (terminal && (!animateOnTerminal || typedComplete)) return { completed: [text], active: "" };
    return { completed: [], active: text };
  }, [text, terminal, animateOnTerminal, typedComplete]);

  if (!text) return null;

  return (
    <>
      {completed.map((block, i) => (
        <CompletedBlock key={`${i}-${block.slice(0, 40)}`} content={block} />
      ))}
      {active ? (
        <StreamingTail
          targetText={active}
          onComplete={terminal ? () => setTypedComplete(true) : undefined}
        />
      ) : null}
    </>
  );
}
```

Key behavior:
- **Streaming** (`terminal=false`): `active=text` → StreamingTail types; same JSX slot as terminal case → NO unmount on transition
- **Terminal + live** (`animateOnTerminal=true`, not yet typed): `active=text` (full) → StreamingTail CONTINUES from its preserved `stateRef` position → types remaining → `onComplete` → `typedComplete=true`
- **Terminal + typed or historical** (`animateOnTerminal=false`): `completed=[text]` → `CompletedBlock` instant
- `useState`/`useEffect` already imported

Also update the imports line to include `useState` and `useEffect` if not already imported (they are, from the typewriter version).

- [ ] **Step 5: Pass `animateOnTerminal` from `FinalAnswerPanel`**

In `frontend/src/components/agent/final-answer-panel.tsx`, change the `ProgressiveMarkdown` render (currently `<ProgressiveMarkdown text={displayText} terminal={isTerminal} />`) to:

```typescript
<ProgressiveMarkdown text={displayText} terminal={isTerminal} animateOnTerminal={wasLiveStreamed} />
```

(`wasLiveStreamed` prop already exists on `FinalAnswerPanel`, default `false`.)

- [ ] **Step 6: Run tests to verify they PASS**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: All 66 tests pass (64 existing + 2 new). If an existing test fails (e.g., a terminal-transition test now keeps the typewriter), update it to the new behavior — do NOT weaken the 2 new tests.

- [ ] **Step 7: Full suite + build**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
cd C:\01_agent_loop_pro\frontend && npx next build
```

Expected: No new failures; build succeeds.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx frontend/src/components/agent/final-answer-panel.tsx frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "fix: keep typewriter typing through terminal transition, instant for history"
```
