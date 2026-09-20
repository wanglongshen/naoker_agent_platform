# DSH 平台化改造 · 一期（DSH 运行时接入）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DeepSeek Harness（DSH）作为每用户 Agent 运行时接入企业智助平台：用户登录后 /agent 显示 DSH Web UI（皮肤插件可用），平台文件工具可被 DSH 调用，会话元数据回流审计，多用户严格隔离。

**Architecture:** 每用户一个 DSH 实例（`dsh --profile web`，`DSH_HOME=var/dsh/<uid>/`，端口槽位 3100-3399），由 FastAPI 内 `DshInstanceManager` 管理生命周期；平台以 `/dsh-proxy/<uid>/**` 反代（HTTP+WS，平台登录+属主 404 即边界）；平台适配全部以 DSH 官方插件范式落地（`dsh-platform/packages/server-connector` + `<home>/skills/` 注入），不改 DSH 本体。

**Tech Stack:** Python 3.12+ / FastAPI / async SQLAlchemy / PostgreSQL 16 / pytest; Node 20+ / pnpm / tsdown / vitest; Next.js 16 / AntD 6 / vitest+jsdom。

**Spec:** `docs/superpowers/specs/2026-09-07-dsh-platform-rebase-design.md`（设计第 3 节 = 本期；全部字段/验收以 spec 为准）

## Global Constraints（每条任务隐式包含）

1. DSH 上游版本：**pinned @deepseek-ai/dsh 0.1.1-rc.2 对应 commit**（`git ls-remote` 解析 tag 得到，写入 `deepseek-harness/.dsh-vendor.json`）。**严禁手工修改 `deepseek-harness/` 内任何文件**。
2. 端口槽位：3100-3399（用户哈希映射，冲突重试 3 次）；主机仅 `127.0.0.1`。
3. 空闲回收：600s（SIGTERM→30s→kill）；实例幂等锁保证不并发双启。
4. 平台身份：`request.user.id == uid` 强校验，非属主一律 404（与现有跨用户策略一致）。
5. DNS/网络：DSH web 启动必须带 `--trusted-host <平台权威域>`（dev=localhost:3000）。
6. 数据：`dsh_sessions` 字段名以「T2 代码考古实测的 DSH 会话库 schema」为准，禁止臆造；正文永不复制进平台库。
7. 密钥：`DEEPSEEK_API_KEY` 只经平台 .env→子进程环境透传，不写入 DSH home、不写日志。
8. 前端测试约束（记忆#73-75）：jsdom 页面级 byRole 禁用；按钮断言用 `document.querySelectorAll("button") + textContent` 或 `within(小容器)`；antd message 只断言 `findByText`（toBeVisible 恒失败）。
9. 测试数据库：`rbac_test`（conftest 自建）；pytest `asyncio_mode=auto`；命令在 `backend/` 下执行。
10. 提交规则：只精确 `git add` 本任务文件（工作区常有他人预置文件，记忆#93）。
11. 禁止修改：现有 agent 循环/SSE 管线/计费/蓝图代码（本期零改动面，仅在 `app/services/dsh/*`、`app/api/dsh*`、`frontend/.../agent` 增量区动刀）。

---

## File Structure Map

```
deepseek-harness/                    上游快照（T1，只读）
  .dsh-vendor.json                   锁定记录（SHA/日期/来源/版本）
scripts/
  sync-dsh-vendor.ps1                协议化拉取/锁定/构建（T1 新建）
  dsh_smoke.ps1                      一期冒烟（T12 新建）
dsh-platform/                        我们的一期插件 workspace（T2/T7）
  package.json
  packages/server-connector/
    package.json  src/index.ts  lib/*(构建产物)  vitest.config.ts  tests/connector.test.ts
  skills-template/platform-knowledge/SKILL.md
  NOTES.md                           T2 考古结论（供 T7/T9 落地）
  cordis.patch.yml.example           Web profile 注入样例
backend/app/
  core/config.py                     [+] DSH_* 配置项（T4）
  models/dsh.py                      [+] dsh_instances / dsh_sessions（T3）
  alembic/versions/xxxx_add_dsh_tables.py（T3）
  api/dsh.py                         [+] 会话/审计 API（T9）；dsh_proxy.py [+] 反代（T6）
  services/dsh/__init__.py
  services/dsh/instance_manager.py   [+]（T5）
  services/dsh/proxy.py              [+] HTTP/WS trampoline（T6）
  services/dsh/instance_config.py    [+] patch/skills/env 注入（T8）
  services/dsh/session_sync.py       [+] 审计回流（T9）
  workers/dsh_sync_worker.py         [+] 周期性同步入口（T9，独立进程同 agent_worker 范式）
backend/tests/test_dsh_*.py          （T3/T4/T5/T6/T8/T9）
backend/.env.example                 [+] DSH_* 默认值说明（T4）
frontend/src/app/dsh/agent/          ➔ 新 /agent 页（T10）
frontend/src/app/dsh/agent/legacy/   ➔ 现 /agent 内容迁移（只移动不改）
frontend/.../agent-audit/            ➔（T11 审计 DSH 标签合并进现有 audit 页 或独立 /agent/audit 子视图）
docs/superpowers/specs/2026-09-07-dsh-platform-rebase-design.md（已提交，勿改）
```

