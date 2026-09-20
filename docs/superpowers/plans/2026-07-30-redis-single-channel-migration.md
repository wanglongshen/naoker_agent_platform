# Redis 单通道 SSE 迁移计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将跨进程 SSE 推送从 PG NOTIFY + Redis 双路简化为 Redis 单路，减少复杂度，提升性能。

**Architecture:** Worker 通过 Redis Pub/Sub 推送完整 EventItem → API 进程 Redis 订阅者接收→放入 EventBus → SSE 生成器直接编码发射（不查 DB）。DB 持久化保留，30s 轮询兜底。删除 PG NOTIFY 和 EventNotify。

**Tech Stack:** Python 3.13 + FastAPI + Redis (redis-py async) + PostgreSQL + asyncio

## Global Constraints

- Redis 地址：`redis://localhost:6379/0`（从 `settings.redis_url` 读取）
- 批量窗口：32ms，批量上限 20 个事件（`agent_redis_batch_window_ms` / `agent_redis_batch_max_size`）
- 所有删除操作不删测试文件，只删源码
- 改动后 `from app.main import app` 必须成功导入

---

### Task 1: 删除 PG NOTIFY 从 agent_repository.py

**Files:**
- Modify: `backend/app/repositories/agent_repository.py:225-244`（append_event 方法，删除 notify 参数）
- Modify: `backend/app/repositories/agent_repository.py:661-668`（删除 notify_run_event 方法）

**Interfaces:**
- Consumes: 无
- Produces: append_event 只做 INSERT，不再触发 pg_notify

- [ ] **Step 1: 删除 append_event 中的 notify_run_event 调用**

在 `agent_repository.py` 的 `append_event` 方法中，删除 `notify_run_event` 调用。当前代码（约第 225-260 行）改为：

```python
async def append_event(
    self,
    run: AgentRun,
    attempt: AgentRunAttempt | None,
    event_type: str,
    payload: dict[str, Any],
) -> AgentRunEvent:
    result = await self.session.execute(
        insert(AgentRunEvent)
        .values(
            run_id=run.id,
            attempt_id=attempt.id if attempt else None,
            event_type=event_type,
            payload=payload,
            seq=agent_run_events_seq.next_value(),
        )
        .returning(AgentRunEvent)
    )
    event = result.scalar_one()
    await self.session.flush()
    return event
```

- [ ] **Step 2: 删除 notify_run_event 方法**

删除 `agent_repository.py` 中 `notify_run_event` 方法（约第 661-668 行）：

```python
# 删除以下全部：
async def notify_run_event(self, run_id: uuid.UUID, seq: int) -> None:
    payload = json.dumps({"run_id": str(run_id), "seq": seq})
    await self.session.execute(
        func.pg_notify("agent_run_events", payload)
    )
```

- [ ] **Step 3: 删除 append_event 的 notify 参数**

在 loop.py 中搜索所有 `append_event(` 调用，确保没有传递 `notify` 关键字参数。这些调用应该已经不存在——仅确认。

- [ ] **Step 4: 验证导入**

```bash
cd C:\01_agent_loop_pro\backend && python -c "from app.repositories.agent_repository import AgentRepository; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backend/app/repositories/agent_repository.py
git commit -m "refactor: remove PG NOTIFY notify_run_event from agent_repository"
```

---

### Task 2: 删除 postgres_event_listener 启动

**Files:**
- Modify: `backend/app/main.py:20-23`（删除 import）
- Modify: `backend/app/main.py:36-44`（删除 lifespan 中的 listener 启动/关闭）

**Interfaces:**
- Consumes: `settings.agent_event_listen_notify_enabled`
- Produces: 不再启动 PG NOTIFY 监听器

- [ ] **Step 1: 删除 import**

在 `main.py` 中删除这两行：

```python
# 删除：
from app.services.agent.postgres_event_listener import (
    shutdown_postgres_event_listener,
    start_postgres_event_listener,
)
```

- [ ] **Step 2: 简化 lifespan**

将 lifespan 中的 listener 相关代码删除：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_session_factory() as session:
        await seed_rbac(session)
        await session.commit()
    redis_bridge = None
    if settings.agent_redis_pubsub_enabled:
        from app.services.agent.redis_bridge import RedisBridge
        from app.services.agent.loop import set_redis_bridge
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

- [ ] **Step 3: 删除 postgres_event_listener 模块引用**

确认没有其他文件导入 `postgres_event_listener`：

```bash
cd backend && python -c "from app.main import app; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "refactor: remove PG NOTIFY listener, keep Redis bridge only"
```

---

### Task 3: 简化 SSE 生成器 — 移除 EventNotify 分支

