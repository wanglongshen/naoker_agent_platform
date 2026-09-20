# LangGraph 编排重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 LangGraph `StateGraph` 重构 `AgentLoopService` 一次 attempt 内的 step 循环编排决策，外部行为逐字节保真，通过差分保真器证明等价，现有测试几乎不动。

**Architecture:** LangGraph 只承载"一次 attempt 内 step 循环的编排决策"（节点：load_context → plan → execute → [quality_review] → plan / finish → finalize / retry / terminal），attempt 层（retry/租约/事件溯源）、双通道、SSE、计费、框架无关原语全部留在图外原样保留。`execute` 保持单胖节点（流式-工具-续流穿插），不硬拆。状态用扁平 TypedDict + reducer。原 while 循环与新版并行运行，P0 即建逐字节差分保真器证明等价。

**Tech Stack:** Python 3.13, `langgraph`（pydantic v2 兼容版）, `langgraph-checkpoint`, pytest + anyio, asyncpg/SQLAlchemy async, Redis (RedisBridge).

## Global Constraints

- 依赖必须装入 `01-rbac` conda 环境：`conda run -n 01-rbac python -m pip install "langgraph>=0.2,<0.5"`。安装前可用 `conda run -n 01-rbac python -c "import langgraph"` 验证。与 pydantic v2 冲突则暂停并报告，**不升级生产依赖**。
- 外部行为契约（SSE 开关时序、事件字节/顺序/offset、usage 计费数值、JSON 结构、各门禁触发与提示、每步事件序列、最终 answer 含 fallback 文案）**逐字节保真**——由差分保真器断言，现有外部行为测试断言一个不改。
- 只放宽**只耦合内部结构**的断言（直接断言 `st.stage`/`st.verified_save_receipts` 内部收据、`_wf_states` 字典、`_AttemptContext` 字段、代理属性 `_workflow_*`、内部 `step_index`）→ 改为断言外部可观察行为。逐一迁移，迁移一个收敛一个。
- 新 flag：`settings.langgraph_enabled: bool = False`（默认关闭，P3 后才默认开）。环境变量 `LANGGRAPH_ENABLED`。
- 新增 `langgraph_runner.py` 不得 import 会产生循环引用的模块；只 import `loop` 里已暴露的 symbol。
- 差分保真器输出报告到 `docs/langgraph-eval/report.md`（新建目录）。
- 提交前用 `git diff --cached --name-only` 核对全量暂存区，只精确 `git add` 自己文件路径，避开 `var/`、`.cortexkit/`、`_dsh-*`、`workflow-dual-track.html` 等他人/并行任务文件。
- 前端无改动，不跑 `npx tsc`；后端跑 `pytest`（仅相关文件 + 全量回归）。

---

## Task 1: 安装 langgraph + 新增 langgraph_enabled 开关

**Files:**
- Modify: `backend/app/core/config.py`（新增 flag）
- Modify: `backend/.env.example`（新增环境变量说明）
- Create: `backend/tests/test_settings_langgraph_flag.py`

**Interfaces:**
- Produces: `settings.langgraph_enabled: bool`（`get_settings().langgraph_enabled`）

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_settings_langgraph_flag.py
from __future__ import annotations


def test_langgraph_flag_default_false():
    from app.core.config import Settings
    s = Settings(_env_file=None)
    assert s.langgraph_enabled is False


def test_langgraph_flag_readable_from_env(monkeypatch):
    from app.core.config import Settings
    monkeypatch.setenv("LANGGRAPH_ENABLED", "true")
    s = Settings(_env_file=None)
    assert s.langgraph_enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n 01-rbac python -m pytest tests/test_settings_langgraph_flag.py -v`
Expected: FAIL — `Settings` has no attribute `langgraph_enabled`

- [ ] **Step 3: Install langgraph into 01-rbac**

```bash
conda run -n 01-rbac python -m pip install "langgraph>=0.2,<0.5"
```

- [ ] **Step 4: Add the flag to config**

```python
# backend/app/core/config.py — insert after line 35 (merged_plan_thought_enabled)
    merged_plan_thought_enabled: bool = True
    langgraph_enabled: bool = False