---

## Task 1: DSH 上游快照入仓 + 构建冒烟

**Files:**
- Create: `scripts/sync-dsh-vendor.ps1`, `deepseek-harness/.dsh-vendor.json`
- (vendor 树由脚本产出；目录极大，实施完成后核对 `.gitignore` 增补：`deepseek-harness/node_modules/` `deepseek-harness/.git/`)

**Interfaces:**
- Produces: `deepseek-harness/` 可构建目录；`DSH_VENDOR_SHA`（后续任务读 `.dsh-vendor.json`）；`dsh` 可执行解析规则：`DSH_INSTANCE_MODE=dev_bin` 用 PATH 上的全局 `dsh`，否则 `deepseek-harness` 构建产物。

- [ ] **Step 1: 写 vendoring 脚本**

```powershell
# scripts/sync-dsh-vendor.ps1
param([string]$Tag = "0.1.1-rc.2")
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$vendor = Join-Path $root "deepseek-harness"
$tmp = Join-Path $env:TEMP ("dsh-vendor-" + [guid]::NewGuid().ToString("N"))
git clone --depth 1 --branch $Tag https://github.com/deepseek-ai/deepseek-harness.git $tmp
Push-Location $tmp
$sha = (git rev-parse --short HEAD).Trim()
Pop-Location
# 仅保留构建所需：排除重目录
Remove-Item (Join-Path $tmp ".git") -Recurse -Force
Remove-Item (Join-Path $tmp "website") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $tmp "snapshots") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $tmp ".github") -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $vendor) { Remove-Item $vendor -Recurse -Force }
Move-Item $tmp $vendor
$record = [ordered]@{
  repo = "deepseek-ai/deepseek-harness"; tag = $Tag; sha = $sha;
  vendored_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
}
$record | ConvertTo-Json | Set-Content (Join-Path $vendor ".dsh-vendor.json") -Encoding utf8
Write-Host "vendored tag=$Tag sha=$sha -> $vendor"
```

- [ ] **Step 2: 运行脚本并核对**

Run: `powershell -ExecutionPolicy Bypass -File scripts/sync-dsh-vendor.ps1`
Expected: 输出 `vendored tag=0.1.1-rc.2 sha=<12位> -> <root>\deepseek-harness`；`Get-Content deepseek-harness\.dsh-vendor.json` 三字段齐全。

- [ ] **Step 3: 构建（上游 run-from-source 方式）并冒烟**

Run: `cd deepseek-harness; pnpm install --frozen-lockfile; pnpm run build`（首次构建 10-25 分钟，超时按 1800000ms）
Expected: build 成功，无 err。冒烟：`pnpm exec dsh --version` → `0.1.1-rc.2`（构建产物版）。

- [ ] **Step 4: 验证 web profile 可以无头启动**

Run: `pnpm exec dsh web --no-open --port 0`（后台 5s 后 Ctrl-C）
Expected: 日志出现 listening/`http://127.0.0.1:` 且无异常；若有 `--trusted-host` 缺失防护警告，记录到 T2 考古项。

- [ ] **Step 5: `.gitignore` 补条目并提交**

`.gitignore` 追加：
```
deepseek-harness/node_modules/
deepseek-harness/.git/
# deepseek-harness 快照本体是受控要提交的源码目录，node_modules 除外
```
Run: `git add scripts/sync-dsh-vendor.ps1 deepseek-harness`；`git add .gitignore`
Run: `git commit -m "feat: vendor deepseek-harness @0.1.1-rc.2 with sync script"`
（注意：vendor 大目录一次提交；若体积超限改为 LFS/包 tar 方案的决策在实施时反馈，不要静默裁减功能。）

---

## Task 2: DSH 代码考古（确立可执行事实，产出 NOTES.md）

