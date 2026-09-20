# SSE-Driven Answer Display (Remove Typewriter Animation) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer display shows text at the pace SSE delivers it (paragraphs render instantly as Markdown when complete), removing the frontend typewriter animation entirely.

**Architecture:** `ProgressiveMarkdown` reverts to the simple structure: streaming (`terminal=false`) splits text via `splitBlocks` — completed paragraphs render instantly as `CompletedBlock` (ReactMarkdown), the active tail renders arrived text directly via ReactMarkdown (no typing animation). Terminal renders full `CompletedBlock`. The `StreamingTail` component (rAF typing), `terminalTyped` state, and `animateTerminal` prop are removed.

**Tech Stack:** TypeScript, React

## Global Constraints

- Thinking area (ThoughtNarrative / `useTypingText`) is UNCHANGED — only the answer display changes
- Backend unchanged — SSE `answer_delta` batching (20ms) is the pacing mechanism
- `FinalAnswerPanel` must compile after the prop removal
- Tests must pass (64 agent-streaming → updated set)

---

### Task 1: Rewrite ProgressiveMarkdown — no typewriter, splitBlocks restored

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx`
- Modify: `frontend/src/components/agent/final-answer-panel.tsx`

**Interfaces:**
- Consumes: `text: string`, `terminal: boolean` (same props minus `animateTerminal`)
- Produces: `{ completed: string[], active: string }` via `splitBlocks`; completed → `CompletedBlock`, active → direct `ReactMarkdown`

- [ ] **Step 1: Write the failing tests**

Update `frontend/src/components/agent/agent-streaming.test.tsx` — the four tests that asserted typewriter behavior must now assert the new behavior (write them FIRST so they fail against current code):

Replace the test at line 149 (`streaming answer does not render completed blocks instantly`) with the INVERSE:

```tsx
test("streaming answer renders completed paragraphs as instant markdown headings", () => {
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);

  const { container } = render(
    <FinalAnswerPanel
      run={baseRun}
      streamingAnswer={`# 标题

完成的段落。

活动`}
      answerStreamId="instant-heading"
    />,
  );

  expect(container.querySelector("h1")).not.toBeNull();
  expect(screen.getByText("完成的段落。")).toBeVisible();
});
```

Replace the test at line 173 (`streaming tail DOM element persists when text grows`) with a test that the markdown content updates as the text grows (no `.streaming-tail` element anymore):

```tsx
test("streaming answer markdown updates as text grows", async () => {
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);
  const { rerender } = render(
    <FinalAnswerPanel run={baseRun} streamingAnswer={`# 标题

稳定段落`} answerStreamId="live-grow" />,
  );
  expect(screen.getByRole("heading", { name: "标题" })).toBeVisible();

  rerender(
    <FinalAnswerPanel run={baseRun} streamingAnswer={`# 标题

稳定段落

尾部继续`} answerStreamId="live-grow" />,
  );

  expect(screen.getByText("尾部继续")).toBeVisible();
});
```

Replace the test at line 200 (`renders streaming answer with long text in a single streaming tail`) with:

```tsx
test("renders streaming answer with long text via markdown", () => {
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);

  const { container } = render(
    <FinalAnswerPanel
      run={baseRun}
      streamingAnswer={`# 长答案标题

稳定的段落。

${"z".repeat(500)}`}
      answerStreamId="large-answer"
    />,
  );

  expect(container.querySelector("h1")).not.toBeNull();
});
```

Replace the test at line 222 (`streaming answer renders typed markdown progressively as headings` — used `installFakeRaf`) with a test that no rAF typing is involved:

```tsx
test("streaming answer heading renders without rAF typing animation", async () => {
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);

  render(
    <FinalAnswerPanel
      run={baseRun}
      streamingAnswer={`# 韭菜炒鸡蛋

第一步已经完成。`}
      answerStreamId="no-typing"
    />,
  );

  expect(screen.getByRole("heading", { name: "韭菜炒鸡蛋" })).toBeVisible();
  expect(document.querySelector(".streaming-tail")).toBeNull();
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: The 4 rewritten tests FAIL against current typewriter code (e.g., heading not found because text goes through StreamingTail with empty initial `displayed`; `.streaming-tail` still exists).

- [ ] **Step 3: Rewrite `progressive-markdown.tsx`**

Replace the ENTIRE file content with:

```typescript
"use client";

import React, { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { splitBlocks } from "@/lib/markdown-split";

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

export default function ProgressiveMarkdown({ text, terminal }: { text: string; terminal: boolean }) {
  const { completed, active } = useMemo(() => {
    if (!text) return { completed: [] as string[], active: "" };
    if (terminal) return { completed: [text], active: "" };
    return splitBlocks(text);
  }, [text, terminal]);

  if (!text) return null;

  return (
    <>
      {completed.map((block, i) => (
        <CompletedBlock key={`${i}-${block.slice(0, 40)}`} content={block} />
      ))}
      {active ? (
        <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={mdComponents}>
          {active}
        </ReactMarkdown>
      ) : null}
    </>
  );
}
```

Key removals: `StreamingTail` (rAF typing), `TYPING_SPEED_MS`, `terminalTyped` state, `animateTerminal` prop, `useEffect`/`useRef`/`useState` imports, `typing-animation` imports.

- [ ] **Step 4: Update `FinalAnswerPanel` — stop passing `animateTerminal`**

In `frontend/src/components/agent/final-answer-panel.tsx`, find the `ProgressiveMarkdown` render (around line 78) with `animateTerminal={isTerminal && wasLiveStreamed}` and change it to:

```typescript
<ProgressiveMarkdown text={displayText} terminal={isTerminal} />
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: All pass (remaining tests untouched — e.g., `advanceTypingText` tests target `use-typing-text` which is unchanged).

- [ ] **Step 6: Run full frontend suite + build**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
cd C:\01_agent_loop_pro\frontend && npx next build
```

Expected: No new failures; build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx frontend/src/components/agent/final-answer-panel.tsx frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "refactor: SSE-driven answer display — remove typewriter animation, restore splitBlocks"
```
