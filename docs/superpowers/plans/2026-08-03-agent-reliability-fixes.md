# Agent 可靠性修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复系统分析中确认的 6 个高优先级缺陷：可见思考流式异常导致 run 静默终止、审计事件接口返回 null、Worker 进程未挂接 RedisBridge、取消未认领 run 永久卡死、recover/reconcile 并发竞态、SSE 终态补齐丢事件。

**Architecture:** 全部改动集中在后端 5 个文件（loop.py、agent_audit.py、agent_repository.py、agent_stream.py 及入口文件 main.py / agent_worker.py），每个修复独立可测。不改数据模型、不加新依赖。

**Tech Stack:** Python 3.11+（代码使用 `datetime.UTC`）、FastAPI、SQLAlchemy 2.0 async、asyncpg、PostgreSQL、pytest（`asyncio_mode=auto`，无需 anyio 标记）。

## Global Constraints

- 所有命令在 `backend/` 目录下执行（`workdir: C:\01_agent_loop_pro\backend`）。
- 测试需要本地 PostgreSQL（conftest 会连 `postgres` 库并自动创建 `rbac_test`，见 README.md:11-30）；测试前先确认 Postgres 在运行。
- 测试命令：`python -m pytest tests/<文件> -q`；失败时加 `-x --tb=short` 看详情。
- 不加任何新依赖（requirements.txt 不改）。
- 提交信息遵循仓库现有风格（`fix: ...` / `feat: ...`，见 git log）。
- 每个任务结束必须提交，禁止跨任务堆积改动。
- `loop.py` 的模块级单例 `agent_loop_service` 与 `redis_bridge` 是跨测试共享的全局状态，测试中改动后必须恢复（用 try/finally 或 monkeypatch 自动还原）。

## File Structure

| 文件 | 任务 | 职责 |
|---|---|---|
| `backend/app/services/agent/loop.py` | T1, T3 | 流式异常重抛 + 空观察改抛错；新增 `init_redis_bridge`/`shutdown_redis_bridge` |
| `backend/app/api/agent_audit.py` | T2 | `list_audit_events` 补 return |
| `backend/app/main.py` | T3 | lifespan 改用共享的 bridge 初始化函数 |
| `backend/app/workers/agent_worker.py` | T3 | Worker 入口挂接 RedisBridge（只发布不订阅） |
| `backend/app/repositories/agent_repository.py` | T4, T5 | `cancel_queued_run` 新增；recover 加行锁、reconcile 修正 |
| `backend/app/api/agent.py` | T4 | cancel 端点对 queued/retry_wait 立即终态 |
| `backend/app/api/agent_stream.py` | T6 | 终态补齐改为分页循环 |
| `backend/tests/test_agent_loop.py` | T1 | 新增 2 个静默终止回归测试 |
| `backend/tests/test_redis_bridge.py` | T3 | 新增 3 个 bridge 初始化测试 |
| `backend/tests/test_agent_api.py` | T4 | 更新 `test_cancel_queued_run` 断言 |
| `backend/tests/test_agent_repository.py` | T4 | 新增 `cancel_queued_run` 仓库测试 |
| `backend/tests/test_reconcile_completed_agent_runs.py` | T5 | 新增 attempt 不匹配跳过测试 |
| `backend/tests/test_agent_worker.py` | T5 | 新增并发恢复测试 |
| `backend/tests/test_agent_stream.py` | T6 | 新增终态分页补齐测试 |

任务之间无代码依赖，按 T1→T6 顺序执行（先难后易验证收益最大的）。

---

### Task 1: 可见思考流式异常不再静默终止（P0-3）

**Files:**
- Modify: `backend/app/services/agent/loop.py:589-610`（except 块）
- Modify: `backend/app/services/agent/loop.py:1448-1457`（调用方 None 处理）
- Test: `backend/tests/test_agent_loop.py`（文件末尾追加新测试类）

**Interfaces:**
- Consumes: `RetryableStreamingError`（loop.py:27 已导入）、`httpx`（loop.py:12 已导入）、`RetryablePlannerError`（loop.py:26 已导入）、`_schedule_retryable_failure(repo, ctx, exc) -> bool`（loop.py:395 已有）、`test_db` fixture（conftest.py:86，session factory）
- Produces: 无新公共 API。行为变化：非 finish 动作的可见思考流式失败（`RetryableStreamingError`/`asyncio.TimeoutError`/`httpx.HTTPError`）改为向上抛，由调用方 `_do_process_attempt` 的重试分支（1450）处理；`_stream_visible_thought_with_tool_interleave` 返回 `(text, None)` 时调用方抛 `RetryablePlannerError`。

