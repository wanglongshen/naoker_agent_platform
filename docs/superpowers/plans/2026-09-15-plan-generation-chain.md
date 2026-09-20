# 三期：平台级 LangGraph 方案生产线 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「生成一份广告营销方案」从单次 agent run 升级为平台级 LangGraph 任务链（调研 → 初稿 → 审校 → 交付 → 计费），DSH 作为执行层跑子任务，前端新增「方案中心」入口，产出 P95 ≤10 分钟。

**Architecture:** 编排层（本计划新增 `backend/app/services/task_chain/`）用 LangGraph 定义平台级状态机，每个阶段把子任务交给 DSH 执行层（新增 `backend/app/services/dsh/executor.py`，headless CLI + 每用户 DSH_HOME 复用）；阶段状态落 `task_chains`/`task_chain_stages` 两张表，独立 worker 进程领取执行；交付阶段落文件 + 飞书文档，计费阶段汇总平台 LLM tokens 与 DSH usage 后复用现有积分服务扣减。现有单 run 的 agent 图（`langgraph_runner.py`）不动，两者职责分离：**任务链是生产线，agent run 是工人**。

**Tech Stack:** FastAPI + SQLAlchemy(async) + Alembic + LangGraph + PostgreSQL 18 + DSH headless CLI（vendored `deepseek-harness/`，Node 22）+ Next.js 16 / Ant Design + vitest / pytest。

## Global Constraints

- 平台既有约束一字不动：统一响应壳 `success(request, ...)`（`backend/app/schemas/common.py`）；CSRF 依赖 `require_csrf`；权限依赖 `require_permissions` / `require_super_admin`（`backend/app/core/dependencies.py:97,113`）。
- **不修改 `deepseek-harness/` 上游源码**；一切 DSH 侧改动走官方插件/CLI 范式。
- 计费只走现有积分服务 `backend/app/services/points.py`（`tokens_to_points` / `deduct_for_run` / `grant_points`），不新建账本；`PointTransaction.type` 只允许 `grant|consume|redeem`。
- 数据模型新增字段必须有来源证据；本计划新增字段全部在任务里给出出处（现有模型/事件/DSH JSONL）。
- 单测不连真实 LLM、不连真实 DSH：LLM 用 fake client，DSH 执行层用 fake 可执行脚本；真实链路只在 T9 验收手测。
- 每个任务结束必须 `git add` 精确路径 + `git diff --cached --name-only` 核对（仓库常有并行会话的未提交改动，见 `AGENTS`/历史教训）。
- 提交信息用 `feat(task-chain): ...` / `fix(...)` 前缀；中文正文可选。
- 运行测试：`cd backend` 后 `X:\python\anaconda\envs\01-rbac\python.exe -m pytest <path> -q`；前端：`cd frontend` 后 `npm test -- --run <path>`。

---

## 文件结构（先锁定边界）

| 文件 | 职责 |
|---|---|
| `backend/app/services/dsh/executor.py`（新） | DSH headless 子任务执行：spawn、超时、结果提取、usage 读取入口 |
| `backend/app/services/dsh/usage.py`（新） | 从 DSH 会话 JSONL 累加 `assistant/message.usage` |
| `backend/app/models/task_chain.py`（新） | `task_chains` / `task_chain_stages` 两表 |
| `backend/app/repositories/task_chain_repository.py`（新） | 任务链 CRUD + 领取（条件 UPDATE） |
| `backend/app/services/task_chain/graph.py`（新） | LangGraph 状态机定义（8 节点） |
| `backend/app/services/task_chain/service.py`（新） | 节点实现 + 依赖注入（executor / llm / points / file service） |
| `backend/app/services/task_chain/__init__.py`（新） | 导出 `TaskChainService`、`build_chain_graph` |
| `backend/app/workers/task_chain_worker.py`（新） | 独立进程：领取 queued 任务链并执行 |
| `backend/app/api/task_chains.py`（新） | REST：创建/列表/详情/取消 |
| `backend/app/schemas/task_chain.py`（新） | 请求/响应模型 |
| `frontend/src/app/(dashboard)/generations/page.tsx`（新） | 方案中心页面 |
| `frontend/src/components/generations/*`（新） | 表单 / 阶段时间线 / 产出预览 |
| `frontend/src/lib/task-chain-api.ts`（新） | 前端 API 客户端 |
| `deploy/Dockerfile.backend`（改） | 多阶段：Node+pnpm 构建 vendored DSH 与 connector → Python 运行时 |
| `deploy/docker-compose.yml`（改） | postgres→pgvector、DSH_* env、`var/dsh` 卷、两个新 worker |
| `deploy/pack.ps1` / `verify-zip.ps1` / `.env.template`（改） | 打包纳入 `deepseek-harness/`、`dsh-platform/`，新环境变量 |

**共享文件唯一属主**（不要并行改）：`backend/app/models/__init__.py` 与 `backend/alembic/env.py`（T3）、`backend/app/main.py`（T5）、`frontend/src/components/layout/app-sidebar.tsx` + `frontend/src/lib/copy.ts`（T7）、`deploy/*`（T8）。

---

