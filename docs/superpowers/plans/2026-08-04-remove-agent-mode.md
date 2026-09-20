# Remove quick/expert Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the quick/expert mode concept so all agent runs execute with the full `max_steps` budget (30), eliminate the 5-step cap that made complete plan-writing tasks fail, raise the LLM output cap so full 8-module plans fit in one call, guide the model to write skeleton-then-fill when the cap is still hit, and never mark a run succeeded when a save-intent goal never actually saved a file.

**Architecture:** Backend: `_run_policy` drops the mode branch (returns `(web_enabled, max_steps)`), planner prompt loses `mode_policy`, schemas drop `AgentMode`/`mode` from `AgentRunCreate` (response keeps `mode: str` for history), repository's `create_run_with_attempt` defaults `mode="expert"`, `should_try_direct_answer` loses its mode gate (fast-path stays enabled for all runs), both LLM payloads get `max_tokens: 8192`, the write_file rejection hint gains skeleton-then-fill guidance, and `_enforce_save_intent` no longer exempts the final step — an unfulfilled save intent raises `RetryablePlannerError` → retry → honest `run_failed` instead of a fake success. Frontend: delete `agent-mode-controls.tsx`, remove `mode` from submit payloads and mode labels from run headers/audit pages.

**Tech Stack:** Python 3.11 / FastAPI / pytest / TypeScript / Next.js / Vitest.

## Global Constraints

- 所有 run 一律走完整 `max_steps`（默认 30），无 5 步限制
- DB 列 `agent_runs.mode` 保留（历史数据兼容），新 run 固定写入 `"expert"`，**不做数据库迁移**
- API 不再接收 mode 字段（前端不再传）
- 快速直答（fast path）保留且对所有 run 启用——它独立于模式概念，删 mode 门控即可
- 现有测试必须全部通过（全量 732 passed 基线）
- 每个任务独立提交，commit 从仓库根 C:\01_agent_loop_pro 执行，路径用仓库根相对路径
- 测试 DB 共享：同一时刻只允许一个 pytest 进程（先 `Get-Process python -ErrorAction SilentlyContinue` 确认无占用）

---

### Task 1: 后端核心 — loop.py 移除模式分支

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_tools.py`

**Interfaces:**
- Consumes: 现有 `_run_policy`（loop.py:325-333）、`should_try_direct_answer`（loop.py:54-58）、`_build_messages`（loop.py:959 附近的内部方法，mode 参数在 959 行）
- Produces:
  - `_run_policy(self, run, max_steps) -> tuple[bool, int]`（新签名：返回 `(web_enabled, effective_max_steps)`，不再返回 mode）
  - `should_try_direct_answer(goal: str, has_attachments: bool) -> bool`（删 mode 参数）
  - `_build_messages(...)` 删 mode 参数

- [ ] **Step 1: Write the failing tests**（修改 `backend/tests/test_agent_tools.py` 的现有断言；先读 405-435 行和 585-615 行现状）

```python
# 替换 411-423 行的现有 _run_policy 断言（原: assert service._run_policy(run, 12) == ("quick", True, 5)）为:
def test_run_policy_returns_full_steps_for_all_modes():
    from app.models.agent import AgentRun

    run1 = AgentRun(mode="quick", network_enabled=True)
    run2 = AgentRun(mode="expert", network_enabled=True)
    run3 = AgentRun(mode="quick", network_enabled=False)
    run4 = AgentRun(mode="expert", network_enabled=False)
    assert AgentLoopService()._run_policy(run1, 12) == (True, 12)
    assert AgentLoopService()._run_policy(run2, 20) == (True, 20)
    assert AgentLoopService()._run_policy(run3, 2) == (False, 2)
    assert AgentLoopService()._run_policy(run4, 12) == (False, 12)