**背景（必读）:** 当前 loop.py:589-610 的 `except Exception:` 把可见思考的流式异常全部吞掉，非 finish 动作返回 `(text, None)`；而 loop.py:1448-1449 对 `None` 直接 `return`——run 无任何终态事件地卡在 running，直到 60s 租约过期才被恢复。`list_files`/`read_file` 的 input 模型全部字段可空（planner.py:40-53），LLM 产出 `"input": {}` 时能通过 `_validate_plan`（planner.py:262），使 loop.py:650-663 的 None 路径真实可达。

- [ ] **Step 1: 写失败测试（追加到 `tests/test_agent_loop.py` 末尾）**

```python
class TestVisibleThoughtFailureHandling:
    async def test_visible_thought_stream_failure_schedules_retry(
        self, test_db, monkeypatch
    ):
        import uuid as _uuid

        import app.services.agent.loop as loop_module
        from argon2 import PasswordHasher
        from sqlalchemy import select as sa_select

        from app.models.agent import AgentRun, AgentRunAttempt, AgentSession
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository
        from app.services.agent.llm import RetryableStreamingError
        from app.services.agent.loop import AgentLoopService

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"vtuser_{_uuid.uuid4().hex[:8]}",
                display_name="VT User",
                password_hash=ph.hash("Password123"),
                status="active",
            )
            s.add(user)
            await s.flush()
            agent_session = AgentSession(owner_user_id=user.id, title="vt")
            s.add(agent_session)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                agent_session, "visible thought failure test", "quick", True, []
            )
            attempt.status = "running"
            attempt.worker_id = "worker-test"
            s.add(attempt)
            await s.commit()
            run_id = run.id

        class RaisingClient:
            async def stream_text(self, messages):
                raise RetryableStreamingError("deepseek_timeout")

        service = AgentLoopService()
        service.llm_client = RaisingClient()

        async def fake_merged(*args, **kwargs):
            return (
                {
                    "thought_summary": "先搜索",
                    "action": {"type": "web_search", "input": {"query": "q"}},
                },
                None,
            )

        monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)
        monkeypatch.setattr(
            loop_module, "should_try_direct_answer", lambda *a, **k: False
        )

        await service.process_attempt(run_id, "worker-test")

        async with test_db() as s:
            run = await s.get(AgentRun, run_id)
            assert run.status == "retry_wait"
            attempts = (
                await s.execute(
                    sa_select(AgentRunAttempt)
                    .where(AgentRunAttempt.run_id == run_id)
                    .order_by(AgentRunAttempt.attempt_number)
                )
            ).scalars().all()
            assert len(attempts) == 2
            assert attempts[0].status == "failed"
            assert attempts[1].status == "queued"
            assert attempts[1].attempt_number == 2

    async def test_empty_tool_input_schedules_retry_not_silent_stop(
        self, test_db, monkeypatch
    ):
        import uuid as _uuid

        import app.services.agent.loop as loop_module
        from argon2 import PasswordHasher
        from sqlalchemy import select as sa_select

        from app.models.agent import AgentRun, AgentRunAttempt, AgentSession
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository
        from app.services.agent.loop import AgentLoopService

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"etuser_{_uuid.uuid4().hex[:8]}",
                display_name="ET User",
                password_hash=ph.hash("Password123"),
                status="active",
            )
            s.add(user)
            await s.flush()
            agent_session = AgentSession(owner_user_id=user.id, title="et")
            s.add(agent_session)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                agent_session, "empty tool input test", "quick", True, []
            )
            attempt.status = "running"
            attempt.worker_id = "worker-test"
            s.add(attempt)
            await s.commit()
            run_id = run.id

        class FakeClient:
            async def stream_text(self, messages):
                yield "我会先查看文件列表"

        service = AgentLoopService()
        service.llm_client = FakeClient()

        async def fake_merged(*args, **kwargs):
            return (
                {
                    "thought_summary": "查看文件",
                    "action": {"type": "list_files", "input": {}},
                },
                None,
            )

        monkeypatch.setattr(service, "_stream_merged_plan_thought", fake_merged)
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)
        monkeypatch.setattr(
            loop_module, "should_try_direct_answer", lambda *a, **k: False
        )

        await service.process_attempt(run_id, "worker-test")

        async with test_db() as s:
            run = await s.get(AgentRun, run_id)
            assert run.status == "retry_wait"
            attempts = (
                await s.execute(
                    sa_select(AgentRunAttempt)
                    .where(AgentRunAttempt.run_id == run_id)
                    .order_by(AgentRunAttempt.attempt_number)
                )
            ).scalars().all()
            assert len(attempts) == 2
            assert attempts[0].status == "failed"
            assert attempts[1].status == "queued"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agent_loop.py -k TestVisibleThoughtFailureHandling -x -q`
Expected: 两个测试均失败（第一个：run 状态停在 `running`，断言 `== "retry_wait"` 失败；第二个：同理）。

- [ ] **Step 3: 实现修改 1（loop.py:589-610 的 except 块）**