### Task 1: DSH headless 子任务执行器

**Files:**
- Create: `backend/app/services/dsh/executor.py`
- Create: `backend/tests/test_dsh_executor.py`
- Modify: `backend/app/services/dsh/instance_config.py`（`install_connector_plugin` 增加 `profile` 参数）

**Interfaces:**
- Produces:
  - `@dataclass DshTaskResult: final_text: str; exit_code: int; stdout: str; stderr: str; duration_seconds: float`
  - `class DshTaskExecutor: async def run(self, *, user_id: uuid.UUID, task: str, timeout_seconds: float | None = None, home_dir: Path | None = None) -> DshTaskResult`
  - `DshTaskExecutor.spawn_command(home: Path, task: str) -> list[str]`（可测纯函数）
- Consumes: `settings.dsh_instance_mode`、`settings.dsh_home_root_path`、`settings.dsh_timeout_seconds`（T1 新增）、`resolve_dsh_js()`（`instance_config.py:25`）

- [ ] **Step 1: 先做 CLI 行为 spike（写进报告，不写代码）**

Run:
```powershell
cd C:\01_agent_loop_pro
$env:DSH_HOME="C:\01_agent_loop_pro\backend\var\dsh\<某已存在用户id>"
node deepseek-harness/apps/cli/lib/bin.js --profile headless "用一句话介绍你自己"
```
记录：stdout 是否就是最终回复、退出码、是否有 `--print` 类开关、报错时 stderr 形态、耗时。
（上游定义：`deepseek-harness/packages/bundle/headless/src/startup.ts:31-41`；`pnpm dsh --profile headless "task"` 见 `deepseek-harness/AGENTS.md` Commands。）
**若 headless profile 缺 connector 插件导致平台工具不可用**，在 Step 3 的实现里对 headless profile 也执行一次 `install_connector_plugin(home, profile="headless")`。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_dsh_executor.py
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.services.dsh.executor import DshTaskExecutor


def test_spawn_command_uses_headless_profile_and_home(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "dsh_instance_mode", "vendored")
    exe = DshTaskExecutor().spawn_command(tmp_path, "写一句话")
    assert exe[0] == "node"
    assert exe[1].endswith("deepseek-harness/apps/cli/lib/bin.js")
    assert exe[2:4] == ["--profile", "headless"]
    assert exe[-1] == "写一句话"


@pytest.mark.anyio
async def test_run_returns_final_text_and_exit_code(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "dsh_instance_mode", "vendored")
    executor = DshTaskExecutor()

    async def fake_spawn(cmd, *, env, cwd, timeout):
        assert env["DSH_HOME"] == str(tmp_path)
        return (0, "这是最终回复\n", "")

    monkeypatch.setattr(executor, "_spawn", fake_spawn)
    result = await executor.run(user_id=uuid.uuid4(), task="写一句话", home_dir=tmp_path)
    assert result.final_text == "这是最终回复"
    assert result.exit_code == 0


@pytest.mark.anyio
async def test_run_marks_nonzero_exit_with_stderr(tmp_path: Path, monkeypatch):
    executor = DshTaskExecutor()

    async def fake_spawn(cmd, *, env, cwd, timeout):
        return (1, "", "boom")

    monkeypatch.setattr(executor, "_spawn", fake_spawn)
    result = await executor.run(user_id=uuid.uuid4(), task="x", home_dir=tmp_path)
    assert result.exit_code == 1
    assert "boom" in result.stderr
