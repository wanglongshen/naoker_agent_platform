# liveStreamed Flag for Terminal Typing Animation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer panel types out via StreamingTail when a live run completes, even after session refresh. Historical runs never animate.

**Architecture:** Add `liveStreamed: boolean` to `RunStreamState`. Set to `true` when the SSE connection opens (proves the run was watched live). `FinalAnswerPanel` receives `wasLiveStreamed` prop and uses it for `animateTerminal` instead of `isLiveRun` (which becomes false after session refresh).

**Tech Stack:** TypeScript, React

## Global Constraints

- Historical sessions must NOT animate (liveStreamed=false on load)
- SSE connection open event is the ONLY source of truth for liveStreamed=true
- All existing tests must pass

---

### Task 1: Add liveStreamed flag to state

**Files:**
- Modify: `frontend/src/lib/run-stream-reducer.ts`

**Interfaces:**
- Consumes: `RunStreamState` type
- Produces: `liveStreamed: boolean` field (default false)

- [ ] **Step 1: Add field to RunStreamState**

At line 47-57 of `frontend/src/lib/run-stream-reducer.ts`, add `liveStreamed` to the type:

```typescript
export type RunStreamState = {
  run: AgentRun | null;
  events: AgentRunEvent[];
  narrativeEvents: AgentRunEvent[];
  lastSeq: number;
  connection: RunStreamConnection;
  answerText: string;
  answerStreamId: string | null;
  visibleThoughtByStep: Record<number, string>;
  visibleThoughtStreamIds: Record<number, string>;
  liveStreamed: boolean;
};
```

- [ ] **Step 2: Add default to createInitialRunStreamState**

At line 100-112 of `frontend/src/lib/run-stream-reducer.ts`, add `liveStreamed: false` to the baseState:

```typescript
  const baseState: RunStreamState = {
    run: options.initialRun ?? null,
    events: [],
    narrativeEvents: [],
    lastSeq: 0,
    connection:
      options.disabled ? "closed" :
      options.initialRun && TERMINAL_STATUSES.has(options.initialRun.status) ? "closed" : "connecting",
    answerText: options.initialRun?.result?.final_answer ?? "",
    answerStreamId: null,
    visibleThoughtByStep: {},
    visibleThoughtStreamIds: {},
    liveStreamed: false,
  };
```

- [ ] **Step 3: Run reducer tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/lib/run-stream-reducer.test.ts -v
```

Expected: All tests pass (adding a field doesn't break existing assertions).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/run-stream-reducer.ts
git commit -m "feat: add liveStreamed flag to run stream state"
```

---

### Task 2: Set liveStreamed=true when SSE opens

**Files:**
- Modify: `frontend/src/hooks/use-run-event-stream.ts:290`

**Interfaces:**
- Consumes: `streamState.liveStreamed`
- Produces: `liveStreamed=true` when EventSource connection opens

- [ ] **Step 1: Set flag in onopen handler**

At line 290 of `frontend/src/hooks/use-run-event-stream.ts`, change:

```typescript
        updateState({ ...stateRef.current, connection: "open" });
```

to:

```typescript
        updateState({ ...stateRef.current, connection: "open", liveStreamed: true });
```

- [ ] **Step 2: Run hook tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/hooks/use-run-event-stream.test.ts -v
```

Expected: No new failures (5 pre-existing failures unchanged).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/use-run-event-stream.ts
git commit -m "feat: mark run as liveStreamed when SSE connection opens"
```

---

### Task 3: Pass wasLiveStreamed to FinalAnswerPanel and use it

**Files:**
- Modify: `frontend/src/components/agent/session-conversation-stream.tsx`
- Modify: `frontend/src/components/agent/final-answer-panel.tsx`

**Interfaces:**
- Consumes: `streamState.liveStreamed` (Task 1+2)
- Produces: `FinalAnswerPanel` prop `wasLiveStreamed: boolean`

- [ ] **Step 1: Add prop to FinalAnswerPanel**

In `frontend/src/components/agent/final-answer-panel.tsx`, add `wasLiveStreamed = false` to props:

```typescript
export default function FinalAnswerPanel({
  run,
  streamingAnswer = "",
  answerStreamId = null,
  isLiveRun = true,
  wasLiveStreamed = false,
  onRegenerate,
}: {
  run: AgentRun;
  streamingAnswer?: string;
  answerStreamId?: string | null;
  isLiveRun?: boolean;
  wasLiveStreamed?: boolean;
  onRegenerate?: () => void;
}) {
```

- [ ] **Step 2: Change animateTerminal to use wasLiveStreamed**

In the same file, line 78, change:

```typescript
<ProgressiveMarkdown text={displayText} terminal={isTerminal} animateTerminal={isTerminal && streamedAnswer !== null && isLiveRun} />
```

to:

```typescript
<ProgressiveMarkdown text={displayText} terminal={isTerminal} animateTerminal={isTerminal && wasLiveStreamed} />
```

- [ ] **Step 3: Pass wasLiveStreamed in SessionTurn**

In `frontend/src/components/agent/session-conversation-stream.tsx`, at the FinalAnswerPanel call (line 100-106), add the prop:

```typescript
      <FinalAnswerPanel
        run={displayRun}
        streamingAnswer={streamState.answerText}
        answerStreamId={streamState.answerStreamId}
        isLiveRun={shouldStream}
        wasLiveStreamed={streamState.liveStreamed}
        onRegenerate={onRegenerate ? () => onRegenerate(run) : undefined}
      />
```

- [ ] **Step 4: Run tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent/final-answer-panel.tsx frontend/src/components/agent/session-conversation-stream.tsx
git commit -m "fix: use liveStreamed flag for terminal typing animation"
```
