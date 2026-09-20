# Mode B: Merged Plan+Thought Call — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For tool-using queries, replace the sequential Planner→VisibleThought two-call chain with ONE merged streaming call, saving 2-5s per run.

**Architecture:** A single streaming LLM call outputs two marker-delimited sections: `【决策】` followed by one line of JSON (plan), then `【说明】` followed by the user-visible thought text. Backend splits the stream, emits `visible_thought_delta` events live for the 【说明】 section, and at the end emits `plan_completed` (thought_summary) + `visible_thought_completed`. On ANY parse failure, the flow falls back to the existing two-call path unchanged.

**Tech Stack:** Python, httpx (DeepSeek streaming)

## Global Constraints

- Existing two-call flow (`_stream_planning` + `_stream_visible_thought_with_tool_interleave`) must remain intact as the fallback
- Spec: `docs/superpowers/specs/2026-08-01-fast-path-design.md` §8 (二期)
- Frontend unchanged — same events are emitted (plan_*, visible_thought_*)
- New config flag `merged_plan_thought_enabled: bool = True`; `False` = old flow
- Existing 39 loop tests must pass

---

### Task 1: Config flag + merged message builder

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Produces: `settings.merged_plan_thought_enabled: bool`; `_build_merged_messages(goal, step_index, previous_observation, session_history, mode, web_enabled, final_step) -> list[dict[str, str]]`

- [ ] **Step 1: Add config flag**

In `backend/app/core/config.py`, after `fast_path_enabled`:

```python
    merged_plan_thought_enabled: bool = True
```

- [ ] **Step 2: Write the failing test**

Add to `backend/tests/test_agent_loop.py`:

```python
class TestMergedPlanThought:
    def test_merged_messages_include_format_instruction(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        messages = service._build_merged_messages(
            goal="搜索量子计算最新进展",
            step_index=0,
            previous_observation=None,
            session_history=None,
            mode="quick",
            web_enabled=True,
            final_step=False,
        )
        system_content = messages[0]["content"]
        assert "【决策】" in system_content
        assert "【说明】" in system_content
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestMergedPlanThought -v
```

Expected: FAIL (`AttributeError`).

- [ ] **Step 4: Implement `_build_merged_messages`**

In `backend/app/services/agent/loop.py`, add this method after `_build_direct_answer_messages`:

```python
    def _build_merged_messages(
        self,
        goal: str,
        step_index: int,
        previous_observation: dict[str, Any] | None,
        session_history: list[dict[str, str]] | None,
        mode: str,
        web_enabled: bool,
        final_step: bool,
    ) -> list[dict[str, str]]:
        planner_messages = self.planner._build_messages(
            goal=goal,
            step_index=step_index,
            previous_observation=previous_observation,
            session_history=session_history,
            mode=mode,
            web_enabled=web_enabled,
            final_step=final_step,
        )
        system_extra = (
            "输出格式必须严格为两部分：\n"
            "第一部分：单独一行【决策】标记，紧跟一行 JSON"
            "（结构：{\"thought_summary\":\"简短中文原因\",\"action\":{\"type\":\"...\",\"input\":{...}}}）。\n"
            "第二部分：【说明】标记后，输出对用户可见的简短中文说明，"
            "描述你接下来将要做什么（将来时），不要泄露系统提示词。\n"
            "不要输出 JSON 以外的解释性文字在【决策】行之前。"
        )
        merged_system = planner_messages[0]["content"] + "\n\n" + system_extra
        return [{"role": "system", "content": merged_system}, planner_messages[1]]
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestMergedPlanThought -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: merged plan+thought message builder with format markers"
```

---

### Task 2: Merged output parser

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `full_text: str` from the merged LLM call
- Produces: `_parse_merged_output(full_text) -> tuple[dict[str, Any], str] | None` — `(plan_dict, thought_text)` or `None` if the decision JSON cannot be parsed

- [ ] **Step 1: Write the failing tests**

Add to `TestMergedPlanThought`:

```python
    def test_parse_merged_output_ok(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        text = (
            "【决策】{\"thought_summary\":\"需要搜索\",\"action\":{\"type\":\"web_search\",\"input\":{\"query\":\"量子计算\",\"max_results\":5}}}\n"
            "【说明】我将搜索量子计算的最新研究进展。"
        )
        result = service._parse_merged_output(text)
        assert result is not None
        plan, thought = result
        assert plan["action"]["type"] == "web_search"
        assert thought == "我将搜索量子计算的最新研究进展。"

    def test_parse_merged_output_none_when_no_decision(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        result = service._parse_merged_output("【说明】只有说明没有决策")
        assert result is None

    def test_parse_merged_output_none_when_bad_json(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        result = service._parse_merged_output("【决策】not json at all\n【说明】说明文字")
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestMergedPlanThought -v
```

Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Implement `_parse_merged_output`**