**Files:**
- Modify: `backend/app/api/agent_stream.py:247-321`（while True 循环）

**Interfaces:**
- Consumes: `event_bus.subscribe()` 返回 `asyncio.Queue[EventItem]`
- Produces: 只处理 EventItem，直接编码发射

- [ ] **Step 1: 简化 while True 循环体**

将 `agent_stream.py` 中 `while True:` 循环内的 `EventNotify` 处理分支删除。关键改动：删除 `isinstance(evt, PersistedEvent)` 分支和 `needs_catchup` 逻辑。循环应该只处理 EventItem：

```python
while True:
    # 非阻塞排空
    while True:
        try:
            item = queue.get_nowait()
            item_seq = getattr(item, "seq", None)
            if item_seq is None or (last_seen_seq is not None and item_seq <= last_seen_seq):
                continue
            encoded = _encode_sse_event(item)
            if encoded is None:
                continue
            last_seen_seq = item_seq
            yield encoded
        except asyncio.QueueEmpty:
            break

    # 检查 run 状态
    async with async_session_factory() as session:
        result = await session.execute(
            sa_select(AgentRun.status).where(AgentRun.id == run_id)
        )
        status = result.scalar_one_or_none()
    if status is None or status in TERMINAL_STATUSES:
        events = await _events_after(run_id, last_seen_seq)
        for event in events:
            encoded = _encode_sse_event(event)
            if encoded is None: continue
            last_seen_seq = event.seq
            yield encoded
        break

    # 阻塞等待
    try:
        item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
    except asyncio.TimeoutError:
        yield ":keepalive\n\n"
        events = await _events_after(run_id, last_seen_seq)
        for event in events:
            encoded = _encode_sse_event(event)
            if encoded is None: continue
            last_seen_seq = event.seq
            yield encoded
        continue

    # 处理 EventItem
    item_seq = getattr(item, "seq", None)
    if item_seq is None or (last_seen_seq is not None and item_seq <= last_seen_seq):
        continue
    encoded = _encode_sse_event(item)
    if encoded is None: continue
    last_seen_seq = item_seq
    yield encoded

    # 快速排空额外事件
    while True:
        try:
            extra = queue.get_nowait()
            extra_seq = getattr(extra, "seq", None)
            if extra_seq is None or (last_seen_seq is not None and extra_seq <= last_seen_seq):
                continue
            encoded = _encode_sse_event(extra)
            if encoded is None: continue
            last_seen_seq = extra_seq
            yield encoded
        except asyncio.QueueEmpty:
            break

    # DB 查回兜底
    events = await _events_after(run_id, last_seen_seq)
    for event in events:
        encoded = _encode_sse_event(event)
        if encoded is None: continue
        last_seen_seq = event.seq
        yield encoded
```

- [ ] **Step 2: 验证导入**

```bash
cd backend && python -c "from app.api.agent_stream import router; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: 运行 SSE 测试**

```bash
cd backend && python -m pytest tests/test_agent_stream.py tests/test_agent_stream_direct.py -v -q
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/agent_stream.py
git commit -m "refactor: simplify SSE loop to single EventItem path, remove EventNotify"
```

---

### Task 4: 清理 event_bus — 移除 EventNotify 类型

**Files:**
- Modify: `backend/app/services/agent/event_bus.py`（删除 PersistedEvent 类）

**Interfaces:**
- Consumes: 无
- Produces: 只有 `EventItem` 一种事件类型

- [ ] **Step 1: 删除 PersistedEvent 类**

删除 `event_bus.py` 中 `PersistedEvent` 数据类定义（约第 10-13 行）：

```python
# 删除：
@dataclass(frozen=True)
class PersistedEvent:
    run_id: UUID
    seq: int
```

- [ ] **Step 2: 清理引用**

检查是否还有其他文件引用 `PersistedEvent`：

```bash
cd backend && python -c "from app.services.agent.event_bus import EventItem, EventBus; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/agent/event_bus.py
git commit -m "refactor: remove PersistedEvent, keep only EventItem"
```

---

### Task 5: 回归测试

- [ ] **Step 1: 全量后端测试**

```bash
cd backend && python -m pytest tests/ -q -k "not test_retryable_tool_failure and not test_events_are_paginated_and_redacted" --ignore=tests/test_agent_audit.py --ignore=tests/test_postgres_event_listener.py
```

- [ ] **Step 2: 确认 postgres_event_listener 测试不需要了**

```bash
cd backend && python -m pytest tests/test_postgres_event_listener.py -v
```
如果还有这些测试文件，可以删除或标记为 skip。

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test: verify Redis single-channel migration, all tests pass"
```
