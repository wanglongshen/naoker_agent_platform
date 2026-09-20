# Agent Loop 异常保护增强方案

> 目标：任何异常（含 DeepSeek 不可达）都提供用户可见的反馈，而非静默失败  
> 原则：失败时有思考过程展示，不在空白页面上只显示"未完成"

---

## 一、问题诊断

### 当前错误传播链

```
planner.next_action()    ← DeepSeek API 调用
  │
  ├─ RetryablePlannerError → _schedule_retryable_failure → emit run_retry_scheduled → OK
  │
  └─ httpx.ConnectError  ← NOT RetryablePlannerError，直接绕过 catch
       │
       └─ propagate → _process_attempt_internal 无外层 catch
            └─ propagate → Worker._execute_claimed_attempt
                 └─ _mark_unhandled_attempt_failure("worker_unhandled_error")
                      └─ 只写 run_failed 事件，无任何思考过程
                           用户看到："未完成" + 空白
```

### 根因

1. `_process_attempt_internal` 没有外层 try/except——任何未分类异常直接炸到 Worker
2. planner 异常只 catch `RetryablePlannerError`——连接错误等不在此类
3. 失败时无思考过程展示——用户看不到任何信息

---

## 二、解决方案

### 2.1 `_process_attempt_internal` 外层保护

```python
async def _process_attempt_internal(self, repo, ctx):
    try:
        # ... 现有全部逻辑 ...
    except Exception as exc:
        # 发射可见思考：告诉用户出错了
        error_msg = f"系统执行过程中遇到错误：{str(exc)[:200]}"
        await self._persist_and_notify(repo, ctx, "visible_thought_started",
            {"step_index": 0, "stream_id": f"error-{ctx.run.id}"})
        await self._persist_and_notify(repo, ctx, "visible_thought_delta",
            {"step_index": 0, "stream_id": f"error-{ctx.run.id}", "offset": 0, "delta": error_msg})
        await self._persist_and_notify(repo, ctx, "visible_thought_completed",
            {"step_index": 0, "stream_id": f"error-{ctx.run.id}", "text": error_msg, "length": len(error_msg), "fallback": True})
        # 标记失败
        await self._persist_terminal_and_notify(
            repo, ctx, "run_failed", {"error": str(exc)[:200]},
            "failed", "failed", failure_code=classify_agent_failure(exc),
        )
```

**效果：** 任何未处理异常→用户看到"系统执行过程中遇到错误：httpx.ConnectError..."→思考区域不再空白。

### 2.2 planner 异常扩大 catch 范围

```python
# 改前：只 catch RetryablePlannerError
except RetryablePlannerError as exc:
    ...

# 改后：catch 所有 planner 异常，先尝试重试
except RetryablePlannerError as exc:
    ...  # 原有重试逻辑
except Exception as exc:
    # 非标准规划器错误（如 HTTP 连接失败）
    # 尝试一次重试
    if await self._schedule_retryable_failure(repo, ctx, exc):
        return
    # 重试也失败，外层 catch 会处理
    raise
```

**效果：** `httpx.ConnectError` 现在也走重试通道（指数退避），不再直接炸。

### 2.3 Worker 兜底增强

```python
# _mark_unhandled_attempt_failure 在标记失败前也发一个简单事件
async def _mark_unhandled_attempt_failure(self, attempt_id, failure_code):
    ...
    if event_ref is not None:
        run_id, seq = event_ref
    # 发射一个 answer_started + answer_failed 让前端有内容展示
    ...
```

---

## 三、改动范围

| 文件 | 改动 | 行数 |
|------|------|------|
| `loop.py:_process_attempt_internal` | 外层 try/except + 错误可见思考 | +15 |
| `loop.py:_process_attempt_internal` | planner except 加 Exception catch + 重试 | +3 |
| `worker.py:_mark_unhandled_attempt_failure` | 发 answer_started + answer_failed 事件 | +5 |

---

## 四、效果

```
改前: DeepSeek 不可达 → 空白思考区 + "未完成"（用户不知道发生了什么）
改后: DeepSeek 不可达 → 思考区显示"系统执行过程中遇到错误" → "未完成"（用户看到原因）
      + 自动重试一次（指数退避）
```
