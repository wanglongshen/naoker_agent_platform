# Streaming Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the 2-8 second silent planner phase by streaming planner output in real-time and trimming the planner prompt.

**Architecture:** Planner switches from non-streaming `create_plan` (HTTP POST, block until full JSON response) to `stream_text` (SSE, yield tokens as they arrive). Each token batch emits `plan_delta` events through the existing `_persist_and_notify` → Redis Stream → SSE pipeline. Frontend `runStreamReducer` handles `plan_*` events identically to `visible_thought_*` events, reusing `visibleThoughtByStep` with `step_index=0`. Planner prompt is trimmed from ~3000 chars to ~800 chars.

**Tech Stack:** Python/httpx (backend), TypeScript/React (frontend)

## Global Constraints

- `stream_text` already exists in `llm.py` — must not break existing visible_thought streaming
- `_persist_and_notify` and EventBus/RedisStream pipeline unchanged
- `plan_delta` events reuse `visibleThoughtByStep` state (step_index=0 reserved for planning)
- Planner prompt must remain Chinese, must produce valid JSON with `thought_summary` + `action`
- Frontend `buildThoughtNarrativeBlocks` must not be broken by new event types

---

### Task 1: Remove non-streaming `create_plan`, Planner uses `stream_text` directly

**Files:**
- Modify: `backend/app/services/agent/llm.py:47-88`
- Modify: `backend/app/services/agent/planner.py:95`

**Interfaces:**
- Consumes: `DeepSeekClient.stream_text(messages) → AsyncIterator[str]`
- Produces: `ResearchPlanner.next_action(...)` now calls `stream_text` instead of `create_plan`

- [ ] **Step 1: Delete `create_plan` method from `DeepSeekClient`**

Remove lines 47-88 of `backend/app/services/agent/llm.py`:

```python
# REMOVE the entire create_plan method (lines 47-88)
```

- [ ] **Step 2: Update `planner.py` to collect stream and extract JSON**

Replace `next_action` method body (lines 95-98 of `backend/app/services/agent/planner.py`):

```python
full_text = ""
async for chunk in self.client.stream_text(messages):
    full_text += chunk
parsed = self.client._parse_json_content(full_text)
normalized_plan = self._normalize_plan(parsed)
validated = self._validate_plan(normalized_plan)
return validated.model_dump(mode="json")
```

Keep the existing `_build_messages` call unchanged (lines 86-94).

- [ ] **Step 3: Run existing planner tests**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -k "plan" -v --timeout=60
```

Expected: All planner-related tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent/llm.py backend/app/services/agent/planner.py
git commit -m "refactor: replace non-streaming create_plan with stream_text in planner"
```

---

### Task 2: Backend — add `_stream_planning` method with plan_delta events

**Files:**
- Modify: `backend/app/services/agent/loop.py` (~line 958)

**Interfaces:**
- Consumes: `self.llm_client.stream_text(messages)`, `self._persist_and_notify()`
- Produces: `plan_started`, `plan_delta`, `plan_completed` events via existing pipeline

- [ ] **Step 1: Add `_stream_planning` method to `AgentLoopService`**

First, add `from uuid import uuid4` to the imports at line 10 of `backend/app/services/agent/loop.py`:

```python
from uuid import UUID, uuid4
```

Then insert new method after `__init__` and before `_commit_repo`:

```python
from uuid import uuid4

async def _stream_planning(
    self,
    repo: AgentRepository,
    ctx: _AttemptContext,
    messages: list[dict[str, str]],
    step_index: int,
) -> dict[str, Any]:
    stream_id = f"plan-{uuid4().hex[:12]}"
    await self._persist_and_notify(
        repo, ctx, "plan_started",
        {"step_index": step_index, "stream_id": stream_id},
    )

    full_text = ""
    offset = 0
    async for chunk in self.llm_client.stream_text(messages):
        full_text += chunk
        await self._persist_and_notify(
            repo, ctx, "plan_delta",
            {"step_index": step_index, "stream_id": stream_id, "offset": offset, "delta": chunk},
        )
        offset += len(chunk)

    await self._persist_and_notify(
        repo, ctx, "plan_completed",
        {"step_index": step_index, "stream_id": stream_id, "text": full_text, "length": len(full_text)},
    )

    return self.planner.client._parse_json_content(full_text)
```

- [ ] **Step 2: Replace `planner.next_action` call with `_stream_planning` + validation**

At lines 958-968 of `backend/app/services/agent/loop.py`, replace:

```python
# Replace the entire try block around planner.next_action (lines 958-968):
plan = await self.planner.next_action(
    planner_goal,
    step_index,
    previous_observation,
    session_history=session_history,
    mode=mode,
    web_enabled=web_enabled,
    final_step=step_index == effective_max_steps - 1,
)
```

