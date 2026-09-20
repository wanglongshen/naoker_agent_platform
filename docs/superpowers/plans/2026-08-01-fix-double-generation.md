# Fix Double-Generation of Thinking & Answer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate duplicated thinking and answer rendering — keep ONLY the frontend typewriter-animation path.

**Architecture:** Two independent fixes. (1) Backend: in `_stream_visible_thought_with_tool_interleave`, when `pre_generated_thought` is provided (merged Mode B path), do NOT re-emit `visible_thought_started`/`visible_thought_delta` — the merged method already streamed them; only the final `visible_thought_completed` is emitted. (2) Frontend: `ProgressiveMarkdown` streaming branch stops using `splitBlocks` — the full text goes through `StreamingTail` (which already renders progressive Markdown), removing the instant `CompletedBlock` duplicates.

**Tech Stack:** Python (backend), TypeScript/React (frontend)

## Global Constraints

- Spec: root cause confirmed in session — merged call emits thought events twice; splitBlocks + StreamingTail render answers twice
- Keep the typewriter path: thinking via `useTypingText`, answer via `StreamingTail`
- `_stream_merged_plan_thought` NOT modified (its live thought streaming is the keeper)
- Existing tests must pass (88 backend tool/loop tests, 63 agent-streaming frontend tests)

---

### Task 1: Backend — no duplicate thought event emission in pre-generated branch

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `pre_generated_thought: str | None` param (already exists)
- Produces: when `pre_generated_thought` is set, only `visible_thought_completed` is emitted (no started/delta)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_agent_loop.py` (inside or near `TestMergedPlanThought`):

```python
    async def test_pre_generated_thought_emits_no_started_or_delta(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append(event_type)
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        async def fake_final_answer(repo, ctx, messages):
            return "答案"
        monkeypatch.setattr(service, "_stream_final_answer", fake_final_answer)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000020"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000021"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        await service._stream_visible_thought_with_tool_interleave(
            repo=mock_repo, ctx=ctx, step_index=0,
            validated_action_type="finish",
            messages=[{"role": "user", "content": "x"}],
            action={"type": "finish", "input": {}},
            previous_observation=None,
            web_enabled=True,
            pre_generated_thought="我将直接回答",
        )

        assert "visible_thought_started" not in emitted
        assert "visible_thought_delta" not in emitted
        assert "visible_thought_completed" in emitted
```

Note: match the method's ACTUAL signature (read it first — `repo, ctx, step_index, validated_action_type, messages, action, previous_observation, web_enabled=True, owner_user_id=None, is_super_admin=False, pre_generated_thought=None`).

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -k "pre_generated_thought_emits_no_started" -v
```

Expected: FAIL — started+delta currently emitted.

- [ ] **Step 3: Implement the fix**

In `backend/app/services/agent/loop.py`, `_stream_visible_thought_with_tool_interleave`:

Move the unconditional `visible_thought_started` emission (currently lines 518-524) INTO the `else:` branch so it only fires for the streaming path. Then change the `if pre_generated_thought is not None:` branch to NOT emit started/delta:

```python
        stream_id = f"visible-thought-{ctx.run.id}-{step_index}"

        text = ""
        fallback = False
        emitted_any_chunk = False
        observation = None

        if pre_generated_thought is not None:
            text = pre_generated_thought
            emitted_any_chunk = True
        else:
            await self._persist_and_notify(
                repo,
                ctx,
                "visible_thought_started",
                {"step_index": step_index, "stream_id": stream_id},
            )
            try:
                async for chunk in self.llm_client.stream_text(messages):
                    # ... existing streaming body unchanged ...
            except Exception:
                # ... existing except body unchanged ...
```

Keep everything after the if/else (finalize, finish branch, tool branch, resume) unchanged — the existing `visible_thought_completed` emission at the finish branch (and the resume/finalize paths) already provides the completion event.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -k "pre_generated_thought_emits_no_started" -v
```

Expected: PASS.

- [ ] **Step 5: Run the full loop suite**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py tests/test_agent_worker.py -v
```

Expected: All pass (existing tests unaffected — they don't use the pre-generated path or mock `_persist_and_notify` at this granularity). If any existing merged-path test breaks, verify it asserts on the OLD duplicate behavior before adjusting; do NOT weaken the new test.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "fix: pre-generated thought no longer re-emits started/delta events"
```

---

### Task 2: Frontend — streaming path uses full text through StreamingTail

**Files:**
- Modify: `frontend/src/components/agent/progressive-markdown.tsx`
- Test: `frontend/src/components/agent/agent-streaming.test.tsx`

**Interfaces:**
- Consumes: `text` prop, `terminal`, `animateTerminal`
- Produces: streaming branch returns `{ completed: [], active: text }` — all text goes through `StreamingTail` (progressive Markdown via ReactMarkdown); `splitBlocks` no longer used

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/agent/agent-streaming.test.tsx` (inside the `FinalAnswerPanel` describe block):

```tsx
test("streaming answer does not render completed blocks instantly (single typed source)", () => {
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList);

  const { container } = render(
    <FinalAnswerPanel
      run={baseRun}
      streamingAnswer={`# 标题

已完成段落

正在写的段落`}
      answerStreamId="single-source"
    />,
  );

  // No instant Markdown heading may exist before typing advances —
  // completed paragraphs must NOT render as separate instant CompletedBlock markdown.
  expect(container.querySelector("h1")).toBeNull();
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -t "does not render completed blocks instantly" -v
```

Expected: FAIL — `splitBlocks` renders `# 标题` as an instant `<h1>` via `CompletedBlock` before typing starts.

- [ ] **Step 3: Implement the fix**

In `frontend/src/components/agent/progressive-markdown.tsx`:

Change the streaming branch of the `useMemo` (line 121) from `splitBlocks(text)` to:

```typescript
    return { completed: [], active: text };
```

Remove the now-unused import (line 11):

```typescript
import { splitBlocks } from "@/lib/markdown-split";
```

- [ ] **Step 4: Run the new test to verify it passes**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -t "does not render completed blocks instantly" -v
```

Expected: PASS.

- [ ] **Step 5: Run full agent-streaming suite**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: All pass (63 existing + 1 new). If any test asserted the OLD split behavior (instant markdown headings during streaming), update that test to assert the typewriter behavior instead — do NOT weaken the new test.

- [ ] **Step 6: Run full frontend suite + build**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
cd C:\01_agent_loop_pro\frontend && npx next build
```

Expected: No new failures; build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/agent/progressive-markdown.tsx frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "fix: streaming renders all text through StreamingTail, remove instant completed blocks"
```