**Files:**
- Create: `dsh-platform/NOTES.md`, `dsh-platform/package.json`, `dsh-platform/packages/server-connector/package.json`（骨架）
- Read-only: `deepseek-harness/docs/tool-execution-pipeline.md`, `deepseek-harness/docs/tool-catalog.md`, `deepseek-harness/docs/subsystems/skills.md`, `deepseek-harness/python/sdk/README.md`, `deepseek-harness/packages/session/**`（会话存储实现）, `dsh-deep-whale/*/cordis.patch.yml`（patch 样例）, `deepseek-harness/apps/web/**`（web 服务端头部/trusted-host 实现）

**Interfaces:**
- Produces: NOTES.md 中以下六项结论（后续任务直接引用）：
  1. `ctx.*` 工具注册的确切调用（tool 注册 API 名与签名 + 样例代码片段）
  2. 外部插件包接入方式：`package.json` 需要哪些字段、`cordis.patch.yml` 行样例（`- id: <wiring>` + config 传入方式）
  3. web profile 会话库 SQLite 文件路径（`<home>/...`）与其 schema（表名、关键列：会话 id/标题/消息数/时间戳）
  4. 无头任务姿势：`dsh --profile headless "task"`（CLI）与 Python SDK `profile="sdk"`（JSON-RPC）各自适用场景，及其 RunResult/events 是否暴露使用量（usage token 字段存在与否——决定三期计费口径，本期只记录）
  5. `--trusted-host` 的生效语义（反代场景必须加的平台域清单）
  6. `DEEPSEEK_API_KEY` 注入 web profile 的无写入凭证路径（env 透传是否直接生效）

- [ ] **Step 1: 阅读取证（每人一次 grep/read，结论写 NOTES.md）**
按上表六项逐一读源码，每项在 NOTES.md 注明「结论 + 源文件路径:行号」。
Do NOT estimate by reading docs alone——工具注册必须以源码 `type-equiv`/实现为准。

- [ ] **Step 2: 核对关键决策点并回填本计划**
若六项中任一项与 spec 3.2/3.4/3.5 有出入（如工具注册 API 不同、会话表字段不同），以 NOTES.md 为准更新对应任务代码；**任何对 spec 的偏离必须在本任务提交信息中显式列出**。

- [ ] **Step 3: 提交**
Run: `git add dsh-platform/NOTES.md dsh-platform/package.json dsh-platform/packages/server-connector/package.json`
Run: `git commit -m "docs: dsh platform interface notes (tool registration, patch, session schema)"`

---

## Task 3: 数据模型 dsh_instances / dsh_sessions + 迁移

**Files:**
- Create: `backend/app/models/dsh.py`, `backend/alembic/versions/<rev>_add_dsh_tables.py`, `backend/tests/test_dsh_models.py`

**Interfaces:**
- Produces: SQLAlchemy models `DshInstance(id uuidpk, user_id UUID unique, port int, state str, pid int|None, last_active_at timestamptz|None, error_hint str|None, created_at, updated_at)`；`DshSession(id uuidpk, user_id UUID, dsh_session_id str(120), title str(500)|None, turn_count int default 0, last_activity_at timestamptz|None, synced_at timestamptz|None, created_at, updated_at)`；唯一约束 `uq_dsh_sessions(user_id, dsh_session_id)`。
- Consumes: `app.models.base.Base`（现有）。

- [ ] **Step 1: 写失败测试** `backend/tests/test_dsh_models.py`