With:

```python
planner_messages = self.planner._build_messages(
    goal=planner_goal,
    step_index=step_index,
    previous_observation=previous_observation,
    session_history=session_history,
    mode=mode,
    web_enabled=web_enabled,
    final_step=step_index == effective_max_steps - 1,
)
raw_plan = await self._stream_planning(repo, ctx, planner_messages, step_index)
normalized_plan = self.planner._normalize_plan(raw_plan)
plan = self.planner._validate_plan(normalized_plan).model_dump(mode="json")
```

- [ ] **Step 3: Run backend integration tests**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -v --timeout=120 2>&1 | tail -20
```

Expected: All existing loop tests still pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent/loop.py
git commit -m "feat: stream planner output as plan_delta events"
```

---

### Task 3: Streamline planner prompt

**Files:**
- Modify: `backend/app/services/agent/planner.py:133-150, 158-181`

**Interfaces:**
- Consumes: `_build_messages` (same signature)
- Produces: Shorter `messages` list (same structure, fewer tokens)

- [ ] **Step 1: Trim system prompt (lines 133-150)**

Replace the `system_prompt` block:

```python
system_prompt = (
    "你是一个研究型 Agent 规划器。你必须只返回合法 JSON，且顶层只能包含 thought_summary 和 action 两个字段。\n"
    f"{action_policy}"
    f"{mode_policy}"
    f"{final_step_policy}"
    "所有 thought_summary 使用简体中文。不要输出 markdown 代码块或额外说明。"
)
```

- [ ] **Step 2: Trim user prompt — 3 examples instead of 11 (lines 158-181)**

Replace the `user_prompt` block:

```python
user_prompt = (
    f"当前目标：{goal}\n"
    f"执行模式：{mode}\n"
    f"网络权限：{'开启' if web_enabled else '关闭'}\n"
    f"当前步数：{step_index}\n"
    f"是否最后一步：{'是，必须选择 finish' if final_step else '否'}\n"
    f"上一轮观察结果：{observation_text}\n"
    f"会话历史：\n{history_block}\n"
    "你现在必须决定下一步唯一动作。"
    "若可直接回答，立即选择 finish。"
    "需要访问页面时，选择官方文档/网站/仓库，不选搜索页或工具类 API。"
    "示例：\n"
    '{"thought_summary":"分析需求后可直接回答","action":{"type":"finish","input":{}}}\n'
    '{"thought_summary":"需要搜索相关资料","action":{"type":"web_search","input":{"query":"关键词","max_results":5}}}\n'
    '{"thought_summary":"需读取文件内容","action":{"type":"read_file","input":{"path":"文档路径"}}}\n'
)
```

- [ ] **Step 3: Run planner validation test**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestLoopHelpers::test_finish_plan_accepts_empty_input -v --timeout=30
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent/planner.py
git commit -m "perf: trim planner prompt from 3000 to 800 chars"
```

---

### Task 4: Frontend — handle plan_delta events in runStreamReducer

**Files:**
- Modify: `frontend/src/lib/run-stream-reducer.ts`

**Interfaces:**
- Consumes: `plan_started`, `plan_delta`, `plan_completed` events from SSE
- Produces: `visibleThoughtByStep[0]` populated with plan text

- [ ] **Step 1: Add plan event types to `StreamEventType` union**

Add after line 16 (`| "visible_thought_paused"`):

```typescript
  | "plan_started"
  | "plan_delta"
  | "plan_completed"
```

- [ ] **Step 2: Add plan event cases to switch — before `default:` case**

Insert before `default:` (line 414) in the switch statement:

```typescript
    case "plan_started": {
      const streamId = readText(event.payload, "stream_id");
      const stepIndex = readStepIndex(event.payload);
      if (stepIndex === null) {
        return {
          ...state,
          lastSeq: event.seq,
          events: appendEvent(state.events, event),
          narrativeEvents: maybeNarrativeAppend(state, event),
        };
      }
      return applyVisibleThoughtSnapshot(state, event, streamId, {
        stepIndex,
        text: "",
      });
    }
    case "plan_completed": {
      const stepIndex = readStepIndex(event.payload);
      if (stepIndex === null) {
        return {
          ...state,
          lastSeq: event.seq,
          events: appendEvent(state.events, event),
          narrativeEvents: maybeNarrativeAppend(state, event),
        };
      }
      return applyVisibleThoughtSnapshot(state, event, readText(event.payload, "stream_id"), {
        stepIndex,
        text: readText(event.payload, "text") ?? state.visibleThoughtByStep[stepIndex] ?? "",
      });
    }
    case "plan_delta": {
      const stepIndex = readStepIndex(event.payload);
      const offset = readNumber(event.payload, "offset") ?? 0;
      const delta = readText(event.payload, "delta") ?? "";
      const streamId = readText(event.payload, "stream_id");
      if (stepIndex === null) {
        return { ...state, connection: "reconnecting" };
      }
      const currentText = state.visibleThoughtByStep[stepIndex] ?? "";
      const currentStreamId = state.visibleThoughtStreamIds[stepIndex] ?? null;
      const streamIdMismatch =
        currentStreamId !== null && streamId !== null && currentStreamId !== streamId;
      if (streamIdMismatch || offset !== currentText.length) {
        return { ...state, connection: "reconnecting" };
      }
      return applyVisibleThoughtSnapshot(state, event, streamId ?? currentStreamId, {
        stepIndex,
        text: currentText + delta,
      });
    }
