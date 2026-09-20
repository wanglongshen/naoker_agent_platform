# Fast-Path Direct Answer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For directly-answerable queries, skip the planner entirely and stream the answer immediately (1-3s first token instead of 8-15s).

**Architecture:** A heuristic gate (`should_try_direct_answer`) decides if Mode A is safe. `_try_direct_answer` streams the answer in ONE LLM call; if the model declares `【需要工具】` in the first chunk, the call is discarded and the existing planner flow (Mode B) takes over. A config flag `fast_path_enabled` is the kill switch.

**Tech Stack:** Python, FastAPI, httpx (DeepSeek streaming)

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-fast-path-design.md`
- `_stream_final_answer` and `_persist_successful_completion` must NOT be modified
- Existing 31 backend tests must pass
- `fast_path_enabled: bool = True` default; `False` restores old behavior entirely
- Gate must be conservative — false negatives OK, false positives NOT (LLM self-route is the safety net)

---

### Task 1: Config flag + heuristic gate

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Produces: `settings.fast_path_enabled: bool`; `should_try_direct_answer(goal: str, has_attachments: bool, mode: str) -> bool` module-level function in `loop.py`

- [ ] **Step 1: Add config flag**

In `backend/app/core/config.py`, add after `run_timeout_seconds` (line 23):

```python
    fast_path_enabled: bool = True