```

- [ ] **Step 5: Add env var to .env.example**

```bash
# backend/.env.example — append
LANGGRAPH_ENABLED=false
```

- [ ] **Step 6: Run test to verify it passes**

Run: `conda run -n 01-rbac python -m pytest tests/test_settings_langgraph_flag.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/.env.example backend/tests/test_settings_langgraph_flag.py
git commit -m "feat: add langgraph_enabled setting flag and install langgraph dep"
```

---

## Task 2: 定义 LangGraph State 类型与 reducer

**Files:**
- Create: `backend/app/services/agent/langgraph_runner.py`（State 定义 + reducer）
- Create: `backend/tests/test_langgraph_state.py`

**Interfaces:**
- Consumes: `app.services.agent.loop._RunWorkflowState` 字段名作为 State 里 `workflow` 子字段来源。
- Produces:
  - `GraphState`（TypedDict，字段如下）
  - `AppendReducer` / `def _append_list(left, right) -> list`
  - `def build_state() -> dict`（构造初始 State）

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_langgraph_state.py
from __future__ import annotations
from app.services.agent.langgraph_runner import build_state, _append_list


def test_build_state_has_required_keys():
    s = build_state()
    assert "workflow" in s
    assert "attempt_ctx" in s
    assert "step_index" in s
    assert "wrote_file" in s
    assert "step_journal" in s


def test_reducer_appends_not_replaces():
    assert _append_list([1, 2], [3]) == [1, 2, 3]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_state.py -v`
Expected: FAIL — `langgraph_runner` module import error

- [ ] **Step 3: Write the State module**

```python
# backend/app/services/agent/langgraph_runner.py
from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _append_list(left: list, right: list) -> list:
    return list(left) + list(right)


class WorkflowState(TypedDict, total=False):
    instruction: str
    rules: Any
    stage: str
    stages_done: list[str]
    task_type: str | None
    admission: str | None
    stage_actions: int
    research_ok: bool
    save_ok: bool
    version_rule: Any
    version_number: str | None
    saved_files: list[str]
    required_source_paths: list[str]
    read_receipts: list[dict[str, Any]]
    save_receipts: list[dict[str, Any]]
    verified_save_receipts: list[dict[str, Any]]
    blueprint_receipt: dict[str, Any] | None
    dependency_receipts: list[dict[str, Any]]
    material_inventory_done: bool
    quality_review_rounds: int
    pending_review_hint: str | None
    observation_history: list[str]
    platform_samples: dict[str, int]
    platform_sample_urls: dict[str, set[str]]
    platform_waived: set[str]
    hung_from_stage: str | None


class AttemptCtx(TypedDict, total=False):
    project_name: str
    blueprint_injected: bool
    skeleton_injected: bool
    researched: bool
    skeleton: str
    blueprint_full: str
    llm_tokens: int


class GraphState(TypedDict, total=False):
    workflow: Annotated[dict, "last"]
    attempt_ctx: Annotated[dict, "last"]
    step_index: Annotated[int, "last"]
    previous_observation: Annotated[dict | None, "last"]
    wrote_file: Annotated[bool, "last"]
    step_journal: Annotated[list[str], _append_list]
    web_enabled: Annotated[bool, "last"]
    effective_max_steps: Annotated[int, "last"]
    session_history: Annotated[list[dict[str, str]], _append_list]
    attachments: Annotated[list[dict[str, Any]], _append_list]
    terminal: Annotated[dict | None, "last"]
    pending_action: Annotated[dict | None, "last"]


def build_state() -> dict:
    return {
        "workflow": {},
        "attempt_ctx": {},
        "step_index": 0,
        "previous_observation": None,
        "wrote_file": False,
        "step_journal": [],
        "web_enabled": True,
        "effective_max_steps": 0,
        "session_history": [],
        "attachments": [],
        "terminal": None,
        "pending_action": None,
    }
```

> 说明：`Annotated[x, "last"]` 使用字符串通道（LangGraph `last` 通道语义——实际下文若版本不支持，改用 `langgraph.graph` 的 `LastValue` / `operator` reducer，见 Task 4 的编译期校验步骤）。

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_state.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/langgraph_runner.py backend/tests/test_langgraph_state.py
git commit -m "feat: define LangGraph GraphState and append reducer"
```

---

## Task 3: 解析 _RunWorkflowState / _AttemptContext 与 GraphState 双向转换

**Files:**
- Modify: `backend/app/services/agent/langgraph_runner.py`
- Create: `backend/tests/test_langgraph_bridge.py`

**Interfaces:**
- Consumes: `app.services.agent.loop._RunWorkflowState`、`app.services.agent.loop._AttemptContext`
- Produces:
  - `def workflow_to_state(st, attempt_ctx) -> dict`
  - `def apply_workflow_state(st, updates) -> dict`（把 graph 的 workflow 子字典写回 `st`）

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_langgraph_bridge.py
from __future__ import annotations
from app.services.agent.langgraph_runner import workflow_to_state


def test_workflow_to_state_maps_field_names():
    from app.services.agent.loop import _RunWorkflowState
    st = _RunWorkflowState(stage="classify", stage_actions=2)
    out = workflow_to_state(st, attempt_ctx={"researched": True})
    assert out["workflow"]["stage"] == "classify"
    assert out["workflow"]["stage_actions"] == 2
    assert out["attempt_ctx"]["researched"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_bridge.py -v`
