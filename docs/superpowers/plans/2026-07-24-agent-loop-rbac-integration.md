# Agent Loop 与 RBAC 生产级集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `X:\01_agent_loop` 的 Agent Loop 能力以可水平扩展、可审计、按用户隔离且支持私有附件的方式整合到 `X:\01_RBAC`。

**Architecture:** `X:\01_RBAC` 的 FastAPI API 是唯一认证、授权与资源编排边界；独立 Worker 使用 PostgreSQL 原子领取和租约执行持久化 attempt。保留 Agent Loop 的 Planner、DeepSeek/Tavily 工具、事件格式、流式 reducer 和组件行为，将旧的匿名表、进程内领取、内嵌附件和裸 JSON API 替换为 RBAC 适配层。

**Tech Stack:** FastAPI、SQLAlchemy 2 async、Alembic、PostgreSQL 16、httpx、Pydantic Settings、Next.js 16、React 19、Ant Design 6、TypeScript、Vitest、pytest。

## Global Constraints

- `X:\01_RBAC` 是唯一交付仓库；不得迁移 `X:\01_agent_loop` 的历史数据库或维持其旧 `/runs` API 兼容层。
- 优先直接迁移 `X:\01_agent_loop` 的领域逻辑、工具安全校验、SSE 协议、reducer、typing 和测试语义；仅在 RBAC、安全、可靠性或附件边界处最小适配。
- Agent 表全部使用 UUID、`agent_` 前缀及 PostgreSQL 外键；不创建通用 `sessions`、`runs`、`steps` 或 `run_events` 表。
- 所有 Agent JSON API 使用既有 `{ data, message, request_id }` 信封；SSE 是唯一的 `text/event-stream` 例外。
- 所有用户资源由服务端 `current_user.id` 授权；跨用户和不存在资源统一返回 `404`；仅活动、未删除的 `super_admin` 可跨用户只读审计。
- API 与 Worker 独立部署。使用 PostgreSQL 原子领取、租约和持久事件；不引入 Redis、RabbitMQ、Celery，也不在 FastAPI `lifespan` 启动 Worker。
- 附件以私有对象存储和 `agent_attachments` 管理；禁止将文件内容、完整 prompt、模型原文、密钥或未脱敏工具载荷写入应用日志、事件 payload 或默认审计响应。
- 运行、attempt、步骤和事件保留 180 天；附件原文件与提取文本保留 90 天。
- 前端复用既有 Ant Design Provider 和 CSS tokens，不引入近似新色值；Markdown 不渲染原始 HTML。
- 每个任务先写失败测试、运行确认失败、最小实现、运行目标测试和相关回归测试，再创建单用途提交。不得暂存或回退工作区已有的无关修改。

---

## Planned File Structure

| 路径 | 责任 | 来源/复用方式 |
|---|---|---|
| `backend/app/models/agent.py` | 全部 Agent ORM 模型、约束、关系和索引 | 结构性迁移 `X:\01_agent_loop\backend\app\models\*.py` |
| `backend/app/schemas/agent.py` | 用户/审计 API、分页、事件和附件 Pydantic 合约 | 适配旧 `schemas/*.py` |
| `backend/app/repositories/agent_repository.py` | 所有权查询、事务内状态迁移、事件持久化、队列领取 | 重构 `repositories/run_repository.py`，移除内部 commit |
| `backend/app/services/agent/loop.py` | Planner、工具、步骤与流式事件编排 | 迁移并适配 `services/agent_loop.py` |
| `backend/app/services/agent/{llm,planner,tool_executor,event_bus}.py` | LLM、规划、工具安全、进程内唤醒 | 高度复用对应 Agent Loop 文件 |
| `backend/app/services/agent/{worker,storage,attachments,retention}.py` | 独立 Worker、存储、附件生命周期、留存清理 | 新增边界适配；Worker 复用旧调度循环思路 |
| `backend/app/api/{agent,agent_stream,agent_audit}.py` | 用户 REST、SSE、只读审计路由 | 拆分/适配 `api/runs.py` 和 `api/stream.py` |
| `backend/app/workers/agent_worker.py` | 独立 Worker 命令入口 | 新增，调用 `AgentWorker` |
| `backend/tests/test_agent_*.py` | Agent 数据、API、Worker、SSE、附件、留存安全测试 | 迁移 Agent Loop 测试语义并新增 RBAC 集成测试 |
| `frontend/src/types/agent.ts` | Agent API、事件、附件和分页 TypeScript 类型 | 迁移 `frontend/lib/api.ts` 中类型 |
| `frontend/src/lib/{agent-api,agent-stream}.ts` | 信封 API 调用、SSE URL、事件解析和状态常量 | 复用旧 API 工具，改为现有 `api<T>()` |
| `frontend/src/lib/run-stream-reducer.ts` | 流式事件幂等 reducer | 直接迁移 `lib/runStreamReducer.ts`，只调整 import/type |
| `frontend/src/hooks/{use-run-event-stream,use-typing-text}.ts` | 有界 SSE 重连和 typing | 迁移对应 Agent Loop hooks |
| `frontend/src/components/agent/*` | Composer、附件、会话流、思考、最终答案、审计视图 | 最大化迁移旧组件，使用 Ant Design 外壳 |
| `frontend/src/app/(agent)/*` | 仅登录可访问的 Agent 路由组 | 新增，复用 `DashboardShell` |
| `frontend/src/app/(dashboard)/*` | 保持用户/角色页面权限边界 | 最小调整 layout 或拆分其 shell |
| `frontend/src/**/*.test.{ts,tsx}` | 迁移的流式行为、路由、导航、API 与 UI 测试 | 从 Jest 转为 Vitest |
| `.env.example`、`README.md` | Worker、存储、SSE、配置和运维说明 | 扩展现有文档 |

### Task 1: Agent 数据基座、配置与 Alembic 迁移

**Files:**
- Create: `backend/app/models/agent.py`
- Create: `backend/app/schemas/agent.py`
- Create: `backend/alembic/versions/<revision>_agent_foundation.py`
- Create: `backend/tests/test_agent_models.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/alembic/env.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `.env.example`
- Modify: `backend/tests/conftest.py`
- Reference: `X:\01_agent_loop\backend\app\models\{session,run,step,event}.py`
- Reference: `X:\01_agent_loop\backend\app\core\config.py`

**Interfaces:**
- Produces ORM models `AgentSession`, `AgentRun`, `AgentRunAttempt`, `AgentStep`, `AgentRunEvent`, `AgentAttachment`, `AgentRunAttachment`, `AgentRetentionJob`.
- Produces enums/literals `AgentRunStatus`, `AgentAttemptStatus`, `AgentMode`, `AgentAttachmentStatus` and settings fields consumed by Tasks 2-7.
- Produces Alembic schema that creates namespaced tables from the current RBAC head.

- [ ] **Step 1: Write schema and metadata failure tests**

```python
# backend/tests/test_agent_models.py
async def test_agent_run_owner_must_match_its_session(session, seeded_user):
    owned = AgentSession(owner_user_id=seeded_user.id, title="会话")
    other = User(username="other", display_name="Other", password_hash="x")
    session.add_all([owned, other])
    await session.flush()
    session.add(AgentRun(session_id=owned.id, owner_user_id=other.id, goal="x", mode="quick"))
    with pytest.raises(IntegrityError):
        await session.flush()

