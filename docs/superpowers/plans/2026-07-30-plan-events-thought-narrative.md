# Plan Event Rendering in Thought Narrative — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show planner streaming text in the thought panel instead of static "正在分析你的需求..."

**Architecture:** Add `plan_started`/`plan_delta`/`plan_completed` handling to `buildThoughtNarrativeBlocks`, reusing the existing "reasoning" block pattern from `visible_thought_*`.

**Tech Stack:** TypeScript

## Global Constraints

- Do NOT change the reducer (`run-stream-reducer.ts`) — it already handles plan_* events
- Do NOT change backend code
- Keep existing `visible_thought_*` behavior unchanged
- Tests must pass

---

### Task 1: Add plan_* handling to `buildThoughtNarrativeBlocks`

**Files:**
- Modify: `frontend/src/lib/thought-narrative.ts:230` (insert before tool_started handler)

**Interfaces:**
- Consumes: `plan_started`, `plan_delta`, `plan_completed` events in `AgentRunEvent[]`
- Produces: "reasoning" blocks in `ThoughtNarrativeBlock[]`

- [ ] **Step 1: Add plan event handlers**

In `frontend/src/lib/thought-narrative.ts`, insert after the `visible_thought_completed` handler (before line 232 `if (event.event_type === "tool_started"`):

```typescript
    if (event.event_type === "plan_started" && streamId && stepIndex !== null) {
      if (findReasoningIndex(blocks, streamId) === -1) {
        blocks.push({
          kind: "reasoning",
          id: `reasoning-${streamId}`,
          streamId,
          stepIndex,
          text: "",
          isComplete: false,
        });
      }
      continue;
    }

    if (event.event_type === "plan_delta" && streamId && stepIndex !== null) {
      let reasoningIndex = findReasoningIndex(blocks, streamId);
      if (reasoningIndex === -1) {
        blocks.push({
          kind: "reasoning",
          id: `reasoning-${streamId}`,
          streamId,
          stepIndex,
          text: "",
          isComplete: false,
        });
        reasoningIndex = blocks.length - 1;
      }
      const block = blocks[reasoningIndex];
      if (block.kind !== "reasoning") {
        continue;
      }
      const offset = readNumber(payload, "offset") ?? 0;
      const delta = typeof payload.delta === "string" ? payload.delta : "";
      if (offset === block.text.length) {
        blocks[reasoningIndex] = { ...block, text: block.text + delta };
      }
      continue;
    }

    if (event.event_type === "plan_completed" && streamId && stepIndex !== null) {
      let reasoningIndex = findReasoningIndex(blocks, streamId);
      if (reasoningIndex === -1) {
        blocks.push({
          kind: "reasoning",
          id: `reasoning-${streamId}`,
          streamId,
          stepIndex,
          text: "",
          isComplete: false,
        });
        reasoningIndex = blocks.length - 1;
      }
      const block = blocks[reasoningIndex];
      if (block.kind === "reasoning") {
        blocks[reasoningIndex] = {
          ...block,
          text: typeof payload.text === "string" ? payload.text.trim() : block.text,
          isComplete: true,
        };
      }
      continue;
    }
```

- [ ] **Step 2: Run thought narrative tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/lib/thought-narrative.test.ts -v
```

Expected: All existing tests pass (the `plan_created` event at line 38 is already handled by the default branch).

- [ ] **Step 3: Run full test suite for safety**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
```

Expected: No new failures introduced.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/thought-narrative.ts
git commit -m "feat: render plan_started/plan_delta/plan_completed in thought narrative"
```