原代码：
```python
            except Exception:
                if not emitted_any_chunk:
```
改为（其余行不变）：
```python
            except (RetryableStreamingError, asyncio.TimeoutError, httpx.HTTPError):
                if validated_action_type != "finish":
                    raise
                if not emitted_any_chunk:
```

- [ ] **Step 4: 实现修改 2（loop.py:1448-1457 调用方）**

原代码：
```python
                if observation_or_answer is None:
                    return
            except (RetryableToolError, RetryableStreamingError, asyncio.TimeoutError) as exc:
```
改为：
```python
                if observation_or_answer is None:
                    raise RetryablePlannerError(
                        f"action produced no observation: {action.get('type')}"
                    )
            except (RetryableToolError, RetryableStreamingError, RetryablePlannerError, asyncio.TimeoutError) as exc:
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_agent_loop.py -k TestVisibleThoughtFailureHandling -q`
Expected: 2 passed

- [ ] **Step 6: 回归整个 loop 测试文件**

Run: `python -m pytest tests/test_agent_loop.py -q`
Expected: 全部通过（无新增失败）

- [ ] **Step 7: 提交**

```bash
git add app/services/agent/loop.py tests/test_agent_loop.py
git commit -m "fix: visible-thought stream failure schedules retry instead of silent stop"
```

---

### Task 2: 审计事件接口补 return（P0-2）

**Files:**
- Modify: `backend/app/api/agent_audit.py:253`（`next_seq` 计算之后）
- Test: 无新测试——`tests/test_agent_audit.py` 已有两个测试覆盖该端点且**当前是红的**（`test_audit_events_with_cursor` :236、`test_audit_events_use_cursor_pagination` :272，均断言 `data["items"]`，端点返回 null 时抛 TypeError）

**Interfaces:**
- Consumes: `success`（agent_audit.py 已导入，224 行已用）、`items`/`next_seq`（251-252 行已计算）
- Produces: `GET /api/agent/audit/runs/{run_id}/events` 返回 `success(request, {"items": [...], "next_seq": int|None})`，与非审计端点 `agent.py:380-386` 格式一致

- [ ] **Step 1: 运行现有测试确认当前是红的**

Run: `python -m pytest tests/test_agent_audit.py -k "audit_events_with_cursor or audit_events_use_cursor_pagination" -x -q`
Expected: 两个测试 ERROR（`TypeError: object of type 'NoneType' has no len()/item` 或断言失败）——证明 bug 存在

- [ ] **Step 2: 实现修复（agent_audit.py，在第 252 行 `next_seq = ...` 之后、第 254 行装饰器之前插入）**

```python
    return success(
        request,
        {
            "items": items,
            "next_seq": next_seq,
        },
    )
```

- [ ] **Step 3: 运行测试确认通过**

Run: `python -m pytest tests/test_agent_audit.py -k "audit_events_with_cursor or audit_events_use_cursor_pagination" -q`
Expected: 2 passed

- [ ] **Step 4: 回归整个审计测试文件**

Run: `python -m pytest tests/test_agent_audit.py -q`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add app/api/agent_audit.py
git commit -m "fix: audit run events endpoint returns items instead of null"
```

---

### Task 3: Worker 进程挂接 RedisBridge（P0-1）

**Files:**
- Modify: `backend/app/services/agent/loop.py:1512-1520`（新增两个 helper + `set_redis_bridge` 接受 None）
- Modify: `backend/app/main.py:29-52`（lifespan 简化）
- Modify: `backend/app/workers/agent_worker.py:27-39`（main 挂接 bridge）
- Test: `backend/tests/test_redis_bridge.py`（文件末尾追加）

**Interfaces:**
- Consumes: `settings`（loop.py:33 模块级单例）、`RedisBridge`（loop.py:31 已导入）、`event_bus`（loop.py:20 已导入）
- Produces:
  - `async def init_redis_bridge(*, subscribe: bool = True) -> RedisBridge | None` — 开关关闭返回 None；否则 connect +（可选）subscribe + `set_redis_bridge` 后返回实例
  - `async def shutdown_redis_bridge() -> None` — 断开并 `set_redis_bridge(None)`
  - `def set_redis_bridge(bridge: RedisBridge | None) -> None` — 签名改为可接受 None

**关键设计决策（必读）:** Worker 进程只调用 `init_redis_bridge(subscribe=False)`——**绝不能订阅**。XREADGROUP 会把流内消息按消费者轮询分发，Worker 加入消费组会吞掉本应给 API 进程 SSE 的事件。

- [ ] **Step 1: 写失败测试（追加到 `tests/test_redis_bridge.py` 末尾）**

```python
class FakeBridge:
    def __init__(self, **kwargs):
        self.connected = False
        self.subscribed = False
        self.disconnected = False

    async def connect(self):
        self.connected = True

    async def subscribe(self, pattern):
        self.subscribed = True

    async def disconnect(self):
        self.disconnected = True