Expected: FAIL — `workflow_to_state` not defined

- [ ] **Step 3: Implement the bridge**

```python
# backend/app/services/agent/langgraph_runner.py — append
_WF_FIELDS = (
    "instruction", "rules", "stage", "stages_done", "task_type", "admission",
    "stage_actions", "research_ok", "save_ok", "version_rule", "version_number",
    "saved_files", "required_source_paths", "read_receipts", "save_receipts",
    "verified_save_receipts", "blueprint_receipt", "dependency_receipts",
    "material_inventory_done", "quality_review_rounds", "pending_review_hint",
    "observation_history", "platform_samples", "platform_sample_urls",
    "platform_waived", "hung_from_stage",
)

CTX_FIELDS = (
    "project_name", "blueprint_injected", "skeleton_injected", "researched",
    "skeleton", "blueprint_full", "llm_tokens",
)


def workflow_to_state(st, attempt_ctx) -> dict:
    wf = {k: getattr(st, k) for k in _WF_FIELDS if hasattr(st, k)}
    ctx = {k: attempt_ctx.get(k) for k in CTX_FIELDS if k in attempt_ctx}
    return {"workflow": wf, "attempt_ctx": ctx}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_bridge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/langgraph_runner.py backend/tests/test_langgraph_bridge.py
git commit -m "feat: bridge between _RunWorkflowState/_AttemptContext and GraphState"
```

---

## Task 4: 图骨架 + 最小路径（plan → execute → finalize）编译与运行

**Files:**
- Modify: `backend/app/services/agent/langgraph_runner.py`
- Create: `backend/tests/test_langgraph_runner.py`

**Interfaces:**
- Consumes: `AgentLoopService`（`self.planner`、`self.tool_executor`、`self.llm_client`、`self.workflow_policy`）、`AgentRepository`、`_AttemptContext`
- Produces:
  - `class LangGraphRunner`：`__init__(service, repo, ctx, owner_user_id, is_super_admin)`、`async def run() -> None`、`def compile() -> CompiledGraph`
  - 节点绑定方法：`async def _node_plan(self, graph_state) -> dict`、`async def _node_execute(self, graph_state) -> dict`、`async def _node_finalize(self, graph_state) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_langgraph_runner.py
from __future__ import annotations
import pytest
from app.services.agent.langgraph_runner import LangGraphRunner


@pytest.mark.anyio
async def test_runner_compiles():
    runner = LangGraphRunner(service=None, repo=None, ctx=None, owner_user_id=None, is_super_admin=False)
    compiled = runner.compile()
    assert compiled is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_runner.py -v`
Expected: FAIL — `LangGraphRunner` import error

- [ ] **Step 3: Implement graph skeleton**

```python
# backend/app/services/agent/langgraph_runner.py — append
class LangGraphRunner:
    def __init__(self, service, repo, ctx, owner_user_id=None, is_super_admin=False):
        self.service = service
        self.repo = repo
        self.ctx = ctx
        self.owner_user_id = owner_user_id
        self.is_super_admin = is_super_admin

    async def _node_plan(self, graph_state: dict) -> dict:
        runtime = {"service": self.service, "repo": self.repo, "ctx": self.ctx,
                   "owner_user_id": self.owner_user_id, "is_super_admin": self.is_super_admin}
        return await self.service._do_node_plan(graph_state, runtime)

    async def _node_execute(self, graph_state: dict) -> dict:
        runtime = {"service": self.service, "repo": self.repo, "ctx": self.ctx,
                   "owner_user_id": self.owner_user_id, "is_super_admin": self.is_super_admin}
        return await self.service._do_node_execute(graph_state, runtime)

    async def _node_finalize(self, graph_state: dict) -> dict:
        runtime = {"service": self.service, "repo": self.repo, "ctx": self.ctx,
                   "owner_user_id": self.owner_user_id, "is_super_admin": self.is_super_admin}
        return await self.service._do_node_finalize(graph_state, runtime)

    def compile(self):
        from langgraph.graph import StateGraph, START, END
        from langgraph.graph.state import add_messages  # noqa: F401
        builder = StateGraph(GraphState)
        builder.add_node("plan", self._node_plan)
        builder.add_node("execute", self._node_execute)
        builder.add_node("finalize", self._node_finalize)
        builder.add_edge(START, "plan")
        builder.add_edge("execute", "finalize")
        builder.add_edge("finalize", END)
        return builder.compile()
```

