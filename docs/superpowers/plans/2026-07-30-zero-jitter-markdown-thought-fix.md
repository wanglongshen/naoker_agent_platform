# Zero-Jitter Streaming Markdown & Thought Narrative Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `ProgressiveMarkdown` to partition the active streaming block at the last balanced inline-marker position so the stable prefix renders as Markdown and the unclosed tail remains plain text — achieving zero layout jitter. Rewrite `useThoughtNarrativeBlocks` as a pure `useMemo` from events only, eliminating duplicate reasoning blocks caused by dual-source (events + snapshots) input.

**Architecture:** Two-layer partition. Block-level: split by `\n\n` with fenced-code-block awareness via `splitBlocks()`. Inline-level: scan for balanced `**`, `*`, ` `` `, `~~`, `[]()` markers via `partitionInline()`. Completed blocks are `React.memo`(ReactMarkdown), stable inline prefix is `React.memo`(ReactMarkdown), active tail is plain text + CSS cursor. Thought narrative hook becomes `buildThoughtNarrativeBlocks(events)` — pure function, no snapshots.

**Tech Stack:** TypeScript, React 19, react-markdown 10 + remark-gfm, Vitest

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-30-zero-jitter-markdown-thought-fix-design.md`
- No new npm dependencies
- `React.memo` with `content`-based equality for all stable Markdown subcomponents
- `splitBlocks()` must preserve fenced code blocks (` ``` ` or `~~~`) as atomic — `\n\n` inside fences is NOT a block separator
- `partitionInline()` is O(n) single-pass, `stable` slice is the maximal prefix where all inline markers are balanced
- Thought narrative hook: remove `visibleThoughtByStep`/`visibleThoughtStreamIds` inputs, derive everything from events
- All existing streaming behavior (typing animation, pause/resume, tool records) preserved
- Tests in `__tests__` directories or adjacent `*.test.ts` files matching existing patterns

## File Structure

| File | Responsibility |
|------|---------------|
| `frontend/src/lib/markdown-split.ts` | **New.** `splitBlocks()`, `partitionInline()`, `fastHash()` |
| `frontend/src/components/agent/progressive-markdown.tsx` | **Rewrite.** Two-layer partition + memoized subcomponents |
| `frontend/src/lib/thought-narrative.ts` | **Edit.** `buildThoughtNarrativeBlocks` — remove snapshot merge |
| `frontend/src/hooks/use-thought-narrative-blocks.ts` | **Rewrite.** Pure `useMemo` from events |
| `frontend/src/components/agent/thought-narrative.tsx` | **Edit.** Remove `visibleThoughtByStep`/`visibleThoughtStreamIds` props |
| `frontend/src/components/agent/session-conversation-stream.tsx` | **Edit.** Remove snapshot props passthrough |
| `frontend/src/lib/markdown-split.test.ts` | **New.** Unit tests for split and partition |
| `frontend/src/hooks/use-thought-narrative-blocks.test.ts` | **New.** Dedup tests |

---

### Task 1: markdown-split.ts — Block & Inline Partition Algorithms

**Files:**
- Create: `frontend/src/lib/markdown-split.ts`
- Create: `frontend/src/lib/markdown-split.test.ts`

**Interfaces:**
- Produces:
  - `splitBlocks(text: string): { completed: string[]; active: string }`
  - `partitionInline(source: string): { stable: string; tail: string }`
  - `fastHash(s: string): number` — FNV-1a 32-bit

- [ ] **Step 1: Write the test file**

