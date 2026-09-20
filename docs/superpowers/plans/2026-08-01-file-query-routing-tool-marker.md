# File-Query Routing + Tool-Marker Detection Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** File-related queries route to the tool chain (`list_files`/`read_file`) instead of the direct-answer fast path; `【需要工具】` never leaks into the final answer.

**Architecture:** (1) `should_try_direct_answer` gains a `FILE_HINTS` check — goals containing path separators, file extensions, or file keywords skip the fast path. (2) `_try_direct_answer` buffers the first ~30 chars into a probe; if `【需要工具】` appears anywhere in the accumulated probe (marker may span chunks), it emits `answer_failed` and returns `None` BEFORE any answer delta is sent — no leak, clean fallback.

**Tech Stack:** Python

## Global Constraints

- Existing gate behavior preserved for non-file queries (conservative: false negatives OK, false positives NOT)
- Existing `TestFastPathGate` tests must pass
- No partial answer emitted before the probe decision (clean tool fallback)
- Full loop suite must pass

---

### Task 1: Gate — file-related queries route to tools

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `should_try_direct_answer(goal, has_attachments, mode)` (existing)
- Produces: same signature; returns `False` when goal contains file hints

- [ ] **Step 1: Write the failing tests**

Add to the `TestFastPathGate` class in `backend/tests/test_agent_loop.py`:

```python
    def test_gate_rejects_goal_with_file_path(self):
        from app.services.agent.loop import should_try_direct_answer
        goal = "读取 00_Agent规范模板/内容维护标准/自控力_短视频内容创作规范.md"
        assert should_try_direct_answer(goal, False, "quick") is False

    def test_gate_rejects_goal_with_file_keyword(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("帮我读取文件", False, "quick") is False
        assert should_try_direct_answer("分析这份文档", False, "quick") is False
        assert should_try_direct_answer("看看我的附件", False, "quick") is False

    def test_gate_still_allows_plain_questions(self):
        from app.services.agent.loop import should_try_direct_answer
        assert should_try_direct_answer("写一个韭菜炒鸡蛋教程", False, "quick") is True
        assert should_try_direct_answer("介绍一下你自己", False, "quick") is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestFastPathGate -v
```

Expected: The 3 new tests FAIL (`should_try_direct_answer` returns True for file goals).

- [ ] **Step 3: Implement the hint check**

In `backend/app/services/agent/loop.py`, near `should_try_direct_answer` (module level, ~line 44):

```python
FILE_HINTS = (
    "/", "\\", ".md", ".docx", ".pdf", ".txt", ".xlsx", ".pptx",
    "读取", "文件", "文档", "附件",
)


def should_try_direct_answer(goal: str, has_attachments: bool, mode: str) -> bool:
    if has_attachments:
        return False
    if mode != "quick":
        return False
    if len(goal) > 200:
        return False
    if any(hint in goal for hint in FILE_HINTS):
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestFastPathGate -v
```

Expected: All 7 tests PASS (4 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "fix: file-related queries bypass direct-answer fast path and use tools"
```

---

### Task 2: Probe-buffer tool-marker detection in `_try_direct_answer`

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: existing `_try_direct_answer(repo, ctx, goal, session_history, step_index)`
- Produces: marker detected across chunk boundaries → `answer_failed` + `None` before any delta; short answers (<30 chars) still flushed at end

- [ ] **Step 1: Write the failing tests**

Add to the `TestTryDirectAnswer` class:

```python
    async def test_direct_answer_detects_marker_split_across_chunks(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages):
                yield "【"
                yield "需要"
                yield "工具】这个问题需要读取文件"

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
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000030"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000031"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._try_direct_answer(mock_repo, ctx, "读取文件", None, 0)

        assert result is None
        assert len(completed) == 0
        assert emitted[-1][0] == "answer_failed"

    async def test_direct_answer_short_answer_without_marker(self, monkeypatch):
        from unittest.mock import MagicMock
        from app.services.agent.loop import AgentLoopService, _AttemptContext

        service = AgentLoopService()

        class FakeStream:
            async def stream_text(self, messages):
                yield "好的"
                yield "，这就回答"

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
        mock_run.__dict__ = {"id": "00000000-0000-0000-0000-000000000032"}
        mock_attempt = MagicMock()
        mock_attempt.__dict__ = {"id": "00000000-0000-0000-0000-000000000033"}
        ctx = _AttemptContext(run=mock_run, attempt=mock_attempt)
        mock_repo = MagicMock()

        result = await service._try_direct_answer(mock_repo, ctx, "介绍一下", None, 0)

        assert result == "好的，这就回答"
        assert emitted[-1][0] == "answer_completed"
        assert len(completed) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestTryDirectAnswer -v
```

Expected: New test 1 FAILS (marker split across chunks not detected — answer contains 工具【需要工具】); new test 2 FAILS or errors (short answer not flushed when probing).

- [ ] **Step 3: Implement probe buffering**

In `backend/app/services/agent/loop.py`, `_try_direct_answer`, replace the streaming section:

```python
        probe_buffer = ""
        probing = True
        try:
            async for chunk in self.llm_client.stream_text(messages):
                if not chunk:
                    continue
                if probing:
                    probe_buffer += chunk
                    if "【需要工具】" in probe_buffer:
                        await self._persist_and_notify(
                            repo, ctx, "answer_failed",
                            {"stream_id": stream_id, "error": "tool_needed", "offset": 0},
                        )
                        return None
                    if len(probe_buffer) >= 30:
                        probing = False
                        answer += probe_buffer
                        pending_chunks.append(probe_buffer)
                        await flush_deltas()
                    continue
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
            if probing and probe_buffer:
                answer += probe_buffer
                pending_chunks.append(probe_buffer)
            await flush_deltas(force=True)
        except Exception as exc:
            if probing and probe_buffer:
                answer += probe_buffer
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
```

Key behavior:
- First 30 chars buffered in `probe_buffer`; marker checked on the ACCUMULATED buffer (cross-chunk safe)
- Marker found → `answer_failed` + `None` — NO delta was emitted (buffer never flushed)
- No marker → probe flushed into the normal delta flow (probe_buffer ≥ 30 case) or after the loop (short answers)
- `first_chunk` variable removed (replaced by `probing`)

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py::TestTryDirectAnswer -v
```

Expected: All 4 tests PASS (2 existing + 2 new). If the existing "tool_need returns None" test still passes (it should — marker in first chunk is still caught by the probe).

- [ ] **Step 5: Run full loop suite**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_loop.py -v
```

Expected: All tests pass (existing + new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "fix: probe-buffer tool-marker detection — no leak across chunks, clean fallback"
```