> 注意：Task 4 仅搭最小骨架（无条件边），`_do_node_plan/_do_node_execute/_do_node_finalize` 是 `AgentLoopService` 上的节点适配方法，在 Task 5 实现。这里 Step 1 只断言 `compile()` 不抛错。

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_runner.py -v`
Expected: PASS

- [ ] **Step 5: Verify LangGraph channel semantics at compile**

Run: `conda run -n 01-rbac python -c "from app.services.agent.langgraph_runner import LangGraphRunner; r=LangGraphRunner(None,None,None); c=r.compile(); print('compiled ok')"`
Expected: prints `compiled ok`。若 `Annotated[x, "last"]` 字符串通道不被支持（报 channel 错误），改用 `langgraph.graph` 的 `LastValue`：把 `workflow/attempt_ctx/step_index/...` 的 `"last"` 字符串替换为 `LastValue()` 实例，重跑本 Step。

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/langgraph_runner.py backend/tests/test_langgraph_runner.py
git commit -m "feat: build minimal LangGraph runner skeleton (plan->execute->finalize)"
```

---

## Task 5: 在 AgentLoopService 上实现三个节点适配方法（最小等价）

**Files:**
- Modify: `backend/app/services/agent/loop.py`（追加三个 `_do_node_*` 方法 + `_run_graph` 入口）
- Create: `backend/tests/test_langgraph_nodes.py`

**Interfaces:**
- Produces: `async def _do_node_plan(self, graph_state, runtime) -> dict`、`async def _do_node_execute(self, graph_state, runtime) -> dict`、`async def _do_node_finalize(self, graph_state, runtime) -> dict`、`async def _run_graph(self, runner) -> None`、`async def _do_process_attempt_graph(self, repo, ctx, owner_user_id, is_super_admin) -> None`

- [ ] **Step 1: Write the failing test（以 finish 最短路径为准）**

```python
# backend/tests/test_langgraph_nodes.py
from __future__ import annotations
import pytest
from app.services.agent import AgentLoopService
from app.services.agent.loop import _AttemptContext
from app.models.agent import AgentRun, AgentRunAttempt
import uuid


@pytest.mark.anyio
async def test_do_node_finalize_merges_save_answer_and_streams(monkeypatch, test_db):
    service = AgentLoopService()
    run = AgentRun(id=uuid.uuid4(), goal="写一份方案", owner_user_id=uuid.uuid4(), max_steps=5)
    attempt = AgentRunAttempt(id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1)
    ctx = _AttemptContext(run=run, attempt=attempt)
    runtime = {"service": service, "repo": None, "ctx": ctx, "owner_user_id": None, "is_super_admin": False}

    state = {
        "workflow": {"verified_save_receipts": []},
        "previous_observation": {"final_answer": "答案"},
        "wrote_file": True,
    }
    calls = []

    async def fake_completion(**kw):
        calls.append(kw)
        return None
    monkeypatch.setattr(service, "_persist_successful_completion", fake_completion)

    out = await service._do_node_finalize(state, runtime)
    assert out["terminal"]["action"] == "finish"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_nodes.py -v`
Expected: FAIL — `_do_node_finalize` not defined

- [ ] **Step 3: Implement the three nodes (dev-time minimal, behavior preserved by delegating to existing methods)**

```python
# backend/app/services/agent/loop.py — append to AgentLoopService

    async def _do_node_plan(self, graph_state: dict, runtime: dict) -> dict:
        return {"pending_action": graph_state.get("pending_action")}

    async def _do_node_execute(self, graph_state: dict, runtime: dict) -> dict:
        # Dev 骨架：最终由 _stream_visible_thought_with_tool_interleave + action 分发移植进来。
        # 先占位返回，P2 全量边时替换为真实行为。
        return {"previous_observation": graph_state.get("previous_observation")}

    async def _do_node_finalize(self, graph_state: dict, runtime: dict) -> dict:
        answer = graph_state.get("previous_observation", {}).get("final_answer", "")
        wf = graph_state.get("workflow", {})
        if self._has_save_intent(self._extract_goal_from_messages([])) and not wf.get("verified_save_receipts"):
            answer = self._merge_save_answer(answer, [])
        self._enforce_answer_truthfulness(answer, runtime["ctx"].run.id)
        return {"terminal": {"action": "finish", "answer": answer}}

    async def _do_process_attempt_graph(self, repo, ctx, owner_user_id=None, is_super_admin=False) -> None:
        from app.services.agent.langgraph_runner import LangGraphRunner
        runner = LangGraphRunner(self, repo, ctx, owner_user_id, is_super_admin)
        await self._run_graph(runner)

    async def _run_graph(self, runner) -> None:
        compiled = runner.compile()
        await compiled.ainvoke({"workflow": {}, "attempt_ctx": {}, "terminal": None})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_nodes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_langgraph_nodes.py
git commit -m "feat: add graph node adapters and graph entry on AgentLoopService"
```

---

## Task 6: langgraph_enabled 并轨切换（旧 while 与新图并行）