```

- [ ] **Step 2: Write the failing test**

Add a new test class to `backend/tests/test_agent_loop.py`:

```python
class TestFastPathGate:
    def test_gate_allows_short_quick_goal_without_attachments(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("写一个韭菜炒鸡蛋教程", False, "quick") is True

    def test_gate_rejects_attachments(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("分析这个文件", True, "quick") is False

    def test_gate_rejects_expert_mode(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("研究一下量子计算", False, "expert") is False

    def test_gate_rejects_long_goal(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("请" * 300, False, "quick") is False
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestFastPathGate -v
```

Expected: FAIL with `ImportError` / `AttributeError` (function not defined).

- [ ] **Step 4: Implement the gate**

In `backend/app/services/agent/loop.py`, add this module-level function near the top (after the `AgentIntegrityError` class, ~line 42):

```python
def should_try_direct_answer(goal: str, has_attachments: bool, mode: str) -> bool:
    if has_attachments:
        return False
    if mode != "quick":
        return False
    if len(goal) > 200:
        return False
    return True
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestFastPathGate -v
```

Expected: 4/4 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: add fast_path_enabled config and should_try_direct_answer gate"
```

---

### Task 2: Direct-answer message builder

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `goal: str`, `session_history: list[dict[str, str]] | None`
- Produces: `_build_direct_answer_messages(goal, session_history) -> list[dict[str, str]]` — system prompt with `【需要工具】` self-route instruction

- [ ] **Step 1: Write the failing test**

Add to `TestFastPathGate` class (or a new `TestDirectAnswerMessages` class) in `backend/tests/test_agent_loop.py`:

```python
class TestDirectAnswerMessages:
    def test_messages_include_tool_self_route_instruction(self):
        from app.services.agent.loop import AgentLoopService
        service = AgentLoopService()
        messages = service._build_direct_answer_messages("写个教程", None)
        system_content = messages[0]["content"]
        assert "【需要工具】" in system_content
        assert messages[1]["content"].startswith("用户目标：写个教程")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestDirectAnswerMessages -v
```

Expected: FAIL (`AttributeError: _build_direct_answer_messages` not found).

- [ ] **Step 3: Implement `_build_direct_answer_messages`**

In `backend/app/services/agent/loop.py`, add this method right after `_build_final_answer_messages` (the method ending around line 855):

```python
    def _build_direct_answer_messages(
        self,
        goal: str,
        session_history: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        history_block = self._format_session_history_short(session_history)
        return [
            {
                "role": "system",
                "content": (
                    "你是一个智能助手。直接输出最终答案，必须使用简体中文。"
                    "若此问题需要网络搜索、读取文件或其他工具才能准确回答，"
                    "第一句必须严格输出【需要工具】四个字，然后停止。"
                    "不需要工具时，直接输出 Markdown 正文，"
                    "不要用 markdown 代码块包裹你的回答。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户目标：{goal}\n\n"
                    f"会话历史：\n{history_block}"
                ),
            },
        ]
```

- [ ] **Step 4: Implement the `_format_session_history_short` helper**

Add this method to `AgentLoopService` (near `_build_session_history`):

```python
    def _format_session_history_short(self, session_history: list[dict[str, str]] | None) -> str:
        if not session_history:
            return "无"
        lines: list[str] = []
        for index, item in enumerate(session_history, start=1):
            user_text = item.get("user", "")[:200]
            assistant_text = item.get("assistant", "")[:200]
            lines.append(f"{index}. 用户：{user_text}")
            lines.append(f"   助手：{assistant_text}")
        return "\n".join(lines)
```

Check whether a similar helper already exists (e.g., on `ResearchPlanner._format_session_history`) — if `loop.py` already has an equivalent, reuse it instead of duplicating.

- [ ] **Step 5: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestDirectAnswerMessages -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: direct-answer message builder with tool self-route instruction"
```

---

### Task 3: `_try_direct_answer` streaming method

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `_persist_and_notify`, `self.llm_client.stream_text(messages)`, `_persist_successful_completion`, `_build_direct_answer_messages`
- Produces: `_try_direct_answer(repo, ctx, goal, session_history, step_index) -> str | None` — returns the answer string on success, `None` when the model declared `【需要工具】`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_agent_loop.py`:

```python
class TestTryDirectAnswer:
    async def test_direct_answer_success_streams_and_completes(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        chunks = ["韭菜炒鸡蛋教程", "步骤：", "1. 打蛋"]

        class FakeStream:
            async def stream_text(self, messages):
                for c in chunks:
                    yield c

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        completed = []
        async def capture_completion(**kwargs):
            completed.append(kwargs)
        monkeypatch.setattr(service, "_persist_successful_completion", capture_completion)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000001"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000002"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._try_direct_answer(mock_repo, ctx, "写教程", None, 0)

        assert result == "韭菜炒鸡蛋教程步骤：1. 打蛋"
        types = [e[0] for e in emitted]
        assert types[0] == "answer_started"
        assert "answer_delta" in types
        assert types[-1] == "answer_completed"
        assert len(completed) == 1

    async def test_direct_answer_detects_tool_need_and_returns_none(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages):
                yield "【需要工具】这个问题需要搜索最新数据"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        emitted = []
        async def capture(repo, ctx, event_type, payload):
            emitted.append((event_type, dict(payload)))
        monkeypatch.setattr(service, "_persist_and_notify", capture)

        completed = []
        async def capture_completion(**kwargs):
            completed.append(kwargs)
        monkeypatch.setattr(service, "_persist_successful_completion", capture_completion)

        mock_run = MagicMock()
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000002"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000003"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._try_direct_answer(mock_repo, ctx, "最新金价", None, 0)

        assert result is None
        assert len(completed) == 0
        assert emitted[-1][0] == "answer_failed"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestTryDirectAnswer -v
```

Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Implement `_try_direct_answer`**

Add to `AgentLoopService` in `backend/app/services/agent/loop.py` (after `_build_direct_answer_messages`):

```python
    async def _try_direct_answer(
        self,
        repo: AgentRepository,
        ctx: _AttemptContext,
        goal: str,
        session_history: list[dict[str, str]] | None,
        step_index: int,
    ) -> str | None:
        stream_id = f"answer-{ctx.run.id}"
        await self._persist_and_notify(
            repo, ctx, "answer_started", {"stream_id": stream_id},
        )

        messages = self._build_direct_answer_messages(goal, session_history)
        answer = ""
        first_chunk = True
        checkpointed_offset = 0
        last_checkpoint_time = time.monotonic()
        pending_chunks: list[str] = []
        last_flush_time = time.monotonic()

        async def flush_deltas(force: bool = False) -> None:
            nonlocal last_flush_time
            if not pending_chunks:
                return
            if not force and time.monotonic() - last_flush_time < 0.02:
                return
            batch = "".join(pending_chunks)
            delta_offset = len(answer) - len(batch)
            pending_chunks.clear()
            last_flush_time = time.monotonic()
            await self._persist_and_notify(
                repo, ctx, "answer_delta",
                {"stream_id": stream_id, "offset": delta_offset, "delta": batch},
            )

        try:
            async for chunk in self.llm_client.stream_text(messages):
                if not chunk:
                    continue
                if first_chunk:
                    first_chunk = False
                    if "【需要工具】" in chunk[:30]:
                        await self._persist_and_notify(
                            repo, ctx, "answer_failed",
                            {"stream_id": stream_id, "error": "tool_needed", "offset": 0},
                        )
                        return None
                answer += chunk
                pending_chunks.append(chunk)
                await flush_deltas()
                uncheckpointed = len(answer) - checkpointed_offset
                elapsed = time.monotonic() - last_checkpoint_time
                if uncheckpointed >= 256 or elapsed >= 0.4:
                    await flush_deltas(force=True)
                    await self._persist_and_notify(
                        repo, ctx, "answer_checkpoint",
                        {"stream_id": stream_id, "text": answer, "offset": len(answer)},
                    )
                    checkpointed_offset = len(answer)
                    last_checkpoint_time = time.monotonic()
            await flush_deltas(force=True)
        except Exception as exc:
            if len(answer) > checkpointed_offset:
                await self._persist_and_notify(
                    repo, ctx, "answer_checkpoint",
                    {"stream_id": stream_id, "text": answer, "offset": len(answer)},
                )
            await self._persist_and_notify(
                repo, ctx, "answer_failed",
                {"stream_id": stream_id, "error": str(exc), "offset": len(answer)},
            )
            raise

        await self._persist_and_notify(
            repo, ctx, "answer_completed",
            {"stream_id": stream_id, "text": answer, "length": len(answer)},
        )
        await self._persist_successful_completion(
            ctx=ctx,
            answer=answer,
            stream_id=stream_id,
            step_number=step_index,
            thought_summary="",
            action_type="finish",
            action_payload={},
            observation={"final_answer": answer},
            step_duration_seconds=0.0,
        )
        return answer
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestTryDirectAnswer -v
```

Expected: 2/2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: try_direct_answer streams answer with tool self-route fallback"
```

---

### Task 4: Wire the gate into the main loop

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `settings.fast_path_enabled` (Task 1), `should_try_direct_answer` (Task 1), `_try_direct_answer` (Task 3)
- Produces: Mode A attempted before planner when the gate passes; run completes without planner when successful

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_agent_loop.py`:

```python
class TestFastPathIntegration:
    async def test_fast_path_bypasses_planner_on_direct_answer(self, monkeypatch, test_db):
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
                username=f"fp_user_{uid}",
                display_name="FP User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="fp")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj, "写个教程", "quick", True, []
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("fp-worker")
            await s.commit()
            assert claimed is not None

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages):
                for c in ["直接回答内容"]:
                    yield c

        monkeypatch.setattr(service, "llm_client", FakeStream())
        monkeypatch.setattr(service.planner, "next_action", None)  # must never be called

        planner_called = {"called": False}
        async def boom(*_args, **_kwargs):
            planner_called["called"] = True
            raise AssertionError("planner must not be called in fast path")
        monkeypatch.setattr(service.planner, "next_action", boom)
        monkeypatch.setattr(service, "_stream_planning", boom)

        import app.services.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        await service.process_attempt(claim_id := attempt_id, "fp-worker")

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "succeeded"
            assert run.result.get("final_answer") == "直接回答内容"
        assert planner_called["called"] is False
```

Note: this integration test must match the EXISTING patterns in the file (see `TestShortTransactionEvents` at line ~493 for the established fixture/monkeypatch style, including how `async_session_factory` is replaced with `test_db`). Adjust the setup accordingly if the existing tests differ.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestFastPathIntegration -v
```

Expected: FAIL — planner path runs (or planner_called assertion fails) because the gate is not wired yet.

- [ ] **Step 3: Wire the gate into `_do_process_attempt`**

In `backend/app/services/agent/loop.py`, inside `_do_process_attempt`, insert after the attachment block (after line 1019, before the `try:` at line 1021):

```python
            if (
                settings.fast_path_enabled
                and should_try_direct_answer(
                    goal=run.goal,
                    has_attachments=bool(attachments),
                    mode=mode,
                )
            ):
                direct_answer = await self._try_direct_answer(
                    repo, ctx, run.goal, session_history, step_index,
                )
                if direct_answer is not None:
                    return
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestFastPathIntegration -v
```

Expected: PASS.

- [ ] **Step 5: Run the full loop test suite**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -v
```

Expected: 31 existing + new tests all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: wire fast-path gate into main loop, skip planner for direct answers"
```
