# SSE 管道复刻开发计划

> 目标：将本系统 SSE 管道与参考系统 `X:\01_agent_loop` 对齐，删除单机部署下的冗余层。
>
> 创建时间：2026-07-29

---

## 一、两个系统 SSE 管道架构对比

### 参考系统 `X:\01_agent_loop`（简洁版）

```
Agent Loop
  │
  ├─ _publish_persisted_event(repo, run_id, event_type, payload)
  │    └─ repo.create_and_refresh_event()  → INSERT + COMMIT → 返回 EventItem
  │    └─ event_bus.publish(event)          → 推入内存队列
  │
  ▼
EventBus（单类型 EventItem）
  │
  ├─ 字段：id, run_id, seq, event_type, payload, created_at
  │
  ▼
SSE event_generator()
  ├─ replay: repo.list_events_after_seq()
  ├─ subscribe: event_bus.subscribe(run_id)
  ├─ catch_up: repo.list_events_after_seq()
  └─ while True:
       ├─ drain_nowait(queue)
       ├─ status_check(repo.get_run)
       ├─ wait_for(queue.get, timeout=30s)
       │    ├─ timeout → heartbeat + catch_up
       │    └─ event → encode → drain_nowait → catch_up
       └─ finally: unsubscribe

编码：单 _encode_sse_event → Pydantic model_validate → model_dump
心跳：30 秒
事件类型：一种，无分支
跨进程：不支持（单机部署不需要）
文件：stream.py（220 行）
```

### 本系统 `C:\01_agent_loop_pro`（改前，冗余版）

```
Agent Loop
  │
  ├─ _persist_and_notify()
  │    └─ append_event()    → INSERT
  │    └─ notify_run_event() → pg_notify("agent_run_events")   ← 冗余层1
  │    └─ COMMIT
  │    └─ agent_event_bus.publish_after_commit(CommittedEvent)  ← 冗余层2（双类型）
  │
  ▼
EventBus（双类型 CommittedEvent + PersistedEvent）
  │
  ├─ CommittedEvent：全字段（同进程 Agent Loop 推送）
  ├─ PersistedEvent：仅 run_id + seq（跨进程 NOTIFY 推送）
  │
  ▼
PostgresEventListener ← 冗余层3
  │  asyncpg LISTEN "agent_run_events"
  │  收到 NOTIFY → 解析 {run_id, seq}
  │  → agent_event_bus.publish_after_commit(PersistedEvent)
  │
  ▼
SSE _stream_persisted_run_events()
  ├─ 双编码路径：
  │    ├─ _encode_direct_sse(CommittedEvent)   ← 同进程直编
  │    └─ _encode_sse_event(AgentRunEvent)       ← DB 查缺再编
  ├─ gap 检测：last_seen_seq + 1 < seq → 回 DB
  ├─ emit_persisted_events() 嵌套函数
  ├─ batch_events 批量处理
  └─ SSE_POLL_INTERVAL = 3 秒（频繁 DB 轮询）

编码：两条路径，逻辑重复
心跳：HEARTBEAT_INTERVAL = 15 秒
事件类型：两种，需要 isinstance 分支
跨进程：支持（PostgreSQL NOTIFY）
文件：agent_stream.py（346 行）
```

### 冗余层总结

| 冗余层 | 作用 | 单机是否需要 | 影响 |
|--------|------|-------------|------|
| `pg_notify()` | 向 PostgreSQL 发送通知 | 否 | 每条事件多一次 DB 调用 |
| `PersistedEvent` 类型 | 只含 run_id+seq 的瘦事件 | 否 | SSE 需额外 DB 查缺 |
| `PostgresEventListener` | asyncpg 监听 NOTIFY | 否 | 多占一个 DB 连接 |
| `_encode_direct_sse` | CommittedEvent 专用编码 | 否 | 与 `_encode_sse_event` 重复 |
| `emit_persisted_events()` | 嵌套 DB 查缺函数 | 否 | 增加嵌套复杂度 |
| gap 检测 | 比对 seq 连续性 | 否（DB catch-up 已覆盖） | 逻辑冗余 |
| `SSE_POLL_INTERVAL = 3s` | 短间隔 DB 轮询 | 否 | 空闲时频繁查 DB |

