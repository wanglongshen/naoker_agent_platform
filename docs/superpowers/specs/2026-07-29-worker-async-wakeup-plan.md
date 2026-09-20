# Worker 异步唤醒：DB 通知方案

> 目标：Run 创建后即时唤醒 Worker，消除轮询延迟  
> 原则：仅恢复必要的 DB 通知基础设施，不引入完整 EventBus 跨进程桥接

---

## 一、当前流程 vs 优化后流程

### 当前

```
POST /runs → INSERT run + attempt → COMMIT
              ↓
Worker:  sleep(1s) → wake → SELECT claim_next_attempt → found!
              ↓
         平均 500ms 延迟（0-1000ms 均匀分布）
```

### 优化后

```
POST /runs → INSERT run + attempt → COMMIT → pg_notify('new_run', run_id)
              ↓                                        ↓
Worker:  asyncio.Event.wait(timeout)  ← 收到通知，立即唤醒
              ↓
         SELECT claim_next_attempt → found!
              ↓
         延迟 1-5ms（DB notify 传播时间）
```

---

## 二、架构设计

### 2.1 新增 channel：`new_run`

```
channel: new_run
payload: run_id（字符串 UUID）

触发时机：POST /api/agent/sessions/{id}/runs 提交后
消费者：  AgentWorker（asyncpg LISTEN）
```

与旧 `agent_run_events` channel 的区别：
- 旧 channel：每个事件都发，高频，需要复杂解析
- 新 channel：只在 run 创建时发一次，极低频，payload 简单

### 2.2 Worker 改动

**新增：** `_new_run_event`（asyncio.Event）

```python
class AgentWorker:
    def __init__(self, ...):
        ...
        self._new_run_event = asyncio.Event()  # 新增
    
    async def _listen_new_runs(self, dsn):
        """asyncpg LISTEN 监听 new_run channel"""
        conn = await asyncpg.connect(dsn=dsn)
        await conn.add_listener("new_run", lambda *_: self._new_run_event.set())
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(1)
        finally:
            await conn.close()
    
    async def run(self):
        ...
        # 启动监听协程
        listen_task = asyncio.create_task(self._listen_new_runs(dsn))
        try:
            while not self._stop_event.is_set():
                recovered = await self._recover_expired()
                claimed = await self._claim_and_execute()
                if not claimed:
                    self._new_run_event.clear()
                    try:
                        await asyncio.wait_for(
                            self._new_run_event.wait(),
                            timeout=settings.worker_poll_interval_seconds,
                        )
                    except asyncio.TimeoutError:
                        pass
        finally:
            listen_task.cancel()
            await self._shutdown()
```

**关键：** `asyncio.Event.wait()` + `pg_notify` → 收到通知立刻唤醒。无通知时退化为 poll（`timeout=1.0`），保证 eventual consistency。

### 2.3 POST run 端点改动

在 `create_run` 中，commit 后 emit notify：

```python
# agent.py create_run
run, _, _ = await repo.create_run_with_attempt(...)
await db.execute(func.pg_notify("new_run", str(run.id)))  # ← 新增一行
return success(...)
```

---

## 三、文件变更

| 文件 | 改动 | 行数 |
|------|------|------|
| `api/agent.py` | `create_run` 中加 `pg_notify("new_run", run_id)` | +1 |
| `services/agent/worker.py` | Worker 加 `_new_run_event` + `_listen_new_runs` | +25 |
| `requirements.txt` | 确认 `asyncpg` 已在依赖中 | 0 |

---

## 四、为什么不用之前删掉的 postgres_event_listener

之前删掉的 `postgres_event_listener.py` 监听的是 `agent_run_events` channel，用于跨进程转发每个事件（高频、复杂解析）。新方案监听 `new_run` channel，仅在 run 创建时触发一次（极低频、无解析），不需要之前的复杂基础设施。

---

## 五、降级与容错

| 场景 | 行为 |
|------|------|
| asyncpg 连接失败 | `_listen_new_runs` 退出，Worker 退化为纯 poll（timeout 兜底） |
| pg_notify 丢失 | Event 不触发，timeout 到期后 poll 认领（最多等 1 秒） |
| Worker 重启 | LISTEN 重新注册，无历史堆积 |
| 多 Worker | 每个 Worker 独立 LISTEN，竞争认领（原子 `claim_next_attempt`） |

---

## 六、验证

```bash
# 1. Worker 启动，观察日志
cd backend && python -m app.workers.agent_worker

# 2. 创建 run，观察 Worker 是否立即认领（< 50ms）
# 3. 断网测试：asyncpg 断开 → Worker 继续 poll，不崩溃
# 4. 单元测试
cd backend && python -m pytest tests/test_agent_worker.py -v
```
