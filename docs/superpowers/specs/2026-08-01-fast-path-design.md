# 企业级快速回答架构设计（Fast Path）

**Date:** 2026-08-01
**Status:** approved

## 1. 问题

当前每个请求执行 3 次串行 LLM 调用：Planner(2-5s) → 可见思考(1-3s) → 答案(5-15s)。用户感知"思考时间长"，根源是 Planner 阶段 UI 静止 2-5 秒。

## 2. 目标

| 场景 | 现状 | 目标 |
|------|------|------|
| 直接回答型问题（~70%） | 8-15s 首字 | **1-3s 首字** |
| 工具型问题（~30%） | 10-20s | 10-20s（不变，二期优化） |

## 3. 目标架构

```
发消息
  ↓
快速路由闸门（毫秒级，非 LLM）
  ├── 通过 → 模式A：单次流式直出答案（本轮实现）
  └── 不通过 → 模式B：现有流程（Planner→思考→工具→答案）
```

### 模式 A：乐观直答 + 自路由（核心）

不依赖脆弱的关键词启发式，而是**让 LLM 自己声明**是否需要工具：

```
1. 流式调用一次（system prompt 强化）：
   "直接输出最终答案。若此问题需要网络搜索、读取文件或其他工具
    才能准确回答，第一句必须输出【需要工具】。"
2. 第一个 chunk 到达：
   ├── 含【需要工具】→ 丢弃已收文本，回退到模式B（损失 ~1-2s）
   └── 正常文本 → 继续流式输出答案（1-3s 首字）
3. 正常完成 → answer_completed → run_succeeded
```

**误判代价分析：** 70% 直接回答省 4-8s；30% 工具问题多花 1-2s（一次废弃的 LLM 调用）。净收益为正且无正确性损失。

### 快速路由闸门（模式 A 的前置门槛）

保守启发式，宁可漏判（走模式B）不可错判（答错）：

```python
def should_try_direct_answer(goal: str, has_attachments: bool, mode: str) -> bool:
    if has_attachments:
        return False                     # 有附件必然涉及文件
    if mode != "quick":
        return False                     # expert 模式保留完整流程
    if len(goal) > 200:
        return False                     # 长问题可能复杂
    return True                          # 其余交给 LLM 自路由兜底
```

## 4. 后端改动

### 4.1 `loop.py` — 主流程改造

`_do_process_attempt` 在 planner 之前插入：

```python
if should_try_direct_answer(goal=run.goal, has_attachments=bool(attachments), mode=mode):
    direct_answer = await self._try_direct_answer(
        repo, ctx, run.goal, session_history, step_index, owner_user_id, is_super_admin,
    )
    if direct_answer is not None:
        return
    # direct_answer 返回 None → 模型声明需要工具 → 落入常规 planner 流程
```

### 4.2 新增 `_try_direct_answer`

```python
async def _try_direct_answer(self, repo, ctx, goal, session_history, step_index, owner_user_id, is_super_admin):
    stream_id = f"answer-{ctx.run.id}"
    await self._persist_and_notify(repo, ctx, "answer_started", {"stream_id": stream_id})

    messages = self._build_direct_answer_messages(goal, session_history)
    answer = ""
    first_chunk = True
    needs_tool = False
    checkpointed_offset = 0
    last_checkpoint_time = time.monotonic()
    pending_chunks: list[str] = []
    last_flush_time = time.monotonic()

    async def flush_deltas(force: bool = False) -> None:
        # 复用 _stream_final_answer 的 20ms 批量逻辑（复制实现）
        ...

    async for chunk in self.llm_client.stream_text(messages):
        if first_chunk:
            first_chunk = False
            if chunk.startswith("【需要工具】") or "【需要工具】" in chunk[:30]:
                needs_tool = True
                await self._persist_and_notify(repo, ctx, "answer_failed",
                    {"stream_id": stream_id, "error": "tool_needed", "offset": 0})
                return None
        answer += chunk
        pending_chunks.append(chunk)
        await flush_deltas()
        # checkpoint 逻辑同 _stream_final_answer

    await flush_deltas(force=True)
    await self._persist_and_notify(repo, ctx, "answer_completed",
        {"stream_id": stream_id, "text": answer, "length": len(answer)})
    await self._persist_successful_completion(
        ctx=ctx, answer=answer, stream_id=stream_id, step_number=step_index,
        thought_summary="", action_type="finish", action_payload={},
        observation={"final_answer": answer}, step_duration_seconds=0.0,
    )
    return answer
```

### 4.3 新增 `_build_direct_answer_messages`

在 `_build_final_answer_messages` 基础上改 system prompt：

```python
"你是一个智能助手。直接输出最终答案，必须使用简体中文。"
"若此问题需要网络搜索、读取文件或其他工具才能准确回答，"
"第一句必须严格输出【需要工具】四个字，然后停止。"
"不需要工具时，直接输出 Markdown 正文，不要用代码块包裹。"
```

### 4.4 配置开关

`config.py` 新增：

```python
fast_path_enabled: bool = True   # 总开关，可紧急关闭
```

## 5. 前端改动（最小）

| 场景 | 行为 |
|------|------|
| 模式A 进行中 | 思考区显示"正在生成回答"，答案区流式逐字显示（现有打字机+Markdown 渐进渲染直接复用） |
| 模式A 回退模式B | `answer_failed` → 前端已处理（connection: reconnecting），随后 planner 事件到达，思考区自然切换 |

**无结构性改动。** 现有 `answer_started/delta/completed` 链路、打字机、渐进 Markdown 全部复用。

## 6. 边界与错误处理

| 场景 | 处理 |
|------|------|
| 模型未按约定输出【需要工具】却答错 | 正确性风险=普通直接回答，可接受（与原 finish 路径等价） |
| 流式中断（RetryableStreamingError） | 复用现有 3 次重试 + 兜底文案 |
| 直接回答为空 | 回退模式B |
| 生产环境问题 | `fast_path_enabled=False` 一键回退旧流程 |

## 7. 测试策略

| 层级 | 用例 |
|------|------|
| 单元 | `should_try_direct_answer` 各分支（附件/模式/长度） |
| 单元 | `_try_direct_answer` 首 chunk 含【需要工具】→ 返回 None |
| 单元 | `_try_direct_answer` 正常流 → 完整 answer + run 成功 |
| 集成 | 模式A 完成路径：answer_started→deltas→completed→succeeded |
| 集成 | 模式A 回退路径：answer_failed→planner 接管 |

## 8. 二期（另行立项）

- 模式B 合并：Planner + 可见思考合并为一次调用（function calling 风格）
- 多步工具链的流式决策展示

## 9. 影响文件清单

| 文件 | 改动 |
|------|------|
| `backend/app/core/config.py` | 加 `fast_path_enabled` |
| `backend/app/services/agent/loop.py` | 主流程插入闸门 + `_try_direct_answer` + `_build_direct_answer_messages` |
| `backend/app/services/agent/loop.py` | `_persist_successful_completion` 签名兼容（thought_summary 传空串） |
| 前端 | 无（可选：思考区文案） |
| `backend/tests/test_agent_loop.py` | 新增测试类 |