---

## 二、复刻策略

**核心原则：逐结构复刻，不写"类似代码"。**

参考系统每个函数的逻辑结构 → 本系统对应函数完全一致。

### 2.1 架构映射

| 参考系统 | 本系统（改后） |
|---------|---------------|
| `stream.py` → `event_generator()` | `agent_stream.py` → `event_generator()` |
| `event_bus.py` → `EventBus` + `EventItem` | `event_bus.py` → `EventBus` + `EventItem` |
| `run_repository.py` → `list_events_after_seq()` | `agent_repository.py` → `list_events_after_seq()`（已有） |
| `run_repository.py` → `get_run()` | 内联 `sa_select(AgentRun.status)` |
| `schemas/event.py` → `RunEventResponse` | `schemas/agent.py` → `AgentRunEventResponse`（已有） |
| `_publish_persisted_event()` → `repo.create_and_refresh_event()` + `event_bus.publish()` | `_persist_and_notify()` → `append_event()` + `event_bus.publish()` |

### 2.2 不动的部分

以下本系统特有功能**保留不动**（参考系统没有，但本系统需要）：

- JWT Cookie 认证（`_authenticate_and_authorize`）
- Origin 校验（`_validate_origin`）
- `_stream_final_answer` 中的共享 session 批量 commit
- `_persist_terminal_and_notify` 多事件原子事务
- 前端的 RAF 合并渲染、`use-run-event-stream` 重连逻辑
- 前端 `parseStreamEvent` 兼容 `type`/`timestamp` 可选字段

---

## 三、逐文件改动详情

### 3.1 `event_bus.py` — 重写（参考系统 61 行 → 本系统 55 行）

**删除：**
- `PersistedEvent` 类（仅 run_id + seq）
- `CommittedEvent` 类（全字段，但名字不统一）
- `PublishableEvent = PersistedEvent | CommittedEvent` 联合类型
- `_BoundedQueue` 子类（asyncio.Queue 自带宽限）
- `AgentEventBus` 类名
- `agent_event_bus` 单例名
- `publish_after_commit` 方法名

**新增（从参考系统复刻）：**
- `EventItem` 数据类（统一事件类型）：`id, run_id, seq, event_type, payload, created_at, attempt_id`
- `EventBus` 类名
- `publish` 方法（替代 `publish_after_commit`）
- `event_bus` 单例名

**完整代码（参考系统 1:1 复刻，适配 UUID 类型）：**

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class EventItem:
    run_id: UUID
    seq: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    id: UUID | None = None
    attempt_id: UUID | None = None


class EventBus:
    def __init__(self, max_queue_size: int = 1000) -> None:
        self._subscribers: dict[UUID, dict[str, asyncio.Queue[EventItem]]] = {}
        self._lock = asyncio.Lock()
        self._max_queue_size = max_queue_size

    async def publish(self, item: EventItem) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(item.run_id, {}).items())
        for subscriber_id, queue in subscribers:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                await self.unsubscribe(item.run_id, subscriber_id)

    async def subscribe(self, run_id: UUID) -> tuple[str, asyncio.Queue[EventItem]]:
        subscriber_id = str(uuid4())
        queue: asyncio.Queue[EventItem] = asyncio.Queue(maxsize=self._max_queue_size)
        async with self._lock:
            self._subscribers.setdefault(run_id, {})[subscriber_id] = queue
        return subscriber_id, queue

    async def unsubscribe(self, run_id: UUID, subscriber_id: str) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(run_id)
            if subscribers is None:
                return
            subscribers.pop(subscriber_id, None)
            if not subscribers:
                del self._subscribers[run_id]