```

注意：先把这段**追加**为独立测试函数（不删旧的），运行确认新测试 RED（`_run_policy` 返回 3 元组 vs 断言 2 元组 → FAIL），再在 Step 3 实现后删旧断言。

同时修改 591-612 行附近的调用（原 `mode, web_enabled, effective_steps = service._run_policy(run, 8)`）为：

```python
    web_enabled, effective_steps = service._run_policy(run, 8)
```

删除原 610-612 行对 `mode == "expert"` 的断言（模式概念已删）。

再修改 54-58 行对应的 `should_try_direct_answer` 调用测试（搜索 `should_try_direct_answer(` 全部调用点，删 `mode` 实参）。

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tools.py -q
```
Expected: 新增 `test_run_policy_returns_full_steps_for_all_modes` FAIL（返回值元组长度不符）

- [ ] **Step 3: Implement**

**3a.** `_run_policy`（loop.py:325-333）整体替换为：

```python
    def _run_policy(self, run: AgentRun, max_steps: int) -> tuple[bool, int]:
        web_enabled = run.network_enabled
        if not isinstance(web_enabled, bool):
            web_enabled = False
        return web_enabled, max_steps
```

**3b.** `should_try_direct_answer`（loop.py:54-58）替换为：

```python
def should_try_direct_answer(goal: str, has_attachments: bool) -> bool:
    if has_attachments:
        return False
    if len(goal) > 200:
        return False
```

（删 `mode: str` 参数与 `if mode != "quick": return False` 行）

**3c.** `_run_policy` 调用处（loop.py:1334 附近）：

```python
        web_enabled, effective_max_steps = self._run_policy(run, max_steps)
```

（删 `mode,` 前缀）

**3d.** `should_try_direct_answer` 调用处（loop.py:1374 附近）：删 `mode=mode,` 实参。

**3e.** 内部 `_build_messages`（loop.py:959-968 附近）：签名删 `mode: str` 参数；调用 planner 处删 `mode=mode,`。**注意：loop.py 里 `_build_messages` 的 mode 参数是从 `_do_process_attempt` 或调用方传入的——沿调用链向上删除所有 mode 传参**（Step 3f 处理主调用方）。

**3f.** 主循环 `_do_process_attempt` 内所有 `mode=mode,` 传参（1390、1402 行附近的两个 `self.planner._build_messages(...)` 调用）删除，并删除 `mode` 变量的来源（1334 行解包后已无 mode 变量——若仍有 `mode` 变量引用会 NameError，grep `mode` 于 loop.py 确认全部清除；1414 行 `model_dump(mode="json")` 是 Pydantic 序列化参数**不要动**）。

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tools.py -q
```
Expected: PASS（新测试绿 + 旧断言更新后通过）

- [ ] **Step 5: 删除旧断言** — 移除 Step 1 中临时保留的旧 `_run_policy` 三元组断言（411-423 行旧版），保留新测试。

- [ ] **Step 6: Run full agent regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tools.py tests/test_agent_loop.py tests/test_agent_worker.py -q
```
Expected: PASS

- [ ] **Step 7: Commit**（从仓库根）

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_tools.py
git commit -m "feat: remove quick/expert mode — all runs get full max_steps"
```

---

### Task 2: 后端外围 — planner / schemas / repository / api

**Files:**
- Modify: `backend/app/services/agent/planner.py`
- Modify: `backend/app/schemas/agent.py`
- Modify: `backend/app/repositories/agent_repository.py`
- Modify: `backend/app/api/agent.py`
- Test: `backend/tests/test_agent_repository.py`

**Interfaces:**
- Consumes: Task 1 的 `_build_messages` 新签名（无 mode 参数）
- Produces: `Planner._build_messages(goal, step_index, previous_observation, session_history=None, web_enabled=True, final_step=False)`（无 mode）；`AgentRunCreate` 无 mode 字段；`create_run_with_attempt(session, goal, network_enabled, attachment_ids, mode="expert")`

- [ ] **Step 1: Write the failing tests**（修改 `backend/tests/test_agent_repository.py:107` 附近——先读该测试确认创建方式）

```python
# 原: assert run.mode == "expert"  （若原测试传了 mode="expert" 则改为不传、断言默认值）
# 新: assert run.mode == "expert"  # 默认值断言
```

若原测试调用 `create_run_with_attempt(..., mode="expert")` → 删除 mode 实参；若断言 `run.mode == "quick"` → 改为 `"expert"`。先读文件确认。

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_repository.py::TestStateTransitions -q
```
Expected: 该测试 FAIL（签名不匹配或默认值断言不符）——若断言本身不失败，跳到 Step 3 直接实现后验证。

- [ ] **Step 3: Implement**

**3a.** `backend/app/schemas/agent.py`：
- 删第 11 行 `AgentMode = Literal["quick", "expert"]`
- `AgentRunCreate`（47-51 行）删 `mode: AgentMode = "quick"` 行
- `AgentRunResponse.mode: str`（59 行）保留

**3b.** `backend/app/repositories/agent_repository.py` `create_run_with_attempt`（160-167 行）：

```python
    async def create_run_with_attempt(
        self,
        session: AgentSession,
        goal: str,
        network_enabled: bool,
        attachment_ids: list[uuid.UUID],
        mode: str = "expert",
    ) -> tuple[AgentRun, AgentRunAttempt, AgentRunEvent]:
```

（mode 移到末尾带默认值 `"expert"`；内部使用不变）

**3c.** `backend/app/api/agent.py` create_run（262-268 行）：

```python
    run, _, _ = await repo.create_run_with_attempt(
        session_obj,
        data.goal,
        data.network_enabled,
        validated_ids,
    )
```

（删 `data.mode,` 实参）

**3d.** `backend/app/services/agent/planner.py`：
- `_build_messages` 签名（154 行）删 `mode: Literal["quick", "expert"] = "quick",`
- 删 185-189 行 `mode_policy` 变量
- 198 行 `f"{mode_policy}"` 从 system_prompt 删除
- 211 行 `f"执行模式：{mode}\n"` 从 user_prompt 删除
- grep 该文件确认无残留 mode 引用（`model_dump(mode="json")` 等 Pydantic 序列化不动）

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_repository.py tests/test_agent_tools.py -q
```
Expected: PASS

- [ ] **Step 5: Grep 全后端确认无残留**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import glob,re; [print(f, len(re.findall(r'\bmode\b', open(f,encoding='utf-8').read()))) for f in ['app/services/agent/planner.py','app/schemas/agent.py','app/api/agent.py','app/repositories/agent_repository.py']]"
```
Expected: 每文件只剩 `model_dump(mode="json")` 序列化用法（planner.py 若有其他 mode 出现需人工核对）

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/services/agent/planner.py backend/app/schemas/agent.py backend/app/repositories/agent_repository.py backend/app/api/agent.py backend/tests/test_agent_repository.py
git commit -m "feat: drop mode from planner prompt, schemas, and run creation"
```

---

### Task 3: 前端 — 删模式 UI 与负载

**Files:**
- Delete: `frontend/src/components/agent/agent-mode-controls.tsx`
- Modify: `frontend/src/types/agent.ts`
- Modify: `frontend/src/components/agent/chat-composer.tsx`
- Modify: `frontend/src/components/agent/new-conversation-composer.tsx`
- Modify: `frontend/src/app/(agent)/agent/page.tsx`
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`
- Modify: `frontend/src/components/agent/run-header.tsx`
- Modify: `frontend/src/app/(agent)/agent/audit/runs/[runId]/page.tsx`
- Modify: `frontend/src/components/governance/governance-transcript.tsx`
- Test: `frontend/src/components/agent/chat-composer.test.tsx`、`frontend/src/lib/agent-api.test.ts`

**Interfaces:**
- Consumes: 现有组件结构（不依赖 Task 1/2 的代码，纯前端独立）
- Produces: `ChatComposerProps.onSubmit: (input: { goal: string; attachmentIds: string[] }) => ...`（无 mode）；`AgentRun.mode: string`（保留字段，类型放宽）

- [ ] **Step 1: Write the failing tests**（修改 `frontend/src/components/agent/chat-composer.test.tsx` 126-141 行附近——先读该测试确认结构）

将 `submits fixed quick mode without exposing a mode control` 测试改为：

```tsx
  it("submits goal without a mode field", async () => {
    render(<ChatComposer {...baseProps} />);
    const textarea = screen.getByPlaceholderText(/给 Agent Loop 发送消息/);
    fireEvent.change(textarea, { target: { value: "写一份方案" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    await waitFor(() => {
      expect(baseProps.onSubmit).toHaveBeenCalledWith({
        goal: "写一份方案",
        attachmentIds: [],
      });
    });
  });
```

同时删 `mode: "quick"` 断言（若存在）；删 120-125 行 `describe("ChatComposer fixed mode")` 的旧标题（改为普通 describe 或并入上层）。

`frontend/src/lib/agent-api.test.ts` 89-131 行：从 `createRun` 请求体断言中移除 `mode: "quick"` 字段。

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/components/agent/chat-composer.test.tsx src/lib/agent-api.test.ts
```
Expected: FAIL（TypeError: onSubmit 收到多余 mode 字段 / 请求体含 mode）

- [ ] **Step 3: Implement**

**3a.** 删除文件 `frontend/src/components/agent/agent-mode-controls.tsx`。

**3b.** `frontend/src/types/agent.ts`：
- 删第 13 行 `export type AgentMode = "quick" | "expert";`
- 第 32 行 `mode: AgentMode;` → `mode: string;`

**3c.** `frontend/src/components/agent/chat-composer.tsx`：
- 删第 9 行 `import type { AgentMode } from "@/types/agent";`
- 第 45 行 onSubmit 类型 `{ goal: string; mode: AgentMode; attachmentIds: string[] }` → `{ goal: string; attachmentIds: string[] }`
- 96 行 `mode: "quick",` 行删除

**3d.** `frontend/src/components/agent/new-conversation-composer.tsx`：
- 20 行 `onSubmit={async ({ goal, mode, attachmentIds }) => {` → 删 `mode`
- 23 行 `formData.set("mode", mode);` 删除

**3e.** `frontend/src/app/(agent)/agent/page.tsx`：
- 14 行签名 `{ goal: string; mode: "quick" | "expert"; attachmentIds: string[] }` → 删 mode
- 19 行 `mode: input.mode,` 删除

**3f.** `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`：
- 84 行签名删 mode；90 行 `mode: input.mode,` 删除；105 行 `mode: "quick",` 删除（先读上下文确认是 createRun 请求体）

**3g.** `frontend/src/components/agent/run-header.tsx`：删 30-31 行"快速模式"标签 span（先读确认结构，保留 `§` 符号或其他装饰）

**3h.** `frontend/src/app/(agent)/agent/audit/runs/[runId]/page.tsx`：删 174 行 `Descriptions.Item label="模式"` 整项

**3i.** `frontend/src/components/governance/governance-transcript.tsx`：删 `modeLabel` 函数（26-27 行）与两处使用（80、131 行，`{modeLabel(turn.run.mode)}` → 删整 span/标签）

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run src/components/agent/chat-composer.test.tsx src/lib/agent-api.test.ts
```
Expected: PASS

- [ ] **Step 5: 类型检查 + 全量前端测试**

```
cd C:\01_agent_loop_pro\frontend
npx tsc --noEmit
npx vitest run
```
Expected: tsc 无错误；全部前端测试通过（注意：mock run 对象中的 `mode: "quick"` 字段因 `AgentRun.mode: string` 类型放宽仍兼容，无需改）

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add frontend/src/components/agent/agent-mode-controls.tsx frontend/src/types/agent.ts frontend/src/components/agent/chat-composer.tsx frontend/src/components/agent/new-conversation-composer.tsx "frontend/src/app/(agent)/agent/page.tsx" "frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx" frontend/src/components/agent/run-header.tsx "frontend/src/app/(agent)/agent/audit/runs/[runId]/page.tsx" frontend/src/components/governance/governance-transcript.tsx frontend/src/components/agent/chat-composer.test.tsx frontend/src/lib/agent-api.test.ts
git commit -m "feat: remove agent mode selector UI and mode payloads"
```

---

### Task 4: 集成验证

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: 后端全量**（仅一个 pytest 进程；先 `Get-Process python -ErrorAction SilentlyContinue`）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/ -q
```
Expected: 732+ passed（零失败；若出现已知 flaky 的 seed/notify 测试单独重跑确认）

- [ ] **Step 2: 前端全量**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run
```
Expected: 全绿（mock 数据含 `mode: "quick"` 的因类型放宽不受影响）

- [ ] **Step 3: 冒烟 — 创建 run 不再传 mode**（直连 API 验证；后端需已重启加载新代码）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import asyncio; exec('''\nimport sys\nsys.path.insert(0, r\"C:\\01_agent_loop_pro\\backend\")\nfrom sqlalchemy import text\n\nasync def main():\n    from app.db.session import async_session_factory\n    async with async_session_factory() as s:\n        rows = (await s.execute(text(\"SELECT mode, status FROM agent_runs ORDER BY created_at DESC LIMIT 3\"))).fetchall()\n        for r in rows:\n            print(r)\n\nasyncio.run(main())\n''')"
```
Expected: 最近 3 条 run 显示 mode 列仍存在（历史值不变，新 run 应为 "expert"）

- [ ] **Step 4: Report** — 无提交；把验证结果追加到 `C:\01_agent_loop_pro\.superpowers\sdd\remove-mode-progress.md`，回报用户：后端测试数 + 前端测试数 + 冒烟结果

---

### Task 5: LLM 输出上限 4096 → 8192

**Files:**
- Modify: `backend/app/services/agent/llm.py`
- Test: `backend/tests/test_llm.py`（若不存在则新建，先 glob 确认）

**Interfaces:**
- Consumes: 现有 `stream_text`（llm.py:158 附近 payload）与 `create_plan`（llm.py:52 附近 payload）
- Produces: 两处 payload 均含 `"max_tokens": 8192`

- [ ] **Step 1: Write the failing test**

新建 `backend/tests/test_llm.py`（若文件已存在则追加）：

```python
import pytest


class TestMaxTokens:
    def test_stream_text_payload_includes_max_tokens(self, monkeypatch):
        from app.services.agent.llm import DeepSeekClient

        captured = {}

        class FakeStream:
            def __init__(self):
                self.status_code = 200

            def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def __aiter__(self):
                return iter([])

        async def fake_stream(method, url, headers=None, json=None, **kw):
            captured["json"] = json
            return FakeStream()

        client = DeepSeekClient()
        monkeypatch.setattr(client._client, "stream", fake_stream)
        monkeypatch.setattr(client, "_collect_stream", lambda *a, **k: asyncgen_noop())

        async def run():
            async for _ in client.stream_text([{"role": "user", "content": "hi"}]):
                pass
            assert captured["json"]["max_tokens"] == 8192
            await client.create_plan([{"role": "user", "content": "hi"}])

        import anyio
        anyio.run(run)


async def asyncgen_noop():
    if False:
        yield None
```

注意：先读 `backend/app/services/agent/llm.py` 的 `DeepSeekClient` 构造与 `_collect_stream`/`create_plan` 实际签名，按真实结构调整 fake（`create_plan` 是非流式 POST，直接 `monkeypatch.setattr(client._client, "post", fake_post)` 捕获 json 断言 max_tokens）。**不要猜——先读代码再写测试。**

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_llm.py -q
```
Expected: FAIL（payload 无 max_tokens 或断言 KeyError）

- [ ] **Step 3: Implement**

`backend/app/services/agent/llm.py` 两处 payload 各加一行：

```python
        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "max_tokens": 8192,
        }
```

```python
        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
            "max_tokens": 8192,
        }
```

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_llm.py -q
```
Expected: PASS

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add backend/app/services/agent/llm.py backend/tests/test_llm.py
git commit -m "feat: raise LLM output cap to 8192 tokens for full-plan generation"
```

---

### Task 6: write_file 被拒 hint 增加分段写引导

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py:513`
- Test: `backend/tests/test_agent_tool_files.py`（TestWriteFileStructureValidation 类内）

**Interfaces:**
- Consumes: 现有 `_write_file` 拒绝返回（509-514 行）
- Produces: 拒绝 response 的 `hint` 字段含分段写引导文案

- [ ] **Step 1: Write the failing test**（追加到 `backend/tests/test_agent_tool_files.py` 的 TestWriteFileStructureValidation 类）

```python
    async def test_rejection_hint_guides_incremental_write(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        async def fake_structure(goal):
            return DEFAULT_MODULES

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/缺模块方案.md",
                       "content": "## 一、Brief Recap\n\n只有一章"}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "edit_file" in result["hint"]
        assert "骨架" in result["hint"]
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation -q
```
Expected: 新测试 FAIL（hint 无 edit_file/骨架 字样）

- [ ] **Step 3: Implement**

`backend/app/services/agent/tool_executor.py:513` 的 hint 改为：

```python
                    "hint": (
                        "请保留你已写的内容，仅按 skeleton 中的模块结构补全缺失模块后重新 write_file，不要重写全文。"
                        "若一次输出放不下全部模块内容：先写入包含全部章节标题与要点的骨架文件（通过校验），"
                        "再用 edit_file 逐章填充详细内容。"
                    ),
```

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation -q
```
Expected: PASS（含既有 8 个测试 + 新 1 个）

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: guide model to write skeleton then fill via edit_file when output cap hit"
```

---

### Task 7: 保存真实性防线 — 未保存成功不许 succeeded

**Files:**
- Modify: `backend/app/services/agent/loop.py:1481-1495`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: `_has_save_intent`（loop.py:397-403）、`wrote_file` 变量（loop.py:1337 初始化、1503 置 True）、`_schedule_retryable_failure`（loop.py:426）、`RetryablePlannerError`
- Produces: finish 分支在「goal 有保存意图 && wrote_file=False」时抛 `RetryablePlannerError("save_intent_unfulfilled")` → 调度重试 → 3 次耗尽才 run_failed

- [ ] **Step 1: Write the failing test**（追加到 `backend/tests/test_agent_loop.py`——先读该文件现有测试风格与 fixture，确认如何构造一个"goal 含保存意图但从未成功 write_file 的 run"）

```python
    async def test_finish_without_save_fails_when_goal_requires_save(self):
        # 构造: goal="读取 brief_test.md 并写方案保存到 brief/"
        # attempt 运行中, wrote_file 从未置 True
        # 模型 plan=finish
        # 期望: 抛 RetryablePlannerError("save_intent_unfulfilled") 而非成功落库
        ...
```

**关键**：先读 `test_agent_loop.py` 中已有的测试（如 `_stream_final_answer` / finish 路径的测试），复用其 mock 模式（fake repo / fake planner / monkeypatch `_persist_successful_completion` 断言不被调用）。若构造复杂，改为直接单测 finish 分支的判断逻辑（提取为辅助函数）：

```python
    def test_save_intent_gate_blocks_finish_without_save(self):
        from app.services.agent.loop import AgentLoopService

        svc = AgentLoopService()
        with pytest.raises(RetryablePlannerError) as exc_info:
            svc._enforce_save_intent(
                goal="读取 brief 写方案保存到 brief/",
                plan={"action": {"type": "finish", "input": {}}},
                wrote_file=False,
                final_step=True,  # 原逻辑此处放行 → 现在必须拦截
            )
        assert "save_intent_unfulfilled" in str(exc_info.value)
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py -q
```
Expected: 新测试 FAIL（当前 `final_step=True` 时 `_enforce_save_intent` 直接返回 plan 不抛异常）

- [ ] **Step 3: Implement**

**3a.** `_enforce_save_intent`（loop.py:405-420）签名与逻辑修改：

```python
    def _enforce_save_intent(
        self,
        goal: str,
        plan: dict[str, Any],
        wrote_file: bool,
        final_step: bool,
    ) -> dict[str, Any]:
        action = plan.get("action") or {}
        if (
            not wrote_file
            and action.get("type") == "finish"
            and self._has_save_intent(goal)
        ):
            raise RetryablePlannerError(
                "save_intent_unfulfilled"
                if final_step
                else "save_intent_requires_write_tool"
            )
        return plan
```

（删 `not final_step` 条件——最后一步没保存成功同样拦截；错误码区分：非最后一步提示"需要先写文件"，最后一步提示"保存意图未完成"）

**3b.** 主循环 finish 分支（loop.py:1481-1495）：在 `_persist_successful_completion` 之前加防线调用：

```python
            if action["type"] == "finish":
                answer = observation_or_answer["final_answer"]
                self._enforce_save_intent(
                    goal=run.goal,
                    plan=plan,
                    wrote_file=wrote_file,
                    final_step=step_index == effective_max_steps - 1,
                )
                step_duration_seconds = (datetime.now(UTC) - step_start).total_seconds()
                await self._persist_successful_completion(...)
```

注意：抛出的 `RetryablePlannerError` 会被 1470 行的 except 捕获 → `_schedule_retryable_failure` → attempt 未达 3 次则调度重试（新 attempt 从头跑，模型有更多机会保存）→ 3 次全失败才 `run_failed`。**这实现了"宁可真失败，不假成功"。**

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py -q
```
Expected: PASS（含新测试；既有测试若因 final_step 语义变化失败则逐一核对——先跑看）

- [ ] **Step 5: Regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py tests/test_agent_tools.py tests/test_agent_worker.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "fix: never mark run succeeded when save intent unfulfilled"
```

---

### Task 8: 最终集成验证（含全部 8 个任务）

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: 后端全量**（仅一个 pytest 进程；先 `Get-Process python -ErrorAction SilentlyContinue`）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/ -q
```
Expected: 732+ passed（零失败；若出现已知 flaky 的 seed/notify 测试单独重跑确认）

- [ ] **Step 2: 前端全量**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run
```
Expected: 全绿（mock 数据含 `mode: "quick"` 的因类型放宽不受影响）

- [ ] **Step 3: 冒烟 — 创建 run 不再传 mode**（直连 API 验证；后端需已重启加载新代码）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import asyncio; exec('''\nimport sys\nsys.path.insert(0, r\"C:\\01_agent_loop_pro\\backend\")\nfrom sqlalchemy import text\n\nasync def main():\n    from app.db.session import async_session_factory\n    async with async_session_factory() as s:\n        rows = (await s.execute(text(\"SELECT mode, status FROM agent_runs ORDER BY created_at DESC LIMIT 3\"))).fetchall()\n        for r in rows:\n            print(r)\n\nasyncio.run(main())\n''')"
```
Expected: 最近 3 条 run 显示 mode 列仍存在（历史值不变，新 run 应为 "expert"）

- [ ] **Step 4: Report** — 无提交；把验证结果追加到 `C:\01_agent_loop_pro\.superpowers\sdd\remove-mode-progress.md`，回报用户：后端测试数 + 前端测试数 + 冒烟结果