```

- [ ] **Step 3: 实现**

```python
# backend/app/services/dsh/executor.py
"""DSH headless 子任务执行层：任务链的「执行工人」。

决策（2026-09-15）：走 headless CLI 而不是 Python SDK——SDK 需要额外 runtime
二进制（deepseek-harness/python/sdk），CLI 已 vendored 且与实例管理共用 DSH_HOME；
两者产物等价（最终文本），usage 统一从会话 JSONL 读取（services/dsh/usage.py）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger("dsh.executor")


@dataclass
class DshTaskResult:
    final_text: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


class DshTaskExecutor:
    def spawn_command(self, home: Path, task: str) -> list[str]:
        settings = get_settings()
        if settings.dsh_instance_mode == "vendored":
            repo_root = Path(__file__).resolve().parents[4]
            exe = ["node", str(repo_root / "deepseek-harness/apps/cli/lib/bin.js")]
        else:
            from app.services.dsh.instance_config import resolve_dsh_js

            js = resolve_dsh_js()
            exe = ["node", js] if js else ["dsh"]
        return exe + ["--profile", "headless", task]

    def _env(self, home: Path) -> dict[str, str]:
        settings = get_settings()
        env = dict(os.environ)
        env["DSH_HOME"] = str(home)
        if settings.deepseek_api_key:
            env["DEEPSEEK_API_KEY"] = settings.deepseek_api_key
        return env

    async def _spawn(self, cmd: list[str], *, env: dict[str, str], cwd: Path, timeout: float):
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env, cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        return (
            int(proc.returncode or 0),
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"),
        )

    async def run(
        self,
        *,
        user_id: uuid.UUID,
        task: str,
        timeout_seconds: float | None = None,
        home_dir: Path | None = None,
    ) -> DshTaskResult:
        settings = get_settings()
        home = home_dir or (settings.dsh_home_root_path / str(user_id))
        home.mkdir(parents=True, exist_ok=True)
        cmd = self.spawn_command(home, task)
        timeout = timeout_seconds or settings.dsh_task_timeout_seconds
        started = time.monotonic()
        try:
            code, out, err = await self._spawn(cmd, env=self._env(home), cwd=home, timeout=timeout)
        except asyncio.TimeoutError:
            code, out, err = 124, "", f"dsh task timeout after {timeout}s"
            logger.warning("dsh task timeout user=%s task=%s", user_id, task[:80])
        return DshTaskResult(
            final_text=out.strip(),
            exit_code=code,
            stdout=out,
            stderr=err,
            duration_seconds=round(time.monotonic() - started, 3),
        )
```

同时：
- `backend/app/core/config.py` 新增 `dsh_task_timeout_seconds: float = 300.0`（挨着其它 `dsh_*` 字段，`:88-96` 区段）。
- `instance_config.py:47` 的 `install_connector_plugin(dsh_home, connector_pkg=None, profile="web")`：把三处 `"--profile", "web"` 换成 `"--profile", profile`；调用点 `instance_manager.py:236` 传默认值不变。

- [ ] **Step 4: 跑绿 + 回归**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_dsh_executor.py tests/test_dsh_instance_config.py -q`
Expected: PASS（新 3 条 + 既有全绿）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/dsh/executor.py backend/tests/test_dsh_executor.py backend/app/services/dsh/instance_config.py backend/app/core/config.py
git diff --cached --name-only
git commit -m "feat(task-chain): dsh headless subtask executor"
```

---

### Task 2: connector token 续签 + 平台侧身份加固

**Files:**
- Modify: `backend/app/services/dsh/instance_manager.py`（`ensure_running` 对 running 实例刷新注入）
- Modify: `backend/app/core/dependencies.py`（校验 `X-Dsh-Platform-User` 与 token `sub` 一致）
- Test: `backend/tests/test_dsh_platform_token.py`（新）

**Interfaces:**
- Consumes: `mint_platform_token`（`security.py:74`）、`decode_platform_token`（`:86`）、`ensure_home_config`（`instance_config.py:107`）
- Produces: `DshInstanceManager.refresh_injection(user_id, db) -> None`（供任务链执行前调用，保证 token 不过期）

**背景（实测缺口）：** `dsh_platform_token_ttl_seconds=300`（`config.py:93`），只在 spawn 时签发（`instance_manager.py:228-235`）；实例 running 时 `ensure_running` 早退（`:182-183`）→ 实例存活超过 5 分钟后 connector 调平台 API 必然 401。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_dsh_platform_token.py
from __future__ import annotations

import uuid

import pytest


@pytest.mark.anyio
async def test_refresh_injection_rewrites_patch_with_fresh_token(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.services.dsh import instance_config

    settings = get_settings()
    monkeypatch.setattr(settings, "dsh_home_root_path", tmp_path)
    monkeypatch.setattr(settings, "dsh_platform_base", "http://localhost:8000")
    calls = {}

    def fake_ensure_home_config(home_dir, **kwargs):
        calls["home"] = home_dir
        calls.update(kwargs)

    monkeypatch.setattr(instance_config, "ensure_home_config", fake_ensure_home_config)
    from app.services.dsh.instance_manager import DshInstanceManager

    manager = DshInstanceManager()
    user_id = uuid.uuid4()
    await manager.refresh_injection(user_id, db=None)
    assert calls["home"] == tmp_path / str(user_id)
    assert calls["platform_token"]
    assert calls["user_id"] == str(user_id)
```

- [ ] **Step 2: 实现**

`instance_manager.py` 新增：

```python
    async def refresh_injection(self, user_id: uuid.UUID, db) -> None:
        """刷新该用户的平台注入（token 会过期，任务链每次执行前调用）。"""
        from app.core.security import mint_platform_token
        from app.services.dsh.instance_config import ensure_home_config

        settings = get_settings()
        home = settings.dsh_home_root_path / str(user_id)
        home.mkdir(parents=True, exist_ok=True)
        ensure_home_config(
            home,
            platform_base=settings.dsh_platform_base,
            user_id=str(user_id),
            platform_token=mint_platform_token(str(user_id)),
            trusted_host=settings.dsh_trusted_host,
            skills_src=self.repo_root / "dsh-platform/skills-template",
        )
```

`dependencies.py` 的 `get_current_user`（`:16-25`）在走 token 分支后追加校验：

```python
        header_user = request.headers.get("x-dsh-platform-user")
        if header_user and header_user != str(payload["sub"]):
            raise HTTPException(status_code=401, detail="platform token subject mismatch")
```

（`payload` 是 `decode_platform_token` 的返回；字段名以实际实现为准。）

- [ ] **Step 3: 跑绿**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_dsh_platform_token.py tests/test_dsh_proxy.py tests/test_dsh_sessions_api.py -q`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add backend/app/services/dsh/instance_manager.py backend/app/core/dependencies.py backend/tests/test_dsh_platform_token.py
git commit -m "fix(dsh): refresh platform injection + verify token subject"
```

---

### Task 3: 任务链数据层

**Files:**
- Create: `backend/app/models/task_chain.py`
- Create: `backend/app/repositories/task_chain_repository.py`
- Create: `backend/alembic/versions/<new>_add_task_chain_tables.py`（`alembic revision -m "add task chain tables"` 生成后手写）
- Modify: `backend/app/models/__init__.py`、`backend/alembic/env.py`（import 新模型）
- Test: `backend/tests/test_task_chain_repository.py`

**Interfaces:**
- Produces:
  - `TaskChain`（表 `task_chains`）：`id`、`user_id`(FK users)、`goal`、`input_payload`(JSONB)、`status`(`queued|running|succeeded|failed|cancelled`)、`current_stage`、`result_file_id`(FK file_objects, nullable)、`feishu_doc_url`、`final_answer`、`error`、`total_tokens`、`points_cost`、`created_at`、`updated_at`、`started_at`、`finished_at`
  - `TaskChainStage`（表 `task_chain_stages`）：`id`、`chain_id`(FK, ondelete CASCADE)、`stage`、`seq`、`status`(`pending|running|succeeded|failed|skipped`)、`attempt`、`input_payload`(JSONB)、`output_payload`(JSONB)、`error`、`tokens`、`started_at`、`finished_at`、`created_at`
  - `TaskChainRepository`：`create_chain(...)`、`get_chain(id, user_id=None)`、`list_chains(user_id, page, page_size)`、`add_stage(chain_id, stage, seq)`、`update_stage(stage_id, **fields)`、`claim_next_chain() -> TaskChain | None`（`UPDATE ... WHERE id = (SELECT id FROM task_chains WHERE status='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING id`）、`set_chain_status(...)`
- 字段来源证据：`input_payload` 对齐现有 run 创建入参（`api/agent.py:277-327` 的 goal/附件/蓝图）；`result_file_id` 对齐 `generation_logs.final_md_file_id`（`models/generation_log.py:12-43`）；`tokens/points_cost` 对齐 `user_points`/`point_transactions`（`models/points.py:12-38`）。

- [ ] **Step 1: 写模型 + 迁移**

（模型按上面字段写，`JSONB` 用 `from sqlalchemy.dialects.postgresql import JSONB`；表名/索引：`ix_task_chains_status_created`、`ix_task_chain_stages_chain_seq` unique。）

- [ ] **Step 2: 写失败测试（真实测试库）**

```python
# backend/tests/test_task_chain_repository.py
from __future__ import annotations

import uuid

import pytest


@pytest.mark.anyio
async def test_create_claim_and_stage_lifecycle(test_db):
    from app.models.rbac import User
    from app.repositories.task_chain_repository import TaskChainRepository

    user = User(id=uuid.uuid4(), username=f"tc-{uuid.uuid4().hex[:8]}", password_hash="x")
    test_db.add(user)
    await test_db.commit()

    repo = TaskChainRepository(test_db)
    chain = await repo.create_chain(user_id=user.id, goal="写一份方案", input_payload={"brand": "X"})
    assert chain.status == "queued"

    claimed = await repo.claim_next_chain()
    assert claimed is not None and claimed.id == chain.id and claimed.status == "running"
    assert await repo.claim_next_chain() is None  # 已领取

    stage = await repo.add_stage(chain_id=chain.id, stage="research_agenda", seq=1)
    await repo.update_stage(stage.id, status="succeeded", output_payload={"topics": ["a"]})
    stages = await repo.list_stages(chain.id)
    assert stages[0].status == "succeeded"
    assert stages[0].output_payload == {"topics": ["a"]}
```

- [ ] **Step 3: 跑绿**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_task_chain_repository.py -q`
Expected: PASS；再跑 `X:\python\anaconda\envs\01-rbac\python.exe -m alembic upgrade head` 与 `alembic heads` 确认单一 head。

- [ ] **Step 4: 提交**

```bash
git add backend/app/models/task_chain.py backend/app/models/__init__.py backend/alembic/versions/<new>_add_task_chain_tables.py backend/alembic/env.py backend/app/repositories/task_chain_repository.py backend/tests/test_task_chain_repository.py
git commit -m "feat(task-chain): tables, repository and migration"
```

---

### Task 4: 任务链状态机（LangGraph 8 节点）

**Files:**
- Create: `backend/app/services/task_chain/__init__.py`、`graph.py`、`service.py`
- Test: `backend/tests/test_task_chain_graph.py`

**Interfaces:**
- Consumes: `DshTaskExecutor.run(...)`（T1）、`TaskChainRepository`（T3）、`deduct_for_run`/`tokens_to_points`（`points.py:27,53`）、`build_plan_summary`/`validate_plan_structure`（`plan_structure.py:335,102`）、`FileRepository`（写交付文件复用 `tool_executor._write_file` 的落盘口径）
- Produces:
  - `STAGES = ("collect_input","research_agenda","run_research","draft_plan","review_gate","polish","deliver","bill")`
  - `class TaskChainService: def __init__(self, repo, executor=None, llm=None, points=None, ...)`；`async def run_chain(self, chain_id) -> None`；节点方法 `_stage_collect_input/_stage_research_agenda/_stage_run_research/_stage_draft_plan/_stage_review_gate/_stage_polish/_stage_deliver/_stage_bill`
  - `def build_chain_graph(service) -> CompiledGraph`（LangGraph `StateGraph(dict)`：线性边 + `review_gate` 条件边 `pass→polish`、`fail→draft_plan`（最多 `task_chain_review_max_rounds=2` 次，超出走 polish 并在 output 标注））
- 节点语义（与设计一致，`docs/superpowers/specs/2026-09-07-dsh-platform-rebase-design.md:213-218`）：
  1. `collect_input`：规整输入（品牌/产品/预算/平台/附件文本），附件文本经 `extract_file_text` 读入 `input_payload`
  2. `research_agenda`：平台 LLM 产出调研清单（JSON list，3-5 条）
  3. `run_research`：`asyncio.gather` 并行 N 个 DSH 子任务（每条清单一个），失败单条重试 1 次，全失败则阶段失败
  4. `draft_plan`：DSH 子任务按 8 模块蓝图产出方案 Markdown（把 `build_plan_summary` 摘要注入 task）
  5. `review_gate`：`validate_plan_structure` + `quality_check` 校验，产出 `{pass: bool, issues: [...]}`（不通过且轮次未满 → 回 draft_plan）
  6. `polish`：DSH 子任务按 review issues 修订
  7. `deliver`：把最终 Markdown 落 `file_objects`（owner=user），记录 `result_file_id`/`final_answer`
  8. `bill`：汇总 tokens（平台 LLM + DSH usage，T6 提供 `collect_dsh_usage`）→ `tokens_to_points` → `deduct_for_run(db, user_id, chain_id, tokens)`（`run_id` 位置传 chain_id，`ref` 语义一致）；usage 缺失时按 `task_chain_flat_points`（新配置，默认 20）记 task 级粗粒度

- [ ] **Step 1: 写失败测试（fake executor，不连真实 DSH/LLM）**

```python
# backend/tests/test_task_chain_graph.py
from __future__ import annotations

import uuid

import pytest


class FakeExecutor:
    def __init__(self):
        self.tasks: list[str] = []

    async def run(self, *, user_id, task, timeout_seconds=None, home_dir=None):
        from app.services.dsh.executor import DshTaskResult

        self.tasks.append(task)
        if "调研" in task:
            return DshTaskResult("调研结果：行业趋势 A/B/C", 0, "", "", 0.1)
        return DshTaskResult("# 方案\n\n## 市场分析\n内容\n## 策略\n内容", 0, "", "", 0.1)


@pytest.mark.anyio
async def test_chain_runs_all_stages_and_delivers(test_db, monkeypatch):
    from app.repositories.task_chain_repository import TaskChainRepository
    from app.services.task_chain.service import TaskChainService
    from app.models.rbac import User

    user = User(id=uuid.uuid4(), username=f"tc-{uuid.uuid4().hex[:8]}", password_hash="x")
    test_db.add(user)
    await test_db.commit()
    repo = TaskChainRepository(test_db)
    chain = await repo.create_chain(user_id=user.id, goal="写一份新品方案", input_payload={})

    service = TaskChainService(repo=repo, executor=FakeExecutor())
    await service.run_chain(chain.id)

    refreshed = await repo.get_chain(chain.id)
    assert refreshed.status == "succeeded"
    stages = await repo.list_stages(chain.id)
    assert [s.stage for s in stages] == list(service.stages_expected_order())
    assert all(s.status == "succeeded" for s in stages if s.stage != "review_gate" or True)
    assert refreshed.result_file_id is not None
```

- [ ] **Step 2: 实现 `graph.py` + `service.py`**

`graph.py`：

```python
from langgraph.graph import END, START, StateGraph

STAGES = ("collect_input","research_agenda","run_research","draft_plan","review_gate","polish","deliver","bill")


def build_chain_graph(service):
    graph = StateGraph(dict)
    graph.add_node("collect_input", service._stage_collect_input)
    graph.add_node("research_agenda", service._stage_research_agenda)
    graph.add_node("run_research", service._stage_run_research)
    graph.add_node("draft_plan", service._stage_draft_plan)
    graph.add_node("review_gate", service._stage_review_gate)
    graph.add_node("polish", service._stage_polish)
    graph.add_node("deliver", service._stage_deliver)
    graph.add_node("bill", service._stage_bill)
    graph.add_edge(START, "collect_input")
    graph.add_edge("collect_input", "research_agenda")
    graph.add_edge("research_agenda", "run_research")
    graph.add_edge("run_research", "draft_plan")
    graph.add_edge("draft_plan", "review_gate")
    graph.add_conditional_edges("review_gate", service._route_after_review, {"draft": "draft_plan", "polish": "polish"})
    graph.add_edge("polish", "deliver")
    graph.add_edge("deliver", "bill")
    graph.add_edge("bill", END)
    return graph.compile()
```

`service.py` 关键实现（节选，完整实现按接口逐节点写）：

```python
    async def run_chain(self, chain_id: uuid.UUID) -> None:
        chain = await self.repo.get_chain(chain_id)
        if chain is None:
            raise ValueError(f"chain not found: {chain_id}")
        await self.repo.set_chain_status(chain_id, "running", started_at=datetime.now(UTC))
        try:
            await build_chain_graph(self).ainvoke({"chain_id": str(chain_id)})
            await self.repo.set_chain_status(chain_id, "succeeded", finished_at=datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001
            await self.repo.set_chain_status(chain_id, "failed", error=str(exc)[:500], finished_at=datetime.now(UTC))
            raise

    async def _stage_run_research(self, state: dict) -> dict:
        chain = await self._chain(state)
        agenda = state["agenda"]
        async def one(topic: str) -> str:
            result = await self.executor.run(user_id=chain.user_id, task=f"调研任务：{topic}")
            return result.final_text
        results = await asyncio.gather(*(one(t) for t in agenda), return_exceptions=True)
        texts = [r for r in results if isinstance(r, str)]
        if not texts:
            raise RuntimeError("all research subtasks failed")
        return {"research": texts}
```

（每个节点内部：`add_stage` 落 `running` → 干活 → `update_stage` 落 `succeeded/failed` + `output_payload`；失败抛异常由 `run_chain` 统一落链级 failed。）

- [ ] **Step 3: 跑绿**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_task_chain_graph.py -q`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add backend/app/services/task_chain backend/tests/test_task_chain_graph.py
git commit -m "feat(task-chain): langgraph state machine with dsh-backed stages"
```

---

### Task 5: 任务链 worker 与 API

**Files:**
- Create: `backend/app/workers/task_chain_worker.py`
- Create: `backend/app/api/task_chains.py`、`backend/app/schemas/task_chain.py`
- Modify: `backend/app/main.py`（`:101-120` 区段 include_router）
- Test: `backend/tests/test_task_chain_api.py`

**Interfaces:**
- Consumes: `TaskChainService`（T4）、`TaskChainRepository`（T3）、权限依赖（`require_permissions`）
- Produces:
  - `POST /api/task-chains`（body：`goal`、`input_payload`、可选 `attachments[]`）→ 创建 queued 链；余额 ≤0 时 400 `INSUFFICIENT_POINTS`（照抄 `api/agent.py:293-295`）
  - `GET /api/task-chains?page=&page_size=`（仅本人）
  - `GET /api/task-chains/{id}`（含 stages 列表；非属主 404）
  - `POST /api/task-chains/{id}/cancel`（queued/running → cancelled）
  - `TaskChainWorker`（`POLL_INTERVAL_SECONDS=3`，循环 `claim_next_chain()` → `run_chain`；照抄 `dsh_sync_worker.py:41-61` 的信号/循环骨架）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_task_chain_api.py
from __future__ import annotations

import uuid

import pytest


@pytest.mark.anyio
async def test_create_and_get_chain_scoped_to_owner(api_client, test_db, auth_headers):
    resp = await api_client.post("/api/task-chains", json={"goal": "写一份方案", "input_payload": {}}, headers=auth_headers)
    assert resp.status_code == 200
    chain_id = resp.json()["data"]["id"]
    detail = await api_client.get(f"/api/task-chains/{chain_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "queued"
```

（`api_client` / `auth_headers` 夹具名以 `backend/tests/conftest.py` 现有为准——先读 conftest 再定测试写法。）

- [ ] **Step 2: 实现**（路由按现有风格：`success(request, ...)` 壳、`Depends(require_csrf)` 写操作、`get_db`）

- [ ] **Step 3: 跑绿**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_task_chain_api.py -q`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add backend/app/workers/task_chain_worker.py backend/app/api/task_chains.py backend/app/schemas/task_chain.py backend/app/main.py backend/tests/test_task_chain_api.py
git commit -m "feat(task-chain): worker and REST API"
```

---

### Task 6: DSH usage 采集与任务级计费口径

**Files:**
- Create: `backend/app/services/dsh/usage.py`
- Modify: `backend/app/services/task_chain/service.py`（`_stage_bill` 接入）
- Test: `backend/tests/test_dsh_usage.py`

**Interfaces:**
- Produces: `def collect_dsh_usage(home_dir: Path, *, since: float, until: float) -> int`（累加 `<home>/sessions/**/session.jsonl.zstd` 中 `time` 落在窗口内事件的 `assistant/message` → `usage.inputTokens+outputTokens+cacheReadTokens+cacheWriteTokens+reasoningTokens`）
- 证据：DSH 事件结构 `deepseek-harness/packages/core/session/src/types.ts:277`、字段 `packages/llm/llm/src/types.ts:135-141`；会话文件布局见 `dsh-platform/NOTES.md` 第 1 项（JSONL+zstd）

- [ ] **Step 1: 写失败测试（构造最小 zstd JSONL fixture）**

```python
# backend/tests/test_dsh_usage.py
from __future__ import annotations

import json
import zstandard

from app.services.dsh.usage import collect_dsh_usage


def _write_session(home, session_id: str, lines: list[dict]):
    d = home / "sessions" / "proj" / session_id
    d.mkdir(parents=True, exist_ok=True)
    raw = "\n".join(json.dumps(x) for x in lines).encode()
    (d / "session.jsonl.zstd").write_bytes(zstandard.ZstdCompressor().compress(raw))


def test_collect_usage_sums_window(tmp_path):
    _write_session(tmp_path, "s1", [
        {"type": "session", "id": "s1", "time": 1000},
        {"type": "assistant/message", "time": 1500, "usage": {"inputTokens": 100, "outputTokens": 20}},
        {"type": "assistant/message", "time": 2500, "usage": {"inputTokens": 10, "outputTokens": 5}},
    ])
    assert collect_dsh_usage(tmp_path, since=1400, until=2000) == 120
    assert collect_dsh_usage(tmp_path, since=0, until=9999) == 135
```

（`zstandard` 已在后端依赖里——T1 之前先 `pip show zstandard` 确认；缺则加入 `requirements.txt` 与本地环境。）

- [ ] **Step 2: 实现**（流式解压 + 逐行 json.loads + 容错跳过坏行 + 窗口过滤）

- [ ] **Step 3: 接入 `_stage_bill`**：`tokens = self.chain_llm_tokens + collect_dsh_usage(home, since=started_at, until=finished_at)`；`points = tokens_to_points(tokens)`；`await deduct_for_run(self.db, chain.user_id, chain.id, tokens)`；把 `tokens/points` 写回 chain。DSH usage 为 0 时回退 `settings.task_chain_flat_points`（新配置，默认 20）。

- [ ] **Step 4: 跑绿 + 提交**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_dsh_usage.py tests/test_task_chain_graph.py -q`

```bash
git add backend/app/services/dsh/usage.py backend/app/services/task_chain/service.py backend/tests/test_dsh_usage.py backend/app/core/config.py
git commit -m "feat(task-chain): dsh usage collection and stage-level billing"
```

---

### Task 7: 前端「方案中心」`/generations`

**Files:**
- Create: `frontend/src/app/(dashboard)/generations/page.tsx`
- Create: `frontend/src/components/generations/chain-form.tsx`、`chain-list.tsx`、`chain-detail-drawer.tsx`
- Create: `frontend/src/lib/task-chain-api.ts`
- Modify: `frontend/src/components/layout/app-sidebar.tsx`（`systemItems`）、`frontend/src/lib/copy.ts`
- Test: `frontend/src/components/generations/chain-list.test.tsx`

**Interfaces:**
- Consumes: `api<T>()`（`lib/api.ts:27-80`，自动 CSRF/错误壳）；复用 `components/agent/final-answer-panel.tsx`（Markdown 预览）、`components/ui/data-surface.tsx`、`components/ui/view-states.tsx`
- Produces: `taskChainApi = { create(input), list(page, pageSize), get(id), cancel(id) }`；页面三段：发布表单（品牌/产品/预算/平台/附件/蓝图）→ 任务链列表（状态徽章 + 耗时）→ 详情抽屉（阶段时间线 + 产出预览 + 下载/飞书链接）

- [ ] **Step 1: 写失败测试（vitest + msw 或 fetch mock，按现有测试风格）**

```tsx
// frontend/src/components/generations/chain-list.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/task-chain-api", () => ({
  taskChainApi: {
    list: vi.fn().mockResolvedValue({
      items: [{ id: "1", goal: "写一份方案", status: "succeeded", current_stage: "bill", duration_seconds: 421 }],
      total: 1,
    }),
  },
}));

import { ChainList } from "./chain-list";

describe("ChainList", () => {
  it("渲染任务链状态与耗时", async () => {
    render(<ChainList />);
    expect(await screen.findByText("写一份方案")).toBeTruthy();
    expect(screen.getByText("7 分 1 秒")).toBeTruthy();
  });
});
```

- [ ] **Step 2: 实现组件与页面**（AntD `Table`/`Drawer`/`Form`/`Timeline`，样式对齐现有 dashboard；菜单项文案「方案中心」，`/generations`，普通登录用户可见）

- [ ] **Step 3: 跑绿 + 提交**

Run: `cd frontend; npm test -- --run src/components/generations`

```bash
git add frontend/src/app/(dashboard)/generations frontend/src/components/generations frontend/src/lib/task-chain-api.ts frontend/src/components/layout/app-sidebar.tsx frontend/src/lib/copy.ts
git commit -m "feat(task-chain): plan center page"
```

---

### Task 8: Docker / 打包整合

**Files:**
- Modify: `deploy/Dockerfile.backend`、`deploy/docker-compose.yml`、`deploy/.env.template`、`deploy/pack.ps1`、`deploy/verify-zip.ps1`、`deploy/upgrade.sh`
- Test: `deploy/` 本地 compose 冒烟（人工，见 Step 3）

**Interfaces:**
- Consumes: vendored `deepseek-harness/`（`apps/cli/lib/bin.js` 已构建）、`dsh-platform/`（connector `lib/index.js`）
- Produces: 镜像内 `node` + `deepseek-harness/` + `dsh-platform/`；compose 新增/修改：
  - `postgres` 镜像 → `pgvector/pgvector:pg16`（设计 §5.3，`spec:227`）
  - `backend` env 增加 `DSH_INSTANCE_MODE=vendored`、`DSH_HOME_ROOT=/app/backend/var/dsh`、`DSH_TRUSTED_HOST`、`DSH_PLATFORM_BASE`
  - 卷 `agent-dsh` → `/app/backend/var/dsh`
  - 新服务 `task-chain-worker`（`python -m app.workers.task_chain_worker`）与 `dsh-sync-worker`（`python -m app.workers.dsh_sync_worker`）
  - 端口：DSH 实例端口 3100-3399 仅在容器网络内，不映射到宿主

- [ ] **Step 1: 改 Dockerfile.backend 为多阶段**

```dockerfile
FROM node:22-bookworm-slim AS dsh-build
RUN corepack enable
WORKDIR /build
COPY deepseek-harness/ deepseek-harness/
COPY dsh-platform/ dsh-platform/
RUN cd deepseek-harness && pnpm install --frozen-lockfile && pnpm run build
RUN cd dsh-platform && pnpm install --frozen-lockfile && pnpm run build

FROM python:3.13-slim
# ... 既有步骤保留 ...
COPY --from=dsh-build /build/deepseek-harness /app/deepseek-harness
COPY --from=dsh-build /build/dsh-platform /app/dsh-platform
RUN apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: 改 compose / pack / verify / env.template**（按上面清单；`pack.ps1:45-52` 的收集列表加入 `deepseek-harness`、`dsh-platform`；`verify-zip.ps1:22` 必需条目加入 `code/deepseek-harness/apps/cli/lib/bin.js`）

- [ ] **Step 3: 本地冒烟（人工/脚本）**

Run:
```powershell
cd deploy
docker compose up -d --build
docker compose exec backend node /app/deepseek-harness/apps/cli/lib/bin.js --version
docker compose exec backend python -m app.workers.task_chain_worker --help
```
Expected: 版本号输出 = `.dsh-vendor.json` 的 tag；worker 能启动。

- [ ] **Step 4: 提交**

```bash
git add deploy/Dockerfile.backend deploy/docker-compose.yml deploy/.env.template deploy/pack.ps1 deploy/verify-zip.ps1 deploy/upgrade.sh
git commit -m "build(deploy): bundle vendored dsh + pgvector + chain workers"
```

---

### Task 9: 端到端验收与文档

**Files:**
- Create: `docs/verification/task-chain-acceptance.md`
- Modify: `docs/superpowers/plans/2026-09-15-plan-generation-chain.md`（勾选进度）

- [ ] **Step 1: 真实链路验收（人工参与，记录墙钟）**
  1. 起后端 + 前端 + `task_chain_worker`；登录普通用户，打开「方案中心」发布任务（带 1 个附件）
  2. 记录：创建时间 → 交付时间（目标 ≤10 分钟，P95）；阶段时间线每段耗时
  3. 检查产出：文件可下载、内容含 8 模块、`final_answer` 含真实文件名/SHA、飞书链接（若配置）
  4. 检查计费：`point_transactions` 出现 `consume`（`ref=<chain_id>`），余额变化 = 页面显示
  5. 失败路径：把 `DSH_TASK_TIMEOUT_SECONDS` 调成 1 重跑 → 链状态 `failed` + 阶段错误可见 + 不扣费

- [ ] **Step 2: 写验收文档**（记录上述实测数值、截图路径、已知限制：DSH usage 口径、并发上限、超时）

- [ ] **Step 3: 提交**

```bash
git add docs/verification/task-chain-acceptance.md docs/superpowers/plans/2026-09-15-plan-generation-chain.md
git commit -m "docs(verification): task chain acceptance results"
```

---

## Self-Review（写完后自查）

- **Spec 覆盖**：设计 §4（`2026-09-07-dsh-platform-rebase-design.md:207-245`）的编排层/执行层/计费双口径/Docker/前端方案中心/全量验收 → 分别对应 T1/T4、T6、T8、T7、T9；「方案产出 ≤10 分钟」在 T9 计量。
- **占位符扫描**：无 TBD；T4 的节点实现给了核心代码与逐节点语义，实现者按语义补全（每个节点的落库/事件写法与 T4 Step 2 展示的模式一致）。
- **类型一致性**：`DshTaskResult`（T1）在 T4 的 fake 与真实实现中字段一致；`claim_next_chain`（T3）在 T5 worker 使用；`collect_dsh_usage`（T6）签名与 T4 `_stage_bill` 调用一致。
- **已知取舍**：走 headless CLI（非 SDK）——理由与替代方案写在 T1 模块 docstring；任务链事件流 v1 用轮询（前端 2s），不新建 SSE 通道（复用现有 run SSE 的成本高于收益，设计允许）。

## Execution Handoff

计划落盘后给用户两种执行方式：**子代理驱动（推荐）**——T1/T2/T3 可并发（无共享文件），T7 依赖 T5 契约后与 T8 并行，T6 与 T5 并行；**或本会话内联**。
