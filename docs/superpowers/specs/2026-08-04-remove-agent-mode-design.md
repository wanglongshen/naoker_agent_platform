# 移除 quick/expert 模式概念设计

**日期：** 2026-08-04
**状态：** 已批准（brainstorming 完成）

## 背景

用户报告"AI 写完整方案"任务反复失败（"步数已达上限无法补齐"）。根因链（DB 实测）：

1. 所有 run 均为 `mode: quick`
2. `_run_policy`（loop.py:325-333）对 quick 强制 `effective_max_steps = min(max_steps, 5)` = 5 步
3. 完整方案任务（读 brief → 写 8 模块方案 → 被拒重试）在 5 步内必然无法完成
4. 09:01 实测 run：read(1) → write 被拒(2) → read(3) → write 被拒(4) → finish(5) 步数耗尽

quick/expert 是历史遗留的"快速问答 vs 深度研究"概念，实际 UI 中专家模式按钮无独立入口（`agent-mode-controls.tsx` 全仓无引用，`chat-composer.tsx:96` 硬编码 `mode: "quick"`）。模式概念不再需要，全部任务应获得完整执行空间。

## 设计

### 核心决策

- **所有 run 一律走完整 `max_steps`（默认 30）**，无 5 步限制
- DB 列 `agent_runs.mode` **保留**（历史数据兼容），新 run 固定写入 `"expert"`（语义"完整执行"），**不做数据库迁移**
- API 不再接收 mode 字段（前端不再传）
- 前端不再显示模式切换 UI 与模式标签

### 后端改动

| 文件 | 改动 |
|---|---|
| `backend/app/services/agent/loop.py` | `_run_policy` 简化：删模式分支，签名改为 `(web_enabled: bool, max_steps: int) -> tuple[bool, int]`（不再返回 mode）；调用处 `mode, web_enabled, effective_max_steps = self._run_policy(...)` → `web_enabled, effective_max_steps = self._run_policy(run, max_steps)` |
| `backend/app/services/agent/planner.py` | 删 `mode_policy` 变量（185-189 行）及其在 system_prompt 中的拼接（198 行）；若 `mode` 参数因此不再被使用，从 `_build_messages` 签名删除（先确认其他用途） |
| `backend/app/schemas/agent.py` | 删 `AgentMode = Literal["quick", "expert"]`（11 行）；`AgentRunCreate` 删 `mode: AgentMode = "quick"`（49 行）；`AgentRunResponse.mode: str` 保留（历史展示） |
| `backend/app/api/agent.py` | `create_run`（262-268 行）不再传 `data.mode` |
| `backend/app/repositories/agent_repository.py` | `create_run_with_attempt` 的 `mode: str` 参数改默认 `mode: str = "expert"`（160-167 行），调用处不传 |

### 前端改动

| 文件 | 改动 |
|---|---|
| `frontend/src/components/agent/agent-mode-controls.tsx` | **删除整个文件**（已确认全仓无引用） |
| `frontend/src/types/agent.ts` | 删 `AgentMode` 类型（13 行）；`AgentRun.mode: AgentMode` → `mode: string`（32 行） |
| `frontend/src/components/agent/chat-composer.tsx` | `onSubmit` 签名 `{ goal: string; mode: AgentMode; attachmentIds }` → 删 `mode`（45 行）；`handleSubmit` 删 `mode: "quick"`（96 行）；删 `import type { AgentMode }`（9 行） |
| `frontend/src/components/agent/new-conversation-composer.tsx` | onSubmit 解构删 `mode`，formData 不再 set `mode`（20-24 行） |
| `frontend/src/app/(agent)/agent/page.tsx` | `handleSubmit` 签名删 `mode`（14、19 行） |
| `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx` | `handleContinue` 签名删 `mode`（84、90 行）；102-105 行附近的 `mode: "quick"` 删除（先确认上下文） |
| `frontend/src/components/agent/run-header.tsx` | 删"快速模式"标签（30-31 行） |
| `frontend/src/app/(agent)/agent/audit/runs/[runId]/page.tsx` | 删 `Descriptions.Item label="模式"`（174 行） |
| `frontend/src/components/governance/governance-transcript.tsx` | `modeLabel` 函数与使用处删除（26-27、80、131 行）——确认该组件是否仍展示模式；若 mode 字段不再有前端语义可保留展示但简化 |

### 测试同步

**后端：**
- `backend/tests/test_agent_tools.py`：411-432 行 `_run_policy` 断言重写（新签名 `(web_enabled, steps)`；quick 不再缩步数 → `_run_policy(run, 12) == (True, 12)` 之类）；591-612 行同；588-591 行 `request.mode == "quick"` 断言调整
- `backend/tests/test_agent_repository.py:107`：`run.mode == "expert"`（若该测试创建 run 时传了 mode 则适配默认值）
- 其他引用 mode 的测试（grep `mode` 于 tests/）逐个核对

**前端：**
- `chat-composer.test.tsx`：120-141 行 "fixed quick mode" 描述测试（126-141）改断言不再含 mode
- `agent-api.test.ts`：89-131 行 `mode: "quick"` 从请求体断言中移除
- `agent-page.test.tsx`、`audit-pages.test.tsx`、`agent-session-view.test.ts`、`use-run-event-stream.test.ts`、`agent-streaming.test.tsx`、`run-diagnostics.test.tsx`、`governance-transcript.test.tsx`、`run-stream-reducer.test.ts`、`sessions/[sessionId]/page.test.tsx` 等 mock run 对象中的 `mode: "quick"` 字段：因 `AgentRun.mode` 保留为 `string`，**mock 数据无需删除**（兼容）；仅类型引用 `AgentMode` 的测试需调整

### 数据流

```
前端输入 goal → API 不传 mode → 后端 run.mode="expert" → _run_policy 恒 max_steps=30
→ 完整 30 步执行（读文件/写方案/被拒重试都够）→ 保存成功 → run_succeeded
```

### 关键效果

- **"5 步写不完方案"问题根除**：方案任务最多 30 步
- 历史 run 显示不受影响（mode 列保留，值为 quick 的历史 run 前端不再展示模式标签）
- 不做 DB 迁移、不删列、不动 worker

### 范围外（YAGNI）

- 本次只解决步数限制问题
- "模型写不全 8 模块被拒循环"与"保存失败时模型撒谎声称成功"是独立问题，后续单独设计（已知）
- 不删 `agent_runs.mode` 列（历史数据 + 审计保留）