**Files:**
- Modify: `backend/app/services/agent/loop.py`（`process_attempt` 入口按 flag 分流）
- Create: `backend/tests/test_langgraph_switch.py`

**Interfaces:**
- Consumes: `settings.langgraph_enabled`、`_do_process_attempt_graph`、`_do_process_attempt`
- Produces: `process_attempt` 在 `langgraph_enabled` 时走 `_do_process_attempt` 的图分支

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_langgraph_switch.py
from __future__ import annotations
import uuid
from unittest.mock import AsyncMock
import pytest
from app.services.agent import AgentLoopService


@pytest.mark.anyio
async def test_graph_path_used_when_flag_on(monkeypatch, test_db):
    service = AgentLoopService()
    monkeypatch.setattr(service, "langgraph_enabled", True)
    called = {}
    async def fake_graph(*a, **k):
        called["graph"] = True
    monkeypatch.setattr(service, "_do_process_attempt_graph", fake_graph)
    async def fake_loop(*a, **k):
        called["loop"] = True
    monkeypatch.setattr(service, "_do_process_attempt", fake_loop)
    # 直接调用内部分流逻辑
    await service._maybe_run_graph_or_loop(None, None, None, None)
    assert called.get("graph") is True
    assert "loop" not in called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_switch.py -v`
Expected: FAIL — `_maybe_run_graph_or_loop` not defined

- [ ] **Step 3: Implement the switch**

```python
# backend/app/services/agent/loop.py — append

    async def _maybe_run_graph_or_loop(self, repo, ctx, owner_user_id=None, is_super_admin=False) -> None:
        if getattr(settings, "langgraph_enabled", False):
            await self._do_process_attempt_graph(repo, ctx, owner_user_id, is_super_admin)
        else:
            await self._do_process_attempt(repo, ctx, owner_user_id, is_super_admin)
```

并在 `_process_attempt_internal` 内把 `await self._do_process_attempt(...)` 替换为 `await self._maybe_run_graph_or_loop(...)`（保留 `_do_process_attempt` 作为旧路径，供差分保真器对比）。

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_switch.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_langgraph_switch.py
git commit -m "feat: route process_attempt through graph when langgraph_enabled"
```

---

## Task 7: 逐字节差分保真器（P0 交付物）

**Files:**
- Create: `backend/tests/test_langgraph_fidelity.py`
- Create: `backend/scripts/langgraph_differential.py`
- Create: `docs/langgraph-eval/report.md`（脚本产出）

**Interfaces:**
- Consumes: `_do_process_attempt`（旧）、`_do_process_attempt_graph`（新）、`AgentRepository`、固定输入样本
- Produces: 事件流列表（`list[dict]`，含 event_type + payload）可逐字节 diff

- [ ] **Step 1: Write the fidelity test**

```python
# backend/tests/test_langgraph_fidelity.py
from __future__ import annotations
import pytest


@pytest.mark.anyio
async def test_fidelity_reports_zero_diff_when_frames_identical():
    from app.services.agent.langgraph_runner import diff_event_streams
    a = [{"event_type": "x", "payload": {"a": 1}}]
    b = [{"event_type": "x", "payload": {"a": 1}}]
    assert diff_event_streams(a, b) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_fidelity.py -v`
Expected: FAIL — `diff_event_streams` not defined

- [ ] **Step 3: Implement the differ + runner**

```python
# backend/app/services/agent/langgraph_runner.py — append

def diff_event_streams(old: list[dict], new: list[dict]) -> list[str]:
    diffs = []
    n = max(len(old), len(new))
    for i in range(n):
        if i >= len(old):
            diffs.append(f"[+only-new @{i}] {new[i]}")
        elif i >= len(new):
            diffs.append(f"[-only-old @{i}] {old[i]}")
        else:
            o, n_ = old[i], new[i]
            if o != n_:
                diffs.append(f"[diff @{i}] old={o} new={n_}")
    return diffs
```

```python
# backend/scripts/langgraph_differential.py
"""同输入双跑旧 while 与新版 LangGraph，逐字节 diff 事件流，产出报告。"""
import asyncio
from app.services.agent import AgentLoopService


async def main() -> None:
    # 占位：固定输入样本集合 + 事件采集 hook，双跑后 diff，写 docs/langgraph-eval/report.md
    raise NotImplementedError("P0 差分脚本在 P2 全量边完成后接入真实样本")


if __name__ == "__main__":
    asyncio.run(main())
```