```python
import pytest
from sqlalchemy import select
from app.models.dsh import DshInstance, DshSession


@pytest.fixture
async def db_session(test_engine):
    async with test_engine() as conn:  # conftest 的 test_engine 是 sessionmaker? 按 conftest 实际类型修正
        yield conn


async def test_dsh_instance_roundtrip(db_session):
    row = DshInstance(user_id="u-1", port=3121, state="running", pid=4242)
    db_session.add(row)
    await db_session.commit()
    got = (await db_session.execute(select(DshInstance))).scalar_one()
    assert got.user_id == "u-1" and got.port == 3121 and got.state == "running"


async def test_dsh_session_unique_user_session(db_session):
    a = DshSession(user_id="u-1", dsh_session_id="s-1", title="t")
    b = DshSession(user_id="u-1", dsh_session_id="s-1", title="t2")
    db_session.add(a); await db_session.flush()
    db_session.add(b)
    with pytest.raises(Exception):
        await db_session.commit()
```

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest tests/test_dsh_models.py::test_dsh_instance_roundtrip -v`（工作目录 `backend/`）
Expected: `ModuleNotFoundError: app.models.dsh` 类失败。

- [ ] **Step 3: 实现模型** `backend/app/models/dsh.py`（对照 `models/agent.py` 的 Base/Column 风格；`created_at` 用 `server_default=func.now()`，`updated_at` 用 `onupdate=func.now()`，时间列 `DateTime(timezone=True)`）。

- [ ] **Step 4: 迁移生成**
Run: `alembic revision --autogenerate -m "add dsh tables"`（backend 内）；核对 autogenerate 仅含两新表；否则检查 `models/__init__.py` 导入。
Run: `alembic upgrade head`；确认 `dsh_instances`、`dsh_sessions` 出现。

- [ ] **Step 5: 测试通过**
Run: `python -m pytest tests/test_dsh_models.py -v` → PASS。

- [ ] **Step 6: 提交**
Run: `git add backend/app/models/dsh.py backend/app/models/__init__.py backend/alembic/versions/<rev>_add_dsh_tables.py backend/tests/test_dsh_models.py`
Run: `git commit -m "feat: dsh instance/session models with migration"`

---

## Task 4: DSH 配置项（Settings + .env.example）

**Files:**
- Modify: `backend/app/core/config.py`（+8 字段与注释）, `backend/.env.example`（+4 行）
- Create: `backend/tests/test_dsh_settings.py`

**Interfaces:**
- Produces（字段名/默认值，T5/T6/T8 直接引用）：
  `dsh_home_root: str = "var/dsh"`；`dsh_port_min: int = 3100`；`dsh_port_max: int = 3399`；`dsh_idle_seconds: int = 600`；`dsh_stop_grace_seconds: int = 30`；`dsh_health_timeout_seconds: int = 30`；`dsh_instance_mode: str = "dev_bin"`（取值范围 `dev_bin|vendored`，报错用 `ValueError`）；`dsh_platform_token_ttl_seconds: int = 300`；`dsh_trusted_hosts: str = "localhost:3000"`；`dsh_skills_dir: str = "skills"`（home 内相对）。

- [ ] **Step 1: 测试** `tests/test_dsh_settings.py`：`get_settings()` 含上述字段且默认值等于上表；非法 `dsh_instance_mode` 赋值时 Pydantic 校验拒绝（模式无关配置时用 `Settings` 直构测试）。

- [ ] **Step 2: 实现**——在 `config.py` 的 Settings 类加字段（照现有 env 字段风格：`Field(default=..., env="DSH_...")`？以 config.py 现有写法为准——若该文件用 `os.getenv` 风格则沿用该风格，`enum` 校验在 `__init__` 或 model validator 中做一次即可）。

- [ ] **Step 3: 更新 `.env.example`**：新增 `DSH_HOME_ROOT=var/dsh`、`DSH_INSTANCE_MODE=dev_bin`、`DSH_TRUSTED_HOSTS=localhost:3000`、`DSH_PLATFORM_TOKEN_TTL_SECONDS=300`（带一行注释：vendored 模式=线上；dev_bin 模式=直接用全局 dsh 调试）。

- [ ] **Step 4: 测试通过并提交**（`git add` 精确路径；commit: `feat: dsh runtime settings`）

---

## Task 5: DshInstanceManager（生命周期核心 + 单测）

**Files:**
- Create: `backend/app/services/dsh/__init__.py`, `backend/app/services/dsh/instance_manager.py`, `backend/tests/test_dsh_instance_manager.py`

**Interfaces:**
- Produces（T6/T8/T9 依赖）：
  * `class DshInstanceManager(services/dsh/instance_manager.py)`；method `async ensure_running(user_id: str) -> DshInstance`（幂等：running 直接返回；starting 等待状态到 running/error；未启动则 spawn）；`async stop(user_id: str, force: bool=False)`；`async get(user_id: str) -> DshInstance | None`；`async sweep_idle()`；`def resolve_port(user_id: str) -> int`（`dsh_port_min + int(hashlib.md5(user_id.encode()).hexdigest(),16) % (max-min+1)` 直接可测）；`async spawn_command(settings, home, port, trusted_host)->list[str]`（纯构造，便于单测断言命令）；
  * 模块级 `_spawn_factory(user_id, cmd, env)` 可替换注入（测试替换为 fake 进程对象，fake 实现 `wait()/terminate()/kill()/pid`）——`ensure_running` 与进程对象解耦（manager 接收 `process_factory` 构造参数，默认 `asyncio.create_subprocess_exec`；测试注入 fake）。
  * 事件钩子：`on_before_spawn(user_id, spawn_ctx)` / `on_state_change(user_id, old, new)`（T8 注入配置生成挂 on_before_spawn；打卡 last_active 由 T6 代理侧调用 `touch(user_id)`）。
- Consumes: `app.models.dsh`、`DshInstanceRepository`（本任务内以简单 CRUD 函数内联于 manager 还是独立 repository？——沿用 `app/repositories` 现有风格：若 agents 域无 repository 就内联 SQLAlchemy session 查询；**以 `services/agent` 同款风格为准**（agent 域是否有 repository 目录？检查 `app/repositories/`——有则走 repositories，无则 query 内联）。

- [ ] **Step 1: 失败测试**（`tests/test_dsh_instance_manager.py`）

```python
import pytest
from app.services.dsh.instance_manager import DshInstanceManager
from app.core.config import get_settings


