# Smooth Streaming Rendering — DOM-Direct Typing + Incremental Markdown

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate both frame-rate stutter (React re-render every 20ms from `useTypingText`) and main-thread freeze (re-parsing entire stable prefix by `ReactMarkdown` on each character growth) by using DOM-direct typing animation in `ProgressiveMarkdown` and incremental stable-segment rendering.

**Architecture:** (1) `FinalAnswerPanel` stops calling `useTypingText` — passes raw answer text directly to `ProgressiveMarkdown`. (2) `ProgressiveMarkdown`'s `tail` span uses a `useRef` + `requestAnimationFrame` loop that writes directly to `textContent`, bypassing React's render cycle. (3) `StableInline` prefix segments are rendered incrementally — only the newly-grown portion creates a new ReactMarkdown instance, previously rendered segments are stable.

**Tech Stack:** TypeScript, React 19, react-markdown + remark-gfm, Vitest

## Global Constraints

- `useTypingText` is NOT modified (still used by `ThoughtNarrative` → `StreamingReasoningBlock`)
- `FinalAnswerPanel` changes: remove `useTypingText` for answer, pass raw text
- `ProgressiveMarkdown` changes: add DOM-direct tail animation, add incremental stable segments
- No new npm dependencies
- Must work with existing `splitBlocks` and `partitionInline` from `markdown-split.ts`

## File Structure

| File | Responsibility |
|------|---------------|
| `frontend/src/components/agent/progressive-markdown.tsx` | **Rewrite.** DOM-direct tail animation + incremental stable segments |
| `frontend/src/components/agent/final-answer-panel.tsx` | **Edit.** Remove `useTypingText` for answer path, pass raw text |

---

### Task 1: ProgressiveMarkdown — DOM-Direct Tail + Incremental Stable

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx`

**Interfaces:**
- Consumes: `splitBlocks`, `partitionInline`, `fastHash` from `@/lib/markdown-split`
- Produces: Same props `{ text: string; terminal: boolean }`, but tail typing is DOM-direct (no React re-renders per char), stable segments are incremental

- [ ] **Step 1: Read current file**

Read `frontend/src/components/agent/progressive-markdown.tsx`.

- [ ] **Step 2: Replace entire file with rewritten version**

Write the following to `frontend/src/components/agent/progressive-markdown.tsx`:

```typescript
"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { splitBlocks, partitionInline, fastHash } from "@/lib/markdown-split";
import {
  createTypingAnimationState,
  advanceTypingAnimation,
  type TypingAnimationState,
} from "@/lib/typing-animation";

const TYPING_SPEED_MS = 20;

function classifyHref(href: string | undefined): { href: string; external: boolean } {
  if (!href) return { href: "", external: false };
  if (href.includes("\\")) return { href: "", external: false };
  try {
    const url = new URL(href);
    return ["http:", "https:", "mailto:"].includes(url.protocol)
      ? { href, external: true }
      : { href: "", external: false };
  } catch {
    return { href: "", external: false };
  }
}

const mdComponents = {
  a: ({ href, children, ...props }: any) => {
    const { href: safeHref, external } = classifyHref(href);
    return (
      <a href={safeHref} {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})} {...props}>
        {children}
        {external ? <span className="sr-only">（在新标签页中打开）</span> : null}
      </a>
    );
  },
  table: ({ children, ...props }: any) => (
    <div className="table-scroll" tabIndex={0}><table {...props}>{children}</table></div>
  ),
  pre: ({ children, ...props }: any) => (
    <div className="code-scroll" tabIndex={0}><pre {...props}>{children}</pre></div>
  ),
};

const CompletedBlock = React.memo(
  function CompletedBlock({ content }: { content: string }) {
    return <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={mdComponents}>{content}</ReactMarkdown>;
  },
  (prev, next) => prev.content === next.content,
);

function StableInlineSegment({ content }: { content: string }) {
  if (!content) return null;
  return (
    <span className="streaming-markdown-inline">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={mdComponents}>
        {content}
      </ReactMarkdown>
    </span>
  );
}

const MemoStableInlineSegment = React.memo(
  StableInlineSegment,
  (prev, next) => prev.content === next.content,
);

function StreamingTail({ targetText }: { targetText: string }) {
  const spanRef = useRef<HTMLSpanElement>(null);
  const stateRef = useRef<TypingAnimationState>(createTypingAnimationState());
  const targetRef = useRef(targetText);
  const rafRef = useRef<number>(0);
  const lastTimeRef = useRef<number>(0);

  useEffect(() => {
    targetRef.current = targetText;

    if (!targetText) {
      stateRef.current = createTypingAnimationState();
      if (spanRef.current) spanRef.current.textContent = "";
      return;
    }

    function tick(now: number) {
      if (!spanRef.current) return;
      const elapsed = lastTimeRef.current ? now - lastTimeRef.current : TYPING_SPEED_MS;
      lastTimeRef.current = now;
      const next = advanceTypingAnimation(
        stateRef.current,
        targetRef.current,
        elapsed,
        TYPING_SPEED_MS,
      );
      stateRef.current = next;
      spanRef.current.textContent = next.displayedText;

      if (next.displayedText !== targetRef.current) {
        rafRef.current = requestAnimationFrame(tick);
      }
    }

    lastTimeRef.current = 0;
    rafRef.current = requestAnimationFrame(tick);

    return () => cancelAnimationFrame(rafRef.current);
  }, [targetText]);

  return (
    <span className="streaming-tail">
      <span ref={spanRef} />
      <span className="streaming-cursor">|</span>
    </span>
  );
}