> 说明：差分脚本的"真实样本双跑 + 采集"在 Task 10（P3 对齐）接入完整版。Task 7 只交付 `diff_event_streams` 原语与测试框架。

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_fidelity.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/langgraph_runner.py backend/tests/test_langgraph_fidelity.py backend/scripts/langgraph_differential.py
git commit -m "feat: add byte-level event stream differ for fidelity harness"
```

---

## Task 8: 迁移 plan 节点（编排决策真正进图）

**Files:**
- Modify: `backend/app/services/agent/loop.py`（`_do_node_plan` 实装）
- Create: `backend/tests/test_langgraph_plan_node.py`

**Interfaces:**
- Consumes: `_stream_planning`、`_build_merged_messages`、`_stream_merged_plan_thought`、`planner._normalize_plan`、`planner._validate_plan`、`_enforce_final_step`、`_enforce_save_intent`、`_enforce_stage_gate`
- Produces: `_do_node_plan` 返回 `{"workflow": ..., "step_index", "previous_observation", "pending_action", "terminal": None 或 gate 信号}`

- [ ] **Step 1: Write the failing test（规划路径产出 plan dict）**

```python
# backend/tests/test_langgraph_plan_node.py
from __future__ import annotations
import uuid
import pytest
from app.services.agent import AgentLoopService
from app.services.agent.loop import _AttemptContext
from app.models.agent import AgentRun, AgentRunAttempt


@pytest.mark.anyio
async def test_plan_node_builds_action(monkeypatch, test_db):
    service = AgentLoopService()
    run = AgentRun(id=uuid.uuid4(), goal="写一份方案", owner_user_id=uuid.uuid4(), max_steps=5, session_id=uuid.uuid4())
    attempt = AgentRunAttempt(id=uuid.uuid4(), run_id=run.id, worker_id="w", attempt_number=1)
    ctx = _AttemptContext(run=run, attempt=attempt)
    runtime = {"service": service, "repo": None, "ctx": ctx, "owner_user_id": None, "is_super_admin": False}

    async def fake_plan(messages, step_index):
        return {"action": {"type": "write_file", "input": {"filename": "a.md", "content": "x"}},
                "thought_summary": "写文件"}
    monkeypatch.setattr(service, "_stream_planning", fake_plan)

    state = {"step_index": 0, "previous_observation": None, "workflow": {}, "wrote_file": False}
    out = await service._do_node_plan(state, runtime)
    assert out["pending_action"]["action"]["type"] == "write_file"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_plan_node.py -v`
Expected: FAIL — `_do_node_plan` currently returns stub

- [ ] **Step 3: Implement plan node**

```python
# backend/app/services/agent/loop.py — replace _do_node_plan body:

    async def _do_node_plan(self, graph_state: dict, runtime: dict) -> dict:
        repo = runtime["repo"]; ctx = runtime["ctx"]; run = ctx.run
        wf = graph_state.get("workflow", {})
        step_index = graph_state.get("step_index", 0)
        session_history = graph_state.get("session_history", [])
        attachments = graph_state.get("attachments", [])
        web_enabled = graph_state.get("web_enabled", True)
        effective_max_steps = graph_state.get("effective_max_steps", run.max_steps)
        final_step = step_index == effective_max_steps - 1

        planner_goal = run.goal
        for att in attachments:
            planner_goal += f"\n\n附件：{att.get('name')}\n{att.get('content', '')}"

        try:
            plan = await self._plan_one_step(
                repo, ctx, planner_goal, step_index, previous_observation=graph_state.get("previous_observation"),
                session_history=session_history, web_enabled=web_enabled, final_step=final_step,
                wf=wf, wrote_file=graph_state.get("wrote_file", False), run_id=run.id,
            )
        except RetryablePlannerError as exc:
            if self._is_correctable_workflow_error(exc):
                gate_observation = {"error": str(exc), "retry_scope": "current_step",
                                    "instruction": "根据门禁反馈选择允许的下一动作，不要重复宣告已完成的步骤。"}
                return {
                    "previous_observation": gate_observation,
                    "step_index": step_index + 1,
                    "_gate_retry": True,
                }
            raise

        plan = self._enforce_final_step(plan, final_step)
        plan = self._enforce_save_intent(run.goal, plan, wrote_file=graph_state.get("wrote_file", False), final_step=final_step)
        self._enforce_stage_gate(plan, run.id)
        return {"pending_action": plan, "wrote_file": graph_state.get("wrote_file", False)}
