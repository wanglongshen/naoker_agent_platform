# Terminal-Phase Typing Animation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When live run completes, type out the full answer via StreamingTail before switching to ReactMarkdown. Historical sessions render ReactMarkdown immediately (no typing).

**Architecture:** `ProgressiveMarkdown` gains an `animateTerminal` prop. When `terminal=true && animateTerminal=true`: render through `StreamingTail` first, then switch to `CompletedBlock` after typing finishes. When `animateTerminal=false` (historical): immediate `CompletedBlock` as before.

**Tech Stack:** TypeScript, React

## Global Constraints

- Task 1 (reducer preserving accumulated answerText) already applied — keep it
- Historical sessions must NOT show typing animation
- Do NOT change backend code
- Existing tests must pass

---

### Task 2: ProgressiveMarkdown — animateTerminal prop + conditional typing

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx`
- Modify: `frontend/src/components/agent/final-answer-panel.tsx`

**Interfaces:**
- Consumes: `StreamingTail` component, `FinalAnswerPanel`
- Produces: `animateTerminal` prop controls terminal typing behavior

- [ ] **Step 1: Add `onComplete` to `StreamingTail`**

In `frontend/src/components/agent/progressive-markdown.tsx`, change `StreamingTail` signature:

```typescript
function StreamingTail({ targetText, onComplete }: { targetText: string; onComplete?: () => void }) {
```

In the `tick` function at line 81, add:

```typescript
      if (next.displayedText !== targetRef.current) {
        rafRef.current = requestAnimationFrame(tick);
      } else if (onComplete) {
        onComplete();
      }
```

- [ ] **Step 2: Add `animateTerminal` prop and terminal typing state**

In `ProgressiveMarkdown`, add the prop and state:

```typescript
export default function ProgressiveMarkdown({ text, terminal, animateTerminal = false }: { text: string; terminal: boolean; animateTerminal?: boolean }) {
  const [terminalTyped, setTerminalTyped] = useState(false);

  useEffect(() => {
    setTerminalTyped(false);
  }, [text, terminal, animateTerminal]);
```

And import `useState`:

```typescript
import React, { useEffect, useMemo, useRef, useState } from "react";
```

- [ ] **Step 3: Conditional terminal rendering**

Replace:

```typescript
  if (terminal) {
    if (!text) return null;
    return <CompletedBlock content={text} />;
  }
```

With:

```typescript
  if (terminal) {
    if (!text) return null;
    if (!animateTerminal || terminalTyped) {
      return <CompletedBlock content={text} />;
    }
    return (
      <span className="streaming-tail">
        <StreamingTail targetText={text} onComplete={() => setTerminalTyped(true)} />
      </span>
    );
  }
```

- [ ] **Step 4: Pass `animateTerminal` from `FinalAnswerPanel`**

In `frontend/src/components/agent/final-answer-panel.tsx`, at line 78, change:

```typescript
<ProgressiveMarkdown text={displayText} terminal={isTerminal} />
```

To:

```typescript
<ProgressiveMarkdown text={displayText} terminal={isTerminal} animateTerminal={isTerminal && streamedAnswer !== null} />
```

- [ ] **Step 5: Run tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

- [ ] **Step 6: Full suite**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx frontend/src/components/agent/final-answer-panel.tsx
git commit -m "fix: type out answer via StreamingTail before ReactMarkdown on terminal, skip for history"
```
