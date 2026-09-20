# StreamingTail LastTimeReset Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix typing animation accumulating lost time on every SSE event, causing large text bursts.

**Architecture:** Change `lastTimeRef` from `number` (where `0` is falsy, accidentally triggering default-speed path) to `number | null` (where `null` unambiguously means "no previous tick"). Remove the reset on line 86 so real elapsed time persists across targetText changes.

**Tech Stack:** TypeScript, React

## Global Constraints

- Do NOT change any other file
- Do NOT change the typing animation algorithm (`advanceTypingAnimation`)
- Do NOT change `TYPING_SPEED_MS`
- Ensure existing `agent-streaming.test.tsx` (62 tests) still passes

---

### Task 1: Fix `lastTimeRef` timing drift

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx:57, 70, 86`

**Interfaces:**
- Consumes: `lastTimeRef` (changed from `number` to `number | null`)
- Produces: Correct `elapsed` calculation in all scenarios

- [ ] **Step 1: Change type declaration**

Line 57 — change from:
```typescript
const lastTimeRef = useRef<number>(0);
```
to:
```typescript
const lastTimeRef = useRef<number | null>(null);
```

- [ ] **Step 2: Change null check**

Line 70 — change from:
```typescript
const elapsed = lastTimeRef.current ? now - lastTimeRef.current : TYPING_SPEED_MS;
```
to:
```typescript
const elapsed = lastTimeRef.current !== null ? now - lastTimeRef.current : TYPING_SPEED_MS;
```

- [ ] **Step 3: Delete the reset**

Line 86 — delete this line entirely:
```typescript
lastTimeRef.current = 0;
```

- [ ] **Step 4: Verify tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: 62 tests pass (same as before the fix)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx
git commit -m "fix: prevent lastTimeRef reset on every SSE event causing typing drift"
```
