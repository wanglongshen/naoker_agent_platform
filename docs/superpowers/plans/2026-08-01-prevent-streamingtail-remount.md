# Prevent StreamingTail Remount on Terminal Transition

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep StreamTail mounted through the streaming→terminal transition so typing state is preserved and the second half doesn't appear instantly.

**Architecture:** Unify the JSX rendering in `ProgressiveMarkdown` so that `StreamingTail` is always at the same React tree position regardless of `terminal` flag. When `terminal=true && animateTerminal=true`, set `onComplete` on the SAME StreamTail instance. When typing finishes, switch from StreamTail to `CompletedBlock` without losing accumulated characters.

**Tech Stack:** TypeScript, React

## Global Constraints

- `StreamingTail` component signature must not change (onComplete prop already added)
- Historical sessions must NOT trigger typing animation
- All existing tests must pass
- Do NOT change `FinalAnswerPanel` or any other file

---

### Task 1: Unify StreamTail rendering to prevent unmount on terminal

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx`

- [ ] **Step 1: Rewrite ProgressiveMarkdown rendering**

Replace the entire `ProgressiveMarkdown` function body (lines 101-133) with this unified version that keeps `StreamingTail` at a fixed position:

```typescript
export default function ProgressiveMarkdown({ text, terminal, animateTerminal = false }: { text: string; terminal: boolean; animateTerminal?: boolean }) {
  const [terminalTyped, setTerminalTyped] = useState(false);

  useEffect(() => {
    setTerminalTyped(false);
  }, [text, terminal, animateTerminal]);

  const { completed, active } = useMemo(() => {
    if (!text) return { completed: [] as string[], active: "" };
    if (terminal && !animateTerminal) return { completed: [text], active: "" };
    if (terminal && animateTerminal && terminalTyped) return { completed: [text], active: "" };
    if (terminal && animateTerminal) return { completed: [], active: text };
    return splitBlocks(text);
  }, [text, terminal, animateTerminal, terminalTyped]);

  if (!text) return null;

  if (terminal && !animateTerminal && completed.length > 0) {
    return <CompletedBlock content={text} />;
  }

  return (
    <>
      {completed.map((block, i) => (
        <CompletedBlock key={`${i}-${block.slice(0, 40)}`} content={block} />
      ))}
      {active ? (
        <StreamingTail
          targetText={active}
          onComplete={terminal && animateTerminal ? () => setTerminalTyped(true) : undefined}
        />
      ) : null}
    </>
  );
}
```

Key changes:
- `StreamingTail` is always rendered in the same JSX slot (inside the fragment, after completed blocks)
- Terminal `active` uses the full `text` when transitioning
- `onComplete` set only when `terminal && animateTerminal`
- After typing completes → `terminalTyped=true` → re-render with `CompletedBlock`

- [ ] **Step 2: Run agent-streaming tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: All 62 tests pass.

- [ ] **Step 3: Run full test suite**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
```

Expected: No new failures.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx
git commit -m "fix: keep StreamTail mounted across terminal transition to preserve typing state"
```