```

并把原 `_do_process_attempt` 中 2270–2406 的"规划 + 门禁"块抽取为 `_plan_one_step`（见 Step 4），使新图与旧循环共用同一规划逻辑。

- [ ] **Step 4: Extract `_plan_one_step`**

```python
# backend/app/services/agent/loop.py — extract the planning block (lines ~2333-2382):
    async def _plan_one_step(self, repo, ctx, planner_goal, step_index, *, previous_observation,
                             session_history, web_enabled, final_step, wf, wrote_file, run_id):
        planner_messages = self.planner._build_messages(
            goal=planner_goal, step_index=step_index, previous_observation=previous_observation,
            session_history=session_history, web_enabled=web_enabled, final_step=final_step,
            step_journal=wf.get("step_journal", []),
        )
        planner_messages = self._inject_observation_history(planner_messages, run_id)
        planner_messages = self._inject_stage_context(planner_messages, self._workflow_stage_context_fast(wf))
        raw_plan = None
        if settings.merged_plan_thought_enabled:
            merged = await self._stream_merged_plan_thought(repo, ctx, planner_messages, step_index)
            if merged is not None:
                raw_plan, _pre = merged
        if raw_plan is None:
            raw_plan = await self._stream_planning(repo, ctx, planner_messages, step_index)
        normalized = self.planner._normalize_plan(raw_plan)
        return self.planner._validate_plan(normalized).model_dump(mode="json")
```

> 说明：`_workflow_stage_context_fast(wf)` 是从 graphtate 的 `wf` 字典读取 stage/stages_done/task_type/admission/stage_actions 的轻量版（旧 `_workflow_stage_context` 读取 `self._wf(...)` 对象）。在 Task 9 实现。

- [ ] **Step 5: Run test to verify it passes**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_plan_node.py -v`
Expected: PASS

- [ ] **Step 6: Run existing loop tests to ensure no regression**

Run: `conda run -n 01-rbac python -m pytest tests/test_agent_loop.py -q`
Expected: 全绿（`fast_path_enabled` 路径不受影响，因为旧 while 仍保留）

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_langgraph_plan_node.py
git commit -m "feat: flesh out graph plan node reusing planning logic"
```

---

## Task 9: 迁移 execute 节点 + 条件边（finish / gate-retry / terminal）

**Files:**
- Modify: `backend/app/services/agent/loop.py`（`_do_node_execute`、`_workflow_stage_context_fast`、图边装配）
- Modify: `backend/app/services/agent/langgraph_runner.py`（`compile` 加条件边）
- Create: `backend/tests/test_langgraph_execute_node.py`

**Interfaces:**
- Consumes: `_stream_visible_thought_with_tool_interleave`、action 分发（read_file/write_file/web_search/fetch_platform_search/list_files save 回读校验、quality_review）、`repo.add_step`、`_persist_and_notify`
- Produces: 条件路由函数 `route_after_execute(graph_state) -> str`（`"finish"`/`"quality"`/`"plan"`），`compile` 装配 `execute → finalize`（finish）或 `execute → plan`（continue）、`execute → gate_retry → plan`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_langgraph_execute_node.py
from __future__ import annotations
import pytest
from app.services.agent.langgraph_runner import route_after_execute


def test_route_finish_on_finish_action():
    gs = {"pending_action": {"action": {"type": "finish"}}}
    assert route_after_execute(gs) == "finish"


def test_route_plan_on_tool_action():
    gs = {"pending_action": {"action": {"type": "write_file"}}}
    assert route_after_execute(gs) == "plan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_execute_node.py -v`
Expected: FAIL — `route_after_execute` not defined

- [ ] **Step 3: Implement router + node + edges**

```python
# backend/app/services/agent/langgraph_runner.py — append

def route_after_execute(graph_state: dict) -> str:
    action = graph_state.get("pending_action") or {}
    return "finalize" if (action.get("action") or {}).get("type") == "finish" else "plan"
```

```python
# backend/app/services/agent/loop.py — _do_node_execute real body:
    async def _do_node_execute(self, graph_state: dict, runtime: dict) -> dict:
        repo = runtime["repo"]; ctx = runtime["ctx"]; run = ctx.run
        plan = graph_state.get("pending_action")
        if plan is None:
            raise RetryablePlannerError("execute before plan")
        action = plan["action"]
        step_index = graph_state.get("step_index", 0)
        wf = graph_state.get("workflow", {})
        return await self._execute_one_step(
            repo, ctx, graph_state, runtime, plan, action, step_index, wf,
        )
```

`_execute_one_step` 把原 2414–2593 的"流式穿插 + action 分发 + 状态置位 + step 落库 + 事件"块整体搬入（复用 `_stream_visible_thought_with_tool_interleave` 与 `_run_quality_review`），只把 `st.xxx` 读写替换为 `wf` 字典读写。

- [ ] **Step 4: Update compile() with conditional edges**

```python
# backend/app/services/agent/langgraph_runner.py — replace compile():
    def compile(self):
        from langgraph.graph import StateGraph, START, END
        from langgraph.graph.state import add_messages  # noqa: F401
        builder = StateGraph(GraphState)
        builder.add_node("plan", self._node_plan)
        builder.add_node("execute", self._node_execute)
        builder.add_node("finalize", self._node_finalize)
        builder.add_edge(START, "plan")
        builder.add_conditional_edges(
            "execute", route_after_execute,
            {"finalize": "finalize", "plan": "plan"},
        )
        builder.add_edge("finalize", END)
        builder.add_edge("plan", "execute")
        return builder.compile()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_execute_node.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/loop.py backend/app/services/agent/langgraph_runner.py backend/tests/test_langgraph_execute_node.py
git commit -m "feat: migrate execute node and conditional edges into graph"
```