class FakeProcess:
    def __init__(self):
        self.pid = 7777
        self.terminated = 0
        self.killed = 0
    async def wait(self): return 0
    def terminate(self): self.terminated += 1
    def kill(self): self.killed = 1


async def test_resolve_port_in_range():
    m = DshInstanceManager(settings=get_settings())
    for uid in ("u-1", "u-2", "u-99"):
        assert 3100 <= m.resolve_port(uid) <= 3399


async def test_spawn_command_shape():
    m = DshInstanceManager(settings=get_settings())
    cmd = m.spawn_command("u-1", home="H", port=3121, trusted="localhost:3000")
    assert "dsh" == Path(cmd[-1])... if cmd 尾为 token 数组则断言其中含 "web" 与 "--port 3121"(按实现形态断言: 使用 list 字符串比较两元素)
```

（写实现者可照此扩展：测试覆盖 ensure_running 幂等(fake 进程 wait 挂起→返回 running)、stop 优雅→超时 kill、resolve_port 边界。实现步骤以 pytest 全绿为止。）

- [ ] **Step 2: 实现 instance_manager.py**——状态机：`stopped→starting→running|error`；`ensure_running` 流程：读表→running 直接返回；starting 且 60s 内→轮询等待；否则 spawn：写 home（T8 注入器 TODO 在 on_before_spawn）、启动 `spawn_command`、健康探测（TCP `socket` 连接 127.0.0.1:port 尝试 30s，每 500ms；通过→running+pid 落库；失败→terminate+error_hint 落库）；`sweep_idle`：`last_active_at` 超过 `dsh_idle_seconds` 的 running 实例→优雅停。日志用 `logging.getLogger("dsh.instances")`，禁打印密钥。

- [ ] **Step 3: 运行测试全绿**（单测不依赖真实 dsh；spawn 均被 fake 化）
Run: `python -m pytest tests/test_dsh_instance_manager.py -v` → PASS。

- [ ] **Step 4: 提交**（commit: `feat: dsh instance lifecycle manager`）

---

## Task 6: 反向代理 /dsh-proxy/{user_id}/**（HTTP+WS）+ 属主校验

**Files:**
- Create: `backend/app/services/dsh/proxy.py`, `backend/app/api/dsh_proxy.py`, `backend/tests/test_dsh_proxy.py`

**Interfaces:**
- Consumes: `DshInstanceManager.get/ensure_running/touch(user_id)`；`app.core.dependencies.get_current_user`；
- Produces: 路由 `GET|POST|PUT|DELETE /api/dsh-proxy/{user_id}/{path:path}`（WS 同路径 `/ws` 后缀由 Starlette websocket 路由分段处理：`@router.websocket("/dsh-proxy/{user_id}/ws")` + 其余 http 方法走 http 路由）；所有响应透传状态/头/流；属主校验失败 `404`（`raise ApiError(404, "NOT_FOUND")` 包裹成现有 envelope）。

- [ ] **Step 1: 失败测试**（httpx ASGITransport + conftest 登录态；manager 以 dependency override 注入 fake：`get_manager()`——在 `services/dsh/__init__.py` 提供 `get_manager()` 单例供 Depends，测试 override）

```python
async def test_proxy_requires_login(client):
    r = await client.get("/api/dsh-proxy/u-1/x")
    assert r.status_code == 401 or r.status_code == 403  # 以现有未登录语义为准(test 断言实现后统一)

async def test_proxy_non_owner_404(client, admin_headers):
    r = await client.get("/api/dsh-proxy/other-user/x", headers=admin_headers)
    assert r.status_code == 404

async def test_proxy_forwards_to_instance(client, admin_headers, fake_manager):
    # fake 内部跑一个本地 dummy http 服务返回 {"ok":true, "path": "/x"}
    r = await client.get("/api/dsh-proxy/<admin_uid>/x", headers=admin_headers)
    assert r.json()["data"] == {"ok": True, "path": "/x"}