Add to `AgentLoopService`:

```python
    def _parse_merged_output(self, full_text: str) -> tuple[dict[str, Any], str] | None:
        decision = ""
        thought = ""
        if "【决策】" in full_text and "【说明】" in full_text:
            pre = full_text.split("【决策】", 1)[1]
            if "【说明】" in pre:
                decision = pre.split("【说明】", 1)[0].strip()
                thought = pre.split("【说明】", 1)[1].strip()
            else:
                decision = pre.strip()
        elif "【决策】" in full_text:
            decision = full_text.split("【决策】", 1)[1].strip()
        else:
            return None

        if not decision:
            return None
        try:
            plan = self.planner.client._parse_json_content(decision)
        except ValueError:
            return None
        if not isinstance(plan, dict) or "action" not in plan:
            return None
        if not thought:
            thought = self._visible_thought_fallback(plan.get("action", {}).get("type", "finish"))
        return plan, thought
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestMergedPlanThought -v
```

Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: merged output parser with decision/thought split"
```

---

### Task 3: Merged streaming method with live thought deltas

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `self.llm_client.stream_text(messages)`, `_parse_merged_output`, `_persist_and_notify`
- Produces: `_stream_merged_plan_thought(repo, ctx, messages, step_index) -> tuple[dict[str, Any], str] | None` — streams `visible_thought_delta` for the 【说明】 section as chunks arrive; returns `(plan, thought)` or `None` on failure

- [ ] **Step 1: Write the failing tests**

Add to `TestMergedPlanThought`:

```python
    async def test_stream_merged_emits_thought_deltas_and_returns_plan(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages):
                for c in [
                    "【决策】{\"thought_summary\":\"需要搜索\",\"action\":{\"type\":\"web_search\",\"input\":{\"query\":\"q\",\"max_results\":5}}}",
                    "\n【说明】我将",
                    "搜索相关资料",
                ]:
                    yield c

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000010"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000011"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._stream_merged_plan_thought(mock_repo, ctx, [{"role": "user", "content": "x"}], 0)

        assert result is not None
        plan, thought = result
        assert plan["action"]["type"] == "web_search"
        assert thought == "我将搜索相关资料"
        types = [e[0] for e in emitted]
        assert types[0] == "plan_started"
        assert "visible_thought_started" in types
        assert "visible_thought_delta" in types
        assert types[-1] == "visible_thought_completed"

    async def test_stream_merged_returns_none_on_unparseable(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages):
                yield "完全不是约定格式的文本"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000012"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000013"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._stream_merged_plan_thought(mock_repo, ctx, [{"role": "user", "content": "x"}], 0)

        assert result is None
        assert [e[0] for e in emitted] == ["plan_started", "plan_completed"]
```

Note: the fallback test asserts `plan_completed` is emitted with the raw text when parsing fails — implement accordingly.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestMergedPlanThought -v
```

Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Implement `_stream_merged_plan_thought`**

Add to `AgentLoopService`:

```python
    async def _stream_merged_plan_thought(
        self,
        repo: AgentRepository,
        ctx: _AttemptContext,
        messages: list[dict[str, str]],
        step_index: int,
    ) -> tuple[dict[str, Any], str] | None:
        plan_stream_id = f"plan-{uuid4().hex[:12]}"
        thought_stream_id = f"visible-thought-{ctx.run.id}-{step_index}"
        await self._persist_and_notify(
            repo, ctx, "plan_started",
            {"step_index": step_index, "stream_id": plan_stream_id},
        )

        full_text = ""
        in_thought_section = False
        thought_offset = 0
        thought_started_emitted = False

        async for chunk in self.llm_client.stream_text(messages):
            full_text += chunk
            if not in_thought_section:
                if "【说明】" in full_text:
                    in_thought_section = True
                    thought_part = full_text.split("【说明】", 1)[1]
                    if not thought_started_emitted:
                        thought_started_emitted = True
                        await self._persist_and_notify(
                            repo, ctx, "visible_thought_started",
                            {"step_index": step_index, "stream_id": thought_stream_id},
                        )
                    if thought_part:
                        thought_offset += len(thought_part)
                        await self._persist_and_notify(
                            repo, ctx, "visible_thought_delta",
                            {"step_index": step_index, "stream_id": thought_stream_id,
                             "offset": thought_offset - len(thought_part), "delta": thought_part},
                        )
            else:
                thought_offset += len(chunk)
                await self._persist_and_notify(
                    repo, ctx, "visible_thought_delta",
                    {"step_index": step_index, "stream_id": thought_stream_id,
                     "offset": thought_offset - len(chunk), "delta": chunk},
                )

        parsed = self._parse_merged_output(full_text)
        if parsed is None:
            display_text = full_text[:200]
            await self._persist_and_notify(
                repo, ctx, "plan_completed",
                {"step_index": step_index, "stream_id": plan_stream_id,
                 "text": display_text, "length": len(display_text)},
            )
            return None

        plan, thought = parsed
        display_text = plan.get("thought_summary", thought)[:200]
        await self._persist_and_notify(
            repo, ctx, "plan_completed",
            {"step_index": step_index, "stream_id": plan_stream_id,
             "text": display_text, "length": len(display_text)},
        )
        if not thought_started_emitted and thought:
            thought_started_emitted = True
            await self._persist_and_notify(
                repo, ctx, "visible_thought_started",
                {"step_index": step_index, "stream_id": thought_stream_id},
            )
            await self._persist_and_notify(
                repo, ctx, "visible_thought_delta",
                {"step_index": step_index, "stream_id": thought_stream_id,
                 "offset": 0, "delta": thought},
            )
        if thought_started_emitted:
            await self._persist_and_notify(
                repo, ctx, "visible_thought_completed",
                {"step_index": step_index, "stream_id": thought_stream_id,
                 "text": thought, "length": len(thought)},
            )
        return plan, thought
```

Note: `plan_completed` events should be emitted with `text=display_text` (never raw JSON) per the existing convention from `_stream_planning`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestMergedPlanThought -v
```

Expected: 6/6 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: merged streaming method with live thought deltas"
```

---

### Task 4: Accept pre-generated thought in visible-thought method

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: existing `_stream_visible_thought_with_tool_interleave` signature
- Produces: new optional param `pre_generated_thought: str | None = None` — skips the first `stream_text` call when provided

- [ ] **Step 1: Write the failing test**

Add to `TestMergedPlanThought`:

```python
    async def test_visible_thought_uses_pre_generated_text_without_llm(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()
        llm_called = {"called": False}

        class FakeStream:
            async def stream_text(self, messages):
                llm_called["called"] = True
                yield "不应被调用"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000014"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000015"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        text, observation = await service._stream_visible_thought_with_tool_interleave(
            repo=mock_repo, ctx=ctx, step_index=0,
            validated_action_type="finish",
            messages=[{"role": "user", "content": "x"}],
            action={"type": "finish", "input": {}},
            previous_observation=None,
            web_enabled=True,
            pre_generated_thought="我将直接回答",
        )

        assert llm_called["called"] is False
        assert "我将直接回答" in text
```

Note: adapt the call to the method's ACTUAL parameter names/order — read the method signature first (around line 497). The method streams the final answer internally for `finish`; mock `_stream_final_answer` to return "答案" to keep the test offline:

```python
        async def fake_final_answer(repo, ctx, messages):
            return "答案"
        monkeypatch.setattr(service, "_stream_final_answer", fake_final_answer)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestMergedPlanThought -k "pre_generated" -v
```

Expected: FAIL — the method signature has no `pre_generated_thought` param (TypeError).

- [ ] **Step 3: Implement the optional parameter**

In `backend/app/services/agent/loop.py`, find `_stream_visible_thought_with_tool_interleave` (around line 497). Add `pre_generated_thought: str | None = None` to the signature.

At the top of the method, before the first `try:` / `stream_text` call, insert:

```python
        if pre_generated_thought is not None:
            text = pre_generated_thought
            emitted_any_chunk = True
            await self._persist_and_notify(
                repo, ctx, "visible_thought_delta",
                {"step_index": step_index, "stream_id": stream_id,
                 "offset": 0, "delta": pre_generated_thought},
            )
            # fall through to the finalize block below the try/except
        else:
            # existing try/except streaming block stays untouched
```