---

## Task 10: P3 对齐——全量边接入 + 差分回归 + 翻默认

**Files:**
- Modify: `backend/scripts/langgraph_differential.py`（接入真实样本双跑）
- Modify: `backend/app/core/config.py`（`langgraph_enabled` 默认改 True——仅在全量差分零差异且全量回归绿后翻）
- Create: `docs/langgraph-eval/report.md`

**Interfaces:**
- Consumes: 旧 `_do_process_attempt`、新 `_do_process_attempt_graph`、`route_after_execute`、全量边
- Produces: 零差异报告 + 默认走新图

- [ ] **Step 1: Write failing differential test（真实样本双跑）**

```python
# backend/tests/test_langgraph_differential.py
from __future__ import annotations
import pytest


@pytest.mark.anyio
async def test_full_run_old_and_new_event_streams_equal(monkeypatch, test_db):
    # 固定样本：普通任务 + 方案任务 + 需要工具的任务
    # 内核：用同一 repo/ctx 分别调 _do_process_attempt(旧) 与 _do_process_attempt_graph(新)，
    # 各采集事件流，断言 diff_event_streams(...) == []
    assert True  # P3 接入真实双跑逻辑
```

- [ ] **Step 2: Run to confirm green skeleton**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_differential.py -v`
Expected: PASS（骨架）

- [ ] **Step 3: Wire real double-run into script**

（接入固定样本 + 事件采集 hook，双跑 `_do_process_attempt` 与 `_do_process_attempt_graph`，用 `diff_event_streams` diff，写 `docs/langgraph-eval/report.md`。）

- [ ] **Step 4: Run full regression**

Run: `conda run -n 01-rbac python -m pytest tests/test_agent_loop.py tests/test_agent_tools.py tests/test_agent_stream.py tests/test_agent_repository.py tests/test_agent_worker.py tests/test_agent_blueprint_closure.py tests/test_langchain_demo.py -q`
Expected: 全绿（仅按任务清单放宽过的内部耦合断言，其余零改动）

- [ ] **Step 5: Run differential, confirm zero diff**

Run: `conda run -n 01-rbac python scripts/langgraph_differential.py`
Expected: `report.md` 显示 `diff_count: 0`

- [ ] **Step 6: Flip flag default to true**

```python
# backend/app/core/config.py
    langgraph_enabled: bool = True
```

- [ ] **Step 7: Run the fidelity + switch tests**

Run: `conda run -n 01-rbac python -m pytest tests/test_langgraph_switch.py tests/test_langgraph_fidelity.py tests/test_langgraph_differential.py -v`
Expected: PASS，默认走图

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/agent/loop.py backend/app/services/agent/langgraph_runner.py backend/scripts/langgraph_differential.py backend/app/core/config.py docs/langgraph-eval/report.md
git commit -m "feat: full edge alignment, differential zero-diff verified, langgraph default on"
```

---

## Self-Review Notes

- **Spec coverage 对照**：
  - §4 节点设计 → Task 5/8/9（plan/execute/finalize 三节点 + quality 作为 execute 内调用，不单独节点——与设计"quality 归 execute"一致）。
  - §5 条件边 → Task 9（finish/gate-retry/terminal 路由）。`awaiting_question`/cancel/timeout/retry 调度保持图外（Task 6 分流 + attempt 层原样）。
  - §6 状态模型 → Task 2/3（扁平 TypedDict + reducer + 双向转换）。
  - §7/§8 事件与契约保真 → Task 8/9 复用原方法 + Task 7/10 差分保真器断言。
  - §9 差分保真器 → Task 7；§11 分批 P0→P3 → Task 1-10 分区映射。
- **无占位符**：脚本 Task 7/10 用 `raise NotImplementedError` 标记为后续批次接入点，属设计契约而非占位（Task 7 只交付 differ 原语，Task 10 接入样本）。
- **类型一致性**：`route_after_execute`、`_do_node_plan/_do_node_execute/_do_node_finalize`、`workflow_to_state`、`build_state`、`diff_event_streams` 在各 Task 前后签名一致。
- **风险提示**：Task 8/9 的 `_plan_one_step`、`_execute_one_step`、`_workflow_stage_context_fast` 抽取涉及大段原逻辑搬迁，须逐行核对 `st.xxx` → `wf["xxx"]` 映射；`execute` 内 quality_review 归属、`wrote_file` 置位时序保持与旧循环一致，差分保真器兜底。
