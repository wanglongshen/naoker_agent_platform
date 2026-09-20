# 全文打字机答案显示（方案 B）— Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer streams smoothly from the first character via the typewriter animation — no instant paragraph bursts at the start.

**Architecture:** Restore the `StreamingTail` component (rAF + `advanceTypingAnimation` + 30fps progressive Markdown + cursor). `ProgressiveMarkdown` streaming branch sends the FULL text to `StreamingTail` (`{ completed: [], active: text }`); terminal renders `CompletedBlock` directly. `splitBlocks` import removed.

**Tech Stack:** TypeScript, React

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-full-typewriter-answer-design.md`
- No `animateTerminal` / `terminalTyped` / run-completion re-typing (that was the rejected "两遍 bug")
- `TYPING_SPEED_MS = 20` (fixed speed, no acceleration — acceleration tiers were removed earlier)
- Thinking area unchanged
- Tests must pass

---

### Task 1: Restore StreamingTail and route full text through it

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx`
- Test: `frontend/src/components/agent/agent-streaming.test.tsx`

**Interfaces:**
- Consumes: `text: string`, `terminal: boolean`
- Produces: streaming → `StreamingTail` (typewriter + progressive Markdown); terminal → `CompletedBlock`

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/agent/agent-streaming.test.tsx`, replace the four tests that currently assert instant/SSE-driven behavior:

Replace `streaming answer renders completed paragraphs as instant markdown headings` (was line 149) with:

```tsx
test("streaming answer does not render headings instantly — typewriter types them", () => {
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
      answerStreamId="no-instant-heading"
    />,
  );

  expect(container.querySelector("h1")).toBeNull();
  expect(container.querySelector(".streaming-tail")).not.toBeNull();
});
```

Replace `streaming answer markdown updates as text grows` (was line 173) with:

```tsx
test("streaming answer types heading after rAF frames advance", async () => {
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

稳定段落

尾部继续`}
        answerStreamId="live-grow"
      />,
    );
    act(() => {
      for (let i = 1; i <= 12; i += 1) {
        raf.runNextFrame(i * 16);
      }
    });
    expect(screen.getByRole("heading", { name: "标题" })).toBeVisible();
    expect(screen.getByText("稳定段落")).toBeVisible();
  } finally {
    vi.restoreAllMocks();
  }
});
```

Replace `renders streaming answer with long text via markdown` (was line 200) with:

```tsx
test("renders streaming answer with long text through a single streaming tail", () => {
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

  expect(container.querySelector(".streaming-tail")).not.toBeNull();
});
```

Replace `streaming answer heading renders without rAF typing animation` (was line 222) with:

```tsx
test("streaming answer heading requires rAF frames to appear", async () => {
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
        streamingAnswer={`# 韭菜炒鸡蛋

第一步已经完成。`}
        answerStreamId="typing-required"
      />,
    );
    expect(screen.queryByRole("heading", { name: "韭菜炒鸡蛋" })).toBeNull();
    act(() => {
      for (let i = 1; i <= 10; i += 1) {
        raf.runNextFrame(i * 16);
      }
    });
    expect(screen.getByRole("heading", { name: "韭菜炒鸡蛋" })).toBeVisible();
  } finally {
    vi.restoreAllMocks();
  }
});
```

Note: `installFakeRaf` is already defined at the bottom of the file (returns `{ pendingCount, runNextFrame }`); `act` is imported at the top.

- [ ] **Step 2: Run tests to verify they FAIL**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: The 4 rewritten tests FAIL (headings render instantly; no `.streaming-tail`).

- [ ] **Step 3: Rewrite `progressive-markdown.tsx`**

Replace the ENTIRE file with:

```typescript
"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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

function StreamingTail({ targetText }: { targetText: string }) {
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

export default function ProgressiveMarkdown({ text, terminal }: { text: string; terminal: boolean }) {
  const { completed, active } = useMemo(() => {
    if (!text) return { completed: [] as string[], active: "" };
    if (terminal) return { completed: [text], active: "" };
    return { completed: [], active: text };
  }, [text, terminal]);

  if (!text) return null;

  if (terminal) {
    return <CompletedBlock content={text} />;
  }

  return (
    <>
      {completed.map((block, i) => (
        <CompletedBlock key={`${i}-${block.slice(0, 40)}`} content={block} />
      ))}
      {active ? <StreamingTail targetText={active} /> : null}
    </>
  );
}
```

Key points:
- `StreamingTail` restored: rAF loop, `advanceTypingAnimation` at fixed 20ms/char, `lastTimeRef` null semantics (no timer drift), every-2-frame setState (30fps), progressive ReactMarkdown, cursor
- No `onComplete` needed (no terminal re-type)
- Streaming branch: `{ completed: [], active: text }` — full text through typewriter
- `splitBlocks` import removed

- [ ] **Step 4: Run tests to verify they PASS**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: All pass. If other tests fail (e.g., any remaining assertion on instant headings), update them to typewriter behavior — do NOT weaken the 4 new tests.

- [ ] **Step 5: Full suite + build**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
cd C:\01_agent_loop_pro\frontend && npx next build
```

Expected: No new failures; build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "feat: full-text typewriter answer display — restore StreamingTail, no instant bursts"
```
