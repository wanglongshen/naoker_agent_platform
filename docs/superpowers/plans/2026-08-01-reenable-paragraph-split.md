# Re-enable Paragraph-Split Markdown Rendering During Streaming

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render completed paragraphs as ReactMarkdown while the active paragraph types character-by-character via StreamingTail.

**Architecture:** Re-import `splitBlocks` and use it during streaming (`terminal=false`). Completed paragraphs (split by `\n\n`) render immediately via `CompletedBlock` (ReactMarkdown). The last incomplete paragraph types through `StreamingTail` (plain text). When the run completes, `animateTerminal=true` types the final answer before switching to full ReactMarkdown.

**Tech Stack:** TypeScript, React

## Global Constraints

- Keep all existing fixes: 20ms/char speed, lastTimeRef drift fix, terminal typing animation, reducer preserving answerText
- Do NOT change backend code
- Existing tests must pass

---

### Task 1: Re-enable paragraph splitting in ProgressiveMarkdown

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx`

**Interfaces:**
- Consumes: `splitBlocks` from `@/lib/markdown-split`
- Produces: Completed blocks rendered as ReactMarkdown, active tail typed as plain text

- [ ] **Step 1: Import splitBlocks**

Add back the import (after line 10):

```typescript
import { splitBlocks } from "@/lib/markdown-split";
```

- [ ] **Step 2: Change useMemo to split during streaming**

Change lines 108-111 from:

```typescript
  const { completed, active } = useMemo(() => {
    if (terminal || !text) return { completed: text ? [text] : [], active: "" };
    return { completed: [], active: text };
  }, [text, terminal]);
```

to:

```typescript
  const { completed, active } = useMemo(() => {
    if (terminal || !text) return { completed: text ? [text] : [], active: "" };
    return splitBlocks(text);
  }, [text, terminal]);
```

- [ ] **Step 3: Run tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

- [ ] **Step 4: Full suite**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx
git commit -m "feat: re-enable paragraph-split markdown rendering during streaming"
```