```

- [ ] **Step 3: Verify build + reducer tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx next build
cd C:\01_agent_loop_pro\frontend && npx vitest run src/lib/run-stream-reducer.test.ts -v
```

Expected: Build passes; all reducer tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/run-stream-reducer.ts
git commit -m "feat: handle plan_started, plan_delta, plan_completed in reducer"
```

---

### Task 5: Backend tests — streaming planner emits plan_delta events

**Files:**
- Modify: `backend/tests/test_agent_loop.py`

- [ ] **Step 1: Write test for `_stream_planning`**

Add new test class using `AsyncMock` to capture emitted events:

```python
class TestStreamingPlanner:
    async def test_stream_planning_emits_events_and_parses_json(
        self, monkeypatch
    ):
        import json
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        plan_chunks = [
            '{"thought_summary"',
            ':"直接回答"',
            ',"action":{"type":"finish","input":{}}}',
        ]

        class FakeStreamClient:
            async def stream_text(self, messages):
                for c in plan_chunks:
                    yield c

        monkeypatch.setattr(service.planner.client, "stream_text", FakeStreamClient().stream_text)

        # Mock _persist_and_notify to capture events instead of writing to DB
        captured_events = []
        async def capture_notify(repo, ctx, event_type, payload):
            captured_events.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture_notify)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000001"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000002"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        messages = [{"role": "user", "content": "test"}]
        result = await service._stream_planning(mock_repo, ctx, messages, 0)

        assert result == json.loads("".join(plan_chunks))
        event_types = [e[0] for e in captured_events]
        assert event_types[0] == "plan_started"
        assert event_types[1] == "plan_delta"
        assert event_types[2] == "plan_delta"
        assert event_types[3] == "plan_delta"
        assert event_types[4] == "plan_completed"
```

- [ ] **Step 2: Run test**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestStreamingPlanner -v --timeout=60
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_agent_loop.py
git commit -m "test: streaming planner emits plan_delta events"
```

---

### Task 6: Frontend tests for plan events in reducer

**Files:**
- Modify: `frontend/src/lib/run-stream-reducer.test.ts`

- [ ] **Step 1: Write plan event reducer tests**

Add to the test file:

```typescript
describe("plan events", () => {
  test("plan_delta appends text to visibleThoughtByStep[0]", () => {
    const state = createInitialState();
    const afterStarted = reduceRunStream(state, makeStreamEvent("plan_started", {
      step_index: 0, stream_id: "plan-1",
    }));
    expect(afterStarted.visibleThoughtByStep[0]).toBe("");

    const afterDelta = reduceRunStream(afterStarted, makeStreamEvent("plan_delta", {
      step_index: 0, stream_id: "plan-1", offset: 0, delta: "分析",
    }));
    expect(afterDelta.visibleThoughtByStep[0]).toBe("分析");

    const afterMore = reduceRunStream(afterDelta, makeStreamEvent("plan_delta", {
      step_index: 0, stream_id: "plan-1", offset: 2, delta: "需求",
    }));
    expect(afterMore.visibleThoughtByStep[0]).toBe("分析需求");
  });

  test("plan_completed sets final text", () => {
    const state = createInitialState();
    const afterStarted = reduceRunStream(state, makeStreamEvent("plan_started", {
      step_index: 0, stream_id: "plan-2",
    }));
    const afterCompleted = reduceRunStream(afterStarted, makeStreamEvent("plan_completed", {
      step_index: 0, stream_id: "plan-2", text: "完整规划", length: 4,
    }));
    expect(afterCompleted.visibleThoughtByStep[0]).toBe("完整规划");
  });
});
```

- [ ] **Step 2: Run reducer tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/lib/run-stream-reducer.test.ts -v
```

Expected: All existing + new tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/run-stream-reducer.test.ts
git commit -m "test: plan_started, plan_delta, plan_completed reducer coverage"
```
