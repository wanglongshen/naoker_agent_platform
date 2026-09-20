# Prevent run_succeeded from Bypassing Typing Animation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `run_succeeded` event from overwriting accumulated `answerText` and triggering an immediate terminal render that bypasses the typing animation.

**Architecture:** Two independent fixes: (1) reducer preserves accumulated answerText instead of replacing it with run_succeeded's final_answer payload, (2) FinalAnswerPanel stays in streaming mode until the typing animation catches up to the full text.

**Tech Stack:** TypeScript, React

## Global Constraints

- Do NOT change backend code
- Do NOT change `StreamingTail` or `ProgressiveMarkdown`
- Do NOT change `use-run-event-stream.ts`
- Existing tests must pass

---

### Task 1: Reducer — preserve accumulated answerText on run_succeeded

**Files:**
- Modify: `frontend/src/lib/run-stream-reducer.ts:271`

**Interfaces:**
- Consumes: `run_succeeded` event with optional `final_answer`/`text` payload
- Produces: State where `answerText` retains the accumulated delta text

- [ ] **Step 1: Change the answerText logic in run_succeeded case**

At line 271 of `frontend/src/lib/run-stream-reducer.ts`, change:

```typescript
answerText: hasFinalAnswer ? finalAnswer : state.answerText,
```

to:

```typescript
answerText: hasFinalAnswer && !state.answerText ? finalAnswer : state.answerText,
```

This means: only use `finalAnswer` from the event payload if there's NO existing `answerText` (i.e., SSE deltas didn't accumulate anything). If deltas DID accumulate text, keep it.

- [ ] **Step 2: Run reducer tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/lib/run-stream-reducer.test.ts -v
```

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/run-stream-reducer.ts
git commit -m "fix: preserve accumulated answerText on run_succeeded instead of overwriting"
```

---

### Task 2: FinalAnswerPanel — stay in streaming mode after run completes

**Files:**
- Modify: `frontend/src/components/agent/final-answer-panel.tsx:71`

**Interfaces:**
- Consumes: `shouldAnimate` boolean, `renderedAnswer` text
- Produces: `terminal` stays false while text needs animation

- [ ] **Step 1: Keep terminal=false until renderedAnswer matches streaming answer**

In `frontend/src/components/agent/final-answer-panel.tsx`, at line 71, change:

```typescript
const isTerminal = !shouldAnimate;
```

to:

```typescript
const isTerminal = !shouldAnimate && !(shouldAnimate === false && streamedAnswer && streamedAnswer.length > 0);
```

This keeps `terminal=false` when transitioning from streaming to terminal — if `streamedAnswer` still has text, let the typing animation finish it before switching to ReactMarkdown.

- [ ] **Step 2: Run agent-streaming tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: All tests pass.

- [ ] **Step 3: Run full test suite**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
```

Expected: No new failures.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/agent/final-answer-panel.tsx
git commit -m "fix: keep streaming mode after run succeeds until animation finishes"
```