class TestInitShutdownBridge:
    async def test_init_redis_bridge_disabled_returns_none(self, monkeypatch):
        import app.services.agent.loop as loop_module

        monkeypatch.setattr(loop_module.settings, "agent_redis_pubsub_enabled", False)
        assert await loop_module.init_redis_bridge() is None

    async def test_init_redis_bridge_connects_and_sets_global(self, monkeypatch):
        import app.services.agent.loop as loop_module

        monkeypatch.setattr(loop_module.settings, "agent_redis_pubsub_enabled", True)
        monkeypatch.setattr(loop_module, "RedisBridge", FakeBridge)
        bridge = None
        try:
            bridge = await loop_module.init_redis_bridge()
            assert bridge is not None
            assert bridge.connected is True
            assert bridge.subscribed is True
            assert loop_module.redis_bridge is bridge
            assert loop_module.agent_loop_service.redis_bridge is bridge
        finally:
            await loop_module.shutdown_redis_bridge()
            assert bridge is not None
            assert bridge.disconnected is True
            assert loop_module.redis_bridge is None

    async def test_init_redis_bridge_worker_mode_skips_subscribe(self, monkeypatch):
        import app.services.agent.loop as loop_module

        monkeypatch.setattr(loop_module.settings, "agent_redis_pubsub_enabled", True)
        monkeypatch.setattr(loop_module, "RedisBridge", FakeBridge)
        bridge = None
        try:
            bridge = await loop_module.init_redis_bridge(subscribe=False)
            assert bridge is not None
            assert bridge.subscribed is False
        finally:
            await loop_module.shutdown_redis_bridge()
            assert bridge is not None
            assert bridge.disconnected is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_redis_bridge.py -k TestInitShutdownBridge -x -q`
Expected: ERROR——`init_redis_bridge` 不存在（ImportError/AttributeError）

- [ ] **Step 3: 实现 loop.py helper（替换 1512-1520 行的 `set_redis_bridge` 定义）**

```python
agent_loop_service = AgentLoopService()

redis_bridge: RedisBridge | None = None


def set_redis_bridge(bridge: RedisBridge | None) -> None:
    global redis_bridge
    redis_bridge = bridge
    agent_loop_service.redis_bridge = bridge


async def init_redis_bridge(*, subscribe: bool = True) -> RedisBridge | None:
    if not settings.agent_redis_pubsub_enabled:
        return None
    bridge = RedisBridge(
        redis_url=settings.redis_url,
        event_bus=event_bus,
        batch_window_ms=settings.agent_redis_batch_window_ms,
        batch_max_size=settings.agent_redis_batch_max_size,
    )
    await bridge.connect()
    if subscribe:
        await bridge.subscribe("run:*")
    set_redis_bridge(bridge)
    return bridge


async def shutdown_redis_bridge() -> None:
    if redis_bridge is not None:
        await redis_bridge.disconnect()
        set_redis_bridge(None)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_redis_bridge.py -k TestInitShutdownBridge -q`
Expected: 3 passed

- [ ] **Step 5: 重构 main.py 的 lifespan（替换 34-52 行的整个 `if settings.agent_redis_pubsub_enabled:` 块）**

原代码（main.py:34-52）：
```python
    redis_bridge = None
    if settings.agent_redis_pubsub_enabled:
        from app.services.agent.redis_bridge import RedisBridge
        from app.services.agent.loop import set_redis_bridge
        from app.services.agent.event_bus import event_bus
        redis_bridge = RedisBridge(
            redis_url=settings.redis_url,
            event_bus=event_bus,
            batch_window_ms=settings.agent_redis_batch_window_ms,
            batch_max_size=settings.agent_redis_batch_max_size,
        )
        await redis_bridge.connect()
        await redis_bridge.subscribe("run:*")
        set_redis_bridge(redis_bridge)
    try:
        yield
    finally:
        if redis_bridge is not None:
            await redis_bridge.disconnect()
```

新代码：
```python
    from app.services.agent.loop import init_redis_bridge, shutdown_redis_bridge
    await init_redis_bridge()
    try:
        yield
    finally:
        await shutdown_redis_bridge()
```

- [ ] **Step 6: 挂接 Worker 入口（修改 `app/workers/agent_worker.py:27-39` 的 `main()`）**

```python
async def main() -> None:
    settings = get_settings()
    validate_agent_worker_settings(settings)
    from app.services.agent.loop import init_redis_bridge, shutdown_redis_bridge
    await init_redis_bridge(subscribe=False)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    logger.info(
        "agent_worker_started",
        extra={
            "worker_id": worker_id,
            "model": settings.deepseek_model,
        },
    )
    try:
        worker = AgentWorker(worker_id=worker_id, concurrency=settings.worker_concurrency)
        await worker.run()
    finally:
        await shutdown_redis_bridge()