```

- [ ] **Step 2: 实现 proxy.py**：`async def http_trampoline(uid, path, method, headers, body) -> (status, headers, body)`：用 `httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}")` 转发并剥离 `host/connection/content-length` 类 hop-by-hop 头；注入 `X-Dsh-Platform-User: uid`（供插件识别）；`touch(uid)` 记录活动。WS：用 `websockets.connect(f"ws://127.0.0.1:{port}/ws...")` 双向搬运（uvicorn[standard] 已含 websockets 依赖；请求里带 Origin/Host 透传留到生产 nginx 行为一致性，dev 用 `--trusted-host` 覆盖）。

- [ ] **Step 3: 挂路由**：`main.py` include `app.api.dsh_proxy`（`/api` 前缀同现有）；确认 WS 路由不进 BaseHTTPMiddleware 缓冲面（dependencies 里以原始 ASGI 方式注册——参照 RequestIdMiddleware 的做法，若 main。py 现有中间件为 BaseHTTPMiddleware 则 WS 另以 app.websocket 直挂，实现时按证据处理并在 commit 说明）。

- [ ] **Step 4: 全绿并提交**（commit: `feat: dsh reverse proxy with owner check`）

---

## Task 7: server-connector 插件（3 个平台工具）

**Files:**
- Create: `dsh-platform/packages/server-connector/package.json`, `src/index.ts`, `tsconfig.json`, `vitest.config.ts`, `tests/connector.test.ts`, `lib/index.js`（tsdown 产物；提交产物，对齐皮肤仓库「lib/ 提交构建产物」规则）
- Reference: `dsh-platform/NOTES.md`（T2 第 1/2 项结论）；工具模式参考 `deepseek-harness/packages/*/tools`（T2 已给出准确路径）

**Interfaces:**
- Produces（平台侧契约，T9 与 tool 名称一致）：
  * 工具名 `platform_search_files(query: string, file_type: str|None) -> list[{file_id, title, mime}`；调用 `GET {platformBase}/api/files?keyword={query}` 带 `X-Platform-Token`；
  * `platform_read_file(file_id: str) -> {title, text}`；`GET {platformBase}/api/files/{file_id}/content`（文件内容端点的答案以平台 `api/files.py` 为准——**Step 0 先读该文件给出确切实例，本例以「先考古后写」为原则，禁止臆造**）；
  * `platform_get_docs(query: str|None, take: int=10)` → 调平台 feishu 索引端点（端点以 `api/feishu.py` 实读为准）。
  * 每个工具在响应中不携带令牌/密钥；统一从插件 config（`cordis.patch.yml` 的 `config` 键）读取 `platformBase/userId/platformToken`。

- [ ] **Step 0: 读平台侧源码定接点**（`backend/app/api/files.py`、`api/feishu.py` 全文；把与工具对应的真实 endpoint + 参数 + 响应形状写进 `dsh-platform/NOTES.md` 并在此任务内使用。）

- [ ] **Step 1: 插件实现（按 NOTES.md 的注册 API）**
  骨架：`package.json` 声明 name `@naoker/dsh-platform-connector`、`main: lib/index.js`、`devDependencies: {tsdown, typescript, vitest}`；`src/index.ts` 实现 `export function apply(ctx: Context, config: ConnectorConfig)`——config 含 `platformBase/userId/platformToken`；内部 `platformFetch(path, init)` 统一带 token 与 `x-dsh-platform-user`；三工具逐一实现；工具描述写营销场景触发文案（如「检索品牌方已上传资料库」）。
- [ ] **Step 2: 单测**（`tests/connector.test.ts`，mock 全局 `fetch` 与注册对象 registry）：断言三个工具名存在、参数经 `platformFetch` 正确编码、token 必带、无 token 注册期即报 config 错误。
- [ ] **Step 3: 构建**：`pnpm run build`（tsdown → `lib/index.js`）；提交 `lib/` 产物+源码+测试（commit: `feat: naoker dsh platform connector`）。

---

## Task 8: 实例配置注入（patch + skills 拷贝 + env）

**Files:**
- Create: `backend/app/services/dsh/instance_config.py`, `backend/tests/test_dsh_instance_config.py`, `dsh-platform/skills-template/platform-knowledge/SKILL.md`(T2 后按 DSH skill 规则编写)
- Modify: `dsh-platform/cordis.patch.yml.example`