async def test_agent_models_are_registered_in_base_metadata():
    assert {"agent_sessions", "agent_runs", "agent_run_attempts", "agent_run_events"} <= set(Base.metadata.tables)
```

- [ ] **Step 2: Run the model test to prove the models do not exist yet**

Run: `python -m pytest tests/test_agent_models.py -v` from `X:\01_RBAC\backend`  
Expected: collection/import failure for `AgentSession` and missing Agent tables.

- [ ] **Step 3: Create the namespaced ORM model contract**

```python
# backend/app/models/agent.py (key contract)
class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (UniqueConstraint("id", "owner_user_id", name="uq_agent_sessions_id_owner"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(["session_id", "owner_user_id"], ["agent_sessions.id", "agent_sessions.owner_user_id"]),
        CheckConstraint("status IN ('queued','running','retry_wait','succeeded','failed','cancel_requested','cancelled')"),
        CheckConstraint("max_steps > 0 AND max_steps <= 200"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    goal: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16), default="quick")
    network_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    current_attempt_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
```

Implement the remaining models with the exact table/index contract from the approved specification: attempt number unique per run; step number unique per attempt; event `seq` generated by a PostgreSQL sequence and indexed as `(run_id, seq)`; attachment metadata and run attachment association; retention job audit fields. Reuse the old `Run`/`Step`/`RunEvent` field semantics where they remain meaningful, but do not carry over old string IDs, generic names, `metadata_json` attachment content, or cascade deletion of audit history.

- [ ] **Step 4: Add settings and ensure metadata discovery**

```python
# backend/app/core/config.py additions
worker_concurrency: int = 3
worker_poll_interval_seconds: float = 1.0
worker_lease_seconds: int = 60
worker_shutdown_grace_seconds: int = 30
http_timeout_seconds: float = 25.0
step_timeout_seconds: float = 30.0
run_timeout_seconds: float = 120.0
retry_backoff_base_seconds: float = 2.0
retry_backoff_max_seconds: float = 30.0
max_retry_attempts: int = 3
deepseek_api_key: str | None = None
deepseek_base_url: str = "https://api.deepseek.com"
deepseek_model: str = "deepseek-chat"
tavily_api_key: str | None = None
tavily_base_url: str = "https://api.tavily.com"
agent_storage_root: str = "./var/agent"
agent_attachment_max_bytes: int = 2_000_000
agent_attachment_max_count: int = 5
agent_attachment_retention_days: int = 90
agent_run_retention_days: int = 180
```

Import all Agent models in both `backend/alembic/env.py` and `backend/tests/conftest.py` before accessing `Base.metadata`. Add non-secret example values and exact environment variable documentation to both environment templates.

- [ ] **Step 5: Generate and review a migration from the current head**

Run: `alembic revision --autogenerate -m "agent foundation"` from `X:\01_RBAC\backend`  
Expected: one revision whose `down_revision` is the current RBAC head and whose upgrade creates only `agent_*` tables, sequence, constraints and indexes.

Replace generated ambiguous names with stable names such as `fk_agent_runs_session_owner`, `uq_agent_run_attempts_run_number`, `ix_agent_run_events_run_seq`, and add an explicit downgrade that drops Agent tables and the event sequence only.

- [ ] **Step 6: Verify migration and ORM behavior**

Run: `alembic upgrade head; python -m pytest tests/test_agent_models.py tests/test_alembic_config.py -v`  
Expected: migrations apply and all selected tests pass.

- [ ] **Step 7: Commit the foundation**

```bash
git add backend/app/models/agent.py backend/app/schemas/agent.py backend/app/models/__init__.py backend/app/core/config.py backend/alembic/env.py backend/alembic/versions backend/tests/conftest.py backend/tests/test_agent_models.py .env.example backend/.env.example
git commit -m "feat: add agent persistence foundation"
```

### Task 2: RBAC Agent authorization, CSRF and owned-resource dependencies

**Files:**
- Create: `backend/app/core/csrf.py`
- Create: `backend/tests/test_agent_authorization.py`
- Modify: `backend/app/core/dependencies.py`
- Modify: `backend/app/api/auth.py`
- Modify: `backend/app/main.py`
- Reference: `backend/app/core/dependencies.py`
- Reference: `backend/app/api/auth.py`

**Interfaces:**
- Consumes: `AgentSession`, `AgentRun`, `AgentAttachment` from Task 1.
- Produces `require_super_admin`, `get_owned_agent_session`, `get_owned_agent_run`, `get_owned_agent_attachment`, `require_csrf`, and `issue_csrf_token`.
- Later API routes must depend on these functions rather than manually comparing ownership.

- [ ] **Step 1: Write failing role, ownership and CSRF tests**

```python
async def test_non_owner_and_missing_agent_runs_are_indistinguishable(client, another_users_run_id):
    response = await client.get(f"/api/agent/runs/{another_users_run_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"

async def test_only_active_super_admin_can_open_audit(client, deactivate_super_admin_role):
    response = await client.get("/api/agent/audit/sessions")
    assert response.status_code == 403

async def test_agent_mutation_requires_matching_csrf_header(client, owned_session_id):
    response = await client.post(f"/api/agent/sessions/{owned_session_id}/runs", json={"goal": "x"})
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_VALIDATION_FAILED"
```

- [ ] **Step 2: Run authorization tests to confirm red state**

Run: `python -m pytest tests/test_agent_authorization.py -v`  
Expected: route/import failures because Agent ownership and CSRF dependencies are absent.

- [ ] **Step 3: Implement dependencies using single ownership-filtered queries**

```python
# backend/app/core/dependencies.py signatures
async def require_super_admin(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User: ...

async def get_owned_agent_session(
    session_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> AgentSession: ...

async def get_owned_agent_run(
    run_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> AgentRun: ...
```

`require_super_admin` must join `UserRole` and `Role`, require `Role.code == "super_admin"`, `Role.status == "active"`, and `Role.is_deleted.is_(False)`. Each owned-resource dependency must query with both identifier and `owner_user_id == current_user.id`, then raise the existing `ApiError` 404 shape if no row exists. Do not first fetch and then compare.

- [ ] **Step 4: Add Origin and CSRF validation**

```python
# backend/app/core/csrf.py contract
CSRF_HEADER = "X-CSRF-Token"

def issue_csrf_token() -> str: ...

async def require_csrf(request: Request, current_user: User = Depends(get_current_user)) -> User:
    """Require an exact allowed Origin/Referer and a matching HttpOnly-session-bound CSRF token."""
```

Expose `GET /api/auth/csrf` to return the token using the normal success envelope. Bind its signed token to the authenticated user ID and an expiration. Add `X-CSRF-Token` to CORS `allow_headers`; do not weaken the existing exact configured origin list. Apply `require_csrf` only to POST/PUT/PATCH/DELETE Agent routes in Tasks 4 and 6, not to GET/SSE.

- [ ] **Step 5: Verify selected authorization behavior**

Run: `python -m pytest tests/test_agent_authorization.py tests/test_auth_api.py tests/test_rbac_end_to_end.py -v`  
Expected: all selected tests pass, including immediate revocation after role disable/deletion.

- [ ] **Step 6: Commit authorization primitives**

```bash
git add backend/app/core/csrf.py backend/app/core/dependencies.py backend/app/api/auth.py backend/app/main.py backend/tests/test_agent_authorization.py
git commit -m "feat: add agent ownership and csrf guards"
```

### Task 3: Transactional Agent repository, immutable attempts and durable event publisher

**Files:**
- Create: `backend/app/repositories/agent_repository.py`
- Create: `backend/app/services/agent/__init__.py`
- Create: `backend/app/services/agent/event_bus.py`
- Create: `backend/tests/test_agent_repository.py`
- Reference: `X:\01_agent_loop\backend\app\repositories\run_repository.py`
- Reference: `X:\01_agent_loop\backend\app\services\event_bus.py`

**Interfaces:**
- Consumes Task 1 models and Task 2 ownership helpers.
- Produces `AgentRepository`, `PersistedEvent`, `AgentEventBus`, and transaction-owned methods used by all API/Worker tasks.
- `AgentRepository` must never call `commit()`; callers own `async with db.begin()` / `await db.commit()`.

- [ ] **Step 1: Write red tests for atomic run creation, retry history and event ordering**

```python
async def test_create_run_creates_first_attempt_and_queued_event_in_one_transaction(session, owned_session):
    repo = AgentRepository(session)
    run, attempt, event = await repo.create_run_with_attempt(owned_session, "分析季度报告", "quick", True, [])
    await session.flush()
    assert attempt.run_id == run.id
    assert event.event_type == "run_queued"
    assert event.attempt_id == attempt.id

async def test_retry_creates_an_immutable_new_attempt(session, terminal_run):
    repo = AgentRepository(session)
    retry = await repo.create_retry_attempt(terminal_run)
    assert retry.attempt_number == 2
    assert retry.retry_of_attempt_id == terminal_run.current_attempt_id
    assert await repo.list_attempts(terminal_run.id)
```

- [ ] **Step 2: Run repository tests to establish failure**

Run: `python -m pytest tests/test_agent_repository.py -v`  
Expected: import failure for `AgentRepository`.

- [ ] **Step 3: Port query intent from `RunRepository` without its per-method commits**

```python
# backend/app/repositories/agent_repository.py public surface
class AgentRepository:
    async def create_session(self, owner_user_id: UUID, title: str | None) -> AgentSession: ...
    async def get_owned_session(self, session_id: UUID, owner_user_id: UUID) -> AgentSession | None: ...
    async def list_owned_sessions(self, owner_user_id: UUID, page: int, page_size: int) -> Page[AgentSession]: ...
    async def create_run_with_attempt(self, session: AgentSession, goal: str, mode: str, network_enabled: bool, attachment_ids: list[UUID]) -> tuple[AgentRun, AgentRunAttempt, AgentRunEvent]: ...
    async def create_retry_attempt(self, run: AgentRun) -> AgentRunAttempt: ...
    async def append_event(self, run: AgentRun, attempt: AgentRunAttempt | None, event_type: str, payload: dict[str, Any]) -> AgentRunEvent: ...
    async def list_events_after_seq(self, run_id: UUID, after_seq: int | None, limit: int) -> list[AgentRunEvent]: ...
```

For each state change, use an update predicate that permits only legal source states and append its event before the transaction commits. Preserve useful query behavior from the old repository: session history ordered by creation, events ordered by seq, and step ordering. Do not port `retry_run()` deletion, in-memory status mutation followed by commit, or the old attachment `metadata_json` model.

- [ ] **Step 4: Implement commit-after-persistence event notification**

```python
# backend/app/services/agent/event_bus.py
@dataclass(frozen=True)
class PersistedEvent:
    run_id: UUID
    seq: int

class AgentEventBus:
    async def publish_after_commit(self, event: PersistedEvent) -> None: ...
    async def subscribe(self, run_id: UUID) -> tuple[str, asyncio.Queue[PersistedEvent]]: ...
    async def unsubscribe(self, run_id: UUID, subscriber_id: str) -> None: ...
```

Reuse the bounded local subscriber queue design from the original `EventBus`; publish only after the enclosing database transaction completes. Add PostgreSQL `NOTIFY agent_run_events, '<run_id>'` after persistence and a listener abstraction that can wake local streams. The stream in Task 5 must still query the event table, so a lost wakeup cannot lose data.

- [ ] **Step 5: Verify repository transaction semantics**

Run: `python -m pytest tests/test_agent_repository.py -v`  
Expected: all tests pass; test output must show no deleted original attempt/events on retry.

- [ ] **Step 6: Commit the repository and event boundary**

```bash
git add backend/app/repositories/agent_repository.py backend/app/services/agent/__init__.py backend/app/services/agent/event_bus.py backend/tests/test_agent_repository.py
git commit -m "feat: add transactional agent repository"
```

### Task 4: User Agent REST API and standard response contracts

**Files:**
- Create: `backend/app/api/agent.py`
- Create: `backend/tests/test_agent_api.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/agent.py`
- Reference: `X:\01_agent_loop\backend\app\api\runs.py`
- Reference: `backend/app/api/users.py`

**Interfaces:**
- Consumes `AgentRepository` and authorization/CSRF dependencies from Tasks 2-3.
- Produces `/api/agent/sessions`, `/api/agent/sessions/{id}`, `/api/agent/sessions/{id}/runs`, `/api/agent/runs/*` JSON endpoints.
- Task 8 frontend calls these endpoints through `agent-api.ts`.

- [ ] **Step 1: Write API contract tests against the RBAC envelope**

```python
async def test_create_session_and_run_returns_enveloped_owned_resources(authenticated_client, csrf_headers):
    session_response = await authenticated_client.post("/api/agent/sessions", json={"title": "报告"}, headers=csrf_headers)
    assert session_response.status_code == 201
    session_id = session_response.json()["data"]["id"]
    run_response = await authenticated_client.post(
        f"/api/agent/sessions/{session_id}/runs",
        json={"goal": "总结数据", "mode": "quick", "network_enabled": True, "attachment_ids": []},
        headers=csrf_headers,
    )
    assert run_response.status_code == 201
    assert run_response.json()["data"]["status"] == "queued"
    assert "request_id" in run_response.json()
```

- [ ] **Step 2: Run the user API test in red**

Run: `python -m pytest tests/test_agent_api.py -v`  
Expected: `404` or import failure because `/api/agent` is not registered.

- [ ] **Step 3: Implement routes by adapting old `api/runs.py` responsibilities**

```python
# backend/app/api/agent.py route signatures
@router.post("/sessions", status_code=201)
async def create_session(request: Request, data: AgentSessionCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_csrf)): ...

@router.post("/sessions/{session_id}/runs", status_code=201)
async def create_run(session_obj: AgentSession = Depends(get_owned_agent_session), ...): ...

@router.post("/runs/{run_id}/cancel")
async def request_cancel(run: AgentRun = Depends(get_owned_agent_run), ...): ...

@router.post("/runs/{run_id}/retry", status_code=201)
async def retry_run(run: AgentRun = Depends(get_owned_agent_run), ...): ...
```

Register the router in `main.py` with prefix `/api/agent`. Adapt the old create/session/list/detail/cancel/retry routes to repository methods and `success(request, data)`. List endpoints must take bounded `page` and `page_size`; event and step endpoints take `after_seq`/page parameters. Cancel only transitions nonterminal runs to `cancel_requested`; retry only accepts a terminal logical run and creates an attempt, returning `409` for invalid transition. Do not allow callers to submit owner IDs, session IDs outside the nested route, storage keys, attempts, or raw attachment content.

- [ ] **Step 4: Verify contracts and existing API regression**

Run: `python -m pytest tests/test_agent_api.py tests/test_contracts.py tests/test_request_id.py -v`  
Expected: all selected tests pass with envelope and request ID checks.

- [ ] **Step 5: Commit the user API**

```bash
git add backend/app/api/agent.py backend/app/main.py backend/app/schemas/agent.py backend/tests/test_agent_api.py
git commit -m "feat: add owned agent api"
```

### Task 5: Directly reused Agent execution services and distributed Worker lifecycle

**Files:**
- Create: `backend/app/services/agent/{llm,planner,tool_executor,loop,worker}.py`
- Create: `backend/app/workers/__init__.py`
- Create: `backend/app/workers/agent_worker.py`
- Create: `backend/tests/test_agent_worker.py`
- Modify: `backend/requirements.txt` only if an imported Agent Loop dependency is absent
- Reference: `X:\01_agent_loop\backend\app\services\{llm,planner,tool_executor,agent_loop,background_worker}.py`
- Reference: `X:\01_agent_loop\backend\app\services\event_bus.py`

**Interfaces:**
- Consumes the repository from Task 3 and config from Task 1.
- Produces `AgentLoopService.process_attempt(attempt_id, worker_id)`, `AgentWorker.run()`, and CLI `python -m app.workers.agent_worker`.
- Task 5 does not expose HTTP routes; Tasks 4 and 6 enqueue/read the state it maintains.

- [ ] **Step 1: Copy reusable services before changing behavior**

Copy these files into `backend/app/services/agent/` with imports redirected from the old Agent Loop packages to `app.services.agent` and `app.core.config.get_settings()`:

```text
X:\01_agent_loop\backend\app\services\llm.py           -> backend/app/services/agent/llm.py
X:\01_agent_loop\backend\app\services\planner.py       -> backend/app/services/agent/planner.py
X:\01_agent_loop\backend\app\services\tool_executor.py -> backend/app/services/agent/tool_executor.py
```

Retain DeepSeek structured planner behavior, Tavily integration, allowed action validation, public-IP/DNS checks, redirect revalidation, method restriction and calculator semantics. Do not copy old `app.db.session.Base`, standalone settings singleton, or unbounded HTTP response behavior.

- [ ] **Step 2: Write red tests for one-time claim, lease recovery and cancel race**

```python
async def test_only_one_worker_claims_a_queued_attempt(test_db, queued_attempt):
    async with test_db() as first, test_db() as second:
        first_claim, second_claim = await asyncio.gather(
            AgentRepository(first).claim_next_attempt("worker-a"),
            AgentRepository(second).claim_next_attempt("worker-b"),
        )
    assert [claim is not None for claim in (first_claim, second_claim)].count(True) == 1

async def test_expired_lease_creates_recovery_attempt(session, claimed_attempt):
    recovered = await AgentRepository(session).recover_expired_attempts(now=claimed_attempt.lease_expires_at + timedelta(seconds=1))
    assert recovered == 1
```

- [ ] **Step 3: Run the worker test to prove distributed behavior is absent**

Run: `python -m pytest tests/test_agent_worker.py -v`  
Expected: import failure for `AgentWorker` / `claim_next_attempt`.

- [ ] **Step 4: Adapt the Agent Loop orchestration around attempts and repository transactions**

```python
# backend/app/services/agent/loop.py public contract
class AgentLoopService:
    async def process_attempt(self, attempt_id: UUID, worker_id: str) -> None:
        """Execute only a valid leased attempt and append durable events after each state transition."""

    async def close(self) -> None:
        await self.llm_client.close()
```

Move the following behavior from old `AgentLoopService` intact where possible: `_run_policy`, `_sanitize_action`, URL/observation sanitization, visible-thought fallback, `_stream_visible_thought_with_tool_interleave`, `_stream_final_answer`, message construction, Planner call, tool execution and event names/payloads. Replace `run_id` with `(run, attempt)` context, old `_active_runs` locking with database leases, old repository commits with one transaction per state/step/event boundary, and old inline `metadata_json["attachments"]` with a repository query that returns bounded, ready attachment extracted text keyed by the run's persisted attachment associations. Task 7 moves that query behind `AttachmentService` without changing the loop contract.

At every LLM chunk/tool boundary call `repository.is_cancel_requested(run.id)`. Treat cancellation as cooperative: write `run_cancelled` only through a conditional terminal transition. Persist events before notifying `AgentEventBus`. Enforce run timeout, step timeout and old exponential retry policy by creating a new retry attempt instead of changing/deleting the original attempt.

- [ ] **Step 5: Implement independent Worker startup and shutdown**

```python
# backend/app/services/agent/worker.py public contract
class AgentWorker:
    def __init__(self, worker_id: str, concurrency: int) -> None: ...
    async def run(self) -> None: ...
    async def stop(self) -> None: ...

# backend/app/workers/agent_worker.py
async def main() -> None:
    worker = AgentWorker(worker_id=f"{socket.gethostname()}:{os.getpid()}", concurrency=get_settings().worker_concurrency)
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
```

Reuse the original `BackgroundRunWorker` semaphore and poll-loop shape. Replace `pop_schedulable_runs()` with transactionally locked `claim_next_attempt()`, periodically renew `lease_expires_at`, and call `recover_expired_attempts()` before new claims. Signal handling must stop new claims, wait up to `worker_shutdown_grace_seconds`, release/expire unfinished leases safely, close the shared LLM client, then dispose the engine. Never instantiate the Worker from FastAPI lifespan.

- [ ] **Step 6: Port Agent Loop service tests and add response limits**

Copy and adapt `X:\01_agent_loop\backend\tests\test_agent_tools.py`, `test_llm_streaming.py`, and `test_event_streaming.py` into the new `backend/tests/test_agent_*.py` modules. Add a tool test that rejects body length exceeding the configured maximum after every redirect.

- [ ] **Step 7: Verify Worker and original domain behavior**

Run: `python -m pytest tests/test_agent_worker.py tests/test_agent_tools.py tests/test_agent_loop.py -v`  
Expected: exactly one claim succeeds, expired leases recover, cancellation preserves legal terminal state, and ported tool/stream tests pass.

- [ ] **Step 8: Commit reusable execution and Worker implementation**

```bash
git add backend/app/services/agent backend/app/workers backend/tests/test_agent_worker.py backend/tests/test_agent_tools.py backend/tests/test_agent_loop.py backend/requirements.txt
git commit -m "feat: add durable agent worker"
```

### Task 6: SSE replay, connection authorization and audit-only read API

**Files:**
- Create: `backend/app/api/agent_stream.py`
- Create: `backend/app/api/agent_audit.py`
- Create: `backend/tests/test_agent_stream.py`
- Create: `backend/tests/test_agent_audit.py`
- Modify: `backend/app/main.py`
- Reference: `X:\01_agent_loop\backend\app\api\stream.py`

**Interfaces:**
- Consumes repository and `AgentEventBus` from Task 3, ownership/role dependencies from Task 2.
- Produces authenticated `GET /api/agent/runs/{run_id}/stream` and all `GET /api/agent/audit/*` routes.
- Frontend Task 8 consumes the exact SSE event protocol.

- [ ] **Step 1: Write failing SSE replay/security and audit pagination tests**

```python
async def test_sse_replays_only_owned_events_after_last_event_id(authenticated_client, owned_run_with_events):
    response = await authenticated_client.get(
        f"/api/agent/runs/{owned_run_with_events.id}/stream",
        headers={"Last-Event-ID": "2", "Origin": "http://test"},
    )
    assert response.status_code == 200
    assert b"id: 3" in response.content

async def test_foreign_sse_is_404_before_stream_body(other_client, owned_run_with_events):
    response = await other_client.get(f"/api/agent/runs/{owned_run_with_events.id}/stream")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")

async def test_audit_events_are_paginated_and_redacted(super_admin_client, foreign_run_with_sensitive_event):
    response = await super_admin_client.get(f"/api/agent/audit/runs/{foreign_run_with_sensitive_event.id}/events?page_size=1")
    payload = response.json()["data"]
    assert len(payload["items"]) == 1
    assert "attachment_content" not in payload["items"][0]["payload"]
```

- [ ] **Step 2: Run stream/audit tests in red**

Run: `python -m pytest tests/test_agent_stream.py tests/test_agent_audit.py -v`  
Expected: route failures because the stream and audit routers are absent.

- [ ] **Step 3: Reuse and narrow the existing stream protocol**

```python
# backend/app/api/agent_stream.py key signatures
def parse_after_seq(value: str | None) -> int | None: ...
def encode_sse_event(event: AgentRunEvent) -> str: ...

@router.get("/runs/{run_id}/stream")
async def stream_run_events(
    request: Request, run: AgentRun = Depends(get_owned_agent_run)
) -> StreamingResponse: ...
```

Copy the original `_parse_after_seq`, `_encode_sse_event`, replay, subscribe, catch-up, heartbeat, terminal-final-catch-up and unsubscribe flow from `api/stream.py`. Replace the dependency-scoped repository captured by the generator with a small `async_session_factory()` read session for each replay/status query. Use 15-second heartbeat, `Cache-Control: no-store, no-transform`, `X-Accel-Buffering: no`, and event IDs equal to `seq`. Validate Origin before returning `StreamingResponse`. On an invalid cursor return the RBAC `ApiError` 400 before streaming.

- [ ] **Step 4: Implement bounded, redacted audit reads**

```python
# backend/app/api/agent_audit.py route set
GET /sessions
GET /sessions/{session_id}
GET /runs/{run_id}
GET /runs/{run_id}/attempts/{attempt_id}/steps
GET /runs/{run_id}/events
```

Every route depends on `require_super_admin`; every collection is paginated with `page >= 1` and `1 <= page_size <= 100`. Create a schema function `to_audit_event(event: AgentRunEvent) -> AgentAuditEvent` that strips attachment text, credential-like keys, raw prompts and raw model/tool content before serializing. Do not add audit download routes or SSE.

- [ ] **Step 5: Verify SSE and audit behavior**

Run: `python -m pytest tests/test_agent_stream.py tests/test_agent_audit.py tests/test_agent_authorization.py -v`  
Expected: replay ordering, final catch-up, 404 resource hiding, no leaked payload content, and admin-only audit all pass.

- [ ] **Step 6: Commit realtime and audit routes**

```bash
git add backend/app/api/agent_stream.py backend/app/api/agent_audit.py backend/app/main.py backend/tests/test_agent_stream.py backend/tests/test_agent_audit.py
git commit -m "feat: add agent streaming and audit api"
```

### Task 7: Private attachment storage, extraction and retention maintenance

**Files:**
- Create: `backend/app/services/agent/storage.py`
- Create: `backend/app/services/agent/attachments.py`
- Create: `backend/app/services/agent/retention.py`
- Create: `backend/app/api/agent_attachments.py`
- Create: `backend/app/workers/agent_maintenance.py`
- Create: `backend/tests/test_agent_attachments.py`
- Create: `backend/tests/test_agent_retention.py`
- Modify: `backend/app/api/agent.py`
- Modify: `backend/app/main.py`
- Reference: `X:\01_agent_loop\backend\app\schemas\run.py`
- Reference: `X:\01_agent_loop\backend\app\services\agent_loop.py:630-672`

**Interfaces:**
- Consumes `AgentAttachment` and `AgentRepository` from Tasks 1 and 3.
- Produces upload/list/download/delete endpoints and `AttachmentService.read_prompt_context(attachment_ids)` for Task 5.
- Produces independent maintenance CLI for 90/180-day deletion.

- [ ] **Step 1: Write failing private-file and lifecycle tests**

```python
async def test_upload_uses_opaque_storage_key_and_never_exposes_source_filename(client, csrf_headers, owned_session_id):
    response = await client.post(
        f"/api/agent/sessions/{owned_session_id}/attachments",
        files={"file": ("../../secrets.txt", b"public report", "text/plain")},
        headers=csrf_headers,
    )
    attachment = response.json()["data"]
    assert "storage_key" not in attachment
    assert ".." not in attachment["filename"]

async def test_foreign_attachment_download_is_404(other_client, owned_attachment_id):
    assert (await other_client.get(f"/api/agent/attachments/{owned_attachment_id}/download")).status_code == 404

async def test_retention_deletes_expired_attachment_before_metadata(session, storage, expired_attachment):
    result = await RetentionService(session=session, storage=storage, batch_size=10).run_once(
        now=expired_attachment.expires_at + timedelta(days=1)
    )
    assert result.deleted_attachments == 1
```

- [ ] **Step 2: Run attachment and retention tests in red**

Run: `python -m pytest tests/test_agent_attachments.py tests/test_agent_retention.py -v`  
Expected: import/route failure because private attachment services do not exist.

- [ ] **Step 3: Implement a private filesystem storage adapter**

```python
# backend/app/services/agent/storage.py
class PrivateObjectStorage:
    async def put(self, key: str, content: AsyncIterator[bytes]) -> int: ...
    async def open(self, key: str) -> AsyncIterator[bytes]: ...
    async def delete(self, key: str) -> None: ...

def build_attachment_key(attachment_id: UUID) -> str:
    return f"attachments/{attachment_id.hex}"
```

The initial adapter may use `agent_storage_root`, but it must resolve and validate paths below that root, never use user filenames in keys, and never register a static mount. Stream reads/writes, calculate SHA-256, enforce configured byte/count limits, allow only a documented text/PDF MIME allowlist after content sniffing, reject archives/executables, and normalize the display filename.

- [ ] **Step 4: Implement upload pipeline and run references**

```python
# backend/app/services/agent/attachments.py
class AttachmentService:
    async def upload(self, owner_user_id: UUID, session: AgentSession, upload: UploadFile) -> AgentAttachment: ...
    async def read_prompt_context(self, attachments: list[AgentAttachment]) -> list[dict[str, str]]: ...
    async def delete_if_unreferenced(self, attachment: AgentAttachment) -> None: ...
```

Persist `pending_scan`, write to temporary private key, run the configured scanner/extractor adapter, cap extracted text length, then atomically promote to `ready` or mark `rejected`. The initial scanner implementation must fail closed if scanning is configured but unavailable. `read_prompt_context` returns only bounded extracted text wrapped with an explicit untrusted-data label. Extend Task 4 run creation to validate that every attachment is `ready`, owned by the user, and belongs to the nested session before inserting `agent_run_attachments`.

- [ ] **Step 5: Add attachment routes and maintenance command**

Implement `POST/GET /sessions/{session_id}/attachments`, `GET /attachments/{attachment_id}/download`, and `DELETE /attachments/{attachment_id}` using Task 2 ownership/CSRF dependencies and `StreamingResponse` for download. Create `python -m app.workers.agent_maintenance` to run daily retention: attachments/extracted text at 90 days; events, steps, attempts and runs at 180 days in small locked batches; sessions only when unreferenced. Record every execution in `agent_retention_jobs` without retaining deleted business content.

- [ ] **Step 6: Verify safety and retention**

Run: `python -m pytest tests/test_agent_attachments.py tests/test_agent_retention.py tests/test_agent_api.py -v`  
Expected: authorization, traversal, MIME spoofing, size/count limits, scan/extract/storage failures, active-run deletion rejection, and retention ordering all pass.

- [ ] **Step 7: Commit private attachments and maintenance**

```bash
git add backend/app/services/agent/storage.py backend/app/services/agent/attachments.py backend/app/services/agent/retention.py backend/app/api/agent_attachments.py backend/app/api/agent.py backend/app/main.py backend/app/workers/agent_maintenance.py backend/tests/test_agent_attachments.py backend/tests/test_agent_retention.py
git commit -m "feat: add private agent attachments"
```

### Task 8: Frontend Agent type/API layer and direct stream reducer migration

**Files:**
- Create: `frontend/src/types/agent.ts`
- Create: `frontend/src/lib/agent-api.ts`
- Create: `frontend/src/lib/agent-stream.ts`
- Create: `frontend/src/lib/run-stream-reducer.ts`
- Create: `frontend/src/lib/run-stream-reducer.test.ts`
- Create: `frontend/src/lib/agent-api.test.ts`
- Modify: `frontend/src/lib/api.ts`
- Reference: `X:\01_agent_loop\frontend\lib\api.ts`
- Reference: `X:\01_agent_loop\frontend\lib\runStreamReducer.ts`
- Reference: `X:\01_agent_loop\frontend\lib\runStreamReducer.test.ts`

**Interfaces:**
- Produces `AgentRun`, `AgentAttempt`, `AgentRunEvent`, `AgentAttachment`, `agentApi`, `streamUrlWithSeq`, `parseStreamEvent`, `reduceRunStream`.
- Tasks 9-10 use these interfaces; preserve event names, sequence dedupe and `stream_id`/`offset` semantics.

- [ ] **Step 1: Copy the old reducer test and change only imports/types**

Copy `X:\01_agent_loop\frontend\lib\runStreamReducer.test.ts` to `frontend/src/lib/run-stream-reducer.test.ts`. Replace the old import path with `@/lib/run-stream-reducer` and fixtures with `AgentRun`/`AgentRunEvent`. Add this assertion for the renamed terminal status:

```ts
expect(reduceRunStream(state, completedEvent).run?.status).toBe("succeeded");
```

- [ ] **Step 2: Run the reducer test in red**

Run: `npm test -- --run src/lib/run-stream-reducer.test.ts` from `X:\01_RBAC\frontend`  
Expected: module-not-found for `@/lib/run-stream-reducer`.

- [ ] **Step 3: Directly migrate the reducer and define target API types**

Copy the implementation of `X:\01_agent_loop\frontend\lib\runStreamReducer.ts` into `frontend/src/lib/run-stream-reducer.ts`. Replace only the old `@/lib/api` imports and map legacy `completed` status/event handling to `succeeded`/`run_succeeded`; preserve sorting, duplicate `seq` rejection, checkpoint behavior, stream ID verification and offset mismatch reconnection behavior.

```ts
// frontend/src/types/agent.ts essential contract
export type AgentRunStatus = "queued" | "running" | "retry_wait" | "succeeded" | "failed" | "cancel_requested" | "cancelled";
export type AgentRun = { id: string; session_id: string; goal: string; status: AgentRunStatus; mode: "quick" | "expert"; network_enabled: boolean; current_attempt_id: string | null; created_at: string; updated_at: string; };
export type AgentRunEvent = { id: string; run_id: string; attempt_id: string | null; seq: number; event_type: AgentStreamEventType; payload: Record<string, unknown>; created_at: string; };
```

- [ ] **Step 4: Implement API and stream adapters over the existing envelope client**

```ts
// frontend/src/lib/agent-api.ts
export const agentApi = {
  createSession: (title?: string) => api<AgentSession>("/api/agent/sessions", { method: "POST", body: JSON.stringify({ title }) }),
  createRun: (sessionId: string, body: CreateAgentRun) => api<AgentRun>(`/api/agent/sessions/${sessionId}/runs`, { method: "POST", body: JSON.stringify(body) }),
  cancelRun: (runId: string) => api<AgentRun>(`/api/agent/runs/${runId}/cancel`, { method: "POST" }),
};

// frontend/src/lib/agent-stream.ts
export function streamUrlWithSeq(runId: string, afterSeq: number): string {
  const params = afterSeq > 0 ? `?after_seq=${afterSeq}` : "";
  return `/api/agent/runs/${runId}/stream${params}`;
}
```

Extend `api<T>()` with an optional `csrf: true` flag that gets `/api/auth/csrf`, adds `X-CSRF-Token`, and never sets JSON `Content-Type` for `FormData`. Use it for all Agent mutations. Keep `credentials: "include"`, request ID propagation and `ApiError` behavior. Do not create a second fetch client or retain the old `NEXT_PUBLIC_API_BASE_URL` EventSource cross-origin behavior.

- [ ] **Step 5: Verify migrated reducer and envelope adapters**

Run: `npm test -- --run src/lib/run-stream-reducer.test.ts src/lib/agent-api.test.ts`  
Expected: copied reducer behavior and new envelope/CSRF/FormData tests pass.

- [ ] **Step 6: Commit the frontend data boundary**

```bash
git add frontend/src/types/agent.ts frontend/src/lib/api.ts frontend/src/lib/agent-api.ts frontend/src/lib/agent-stream.ts frontend/src/lib/run-stream-reducer.ts frontend/src/lib/run-stream-reducer.test.ts frontend/src/lib/agent-api.test.ts
git commit -m "feat: add agent frontend data layer"
```

### Task 9: SSE hook, typing hook and Agent Loop component migration

**Files:**
- Create: `frontend/src/hooks/use-run-event-stream.ts`
- Create: `frontend/src/hooks/use-typing-text.ts`
- Create: `frontend/src/components/agent/{new-conversation-composer,session-conversation-stream,thought-narrative,final-answer-panel,agent-mode-controls,attachment-input}.tsx`
- Create: `frontend/src/components/agent/agent-streaming.test.tsx`
- Create: `frontend/src/hooks/use-run-event-stream.test.ts`
- Modify: `frontend/package.json`
- Reference: `X:\01_agent_loop\frontend\hooks\{useRunEventStream,useTypingText}.ts`
- Reference: `X:\01_agent_loop\frontend\components\{NewConversationComposer,SessionConversationStream,ThoughtNarrative,FinalAnswerPanel,AgentModeControls,AttachmentInput,ComposerForm,SubmitTextarea}.tsx`
- Reference: `X:\01_agent_loop\frontend\components\streamingUi.test.tsx`

**Interfaces:**
- Consumes Task 8 stream and API contracts.
- Produces `<NewConversationComposer>`, `<SessionConversationStream>`, `useRunEventStream` and attachment selection callbacks used by Task 10 pages.

- [ ] **Step 1: Port stream behavior tests before the hook**

Copy Agent Loop `useRunEventStream` test cases into `frontend/src/hooks/use-run-event-stream.test.ts`. Use a mock `EventSource` and assert these production requirements:

```ts
expect(MockEventSource.urls.at(-1)).toBe("/api/agent/runs/run-1/stream?after_seq=7");
expect(reconnectDelays).toEqual([1000, 2000, 4000, 5000, 5000]);
expect(state.connection).toBe("closed"); // terminal event
expect(mock.close).toHaveBeenCalledTimes(1); // 404/410/protocol error
```

- [ ] **Step 2: Run the hook test in red**

Run: `npm test -- --run src/hooks/use-run-event-stream.test.ts`  
Expected: module-not-found for the new hook.

- [ ] **Step 3: Migrate `useRunEventStream` with bounded reconnect behavior**

Copy `X:\01_agent_loop\frontend\hooks\useRunEventStream.ts` and redirect imports to Task 8 modules. Preserve reset behavior, state ref, EventSource listener registration, reducer use and `after_seq` reconnect. Change terminal statuses to `succeeded`, `failed`, `cancelled`; cap retry delay at 5 seconds and cap attempts at 8. Treat parsed API errors `401`, `403`, `404`, `410` and malformed JSON as `failed`/closed rather than reconnecting forever. Open EventSource only for a current nonterminal attempt.

- [ ] **Step 4: Port components with Ant Design shells, not a behavioral rewrite**

Copy the listed Agent Loop components into `frontend/src/components/agent/`. Preserve their mode selection, enter-to-send, file selection, visible thought, step timeline and final-answer presentation behavior. Replace old custom outer layout/forms/buttons with `Card`, `Form`, `Input.TextArea`, `Upload`, `Button`, `Segmented`, `Tag`, `Alert`, `Spin` and existing CSS variables. `AttachmentInput` must upload via Task 8 `agentApi` first, then pass returned attachment IDs to run creation; it must not call `File.text()` or build `{ name, media_type, content }`.

For `FinalAnswerPanel`, add `react-markdown` and `remark-gfm` only if the direct migrated component needs them. Configure `skipHtml` and an external-link renderer with `target="_blank"` and `rel="noreferrer noopener"`. Preserve the Agent Loop content hierarchy; do not replace it with a generic chat bubble.

- [ ] **Step 5: Port typing and streaming UI tests into Vitest**

Copy the relevant behavior from `useTypingText.test.ts`, `streamingUi.test.tsx`, `NewConversationComposer.test.tsx`, and `AgentModeControls.test.tsx`. Verify component behavior for uploading-ready/rejected files, cancel/retry controls, empty/loading/error states, streamed thought/answer text and safe Markdown links.

- [ ] **Step 6: Verify hooks and components**

Run: `npm test -- --run src/hooks/use-run-event-stream.test.ts src/components/agent/agent-streaming.test.tsx`  
Expected: reconnection, terminal close, component migration and attachment-ID behavior pass.

- [ ] **Step 7: Commit migrated frontend Agent behavior**

```bash
git add frontend/src/hooks frontend/src/components/agent frontend/package.json frontend/package-lock.json
git commit -m "feat: migrate agent streaming components"
```

### Task 10: Agent routes, authenticated shell, navigation and administrator audit UI

**Files:**
- Create: `frontend/src/app/(agent)/layout.tsx`
- Create: `frontend/src/app/(agent)/agent/page.tsx`
- Create: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`
- Create: `frontend/src/app/(agent)/agent/audit/page.tsx`
- Create: `frontend/src/app/(agent)/agent/audit/sessions/[sessionId]/page.tsx`
- Create: `frontend/src/app/(agent)/agent/audit/runs/[runId]/page.tsx`
- Create: `frontend/src/components/auth/authenticated-page.tsx`
- Create: `frontend/src/lib/roles.ts`
- Create: `frontend/src/app/(agent)/agent/agent-routes.test.tsx`
- Modify: `frontend/src/components/layout/app-sidebar.tsx`
- Modify: `frontend/src/components/auth/login-form.tsx`
- Modify: `frontend/src/lib/copy.ts`
- Modify: `frontend/src/app/(dashboard)/layout.tsx` only if required to preserve existing page access
- Reference: `X:\01_agent_loop\frontend\app\sessions\page.tsx`
- Reference: `X:\01_agent_loop\frontend\app\sessions\[id]\page.tsx`
- Reference: `frontend/src/components/layout/dashboard-shell.tsx`

**Interfaces:**
- Consumes Task 8 API layer and Task 9 components.
- Produces login-required Agent pages for all users and role-gated audit pages.
- Preserves existing `/users` and `/roles` permission behavior.

- [ ] **Step 1: Write route and sidebar red tests**

```tsx
it("renders Agent navigation for any authenticated user but audit only for super_admin", async () => {
  render(<AppSidebar user={ordinaryUser} />);
  expect(screen.getByRole("link", { name: "智能助手" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Agent 运行审计" })).not.toBeInTheDocument();
});

it("allows ordinary users into /agent without USER_READ", async () => {
  render(<AgentLayout>{<div>assistant</div>}</AgentLayout>);
  expect(await screen.findByText("assistant")).toBeVisible();
});
```

- [ ] **Step 2: Run route tests in red**

Run: `npm test -- --run src/app/(agent)/agent/agent-routes.test.tsx`  
Expected: missing Agent layout and navigation entries.

- [ ] **Step 3: Add login-only and super-admin page guards**

```tsx
// frontend/src/components/auth/authenticated-page.tsx
export default function AuthenticatedPage({ children }: { children: (user: CurrentUser) => ReactNode }) {
  // fetchCurrentUser; redirect only 401 to /login; render children for every authenticated user
}

// frontend/src/lib/roles.ts
export function isSuperAdmin(user: CurrentUser): boolean {
  return user.roles.some((role) => role.code === "super_admin");
}
```

Create `(agent)/layout.tsx` that uses `AuthenticatedPage` plus existing `DashboardShell`; do not reuse `(dashboard)/layout.tsx`, because it is globally wrapped with `USER_READ`. Preserve `ProtectedPage` and permission checks for `/users` and `/roles`. Audit pages should display a friendly forbidden state for non-super-admin users while the server remains authoritative.

- [ ] **Step 4: Adapt existing session pages with minimal logic changes**

Base `/agent` on old `app/sessions/page.tsx`: use Task 9 composer to create a session then a run, call `router.push(`/agent/sessions/${session.id}`)`, and list only the current user’s sessions. Base `/agent/sessions/[sessionId]` on old detail page: load session/run summaries with Task 8 API, render historical terminal turns from REST, and attach `useRunEventStream` to only the latest active run. Keep mode controls, composition flow and Chinese labels from Agent Loop; remove server actions, `AppShell`, old `/sessions` links and raw text-file attachment conversion.

Build audit list/detail views from Task 8 audit endpoints with paginated Ant Design Table/Descriptions and redacted event/step summaries. Never instantiate an `EventSource` in audit pages.

- [ ] **Step 5: Extend sidebar, copy and login redirect**

```tsx
// app-sidebar selection rule
const selectedKey = pathname.startsWith("/agent/audit")
  ? "/agent/audit"
  : pathname.startsWith("/agent")
    ? "/agent"
    : pathname;
```

Add an “智能助手” item for all authenticated users and “Agent 运行审计” only for `isSuperAdmin(user)`. Retain permission-based “用户管理” and “角色管理” items. Add all Chinese copy keys to `copy.ts`. Change login completion to fetch current user and route `super_admin` to a valid callback or `/users`, and others to a valid callback or `/agent`; reject callback paths not beginning with `/` or beginning with `//`.

- [ ] **Step 6: Verify navigation and existing dashboard regression**

Run: `npm test -- --run src/app/(agent)/agent/agent-routes.test.tsx src/components/layout/dashboard-shell.test.tsx src/components/auth/login-form.test.tsx; npm run build`  
Expected: Agent route tests and prior layout/login tests pass; Next production build exits 0.

- [ ] **Step 7: Commit routes and navigation**

```bash
git add frontend/src/app/(agent) frontend/src/components/auth/authenticated-page.tsx frontend/src/components/layout/app-sidebar.tsx frontend/src/lib/roles.ts frontend/src/lib/copy.ts frontend/src/components/auth/login-form.tsx frontend/src/app/(dashboard)/layout.tsx
git commit -m "feat: add agent workspace and audit views"
```

### Task 11: Deployment documentation, operational checks and full quality gate

**Files:**
- Create: `backend/tests/test_agent_migration_e2e.py`
- Create: `backend/tests/test_agent_security_e2e.py`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Modify: `docs/superpowers/specs/2026-07-24-agent-loop-integration-design.md` only if implementation forces an approved design correction

**Interfaces:**
- Consumes all prior tasks.
- Produces operator documentation for API, Worker, storage, SSE proxy and maintenance processes, plus end-to-end verification evidence.

- [ ] **Step 1: Write end-to-end red tests for deployment-critical flows**

```python
async def test_migration_from_rbac_head_creates_agent_schema_and_api_can_enqueue(admin_client, csrf_headers):
    session_response = await admin_client.post("/api/agent/sessions", json={"title": "迁移验证"}, headers=csrf_headers)
    assert session_response.status_code == 201
    run_response = await admin_client.post(
        f"/api/agent/sessions/{session_response.json()['data']['id']}/runs",
        json={"goal": "验证已入队", "mode": "quick", "network_enabled": False, "attachment_ids": []},
        headers=csrf_headers,
    )
    assert run_response.status_code == 201
    assert run_response.json()["data"]["status"] == "queued"

async def test_cross_user_end_to_end_boundary_covers_rest_sse_and_attachments(owner_client, other_client, owner_run, owner_attachment):
    assert (await other_client.get(f"/api/agent/runs/{owner_run.id}")).status_code == 404
    assert (await other_client.get(f"/api/agent/runs/{owner_run.id}/stream")).status_code == 404
    assert (await other_client.get(f"/api/agent/attachments/{owner_attachment.id}/download")).status_code == 404
```

- [ ] **Step 2: Run the end-to-end tests before final hardening**

Run: `python -m pytest tests/test_agent_migration_e2e.py tests/test_agent_security_e2e.py -v`  
Expected: identify any unregistered route, missing migration model import, missing CSRF header, cross-user leak, or storage cleanup gap.

- [ ] **Step 3: Document exact development and production operations**

Add this operational contract to `README.md`:

```powershell
# API
cd X:\01_RBAC\backend
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Independent Agent Worker
cd X:\01_RBAC\backend
python -m app.workers.agent_worker

# Daily retention maintenance (schedule once per day)
cd X:\01_RBAC\backend
python -m app.workers.agent_maintenance
```

Document all Agent environment variables, required private storage permissions, antivirus/extractor configuration, no-secret logging policy, reverse-proxy requirements `proxy_buffering off`/suitable SSE idle timeout, HTTPS `Secure` cookies, backup strategy, Worker scale-out behavior, lease recovery and retention guarantees. State explicitly that API replicas do not execute runs and that all public frontend/API requests should be same-origin through the Next.js proxy.

- [ ] **Step 4: Run complete backend verification**

Run: `python -m pytest -v` from `X:\01_RBAC\backend`  
Expected: all existing RBAC and new Agent tests pass with zero failures.

- [ ] **Step 5: Run complete frontend verification**

Run: `npm test -- --run` from `X:\01_RBAC\frontend`  
Expected: all Vitest suites pass with zero failures.

Run: `npm run build` from `X:\01_RBAC\frontend`  
Expected: Next.js production build exits 0.

- [ ] **Step 6: Verify repository state and migration cleanliness**

Run: `alembic current -v; alembic upgrade head; git diff --check; git status --short` from `X:\01_RBAC\backend`  
Expected: Alembic is at the Agent migration head, no whitespace errors, and only intentional Task 11 files remain unstaged/staged.

- [ ] **Step 7: Commit operations and quality gate**

```bash
git add README.md .env.example backend/.env.example backend/tests/test_agent_migration_e2e.py backend/tests/test_agent_security_e2e.py
git commit -m "docs: document agent operations"
```

## Plan Self-Review

### Spec coverage

| Approved requirement | Implementing tasks |
|---|---|
| Namespaced UUID schema, owner composite FK, attempts, events, retention records | Tasks 1 and 3 |
| Existing roles preserved; owner-only access; super-admin audit; CSRF/Origin | Task 2 and Tasks 4, 6, 7 |
| Agent JSON envelope and API matrix | Task 4 and Task 7 |
| Independent atomic-claim Worker, lease recovery, immutable retries/cancel | Task 5 |
| Durable SSE replay, seq/offset idempotence, short DB sessions | Tasks 3, 6, 8, 9 |
| Formal private upload, scanning/extraction, prompt isolation, 90-day deletion | Task 7 |
| 180-day Agent retention and observability/operations | Tasks 7 and 11 |
| Maximum Agent Loop code reuse | Tasks 3, 5, 6, 8, 9, 10 explicitly identify source modules |
| Login-only Agent routes, role-aware navigation, existing RBAC preservation | Task 10 |
| Backend/frontend/security/migration acceptance tests | Tasks 1-11, final full gate in Task 11 |

### Placeholder scan

The plan contains no unresolved implementation placeholders. `<revision>` in the Alembic filename is intentionally generated by Alembic and is constrained in Task 1 to use the current migration head. Every operational or code step defines its command, target behavior, or interface.

### Type consistency

- `AgentRun` uses terminal status `succeeded`; the frontend reducer explicitly maps migrated legacy completed events to this state.
- Ownership dependencies return `AgentSession`, `AgentRun`, or `AgentAttachment`; user, stream and attachment routes consume the same dependencies.
- `AgentRepository` owns database writes but never transaction commits; API/Worker callers own transactions and publish only after commit.
- Frontend stream names `streamUrlWithSeq`, `parseStreamEvent`, `AgentRunEvent`, `reduceRunStream`, and `useRunEventStream` are introduced in Tasks 8-9 before Task 10 consumes them.