event_bus = EventBus()
```

**关键差异说明：**
- 参考系统 `EventItem.id` 是 `str`；本系统保留 `UUID`（与现有 `AgentRunEvent.id` 一致，保证 `_encode_sse_event` 中 Pydantic 校验通过）
- 参考系统 `run_id` 是 `str`；本系统保留 `UUID`（与现有模型一致）

---

### 3.2 `agent_stream.py` — 重写（参考系统 220 行 → 本系统 276 行）

**删除：**
- `_encode_direct_sse()` 第二编码路径
- `_should_emit_direct()` 判断函数
- `emit_persisted_events()` 嵌套 DB 查缺函数
- gap 检测逻辑（`last_seen_seq + 1 < queue_event.seq`）
- `batch_events` 批量处理
- `SSE_POLL_INTERVAL` 常量（3 秒）
- `TERMINAL_EVENT_TYPES` 常量
- `CommittedEvent` / `PersistedEvent` 类型分支
- `agent_event_bus` 引用
- `settings` 引用（不再需要 `agent_event_compensation_poll_seconds`）
- 终态 warning 日志

**保留：**
- `_authenticate_and_authorize()` — JWT 认证（参考系统无，本系统必需）
- `_validate_origin()` — Origin 校验（参考系统无，本系统必需）
- `_parse_after_seq()` — 游标解析
- `_encode_sse_event()` — 统一编码函数（参考系统同名函数）
- `_events_after()` — DB 查询封装

**新增（从参考系统复刻）：**
- `event_generator()` 内部函数：drain → status_check → wait → drain → catch_up 循环
- `HEARTBEAT_INTERVAL = 30.0` 常量
- `CATCH_UP_LIMIT = 200` 常量

**核心循环逻辑（与参考系统完全一致）：**

```
Phase 1: replay      → _events_after(run_id, after_seq) 追批已有事件
Phase 2: subscribe   → event_bus.subscribe(run_id)       订阅实时推送
Phase 3: gap_fill    → _events_after(run_id, last_seq)   填补订阅间隙
Phase 4: live loop   →
  while True:
    ① drain_nowait   → 非阻塞取空队列中已有事件
    ② status_check   → SELECT status，终态则 break
    ③ await queue.get(timeout=30s)
       ├─ TimeoutError: heartbeat + DB catch_up + continue
       └─ event:
           ④ encode  → _encode_sse_event(item)
           ⑤ drain   → 非阻塞取空同批到达事件
           ⑥ catch_up → DB 查缺兜底
  finally: unsubscribe
```

完整代码见文件末尾附录 A。

---

### 3.3 `loop.py` — 局部修改

**改动点 1：`_persist_and_notify` 内部函数 `_write`**

```python
# 改前：
committed = CommittedEvent(
    run_id=run_id, seq=event.seq, event_type=event_type,
    payload=payload, created_at=event.created_at,
    id=event.id, attempt_id=attempt_id,
)
await event_repo.notify_run_event(run_id, event.__dict__["seq"])  # ← 删除这行

# 改后：
committed = EventItem(
    run_id=run_id, seq=event.seq, event_type=event_type,
    payload=payload, created_at=event.created_at,
    id=event.id, attempt_id=attempt_id,
)
# notify_run_event 调用已删除 — 不再需要 pg_notify
```

**改动点 2：`event_bus` 调用方式**

```python
# 改前（publish_after_commit 被删，agent_event_bus 被改名）：
await agent_event_bus.publish_after_commit(committed)

# 改后：
await event_bus.publish(committed)
```

**改动点 3：`_persist_terminal_and_notify` 中同样删除 `notify_run_event` 调用**

```python
# 改前（loop.py:138）：
await event_repo.notify_run_event(run_id, event.__dict__["seq"])  # ← 删除
await event_session.commit()
await event_bus.publish(committed)