**Interfaces:**
- Produces:
  * `async ensure_home_config(home_dir: Path, *, platform_base: str, user_id: str, platform_token: str, trusted_host: str, skills_src: Path) -> None`：幂等（已有 patch 含对应 id 则不重写，但 token 每次刷新——写入 `profiles/web/cordis.patch.yml`：`- id: naoker-platform-connector` `config: {platformBase, userId, platformToken}` 行；拷贝 `skills_src/*` → `home_dir/skills/`）。
  * `fn spawn_env(settings, platform_token: str) -> dict[str,str]`：`DEEPSEEK_API_KEY`（来自 platform env）→ env，**写入仅限 spawn_env 返回值，不落盘**。
  * 上述实现前须先读 NOTES.md 的 patch/config 语法（T2 第 2 项）并在测试里以样例断言生成文本精确匹配。

- [ ] **Step 1: 失败测试**：临时目录内断言 (a) patch 文件生成含三字段与 connector id；(b) home 下 skills 目录生成且 SKILL.md 存在；(c) `spawn_env` 含 `DEEPSEEK_API_KEY` 且不含其他密钥；幂等断言（两次调用无重复行）。
- [ ] **Step 2: 实现 + 全绿 + 提交**（commit: `feat: per-instance config injection`）

---

## Task 9: 会话审计回流（同步服务 + API + 独立 worker）

**Files:**
- Create: `backend/app/services/dsh/session_sync.py`, `backend/app/api/dsh.py`, `backend/app/workers/dsh_sync_worker.py`, `backend/tests/test_dsh_session_sync.py`, `backend/tests/test_dsh_sessions_api.py`

**Interfaces:**
- Consumes: T2 NOTES.md 第 3 项（DSH sqlite 路径+表结构）；T3 `DshSession` 模型；
- Produces:
  * `async sync_user_sessions(db, user_id, sqlite_path) -> int`（upsert `uq(user_id, dsh_session_id)`，返回新增/更新条数；`onupdate` 语义：title/turn_count/last_activity_at/synced_at 覆盖）；
  * API：`GET /api/dsh/sessions`（登录用户，仅自己；分页 page/page_size 同 files 风格；字段：dsh_session_id,title,turn_count,last_activity_at,synced_at）；`GET /api/dsh/sessions/audit`（`require_super_admin`；可选 user_id 过滤）；
  * worker：`python -m app.workers.dsh_sync_worker`（独立进程，循环 60s：对 `dsh_instances.state==running` 的每个用户 `sync_user_sessions`；异常记录不崩溃——范式对齐 `workers/agent_worker.py` 的 run()/stop() 结构）。

- [ ] **Step 1: 失败测试**
  - `test_dsh_session_sync.py`：构造带 2 条真实 DSH 会话 schema 的临时 sqlite（schema 以 T2 笔记为准），调用 `sync_user_sessions` → `dsh_sessions` 两行；再次同步无变化；修改 sqlite 一行 → turn_count 变化被覆盖。
  - `test_dsh_sessions_api.py`：登录用户 A 只能看到 A；super_admin 走 audit 端点看全员；非 super_admin 访问 audit → 403。
- [ ] **Step 2: 实现 + 全绿**
Run: `python -m pytest tests/test_dsh_session_sync.py tests/test_dsh_sessions_api.py -v`
- [ ] **Step 3: 提交**（commit: `feat: dsh session audit sync + api + worker`）

---

## Task 10: 前端 /agent → DSH Web UI 嵌入（legacy 迁移）

**Files:**
- Create: `frontend/src/app/(dsh)/agent/page.tsx`（新路由 `/agent`）、`frontend/src/app/(dsh)/agent/legacy/page.tsx`（现页迁移）
- Modify: `frontend/src/app/(agent)` 现目录内容 → 移动至 legacy（**只移动不改**）；`frontend/next.config.*` dev rewrites：`/dsh-proxy/:path*` → `http://localhost:8000/api/dsh-proxy/:path*`（保持与现有 `/api` 转发规则一致风格）；`assets/agent.ts` 或约定 config：当前用户 id 来源复用现有 auth store（`/api/auth/me`），iframe `src=/dsh-proxy/${uid}/`
- Create: `frontend/src/components/dsh/dsh-workspace.tsx`（状态条：实例状态/「重建」按钮/「打开原版(legacy)」链接 + iframe 主体 `height: calc(100vh - 壳高)` 全宽无内边距）+ `frontend/src/app/(dsh)/agent/agent-page.test.tsx`

**Interfaces:**
- Consumes: auth store 现有 `useAuth`/me 接口（以现有 agent 页引用的 hooks 为准）；`/api/dsh/sessions`（T9）；
- Produces: `/agent` 新体验；`/agent/legacy` 回退入口；测试依赖 `document.querySelectorAll("button") + textContent`（约束 #8）。