Create `frontend/src/lib/markdown-split.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { splitBlocks, partitionInline, fastHash } from "./markdown-split";

describe("splitBlocks", () => {
  it("splits by double newline", () => {
    const result = splitBlocks("a\n\nb");
    expect(result.completed).toEqual(["a"]);
    expect(result.active).toBe("b");
  });

  it("returns empty completed when no delimiter", () => {
    const result = splitBlocks("hello");
    expect(result.completed).toEqual([]);
    expect(result.active).toBe("hello");
  });

  it("returns empty active when text ends with delimiter", () => {
    const result = splitBlocks("hello\n\n");
    expect(result.completed).toEqual(["hello"]);
    expect(result.active).toBe("");
  });

  it("preserves fenced code block as atomic (```)", () => {
    const result = splitBlocks("```\n\ninner\n```\n\nafter");
    expect(result.completed).toEqual(["```\n\ninner\n```"]);
    expect(result.active).toBe("after");
  });

  it("preserves fenced code block as atomic (~~~)", () => {
    const result = splitBlocks("~~~\n\ninner\n~~~\n\nafter");
    expect(result.completed).toEqual(["~~~\n\ninner\n~~~"]);
    expect(result.active).toBe("after");
  });

  it("handles unclosed fence as active block", () => {
    const result = splitBlocks("done\n\n```\nopen fence");
    expect(result.completed).toEqual(["done"]);
    expect(result.active).toBe("```\nopen fence");
  });

  it("handles multiple completed blocks", () => {
    const result = splitBlocks("a\n\nb\n\nc");
    expect(result.completed).toEqual(["a", "b"]);
    expect(result.active).toBe("c");
  });

  it("handles empty string", () => {
    const result = splitBlocks("");
    expect(result.completed).toEqual([]);
    expect(result.active).toBe("");
  });

  it("handles delimiter inside code fence as content", () => {
    const result = splitBlocks("```\ncode\n\ninside\n```\n\nafter");
    expect(result.completed).toEqual(["```\ncode\n\ninside\n```"]);
    expect(result.active).toBe("after");
  });

  it("handles text with only newlines (no double)", () => {
    const result = splitBlocks("line1\nline2");
    expect(result.completed).toEqual([]);
    expect(result.active).toBe("line1\nline2");
  });
});

describe("partitionInline", () => {
  it("returns full text as stable when all markers balanced", () => {
    const result = partitionInline("Hello **world**");
    expect(result.stable).toBe("Hello **world**");
    expect(result.tail).toBe("");
  });

  it("splits at unbalanced bold marker", () => {
    const result = partitionInline("Hello **wor");
    expect(result.stable).toBe("Hello ");
    expect(result.tail).toBe("**wor");
  });

  it("splits at unbalanced inline code", () => {
    const result = partitionInline("text `cod");
    expect(result.stable).toBe("text ");
    expect(result.tail).toBe("`cod");
  });

  it("returns full text as stable with balanced inline code", () => {
    const result = partitionInline("text `code` end");
    expect(result.stable).toBe("text `code` end");
    expect(result.tail).toBe("");
  });

  it("handles empty string", () => {
    const result = partitionInline("");
    expect(result.stable).toBe("");
    expect(result.tail).toBe("");
  });

  it("handles text with no markers", () => {
    const result = partitionInline("plain text 123");
    expect(result.stable).toBe("plain text 123");
    expect(result.tail).toBe("");
  });

  it("handles unbalanced italic", () => {
    const result = partitionInline("Hello *wor");
    expect(result.stable).toBe("Hello ");
    expect(result.tail).toBe("*wor");
  });

  it("handles balanced italic", () => {
    const result = partitionInline("Hello *world* end");
    expect(result.stable).toBe("Hello *world* end");
    expect(result.tail).toBe("");
  });

  it("handles unbalanced link (missing paren)", () => {
    const result = partitionInline("see [link");
    expect(result.stable).toBe("see ");
    expect(result.tail).toBe("[link");
  });

  it("handles balanced link", () => {
    const result = partitionInline("see [link](https://x.com) ok");
    expect(result.stable).toBe("see [link](https://x.com) ok");
    expect(result.tail).toBe("");
  });

  it("handles unbalanced strikethrough", () => {
    const result = partitionInline("text ~~strike");
    expect(result.stable).toBe("text ");
    expect(result.tail).toBe("~~strike");
  });

  it("handles balanced strikethrough", () => {
    const result = partitionInline("text ~~strike~~ end");
    expect(result.stable).toBe("text ~~strike~~ end");
    expect(result.tail).toBe("");
  });

  it("handles nested bold-italic", () => {
    const result = partitionInline("**bold *italic* end**");
    expect(result.stable).toBe("**bold *italic* end**");
    expect(result.tail).toBe("");
  });

  it("handles bold opening only", () => {
    const result = partitionInline("start **bold content");
    expect(result.stable).toBe("start ");
    expect(result.tail).toBe("**bold content");
  });

  it("returns everything as tail when bold never opened", () => {
    const result = partitionInline("no markers here");
    expect(result.stable).toBe("no markers here");
    expect(result.tail).toBe("");
  });
});