```

- [ ] **Step 7: 回归相关测试**

Run: `python -m pytest tests/test_redis_bridge.py tests/test_agent_worker_startup.py tests/test_health.py tests/test_redis_integration.py -q`
Expected: 全部通过（ASGITransport 不触发 lifespan，`test_health` 等不受影响）

- [ ] **Step 8: 提交**

```bash
git add app/services/agent/loop.py app/main.py app/workers/agent_worker.py tests/test_redis_bridge.py
git commit -m "feat: wire RedisBridge into worker process for cross-process events"
```

---

### Task 4: 取消 queued/retry_wait run 立即终态（P1-5）

**Files:**
- Modify: `backend/app/repositories/agent_repository.py:384-387`（`request_cancel` 之后新增方法）
- Modify: `backend/app/api/agent.py:403-417`（`request_cancel` 端点）
- Test: `backend/tests/test_agent_repository.py`（新增 2 个测试）、`backend/tests/test_agent_api.py:676-697`（更新 1 个断言）

**Interfaces:**
- Consumes: `_transition_run_status`（agent_repository.py:353）、`AgentRunResponse`/`success`/`ApiError`（agent.py 已导入）
- Produces: `async def cancel_queued_run(self, run: AgentRun) -> bool` — `queued/retry_wait → cancelled` 条件更新，rowcount 判真

**背景（必读）:** `request_cancel` 允许 queued/retry_wait→cancel_requested，但只有 worker 在步骤边界才执行 `mark_run_cancelled`；queued 的 run 永远不会被认领（claim 只认 queued/retry_wait），于是永久停在 cancel_requested。

- [ ] **Step 1: 写失败测试（追加到 `tests/test_agent_repository.py`，放在 `test_request_cancel_from_running` 附近）**

```python
    async def test_cancel_queued_run_marks_cancelled(self, session, owned_session):
        repo = AgentRepository(session)
        run, attempt, event = await repo.create_run_with_attempt(
            owned_session, "cancel queued", "quick", True, []
        )
        await session.flush()
        assert run.status == "queued"

        result = await repo.cancel_queued_run(run)

        assert result is True
        assert run.status == "cancelled"

    async def test_cancel_queued_run_rejects_running(self, session, owned_session):
        repo = AgentRepository(session)
        run, attempt, event = await repo.create_run_with_attempt(
            owned_session, "cancel running", "quick", True, []
        )
        await session.flush()
        assert await repo.mark_run_running(run) is True

        result = await repo.cancel_queued_run(run)

        assert result is False
        assert run.status == "running"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agent_repository.py -k cancel_queued_run -x -q`
Expected: ERROR——`cancel_queued_run` 不存在（AttributeError）

- [ ] **Step 3: 实现仓库方法（agent_repository.py，`request_cancel` 定义之后插入）**

```python
    async def cancel_queued_run(self, run: AgentRun) -> bool:
        return await self._transition_run_status(
            run, {"queued", "retry_wait"}, "cancelled"
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agent_repository.py -k cancel_queued_run -q`
Expected: 2 passed

- [ ] **Step 5: 实现端点修改（agent.py:403-410，在 `repo = AgentRepository(db)` 之后插入分支）**

原代码：
```python
    repo = AgentRepository(db)
    ok = await repo.request_cancel(run)
    if not ok:
```
改为：
```python
    repo = AgentRepository(db)
    if run.status in {"queued", "retry_wait"}:
        if await repo.cancel_queued_run(run):
            await repo.append_event(
                run,
                None,
                "run_cancelled",
                {"run_id": str(run.id), "status": "cancelled"},
            )
            return success(
                request,
                AgentRunResponse.model_validate(run).model_dump(mode="json"),
            )
    ok = await repo.request_cancel(run)
    if not ok:
```

- [ ] **Step 6: 更新现有测试断言（test_agent_api.py:696）**

原代码：
```python
        assert body["data"]["status"] == "cancel_requested"
```
改为：
```python
        assert body["data"]["status"] == "cancelled"
```

- [ ] **Step 7: 运行 API 取消相关测试**

Run: `python -m pytest tests/test_agent_api.py -k cancel -q`
Expected: 4 passed（含 `test_cancel_without_csrf_fails`、`test_cannot_cancel_terminal_run`）

- [ ] **Step 8: 回归仓库测试文件**

Run: `python -m pytest tests/test_agent_repository.py -q`
Expected: 全部通过

- [ ] **Step 9: 提交**

```bash
git add app/repositories/agent_repository.py app/api/agent.py tests/test_agent_repository.py tests/test_agent_api.py
git commit -m "fix: cancelling a queued run terminates it immediately instead of stalling"
```

---

### Task 5: recover/reconcile 竞态与扫描修复（P1-6）

**Files:**
- Modify: `backend/app/repositories/agent_repository.py:525-530`（recover 加行锁）
- Modify: `backend/app/repositories/agent_repository.py:587-595`（answer_sub 关联过滤）
- Modify: `backend/app/repositories/agent_repository.py:655-657`（reconcile attempt 匹配校验）
- Test: `backend/tests/test_reconcile_completed_agent_runs.py`（新增 1 个）、`backend/tests/test_agent_worker.py`（新增 1 个并发测试）

**Interfaces:**
- Consumes: `recover_expired_attempts(now=None) -> int`、`find_reconcilable_completed_answer_run_ids() -> list[uuid.UUID]`、`reconcile_completed_answer_run(run_id) -> bool`（均已存在，仅内部改）
- Produces: 无新 API。行为变化：并发 recover 单写者；reconcile 拒绝"答案来自旧 attempt"的场景。

**背景（必读）:** 三处缺陷：(a) `recover_expired_attempts` 先 SELECT 再逐行 UPDATE 无锁，两个维护进程会重复恢复同一 attempt 并各建一个 retry attempt（撞 `(run_id, attempt_number)` 唯一约束）；(b) `find_reconcilable...` 的 `answer_sub` 未关联 `run_id == AgentRun.id`，子查询退化为全表扫描；(c) `reconcile_completed_answer_run` 拿 run 当前 attempt，但 answer 事件可能来自上一个 attempt——崩溃恢复后会用旧答案把新 queued attempt 标成 succeeded。

- [ ] **Step 1: 写失败测试 1（追加到 `tests/test_reconcile_completed_agent_runs.py` 的 `TestReconcileCompletedAgentRuns` 类内）**

```python
    async def test_reconcile_skips_answer_from_previous_attempt(
        self, session, seeded_user
    ):
        agent_session = AgentSession(
            owner_user_id=seeded_user.id, title="skip reconcile"
        )
        session.add(agent_session)
        await session.flush()

        repo = AgentRepository(session)
        run, attempt1, _ = await repo.create_run_with_attempt(
            agent_session, "skip reconcile goal", "quick", True, []
        )
        await session.flush()

        attempt1.status = "running"
        attempt1.worker_id = "dead-worker"
        attempt1.claimed_at = datetime.now(UTC) - timedelta(minutes=10)
        attempt1.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
        session.add(attempt1)
        await session.flush()

        await repo.append_event(
            run, attempt1, "answer_completed",
            {"text": "answer from attempt 1", "stream_id": str(uuid.uuid4())},
        )
        await session.flush()

        attempt1.status = "failed"
        attempt2 = AgentRunAttempt(
            run_id=run.id,
            attempt_number=2,
            status="queued",
            retry_of_attempt_id=attempt1.id,
            not_before=datetime.now(UTC) + timedelta(seconds=5),
        )
        session.add(attempt2)
        run.status = "retry_wait"
        run.current_attempt_id = attempt2.id
        await session.flush()

        result = await repo.reconcile_completed_answer_run(run.id)

        assert result is False
        await session.refresh(run)
        await session.refresh(attempt2)
        assert run.status == "retry_wait"
        assert attempt2.status == "queued"
```

- [ ] **Step 2: 写失败测试 2（追加到 `tests/test_agent_worker.py`，仿照已有的 `TestConcurrentClaim` 类风格）**

```python
class TestConcurrentRecover:
    async def test_only_one_recovery_schedules_retry(self, test_db):
        import uuid as _uuid
        from datetime import UTC, datetime, timedelta
        from sqlalchemy import select as sa_select

        from argon2 import PasswordHasher

        from app.models.agent import AgentRunAttempt, AgentSession
        from app.models.rbac import User
        from app.repositories.agent_repository import AgentRepository

        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"recover_user_{_uuid.uuid4().hex[:8]}",
                display_name="Recover Test User",
                password_hash=ph.hash("Test1234"),
                status="active",
            )
            s.add(user)
            await s.flush()

            agent_session = AgentSession(owner_user_id=user.id, title="recover test")
            s.add(agent_session)
            await s.flush()

            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                agent_session, "concurrent recover test", "quick", True, []
            )
            attempt.status = "running"
            attempt.worker_id = "dead-worker"
            attempt.claimed_at = datetime.now(UTC) - timedelta(minutes=10)
            attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
            s.add(attempt)
            await s.commit()
            run_id = run.id

        async def do_recover() -> int:
            async with test_db() as s:
                repo = AgentRepository(s)
                try:
                    count = await repo.recover_expired_attempts()
                    await s.commit()
                    return count
                except Exception:
                    await s.rollback()
                    raise

        results = await asyncio.gather(do_recover(), do_recover())
        assert sum(results) == 1

        async with test_db() as s:
            attempts = (
                await s.execute(
                    sa_select(AgentRunAttempt)
                    .where(AgentRunAttempt.run_id == run_id)
                    .order_by(AgentRunAttempt.attempt_number)
                )
            ).scalars().all()
            assert len(attempts) == 2