# 改后：
await event_session.commit()
await event_bus.publish(committed)
```

**改动点 4：`_persist_successful_completion` 中同样删除**

```python
# 改前（loop.py:247）：
await event_repo.notify_run_event(run_id, run_succeeded_event.__dict__["seq"])  # ← 删除
await event_session.commit()

# 改后：
await event_session.commit()
```

**改动点 5：import 更新**

```python
# 改前：
from app.services.agent.event_bus import CommittedEvent, PersistedEvent, agent_event_bus

# 改后：
from app.services.agent.event_bus import EventItem, event_bus
```

**改动点 6：所有 `CommittedEvent(` → `EventItem(`**（名称统一）

---

### 3.4 `worker.py` — 局部修改

**改动点 1：`_mark_unhandled_attempt_failure` 中删除 `notify_run_event`**

```python
# 改前（worker.py:177）：
if event_ref is not None:
    run_id, seq = event_ref
    await repo.notify_run_event(run_id, seq)  # ← 删除
await session.commit()
if event_ref is not None:
    await event_bus.publish(EventItem(run_id=run_id, seq=seq))  # ← 缺字段

# 改后：
if event_ref is not None:
    run_id, seq = event_ref
await session.commit()
if event_ref is not None:
    await event_bus.publish(
        EventItem(
            run_id=run_id, seq=seq,
            event_type="run_failed",
            payload={"error": failure_code},
            created_at=datetime.now(UTC),
        )
    )
```

**改动点 2：import 更新**

```python
# 改前：
from app.services.agent.event_bus import PersistedEvent, agent_event_bus

# 改后：
from app.services.agent.event_bus import EventItem, event_bus
```

---

### 3.5 `agent_repository.py` — 删除方法

**删除 `notify_run_event` 方法（第 661-668 行）：**

```python
# 删除以下全部代码：
async def notify_run_event(self, run_id: uuid.UUID, seq: int, event_type: str = "", payload: dict[str, Any] | None = None) -> None:
    notify_payload = {"run_id": str(run_id), "seq": seq}
    if event_type:
        notify_payload["event_type"] = event_type
        notify_payload["payload"] = payload or {}
    await self.session.execute(
        func.pg_notify("agent_run_events", json.dumps(notify_payload))
    )
```

---

### 3.6 `main.py` — 删除 Listener 启动

**删除 lifespan 中的 postgres_event_listener 逻辑：**

```python
# 改前：
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_session_factory() as session:
        await seed_rbac(session)
        await session.commit()
    listener_task = None                          # ← 删除
    if settings.agent_event_listen_notify_enabled: # ← 删除
        listener_task = start_postgres_event_listener()  # ← 删除
    try:
        yield
    finally:
        if listener_task is not None:              # ← 删除
            await shutdown_postgres_event_listener(listener_task)  # ← 删除

# 改后：
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_session_factory() as session:
        await seed_rbac(session)
        await session.commit()
    yield
```

**同时删除 import：**

```python
# 改前：
from app.services.agent.postgres_event_listener import (
    shutdown_postgres_event_listener,
    start_postgres_event_listener,
)

# 改后：
# 整个 import 块删除
```

---

### 3.7 `__init__.py` — 更新导出

```python
# 改前 __all__ 包含：
"AgentEventBus", "PersistedEvent", "agent_event_bus"

# 改后 __all__ 包含：
"EventBus", "EventItem", "event_bus"
```

---

### 3.8 `postgres_event_listener.py` — 保持兼容

此文件不再被 `main.py` 引用，但保留在代码库中供将来多机部署使用。需更新引用：

```python
# 改前 import：
from app.services.agent.event_bus import CommittedEvent, PersistedEvent, PublishableEvent, agent_event_bus

# 改后 import：
from app.services.agent.event_bus import EventItem, event_bus
```

`parse_notification_payload` 返回值改为 `EventItem`（而非 `CommittedEvent | PersistedEvent | None`）。

---

## 四、测试文件改动详情

### 4.1 `test_agent_stream.py`（1 处）

```python
# 改前：
from app.services.agent.event_bus import AgentEventBus, PersistedEvent
bus = AgentEventBus(max_queue_size=4)
event = PersistedEvent(run_id=run_id, seq=1)
await bus.publish_after_commit(event)

# 改后：
from app.services.agent.event_bus import EventBus, EventItem
bus = EventBus(max_queue_size=4)
event = EventItem(run_id=run_id, seq=1, event_type="test", payload={}, created_at=datetime.now(timezone.utc))
await bus.publish(event)
```

需要新增 import：`from datetime import datetime, timezone`

### 4.2 `test_agent_stream_direct.py`（2 处）

```python
# 改前：
from app.services.agent.event_bus import CommittedEvent
event = CommittedEvent(run_id=..., seq=1, event_type="test", payload={}, created_at=..., id=..., attempt_id=...)

# 改后：
from app.services.agent.event_bus import EventItem
event = EventItem(run_id=..., seq=1, event_type="test", payload={}, created_at=..., id=..., attempt_id=...)
```

### 4.3 `test_agent_notify.py`（1 处）

删除整个 `notify_run_event` 测试函数（方法已不再存在）。

### 4.4 `test_agent_notify_integration.py`（3 处）

```python
# 改前：
from app.services.agent.event_bus import agent_event_bus
await agent_event_bus.subscribe(run_id)
await agent_event_bus.unsubscribe(run_id, subscriber_id)

# 改后：
from app.services.agent.event_bus import event_bus
await event_bus.subscribe(run_id)
await event_bus.unsubscribe(run_id, subscriber_id)
```

### 4.5 `test_agent_notify_sse.py`（3 处）

```python
# 改前：
from app.services.agent.event_bus import PersistedEvent
from app.services.agent.event_bus import agent_event_bus
event_bus = agent_event_bus
await event_bus.publish_after_commit(PersistedEvent(run_id=run_id, seq=1))

# 改后：
from app.services.agent.event_bus import EventItem, event_bus
await event_bus.publish(EventItem(run_id=run_id, seq=1, event_type="test", payload={}, created_at=datetime.now(timezone.utc)))
```

### 4.6 `test_agent_loop.py`（2 处）

```python
# 改前：
loop_module.agent_event_bus.publish_after_commit

# 改后：
loop_module.event_bus.publish
```

### 4.7 `test_agent_worker.py`（3 处）

```python
# 改前：
notify_run_event=AsyncMock(),
worker_module.agent_event_bus
repo.notify_run_event.assert_awaited_once_with(run_id, 42)

# 改后：
# notify_run_event mock 删除
worker_module.event_bus
# notify_run_event 断言删除
```

### 4.8 `test_postgres_event_listener.py`（1 处）

```python
# 改前：
from app.services.agent.event_bus import PersistedEvent

# 改后：
from app.services.agent.event_bus import EventItem
```

---

## 五、验证步骤

### 5.1 导入验证

```bash
cd C:\01_agent_loop_pro\backend
python -c "from app.main import app; print('import ok')"
```

### 5.2 单元测试

```bash
cd C:\01_agent_loop_pro\backend
python -m pytest tests/test_agent_stream.py tests/test_agent_stream_direct.py tests/test_agent_loop.py tests/test_agent_worker.py tests/test_agent_notify.py tests/test_agent_notify_integration.py tests/test_agent_notify_sse.py tests/test_postgres_event_listener.py -v
```

### 5.3 全量回归测试

```bash
cd C:\01_agent_loop_pro\backend
python -m pytest tests/ -v -k "not test_retryable_tool_failure"
```

### 5.4 前端构建验证

```bash
cd C:\01_agent_loop_pro\frontend
npx next build
```

---

## 六、回滚方案

所有改动均为结构替换（非逻辑创新）。如需回滚，`git checkout` 以下文件即可恢复：

```bash
git checkout HEAD -- backend/app/api/agent_stream.py
git checkout HEAD -- backend/app/services/agent/event_bus.py
git checkout HEAD -- backend/app/services/agent/loop.py
git checkout HEAD -- backend/app/services/agent/worker.py
git checkout HEAD -- backend/app/repositories/agent_repository.py
git checkout HEAD -- backend/app/main.py
git checkout HEAD -- backend/app/services/agent/__init__.py
git checkout HEAD -- backend/app/services/agent/postgres_event_listener.py
git checkout HEAD -- backend/tests/
```

---

## 附录 A：`agent_stream.py` 完整代码

```python
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from jose import JWTError
from pydantic import ValidationError
from sqlalchemy import select as sa_select

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.messages import Messages
from app.core.security import decode_access_token
from app.db.session import async_session_factory
from app.models.agent import AgentRun, AgentRunEvent
from app.models.rbac import User
from app.schemas.agent import AgentRunEventResponse
from app.services.agent.event_bus import event_bus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent Stream"])

settings = get_settings()

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "completed"}
HEARTBEAT_INTERVAL = 30.0
CATCH_UP_LIMIT = 200


def _parse_after_seq(cursor: str | None) -> int | None:
    if cursor is None:
        return None
    try:
        return int(cursor)
    except ValueError:
        raise ApiError(status_code=400, code="INVALID_CURSOR", message="无效的事件游标")


def _encode_sse_event(event: object) -> str | None:
    try:
        payload = AgentRunEventResponse.model_validate(event).model_dump(mode="json")
    except ValidationError:
        return None
    return f"id: {payload['seq']}\nevent: {payload['event_type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _validate_origin(request: Request) -> None:
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    allowed = [o.strip() for o in settings.cors_origins.split(",")]
    parsed_origin = None
    allowed_origins = set()
    try:
        origin_parts = urlsplit(origin)
        parsed_origin = (origin_parts.scheme, origin_parts.hostname, origin_parts.port)
    except ValueError:
        pass
    for allowed_origin in allowed:
        try:
            parts = urlsplit(allowed_origin)
            if parts.scheme and parts.hostname:
                allowed_origins.add((parts.scheme, parts.hostname, parts.port))
        except ValueError:
            continue
    if parsed_origin not in allowed_origins:
        raise ApiError(status_code=403, code="CSRF_VALIDATION_FAILED", message="无效的请求来源")


async def _authenticate_and_authorize(request: Request, run_id: uuid.UUID) -> AgentRun:
    token = request.cookies.get("access_token")
    if not token:
        raise ApiError(status_code=401, code="AUTHENTICATION_REQUIRED", message=Messages.AUTH_EXPIRED)
    try:
        payload = decode_access_token(token)
    except (JWTError, ValueError):
        raise ApiError(status_code=401, code="AUTHENTICATION_REQUIRED", message=Messages.AUTH_EXPIRED)
    user_id = uuid.UUID(payload.sub)
    async with async_session_factory() as session:
        user = await session.scalar(
            sa_select(User).where(User.id == user_id, User.is_deleted == False, User.status == "active")
        )
        if user is None:
            raise ApiError(status_code=401, code="AUTHENTICATION_REQUIRED", message=Messages.ACCOUNT_DISABLED)
        run = await session.scalar(
            sa_select(AgentRun).where(AgentRun.id == run_id, AgentRun.owner_user_id == user_id)
        )
        if run is None:
            raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="资源不存在")
        return run