describe("fastHash", () => {
  it("returns same hash for same content", () => {
    expect(fastHash("hello")).toBe(fastHash("hello"));
  });

  it("returns different hash for different content", () => {
    expect(fastHash("hello")).not.toBe(fastHash("world"));
  });

  it("handles empty string", () => {
    expect(typeof fastHash("")).toBe("number");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
npx vitest run src/lib/markdown-split.test.ts 2>&1
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement markdown-split.ts**

Create `frontend/src/lib/markdown-split.ts`:

```typescript
export function splitBlocks(text: string): { completed: string[]; active: string } {
  if (!text) return { completed: [], active: "" };

  const completed: string[] = [];
  let inFence = false;
  let fenceChar = "";
  let blockStart = 0;
  let i = 0;

  while (i < text.length) {
    // Check for fence start/end at current position
    if (!inFence) {
      if ((text[i] === "`" && text[i + 1] === "`" && text[i + 2] === "`") ||
          (text[i] === "~" && text[i + 1] === "~" && text[i + 2] === "~")) {
        inFence = true;
        fenceChar = text[i];
        i += 3;
        continue;
      }
    } else {
      if (text[i] === fenceChar && text[i + 1] === fenceChar && text[i + 2] === fenceChar) {
        inFence = false;
        fenceChar = "";
        i += 3;
        continue;
      }
    }

    // Check for block delimiter \n\n outside fences
    if (!inFence && text[i] === "\n" && text[i + 1] === "\n") {
      completed.push(text.slice(blockStart, i));
      i += 2;
      blockStart = i;
      continue;
    }

    i++;
  }

  const active = text.slice(blockStart);
  return { completed, active };
}

export function partitionInline(source: string): { stable: string; tail: string } {
  if (!source) return { stable: "", tail: "" };

  let lastBalanced = 0;
  let boldOpen = false;
  let italicOpen = false;
  let codeOpen = false;
  let linkBracketDepth = 0;
  let linkInParen = false;
  let linkParenCount = 0;
  let strikeOpen = false;
  let escapeActive = false;

  function allClosed(): boolean {
    return !boldOpen && !italicOpen && !codeOpen && linkBracketDepth === 0 && !linkInParen && !strikeOpen;
  }

  for (let i = 0; i < source.length; i++) {
    const ch = source[i];
    const next = source[i + 1] ?? "";
    const lookahead2 = source[i + 2] ?? "";

    if (escapeActive) {
      escapeActive = false;
      continue;
    }

    if (ch === "\\") {
      escapeActive = true;
      continue;
    }

    if (codeOpen) {
      if (ch === "`" && next !== "`") {
        codeOpen = false;
        if (allClosed()) lastBalanced = i + 1;
      }
      continue;
    }

    if (ch === "`") {
      codeOpen = true;
      continue;
    }

    // Bold: ** or __
    if (ch === "*" && next === "*" && lookahead2 !== "*" && !italicOpen) {
      boldOpen = !boldOpen;
      i++; // skip second *
      if (allClosed()) lastBalanced = i + 1;
      continue;
    }
    if (ch === "_" && next === "_" && lookahead2 !== "_" && !italicOpen) {
      boldOpen = !boldOpen;
      i++;
      if (allClosed()) lastBalanced = i + 1;
      continue;
    }

    // Italic: * or _ (not part of bold)
    if (ch === "*" && next !== "*" && !boldOpen) {
      italicOpen = !italicOpen;
      if (allClosed()) lastBalanced = i + 1;
      continue;
    }
    if (ch === "_" && next !== "_" && !boldOpen) {
      italicOpen = !italicOpen;
      if (allClosed()) lastBalanced = i + 1;
      continue;
    }

    // Strikethrough: ~~
    if (ch === "~" && next === "~") {
      strikeOpen = !strikeOpen;
      i++;
      if (allClosed()) lastBalanced = i + 1;
      continue;
    }

    // Link: [text](url)
    if (linkInParen) {
      if (ch === ")") {
        linkParenCount--;
        if (linkParenCount === 0) {
          linkInParen = false;
          if (allClosed()) lastBalanced = i + 1;
        }
      } else if (ch === "(") {
        linkParenCount++;
      }
      continue;
    }

    if (ch === "[") {
      linkBracketDepth++;
      continue;
    }

    if (ch === "]" && linkBracketDepth > 0) {
      if (next === "(") {
        linkBracketDepth--;
        linkInParen = true;
        linkParenCount = 1;
        i++; // skip '('
      } else {
        linkBracketDepth--;
        if (allClosed()) lastBalanced = i + 1;
      }
      continue;
    }

    // Plain text character
    if (allClosed()) lastBalanced = i + 1;
  }

  return {
    stable: source.slice(0, lastBalanced),
    tail: source.slice(lastBalanced),
  };
}