export default function ProgressiveMarkdown({ text, terminal }: { text: string; terminal: boolean }) {
  const { completed, active } = useMemo(() => {
    if (terminal || !text) return { completed: text ? [text] : [], active: "" };
    return splitBlocks(text);
  }, [text, terminal]);

  const { stable, tail } = useMemo(() => {
    if (terminal || !active) return { stable: "", tail: "" };
    return partitionInline(active);
  }, [active, terminal]);

  const prevStableLenRef = useRef(0);
  const [stableSegments, setStableSegments] = useState<string[]>([]);

  useEffect(() => {
    if (!stable) {
      prevStableLenRef.current = 0;
      setStableSegments([]);
      return;
    }
    const prevLen = prevStableLenRef.current;
    if (stable.length <= prevLen) {
      if (stable !== stableSegments.join("")) {
        prevStableLenRef.current = 0;
        setStableSegments([]);
      }
      return;
    }
    const newPortion = stable.slice(prevLen);
    prevStableLenRef.current = stable.length;
    setStableSegments((prev) => [...prev, newPortion]);
  }, [stable]);

  if (terminal) {
    if (!text) return null;
    return <CompletedBlock content={text} />;
  }

  return (
    <>
      {completed.map((block) => (
        <CompletedBlock key={fastHash(block).toString(36)} content={block} />
      ))}
      {stableSegments.map((seg, i) => (
        <MemoStableInlineSegment key={`${i}-${fastHash(seg).toString(36)}`} content={seg} />
      ))}
      {tail ? <StreamingTail targetText={tail} /> : null}
    </>
  );
}
```

- [ ] **Step 3: Run TypeScript check**

```powershell
npx tsc --noEmit 2>&1 | Select-String "progressive-markdown"
```

Expected: no errors.

- [ ] **Step 4: Run existing frontend tests**

```powershell
npx vitest run src/components/agent/agent-streaming.test.tsx --reporter=verbose
```

Expected: existing tests pass. Note any failures for adjustment.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx
git commit -m "perf: DOM-direct tail animation + incremental stable segments in ProgressiveMarkdown"
```

---

### Task 2: FinalAnswerPanel — Remove useTypingText for Answer

**Files:**
- Modify: `frontend/src/components/agent/final-answer-panel.tsx`

**Interfaces:**
- Consumes: `ProgressiveMarkdown` from Task 1
- Produces: Passes raw answer text (no per-frame typed text from `useTypingText`)

- [ ] **Step 1: Read current file**

Read `frontend/src/components/agent/final-answer-panel.tsx`.

- [ ] **Step 2: Remove useTypingText from answer path**

In `frontend/src/components/agent/final-answer-panel.tsx`, remove the import of `useTypingText` (line 7). It is no longer needed — the typing animation is now handled by `ProgressiveMarkdown` internally via DOM-direct writes.

Remove `useTypingText` from imports:

```typescript
import ProgresiveMarkdown from "@/components/agent/progressive-markdown";
```

(Do NOT import useTypingText anymore.)

In the component body (around lines 60-81), find and replace the `typed` logic. Currently:

```typescript
  const typed = useTypingText(renderedAnswer ?? "", { resetKey: answerStreamId });

  // ... later:
  const displayText = shouldAnimate ? typed : answerText;
  // ...
  <ProgressiveMarkdown text={displayText} terminal={isTerminal} />
```

Change to:

```typescript
  const displayText = shouldAnimate ? (renderedAnswer ?? "") : answerText;

  // ... later (same JSX):
  <ProgressiveMarkdown text={displayText} terminal={isTerminal} />
```

This means:
- When animating: pass the raw streaming answer text to `ProgressiveMarkdown`
- When terminal: pass the full answer text
- `ProgressiveMarkdown` internally handles the typing animation via its own `StreamingTail` component
- `useTypingText` import is removed entirely

- [ ] **Step 3: Run TypeScript check**

```powershell
npx tsc --noEmit 2>&1 | Select-String "final-answer-panel"
```

Expected: no errors.

- [ ] **Step 4: Run existing tests**

```powershell
npx vitest run src/components/agent/agent-streaming.test.tsx --reporter=verbose
```

Expected: existing tests pass. Note any failures — adjust test expectations if tests were asserting on the per-frame typed text behavior (they should now expect raw text to be passed to ProgressiveMarkdown).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent/final-answer-panel.tsx
git commit -m "perf: remove useTypingText from FinalAnswerPanel, delegate to ProgressiveMarkdown DOM-direct typing"
```