async def _events_after(run_id: uuid.UUID, after_seq: int | None, limit: int = CATCH_UP_LIMIT) -> list[AgentRunEvent]:
    async with async_session_factory() as session:
        result = await session.execute(
            sa_select(AgentRunEvent)
            .where(
                AgentRunEvent.run_id == run_id,
                AgentRunEvent.seq > after_seq if after_seq is not None else True,
            )
            .order_by(AgentRunEvent.seq.asc())
            .limit(limit)
        )
        return list(result.scalars().all())


@router.get("/runs/{run_id}/stream")
async def stream_run_events(request: Request, run_id: uuid.UUID) -> StreamingResponse:
    run = await _authenticate_and_authorize(request, run_id)
    _validate_origin(request)

    last_event_id = request.headers.get("last-event-id")
    after_seq = request.query_params.get("after_seq")
    after_seq_val = _parse_after_seq(last_event_id or after_seq)

    async def event_generator():
        last_seen_seq = after_seq_val
        subscriber_id = None
        try:
            # Phase 1: replay historical events
            replay_events = await _events_after(run_id, after_seq_val)
            for event in replay_events:
                encoded = _encode_sse_event(event)
                if encoded is None:
                    continue
                last_seen_seq = event.seq
                yield encoded

            # Phase 2: subscribe to real-time events
            subscriber_id, queue = await event_bus.subscribe(run_id)

            # Phase 3: fill gap between replay and subscribe
            catch_up_events = await _events_after(run_id, last_seen_seq)
            for event in catch_up_events:
                encoded = _encode_sse_event(event)
                if encoded is None:
                    continue
                if last_seen_seq is not None and event.seq <= last_seen_seq:
                    continue
                last_seen_seq = event.seq
                yield encoded

            # Phase 4: live loop
            while True:
                # Drain any events already in the queue (non-blocking)
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

                # Check run status
                async with async_session_factory() as session:
                    result = await session.execute(
                        sa_select(AgentRun.status).where(AgentRun.id == run_id)
                    )
                    status = result.scalar_one_or_none()
                if status is None or status in TERMINAL_STATUSES:
                    events = await _events_after(run_id, last_seen_seq)
                    for event in events:
                        encoded = _encode_sse_event(event)
                        if encoded is None:
                            continue
                        last_seen_seq = event.seq
                        yield encoded
                    break

                # Wait for next event with heartbeat timeout
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                except asyncio.TimeoutError:
                    yield ":keepalive\n\n"
                    events = await _events_after(run_id, last_seen_seq)
                    for event in events:
                        encoded = _encode_sse_event(event)
                        if encoded is None:
                            continue
                        last_seen_seq = event.seq
                        yield encoded
                    continue

                # Process the event
                item_seq = getattr(item, "seq", None)
                if item_seq is None or (last_seen_seq is not None and item_seq <= last_seen_seq):
                    continue
                encoded = _encode_sse_event(item)
                if encoded is None:
                    continue
                last_seen_seq = item_seq
                yield encoded

                # Drain additional events that arrived simultaneously
                while True:
                    try:
                        extra = queue.get_nowait()
                        extra_seq = getattr(extra, "seq", None)
                        if extra_seq is None or (last_seen_seq is not None and extra_seq <= last_seen_seq):
                            continue
                        encoded = _encode_sse_event(extra)
                        if encoded is None:
                            continue
                        last_seen_seq = extra_seq
                        yield encoded
                    except asyncio.QueueEmpty:
                        break

                # Catch-up query for any missed events
                events = await _events_after(run_id, last_seen_seq)
                for event in events:
                    encoded = _encode_sse_event(event)
                    if encoded is None:
                        continue
                    last_seen_seq = event.seq
                    yield encoded
        finally:
            if subscriber_id is not None:
                await event_bus.unsubscribe(run_id, subscriber_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

---

## 附录 B：改动量统计

| 文件 | 类型 | 改动行数 |
|------|------|---------|
| `event_bus.py` | 重写 | -72 +55 |
| `agent_stream.py` | 重写 | -346 +276 |
| `loop.py` | 修改 | -6 行 |
| `worker.py` | 修改 | -2 +6 |
| `agent_repository.py` | 删除方法 | -8 |
| `main.py` | 删除 | -9 |
| `__init__.py` | 修改 | -3 +3 |
| `postgres_event_listener.py` | 修改 | -3 +2 |
| 7 个测试文件 | 修改 | ~20 |
| **合计** | | **约 -100 行净减少** |