export function fastHash(s: string): number {
  let hash = 2166136261;
  for (let i = 0; i < s.length; i++) {
    hash ^= s.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
npx vitest run src/lib/markdown-split.test.ts 2>&1
```

Expected: all 26 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/markdown-split.ts frontend/src/lib/markdown-split.test.ts
git commit -m "feat: add zero-jitter markdown block and inline partition algorithms"
```

---

### Task 2: ProgressiveMarkdown — Rewrite with Two-Layer Partition

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx`

**Interfaces:**
- Consumes: `splitBlocks()`, `partitionInline()`, `fastHash()` from `@/lib/markdown-split` (Task 1)
- Produces: Same props `{ text: string; terminal: boolean }`, zero-jitter rendering

- [ ] **Step 1: Rewrite the component**

Replace the entire content of `frontend/src/components/agent/progressive-markdown.tsx`:

```typescript
"use client";

import React, { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { splitBlocks, partitionInline, fastHash } from "@/lib/markdown-split";

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

const StableInline = React.memo(
  function StableInline({ content }: { content: string }) {
    if (!content) return null;
    return (
      <span className="streaming-markdown-inline">
        <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={mdComponents}>
          {content}
        </ReactMarkdown>
      </span>
    );
  },
  (prev, next) => prev.content === next.content,
);

export default function ProgressiveMarkdown({ text, terminal }: { text: string; terminal: boolean }) {
  const { completed, active } = useMemo(() => {
    if (terminal || !text) return { completed: text ? [text] : [], active: "" };
    return splitBlocks(text);
  }, [text, terminal]);

  const { stable, tail } = useMemo(() => {
    if (terminal || !active) return { stable: "", tail: "" };
    return partitionInline(active);
  }, [active, terminal]);

  if (terminal) {
    if (!text) return null;
    return <CompletedBlock content={text} />;
  }

  return (
    <>
      {completed.map((block) => (
        <CompletedBlock key={fastHash(block).toString(36)} content={block} />
      ))}
      {stable ? (
        <StableInline key={fastHash(stable).toString(36)} content={stable} />
      ) : null}
      {tail ? (
        <span className="streaming-tail">{tail}<span className="streaming-cursor">|</span></span>
      ) : null}
    </>
  );
}
```

- [ ] **Step 2: Run existing frontend tests to confirm no regression**

```powershell
npx vitest run --reporter=verbose 2>&1 | tail -20
```

Expected: existing tests pass (no regressions). If any test references old `ProgressiveMarkdown` behavior (e.g., expecting `streaming-tail` div), those are expected to fail — note them for Task 5.

- [ ] **Step 3: Run TypeScript type-check**

```powershell
npx tsc --noEmit 2>&1 | head -5
```

Expected: no new type errors from `progressive-markdown.tsx`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx
git commit -m "feat: rewrite ProgressiveMarkdown with zero-jitter two-layer partition"
```

---

### Task 3: Thought Narrative Hook — Pure useMemo Rewrite

**Files:**
- Modify: `frontend/src/hooks/use-thought-narrative-blocks.ts`
- Modify: `frontend/src/lib/thought-narrative.ts` (remove snapshot merge from `buildThoughtNarrativeBlocks`)
- Create: `frontend/src/hooks/use-thought-narrative-blocks.test.ts`

**Interfaces:**
- Consumes: `buildThoughtNarrativeBlocks` from `@/lib/thought-narrative` (edited in this task)
- Produces: `function useThoughtNarrativeBlocks(events: AgentRunEvent[]): ThoughtNarrativeBlock[]`

- [ ] **Step 1: Write the dedup test**

Create `frontend/src/hooks/use-thought-narrative-blocks.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { buildThoughtNarrativeBlocks } from "@/lib/thought-narrative";
import type { AgentRunEvent } from "@/types/agent";

let seqCounter = 0;
function makeEvent(event_type: string, payload: Record<string, unknown>, run_id = "r1"): AgentRunEvent {
  seqCounter++;
  return {
    id: `evt-${seqCounter}`,
    run_id,
    attempt_id: null,
    seq: seqCounter,
    event_type,
    type: event_type,
    payload,
    created_at: new Date().toISOString(),
    timestamp: new Date().toISOString(),
  } as AgentRunEvent;
}

describe("buildThoughtNarrativeBlocks", () => {
  beforeEach(() => { seqCounter = 0; });

  it("creates one reasoning block from started + delta + completed", () => {
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 0, delta: "Hello" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 5, delta: " world" }),
      makeEvent("visible_thought_completed", { step_index: 0, stream_id: "s1", text: "Hello world" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: "reasoning", text: "Hello world", isComplete: true });
  });

  it("does not duplicate when delta events are replayed (seq-based)", () => {
    seqCounter = 0;
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 0, delta: "Hello" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 5, delta: " world" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: "reasoning", text: "Hello world", isComplete: false });
  });

  it("handles pause-tool-resume flow without duplicates", () => {
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 0, delta: "Searching..." }),
      makeEvent("visible_thought_paused", { step_index: 0, stream_id: "s1", text: "Searching..." }),
      makeEvent("tool_started", { step_index: 0, action_type: "web_search" }),
      makeEvent("tool_completed", { step_index: 0, action_type: "web_search" }),
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1-resume" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1-resume", offset: 0, delta: "Found results" }),
      makeEvent("visible_thought_completed", { step_index: 0, stream_id: "s1-resume", text: "Found results" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    const reasoningBlocks = blocks.filter(b => b.kind === "reasoning");
    expect(reasoningBlocks).toHaveLength(2);
    expect(reasoningBlocks[0]).toMatchObject({ text: "Searching...", isComplete: true });
    expect(reasoningBlocks[1]).toMatchObject({ text: "Found results", isComplete: true });
    expect(blocks.filter(b => b.kind === "tool")).toHaveLength(1);
  });

  it("handles completed event with full text overwrite", () => {
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
      makeEvent("visible_thought_delta", { step_index: 0, stream_id: "s1", offset: 0, delta: "abc" }),
      makeEvent("visible_thought_completed", { step_index: 0, stream_id: "s1", text: "Finalized text" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: "reasoning", text: "Finalized text", isComplete: true });
  });

  it("returns empty for no events", () => {
    expect(buildThoughtNarrativeBlocks([])).toEqual([]);
  });

  it("ignores empty-text reasoning blocks when filtered", () => {
    const events = [
      makeEvent("visible_thought_started", { step_index: 0, stream_id: "s1" }),
    ];
    const blocks = buildThoughtNarrativeBlocks(events);
    // Empty reasoning block with no text should be filtered out
    expect(blocks).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
npx vitest run src/hooks/use-thought-narrative-blocks.test.ts 2>&1
```

Expected: FAIL — test expects `buildThoughtNarrativeBlocks` without snapshots parameters.

- [ ] **Step 3: Edit thought-narrative.ts — remove snapshot merge**

Open `frontend/src/lib/thought-narrative.ts`. In function `buildThoughtNarrativeBlocks` (line 177-315), remove the snapshot merge section (lines 289-311 — the `for (const [rawStepIndex, ...] of Object.entries(visibleThoughtByStep))` block). Replace the function signature from:

```typescript
export function buildThoughtNarrativeBlocks(
  events: AgentRunEvent[],
  visibleThoughtByStep: Record<number, string>,
  visibleThoughtStreamIds: Record<number, string>,
): ThoughtNarrativeBlock[] {
```

To:

```typescript
export function buildThoughtNarrativeBlocks(
  events: AgentRunEvent[],
): ThoughtNarrativeBlock[] {
```

And remove the entire `for (const [rawStepIndex, snapshotText] ...) { ... }` block (lines 289-311).

At the end, change the return from:
```typescript
  return mergeAdjacentReasoningBlocks(
    blocks.filter((block) => block.kind === "tool" || block.text.trim()),
  );
```
To:
```typescript
  return blocks.filter((block) => block.kind === "tool" || block.text.trim());
```

Remove `mergeAdjacentReasoningBlocks` function entirely (lines 158-175).

- [ ] **Step 4: Rewrite use-thought-narrative-blocks.ts**

Replace the entire content of `frontend/src/hooks/use-thought-narrative-blocks.ts`:

```typescript
"use client";

import { useMemo } from "react";
import type { AgentRunEvent } from "@/types/agent";
import type { ThoughtNarrativeBlock } from "@/lib/thought-narrative";
import { buildThoughtNarrativeBlocks } from "@/lib/thought-narrative";

export default function useThoughtNarrativeBlocks(
  events: AgentRunEvent[],
): ThoughtNarrativeBlock[] {
  return useMemo(() => buildThoughtNarrativeBlocks(events), [events]);
}
```

- [ ] **Step 5: Run hook tests to verify they pass**

```powershell
npx vitest run src/hooks/use-thought-narrative-blocks.test.ts 2>&1
```

Expected: all tests PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/use-thought-narrative-blocks.ts frontend/src/hooks/use-thought-narrative-blocks.test.ts frontend/src/lib/thought-narrative.ts
git commit -m "feat: rewrite thought narrative hook as pure useMemo, remove snapshot merge"
```

---

### Task 4: Remove Snapshot Props from Component Chain

**Files:**
- Modify: `frontend/src/components/agent/thought-narrative.tsx` — remove `visibleThoughtByStep`/`visibleThoughtStreamIds` from props
- Modify: `frontend/src/components/agent/session-conversation-stream.tsx` — stop passing snapshot props

**Interfaces:**
- Consumes: Updated `useThoughtNarrativeBlocks(events)` from Task 3 (no longer takes snapshots)
- Produces: Cleaner component chain without snapshot passthrough

- [ ] **Step 1: Edit thought-narrative.tsx — remove snapshot props**

In `frontend/src/components/agent/thought-narrative.tsx`:

Replace the Props type (lines 16-24):

```typescript
type Props = {
  run: AgentRun;
  steps: { id: string; step_number: number; thought_summary: string | null; action_type: string | null; status: string }[];
  events: AgentRunEvent[];
  isLiveRun?: boolean;
  answerStartedAt?: string | null;
};
```

Replace the component function signature (lines 91-99):

```typescript
const ThoughtNarrative = React.memo(function ThoughtNarrativeImpl({
  run,
  steps: _steps,
  events,
  isLiveRun = false,
  answerStartedAt = null,
}: Props) {
```

Replace the `useThoughtNarrativeBlocks` call (line 114):

```typescript
  const blocks = useThoughtNarrativeBlocks(events);
```

In the `React.memo` comparison function (lines 180-187), remove `visibleThoughtByStep` and `visibleThoughtStreamIds` comparisons:

```typescript
}, (prevProps, nextProps) => {
  return prevProps.run === nextProps.run &&
    prevProps.steps === nextProps.steps &&
    prevProps.events === nextProps.events &&
    prevProps.isLiveRun === nextProps.isLiveRun;
});
```

- [ ] **Step 2: Edit session-conversation-stream.tsx — stop passing snapshot props**

In `frontend/src/components/agent/session-conversation-stream.tsx`, lines 93-101, change the ThoughtNarrative usage from:

```typescript
      <ThoughtNarrative
        run={displayRun}
        steps={adaptedSteps}
        events={streamState.narrativeEvents}
        visibleThoughtByStep={streamState.visibleThoughtByStep}
        visibleThoughtStreamIds={streamState.visibleThoughtStreamIds}
        isLiveRun={shouldStream}
        answerStartedAt={answerStartedEvent?.created_at ?? null}
      />
```

To:

```typescript
      <ThoughtNarrative
        run={displayRun}
        steps={adaptedSteps}
        events={streamState.narrativeEvents}
        isLiveRun={shouldStream}
        answerStartedAt={answerStartedEvent?.created_at ?? null}
      />
```

- [ ] **Step 3: Run TypeScript type-check**

```powershell
npx tsc --noEmit 2>&1 | Select-String "thought-narrative|session-conversation" 2>&1
```

Expected: no type errors from these files.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/agent/thought-narrative.tsx frontend/src/components/agent/session-conversation-stream.tsx
git commit -m "refactor: remove snapshot props from thought narrative component chain"
```

---

### Task 5: Integration Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full frontend test suite**

```powershell
npx vitest run 2>&1 | Select-Object -Last 15
```

Expected: all tests pass.

- [ ] **Step 2: Run TypeScript full check**

```powershell
npx tsc --noEmit 2>&1 | Select-Object -Last 20
```

Expected: zero type errors.

- [ ] **Step 3: ESLint check**

```powershell
npx eslint src/lib/markdown-split.ts src/components/agent/progressive-markdown.tsx src/hooks/use-thought-narrative-blocks.ts src/components/agent/thought-narrative.tsx src/components/agent/session-conversation-stream.tsx 2>&1
```

Expected: zero lint errors.

- [ ] **Step 4: Manual visual verification**

Start the dev server (`npm run dev`), create a new agent run, observe:
1. Thinking panel: each reasoning step appears once, no duplicated text
2. Final answer: completed paragraphs render as styled Markdown, active tail is plain text with blinking cursor
3. `**bold**, *italic*, `code`` markers in the active tail are visible as raw text (not parsed) until closed
4. Fenced code blocks appear as atomic units, no split in the middle

- [ ] **Step 5: Final commit**

```bash
git add -A
git diff --staged --stat
git commit -m "chore: integration verification — all tests pass, zero type errors"
```