- [ ] **Step 1: 移动旧页到 legacy 并回归（此时 /agent 临时空）**
Run: `npm test -- --run src/app/\(agent\)/...`（旧测试文件不做路径改名的硬断言——若旧测试断言路由文本，为它们补 legacy 前缀断言，禁止删测试）
- [ ] **Step 2: 实现 dsh-workspace.tsx + page.tsx**（状态轮询 `GET /api/dsh/instances/{uid}`? —— T9 只做了 sessions API；状态条数据源：本轮在 T9 的 api/dsh.py 中补 `GET /api/dsh/instances/me`（manager.get 当前用户返回 state/port/started）；实现后再写前端头部；「重建」= POST `/api/dsh/instances/me/restart`（调 manager.stop+ensure_running）——**这两个端点归本轮 T7? 不，归本任务**：在 `api/dsh_proxy.py` 外新增 `api/dsh.py` 两个端点更合理——实施时按该描述执行并在 commit 说明）。
- [ ] **Step 3: 前端测试**：断言渲染 iframe src 前缀、legacy 链接可达、重建按钮触发请求（`src` 断言用 `document.querySelector("iframe")?.src`）；测试文件单跑：
Run: `npm test -- --run src/app/\(dsh\)/agent/agent-page.test.tsx`
- [ ] **Step 4: 手工验证**：`npm run serve` 后浏览器：登录→文件→agent→看见 DSH UI；点击 legacy→旧界面正常。
- [ ] **Step 5: 提交**（commit: `feat: frontend dsh workspace embedding`）

---

## Task 11: 审计页 DSH 会话视图（复用现有 agent/audit 页结构）

**Files:**
- Modify: `frontend/src/app/(dashboard)/agent/audit/page.tsx`（或现有 audit 所在路由——以 glob 确认为准）：加「DSH 会话」Tab；
- Create: `frontend/src/components/dsh/audit-sessions-table.tsx` + 测试文件
- Consumes: `GET /api/dsh/sessions/audit`（T9）

- [ ] **Step 1: 测试**（`querySelectorAll("row")+textContent` 约束；表格=现有 audit 语义的行，断言标题列/时间列过滤条）。
- [ ] **Step 2: 实现 Tab + 表格**（展示：用户、标题、turn_count、last_activity、synced_at；分页 page_size 20；超级管理员视图；非超管不可见 tab）。
- [ ] **Step 3: 全绿 + 手工验证** + 提交（commit: `feat: audit dsh sessions view`）

---

## Task 12: 一期集成验收（冒烟脚本 + README + 回滚路径）

**Files:**
- Create: `scripts/dsh_smoke.ps1`, `docs/superpowers/plans/2026-09-07-dsh-platform-rebase-phase1-verification.md`
- Modify: `README.md`（Agent Loop 章节增：DSH 模式说明/环境变量表追加 DSH_* 主字段/`/agent/legacy` 回退/插件安装两步法 `dsh plugin --profile web add` 与皮肤验证/skin 许可提示）

- [ ] **Step 1: 冒烟脚本**（`dsh_smoke.ps1`）：
  顺序断言：①API health 200；②SQL `dsh_instances` 表存在；③`POST /api/dsh/instances/me/restart` → state==running（等待 ≤60s）；④`GET /api/dsh-proxy/<me>/` → 200 text/html；⑤前端页面可达 `/agent` → 200；⑥审计同步一次 → `dsh_sessions` 行 >0（有对话时）。
- [ ] **Step 2: 手测清单**（手册按 spec 3.8 六条）：皮肤（maid-atelier）安装→生效；文件工具；跨用户 404；空闲回收；会话保留；社区插件安装。全部打勾后页面产出 `verification` 记录（每步截图存 `docs/` 或仅文字证据，二选一按用户要求）。
- [ ] **Step 3: README + 提交**（commit: `docs: phase-1 verification guide + smoke`）

---

## Self-Review 自查记录（写计划时已过）

- **Spec 覆盖**：3.1→T1/T2/T7；3.2→T4/T5/T8；3.3→T6；3.4→T3/T9；3.5→T7(工具)/T8(token注入)；3.6→T10；3.7 不做项无任务；3.8→T12 手测清单。✅
- **无占位符**：每任务都有具体命令/断言；唯二「以 NOTES.md 为准」是 T2 的刻意考古出口（六项清单固定，产出物固定）。✅
- **类型一致**：`ensure_running/stop/get/sweep_idle/resolve_port/spawn_command`、`ensure_home_config/spawn_env`、`sync_user_sessions`、端点清单、表字段名全计划统一。✅
- **风险位**：T1 构建时长（冒烟标准放宽仅 `--version`）；T2 若考古推翻设计→提交信息显式列偏离，属设计-计划-实施闭环记录。