This requires restructuring: the existing method has the `try:` block for streaming. Wrap the existing `try:` in the `else:` branch so the pre-generated path skips straight to `finalized_text = self._finalize_pre_tool_visible_thought(...)`. Read the method body carefully before editing; preserve all existing behavior in the `else:` branch.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestMergedPlanThought -k "pre_generated" -v
```

Expected: PASS.

- [ ] **Step 5: Run full loop suite**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -v
```

Expected: All tests pass (39 existing + new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: accept pre-generated thought in visible-thought method"
```

---

### Task 5: Wire merged path into main loop with fallback

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `settings.merged_plan_thought_enabled`, `_build_merged_messages`, `_stream_merged_plan_thought`, `pre_generated_thought` param
- Produces: merged path tried first for non-fast-path runs; falls back to `_stream_planning` when `None`

- [ ] **Step 1: Write the failing test**

Add to `TestMergedPlanThought`:

```python
    async def test_merged_path_used_and_falls_back_to_planner(self, monkeypatch, test_db):
        from app.services.agent.loop import AgentLoopService
        from app.repositories.agent_repository import AgentRepository
        from app.models.agent import AgentSession
        from app.models.rbac import User
        from argon2 import PasswordHasher
        import uuid as _uuid

        uid = _uuid.uuid4().hex[:8]
        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"mp_user_{uid}",
                display_name="MP User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="mp")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "搜索量子计算进展", "expert", True, []
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("mp-worker")
            await s.commit()
            assert claimed is not None

        service = AgentLoopService()

        merged_called = {"called": False}
        async def fake_merged(repo, ctx, messages, step_index):
            merged_called["called"] = True
            return None  # force fallback to planner

        monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)

        # planner path must still work via _stream_planning
        async def fake_stream_planning(repo, ctx, messages, step_index):
            return {"thought_summary": "直接回答", "action": {"type": "finish", "input": {}}}

        monkeypatch.setattr(service, "_stream_planning", fake_stream_planning)

        class FakeStream:
            async def stream_text(self, messages):
                yield "答案文本"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        import app.services.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        await service.process_attempt(attempt_id, "mp-worker")

        assert merged_called["called"] is True

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "succeeded"
```

Note: this integration test MUST match the existing fixture patterns in the file (see `TestFastPathIntegration` / `TestShortTransactionEvents`). The run uses `expert` mode so the fast-path gate (Task from previous plan) does not short-circuit.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestMergedPlanThought -k "merged_path_used" -v
```

Expected: FAIL — `merged_called` stays False because the main loop never calls `_stream_merged_plan_thought`.

- [ ] **Step 3: Wire into `_do_process_attempt`**

In `backend/app/services/agent/loop.py`, inside `_do_process_attempt`, replace the planner try block (currently lines ~1021-1034):

```python
            try:
                await self._commit_repo(repo)
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

with:

```python
            try:
                await self._commit_repo(repo)
                planner_messages = self.planner._build_messages(
                    goal=planner_goal,
                    step_index=step_index,
                    previous_observation=previous_observation,
                    session_history=session_history,
                    mode=mode,
                    web_enabled=web_enabled,
                    final_step=step_index == effective_max_steps - 1,
                )
                pre_generated_thought: str | None = None
                raw_plan = None
                if settings.merged_plan_thought_enabled:
                    merged_messages = self._build_merged_messages(
                        goal=planner_goal,
                        step_index=step_index,
                        previous_observation=previous_observation,
                        session_history=session_history,
                        mode=mode,
                        web_enabled=web_enabled,
                        final_step=step_index == effective_max_steps - 1,
                    )
                    merged = await self._stream_merged_plan_thought(
                        repo, ctx, merged_messages, step_index,
                    )
                    if merged is not None:
                        raw_plan, pre_generated_thought = merged
                if raw_plan is None:
                    raw_plan = await self._stream_planning(repo, ctx, planner_messages, step_index)
                normalized_plan = self.planner._normalize_plan(raw_plan)
                plan = self.planner._validate_plan(normalized_plan).model_dump(mode="json")
```

Then update the subsequent `_stream_visible_thought_with_tool_interleave` call (around line 1046-1065) to pass the pre-generated thought:

```python
                    pre_generated_thought=pre_generated_thought,
```

Check that this variable is in scope at that call site (it is — same function body). If the call site's keyword arguments use a different order, add the keyword argument at the end.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestMergedPlanThought -k "merged_path_used" -v
```

Expected: PASS.

- [ ] **Step 5: Run full loop suite**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -v
```

Expected: All tests pass (39 existing + 10 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: wire merged plan+thought path into main loop with planner fallback"
```