```

（如该文件顶部已 `import asyncio` 则无需重复；否则在文件顶部补 `import asyncio`。）

- [ ] **Step 3: 运行两个测试确认失败**

Run: `python -m pytest tests/test_reconcile_completed_agent_runs.py tests/test_agent_worker.py -k "TestConcurrentRecover or skips_answer_from_previous_attempt" -x -q`
Expected: 测试 1 失败（当前代码把 attempt2 标成 succeeded，断言 `== "retry_wait"` 失败）；测试 2 失败或抛 UniqueViolation（两个并发 recover 都创建 attempt 2）。

- [ ] **Step 4: 实现修复 (a) recover 行锁（agent_repository.py:525-530）**

原代码：
```python
        expired_attempts = await self.session.execute(
            select(AgentRunAttempt).where(
                AgentRunAttempt.status == "running",
                AgentRunAttempt.lease_expires_at < now,
            )
        )
```
改为：
```python
        expired_attempts = await self.session.execute(
            select(AgentRunAttempt)
            .where(
                AgentRunAttempt.status == "running",
                AgentRunAttempt.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
        )
```

- [ ] **Step 5: 实现修复 (b) answer_sub 关联（agent_repository.py:587-595）**

原代码：
```python
        answer_sub = (
            select(AgentRunEvent.run_id)
            .where(
                AgentRunEvent.event_type == "answer_completed",
                AgentRunEvent.payload["text"].as_string() != "",
                AgentRunEvent.payload["text"].as_string() != None,
            )
            .correlate(AgentRun)
        )
```
改为：
```python
        answer_sub = (
            select(AgentRunEvent.run_id)
            .where(
                AgentRunEvent.event_type == "answer_completed",
                AgentRunEvent.run_id == AgentRun.id,
                AgentRunEvent.payload["text"].as_string() != "",
                AgentRunEvent.payload["text"].as_string() != None,
            )
            .correlate(AgentRun)
        )
```

- [ ] **Step 6: 实现修复 (c) attempt 匹配校验（agent_repository.py:655-657 之后插入）**

在 `answer_event = answer_event_result.scalar_one_or_none()` 与 `if answer_event is None: return False` 之间（即 :655-657 之后）插入：

```python
        if answer_event.attempt_id != attempt.id:
            return False
```

- [ ] **Step 7: 运行两个测试确认通过**

Run: `python -m pytest tests/test_reconcile_completed_agent_runs.py tests/test_agent_worker.py -k "TestConcurrentRecover or skips_answer_from_previous_attempt" -q`
Expected: 2 passed

- [ ] **Step 8: 回归相关测试文件**

Run: `python -m pytest tests/test_reconcile_completed_agent_runs.py tests/test_agent_worker.py tests/test_agent_repository.py -q`
Expected: 全部通过

- [ ] **Step 9: 提交**

```bash
git add app/repositories/agent_repository.py tests/test_reconcile_completed_agent_runs.py tests/test_agent_worker.py
git commit -m "fix: single-writer recovery, correlated answer scan, attempt-matched reconciliation"
```

---

### Task 6: SSE 终态补齐分页循环（P1-7）

**Files:**
- Modify: `backend/app/api/agent_stream.py:230-237`（终态分支）
- Test: `backend/tests/test_agent_stream.py`（新增 1 个，放在 `test_sse_replays_every_event_beyond_catch_up_limit` 之后）

**Interfaces:**
- Consumes: `_events_after(run_id, after_seq, limit=CATCH_UP_LIMIT)`（agent_stream.py:140）、`_encode_sse_event`、`TERMINAL_STATUSES`、`CATCH_UP_LIMIT`（=200，:31-33）
- Produces: 无新 API。行为变化：终态补齐改为循环拉页直到返回不足一页。

**背景（必读）:** 当前终态分支只拉一次 `_events_after`（最多 200 条）就 break。若断线期间新增事件 >200（长答案的 answer_delta 轻松超过），中间事件永久丢失。现有测试 `test_sse_replays_every_event_beyond_catch_up_limit`（:240）恰好用 400 条 = 2×200，初始回放 200 + 终态补齐 200，碰巧全通过——没有覆盖真实缺陷。

- [ ] **Step 1: 写失败测试（追加到 `tests/test_agent_stream.py` 的 `TestAgentStream` 类内）**

```python
    async def test_terminal_catch_up_loops_beyond_single_page(
        self, ordinary_client, ordinary_user, stream_db, monkeypatch
    ):
        import app.api.agent_stream as asm
        from sqlalchemy import select as sa_select

        async with stream_db() as s:
            session_obj = AgentSession(
                owner_user_id=ordinary_user.id, title="paged terminal"
            )
            s.add(session_obj)
            await s.flush()
            run = AgentRun(
                session_id=session_obj.id,
                owner_user_id=ordinary_user.id,
                goal="paged terminal goal",
                mode="quick",
                status="succeeded",
            )
            s.add(run)
            await s.flush()
            for i in range(5):
                s.add(
                    AgentRunEvent(
                        run_id=run.id,
                        event_type="answer_delta",
                        payload={"delta": str(i)},
                    )
                )
            await s.flush()
            result = await s.execute(
                sa_select(AgentRunEvent.seq)
                .where(AgentRunEvent.run_id == run.id)
                .order_by(AgentRunEvent.seq.asc())
            )
            expected_seqs = list(result.scalars())
            await s.commit()

        real_events_after = asm._events_after

        async def small_pages(run_id, after_seq, limit=2):
            return await real_events_after(run_id, after_seq, limit=limit)

        monkeypatch.setattr(asm, "_events_after", small_pages)

        response = await ordinary_client.get(
            f"/api/agent/runs/{run.id}/stream?after_seq={expected_seqs[0] - 1}",
            headers={"Origin": TEST_ORIGIN},
        )

        assert response.status_code == 200
        emitted_seqs = [
            int(line[4:])
            for line in response.text.split("\n")
            if line.startswith("id: ")
        ]
        assert emitted_seqs == expected_seqs
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_agent_stream.py -k terminal_catch_up_loops -x -q`
Expected: 失败——`emitted_seqs` 只有 4 条（初始回放 2 + 终态补齐 2），缺第 5 条

- [ ] **Step 3: 实现修复（agent_stream.py:230-237）**

原代码：
```python
                if status is None or status in TERMINAL_STATUSES:
                    events = await _events_after(run_id, last_seen_seq)
                    for event in events:
                        encoded = _encode_sse_event(event)
                        if encoded is None: continue
                        last_seen_seq = event.seq
                        yield encoded
                    break
```
改为：
```python
                if status is None or status in TERMINAL_STATUSES:
                    while True:
                        events = await _events_after(run_id, last_seen_seq)
                        for event in events:
                            encoded = _encode_sse_event(event)
                            if encoded is None: continue
                            last_seen_seq = event.seq
                            yield encoded
                        if len(events) < CATCH_UP_LIMIT:
                            break
                    break
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_agent_stream.py -k terminal_catch_up_loops -q`
Expected: 1 passed

- [ ] **Step 5: 回归 SSE 测试文件（含原有 400 条大回放测试）**

Run: `python -m pytest tests/test_agent_stream.py -q`
Expected: 全部通过（大回放测试约需 12 秒，属正常）

- [ ] **Step 6: 提交**

```bash
git add app/api/agent_stream.py tests/test_agent_stream.py
git commit -m "fix: SSE terminal catch-up paginates until all events replayed"
```

---

## 最终验收

- [ ] **运行整个后端测试套件**

Run: `python -m pytest -q`（在 `backend/` 下）
Expected: 全部通过；与改动前相比新增 8 个通过测试（T1×2、T3×3、T4×2、T5×2、T6×1——其中 T4 的 1 个是更新断言而非新增）

- [ ] **验证 Redis 通道端到端（可选，需要本地 Redis）**

1. 启动 API：`python -X utf8 -m uvicorn app.main:app --reload --port 8000`（终端 1）
2. 启动 Worker：`python -X utf8 -m app.workers.agent_worker`（终端 2）
3. Worker 启动日志应出现 `redis_bridge_connected`（redis_bridge.py:83）
4. 创建 run 后，`XREADGROUP GROUP sse-consumers` 能读到 `agent:events` 流中的新事件
5. 断点或日志确认 API 进程 `_subscribe_loop` 收到事件并 `event_bus.publish`

---

## Self-Review 结果

- **Spec 覆盖**：6 个缺陷（P0-3/P0-2/P0-1/P1-5/P1-6/P1-7）各有一个任务；分析报告中提出的 P1-2（XACK 缺失）、P1-7 之外的问题（如 `fail_attempt_and_run` 覆盖 cancel_requested、CSRF 前缀匹配等）不在本次范围，属于后续计划。
- **占位符检查**：所有步骤含完整代码，无 TBD/TODO/“类似 Task N”。
- **类型一致性**：`init_redis_bridge`/`shutdown_redis_bridge` 在 T3 各步骤签名一致；`cancel_queued_run` 在 T4 的仓库/API/测试三处签名一致；T1 中 `fake_merged` 返回 `(plan_dict, None)` 与 loop.py:1389-1390 的元组解包一致；T6 的 `small_pages` 签名与 `_events_after(run_id, after_seq, limit=...)` 一致。
- **测试陷阱**：T1/T3 的测试均通过 monkeypatch/finally 恢复 `agent_loop_service.redis_bridge` 与 `loop_module.settings` 全局状态；T6 用 monkeypatch 替换 `_events_after`（模块级名字在调用时解析，可行），避免 400 事件 × 30ms 的慢测试。
