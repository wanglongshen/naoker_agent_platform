# 提交到首个可见输出的等待时间优化方案

> 目标：缩短用户点击发送到看到第一个思考文字之间的空白等待  
> 范围：配置级优化 + 前端即时反馈，不动架构

---

## 一、等待时间分解（实测）

```
阶段                     耗时            可优化？
─────────────────────────────────────────────────
POST create session      ~100ms          否（HTTP + DB）
POST create run          ~100ms          否（HTTP + DB）
页面跳转 + SSE 握手      ~200ms          否（浏览器渲染）
Worker 轮询认领          0-1000ms        是 ← 主要优化点
Planner → DeepSeek       2000-5000ms     否（LLM 固有延迟）
发出第一个 visible_thought
─────────────────────────────────────────────────
合计（典型）             2500-6500ms
平均等待                 约 4.5 秒
```

**可优化空间：Worker 轮询间隔（1.0s → 0.1s），省 900ms。**

Planner LLM 的 2-5 秒是 DeepSeek API 固有延迟，没法从代码层面缩短。

---

## 二、方案：缩短 Worker 轮询间隔

### 当前配置

```python
worker_poll_interval_seconds: float = 1.0
```

Worker 主循环：`claim → sleep(poll_interval) → claim → sleep → ...`

每次睡 1 秒，最坏情况刚睡下就有新 run，要等 1 秒才认领。

### 优化后

```python
worker_poll_interval_seconds: float = 0.1
```

| 指标 | 改前 | 改后 |
|------|------|------|
| 最短等待 | ~0ms | ~0ms |
| 最长等待 | 1000ms | 100ms |
| 平均等待 | 500ms | 50ms |
| CPU 影响 | 忽略不计 | 忽略不计（poll 只是 `SELECT ... LIMIT 1`） |

### 为什么 0.1 秒而不是 0.01 秒

- 0.01 秒 = 每秒 100 次 DB 查询，空转时浪费连接池
- 0.1 秒 = 每秒 10 次 DB 查询，完全可接受
- 0.1 秒对用户感知而言 ≈ "瞬间"（浏览器 60fps = 16.7ms/帧，10 帧）

### 改动

| 文件 | 改动 |
|------|------|
| `backend/app/core/config.py` | `worker_poll_interval_seconds: 1.0 → 0.1` |
| `backend/.env.example` | 文档更新 |

**一行改动，省 900ms。**

---

## 三、前端即时反馈（不改代码，仅认知）

当前前端已有此能力，无需改动：

```
用户发送 → composer 禁用 + "发送中" → session + run 创建完成 → 跳转
                                                      ↓
                                              SSE 连接 + "等待中" 标签
                                                      ↓
                                              Worker 认领 → "思考中" 标签
```

跳转后到 Worker 认领前的空白期，前端已经显示"等待中"。改 Worker 轮询后，这个空白从 1000ms 降到 100ms——用户几乎感觉不到。

---

## 四、不可优化的部分（说明原因）

| 阶段 | 为什么不动 |
|------|-----------|
| DeepSeek Planner | 模型推理延迟，非代码层面 |
| HTTP + DB 写入 | 必须的持久化步骤 |
| 页面跳转 + 渲染 | 浏览器渲染流程 |

---

## 五、Pro 方案（将来参考，不纳入本次）

如果 0.1s 仍不够，可考虑：

**A. Worker 订阅 DB 通知（异步唤醒）**
- Run 创建后 `pg_notify('new_run', run_id)`
- Worker `LISTEN new_run` → 收到立刻认领
- 延迟从 100ms 降到 1-5ms
- 需要恢复之前删除的 listener 基础设施

**B. 预测式预连接 SSE**
- 前端在 session 创建后立刻打开 SSE（不等 run 创建）
- 但 SSE 需要 run_id，当前架构不适用

---

## 六、验证

```bash
cd backend && python -m pytest tests/test_agent_worker.py -v
```
