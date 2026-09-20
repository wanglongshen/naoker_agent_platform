# LangGraph 编排重构设计（2026-08-27）

## 0. 决策摘要

- **目标**：满足团队"必须使用 LangGraph"的组织/标准化需求，将 agent 编排层的**控制流决策**迁移到 LangGraph `StateGraph`；框架无关原语（SSE 流式、工具执行、计费、retry 状态机、双通道推送、DB 事件溯源）**原样保留**。
- **形态**：形态B"真图演化"——行为逻辑真正进图（图=编排决策层），不是把旧 while 循环包一层壳。
- **外部行为契约**：SSE 开关时序、事件字节/顺序/offset、usage 计费、JSON 结构、各门禁触发与提示、每步事件序列、最终 answer——**逐字节保真**。
- **5 个关键裁决**（详见各节）：①图只表达"一次 attempt 内 step 循环的编排决策"，attempt 层（retry/租约/事件溯源）留在图外；②`awaiting_question` 不使用 LangGraph `interrupt`；③状态保持扁平单层 TypedDict + reducer，不拆子图；④P0 交付**逐字节差分保真器**（同输入→旧 while+新图双跑→事件流 diff）作为正确性证据；⑤每步循环内的"流式-工具-续流穿插"保持单胖节点，不硬拆。
- **实现分批**：P0 基建 → P1 状态迁移 → P2 全量边 → P3 对齐。每步可验证增量，且现有测试几乎不动。

## 1. 背景与动机

- 团队要求引入 LangGraph（组织/标准化/学习动机，与 2026-08-10 LangChain 实验同源）。
- 现状：`backend/app/services/agent/loop.py`（2454 行）是自研编排循环。价值层（SSE 流式、事件审计、双通道推送、usage 计费、调研门、骨架预填、自审门、workflow stage 门、save intent 强制、retry 状态机）**全部框架无关**且已被 TDD 打磨（13 个测试文件）。
- LangChain 实验结论（`docs/superpowers/specs/2026-08-10-langchain-demo-design.md`）：生产热路径不宜直接换框架——计费 usage 透传、JSON 结构化、SSE 流式三条关键路径存在重适配风险。LangGraph 相比 LangChain 是更底层的**编排替换**，风险更高，故本设计以"测试作契约（形态B 放宽少数内部耦合断言）+ 差分保真器"双保险控制风险。
- 用户裁决链：方案A（全量替换编排）→ 测试作契约 → 形态B（真图演化，外部行为逐字节保真，仅放宽内部结构耦合断言）。

## 2. 范围

### 做
- 用 LangGraph 重构**一次 attempt 内的 step 循环编排**：把 while 循环的决策点（plan → gate → execute → quality→ plan / finish / retry / terminal / awaiting_question）映射为 `StateGraph` 节点 + 条件边。
- 新建 `backend/app/services/agent/langgraph_runner.py`（图定义、编译、状态 reducer、节-边装配）。
- 内部耦合抽换：`_RunWorkflowState` + `_AttemptContext`（迁移字段）→ LangGraph typed State + reducer。
- 差分保真器：同输入双跑旧 while 与新图，逐字节 diff 事件流，产出等价性报告/断言。
- feature flag（如 `settings.langgraph_enabled`）控制新旧引擎并轨切换。
- 依赖 `langgraph`（含 checkpoint/persistence 可选组件）装入 01-rbac conda 环境。

### 不做（YAGNI）
- 不迁移 attempt 层：retry/租约/事件溯源/attempt 状态机、worker 调度、`_schedule_retryable_failure`、`agent_run_events_seq`。
- 不使用 LangGraph `interrupt`（awaiting_question 保持现有 DB pause + `run_awaiting_question` 事件）。
- 不拆子图/子状态（保持单层扁平 State，逐 step 全量返回 "last" 通道）。
- 不迁移双通道推送/EventBus/DB 持久化/审计机制——它们保持现行架构。
- 不迁移 planner/tool_executor/quality_review/plan_structure 等"工具与原语"实现。
- 不引入多智能体（supervisor/worker graph）等 LangGraph 高阶特性。

## 3. 架构总览

```
[worker 驱动: process_attempt → _do_process_attempt 的 attempt 层]
   ↓  一切 attempt 级守卫（cancel/timeout/retry 调度/租约/事件溯源）留在图外
┌─────────────────────────────────────────────┐
│  LangGraphRunner（一次 attempt 内 step 循环） │
│                                             │
│  State = {                                  │
│    workflow: {...receipts / flags / stage}, │  ← 逐 step 全量返回（"last"）
│    attempt_ctx: {blueprint_injected,        │
│      researched, skeleton, blueprint_full,  │
│      project_name, llm_tokens},             │
│    step_index, previous_observation,        │
│    wrote_file, step_journal, web_enabled,   │
│    effective_max_steps, session_history,    │
│    attachments, terminal, pending_action,   │
│    pre_generated_thought, _gate_retry,      │
│    _retryable, step_duration_seconds,       │
│  }                                          │
│                                             │
│  plan → execute → (finish → finalize │  ← 单步引擎：一次 ainvoke = 一个 step
│           │ finish → end)           │     driver 在外层循环
│  （route_after_plan / route_after_execute）│
└─────────────────────────────────────────────┘
   ↓ 原语/事件/持久化在节点内部调用现有实现
EventBus(实时) + PostgreSQL(安全网/溯源) + SSE
```

## 4. 节点设计（行为逻辑真正进图）

节点**复用现有方法**作为叶子，但由图装配编排决策。图是**单步引擎**：一次 `ainvoke` 只处理一个 step，`plan → execute → (finish → finalize | end)`；attempt 层（load_context/cancel/timeout/stage/attachment/direct-answer/retry 调度）由 driver `_do_process_attempt_graph` 在外层循环。

| 节点 | 行为（复用现有实现） | 输出 |
|---|---|---|
| `plan` | `_build_messages`/`_build_merged_messages`/`_stream_planning`、`_stream_merged_plan_thought`、`_normalize_plan`、`_validate_plan`、`_enforce_final_step`/`_enforce_save_intent`/`_enforce_stage_gate`（在 try 内，可纠正 gate→`_gate_retry`）、`plan_created` 事件 | plan dict（`pending_action`），或 `_gate_retry`（可纠正）/broad-exception→`_retryable` |
| `execute` | **内部保留"流式-工具-续流穿插"**：`visible_thought` → 工具执行 → resume → 保存回读校验 → research/save 置位 → `step_completed` 事件 | (previous_observation, workflow 状态置位, step_index+1, wrote_file, step_journal, step_duration_seconds)；错误路径 `_retryable`/`terminal=failed` |
| `finalize` | finish 分支：`_merge_save_answer`、`_enforce_answer_truthfulness`、`_persist_successful_completion` | 终态 `terminal=finish` |

> `execute` 保持"胖节点"是刻意设计：流式+工具+续流是**框架无关原语卖点**，硬拆成节点拿不到编排价值，只会破坏字节级事件顺序。`quality_review` 不单独成节点，在 `_execute_one_step` 内调用（同 live loop）。

## 5. 条件边（单步引擎）

- `plan` → `route_after_plan`：`_gate_retry` 时 → `end`（driver 记录 observation + journal 后重新规划）；否则 → `execute`。
- `execute` → `route_after_execute`：`action.type == "finish"` → `finalize`；否则 → `end`（driver 步进后循环下一 step）。`pending_action` 被终端失败清空时 → `end`（不误入 finalize）。
- 终态/att attempt 级：`cancel` → `run_cancelled`；`timeout` → `run_failed`；`max_steps` ≥ effective_max_steps → `run_failed(max_steps_exceeded)`；attempt retry 调度成功 → `_retryable` 停止本 attempt。全部在 driver（图外）。

## 6. 状态模型

用单层扁平 TypedDict `State`，替换就地可变 `_RunWorkflowState` 与 `_AttemptContext` 的迁移字段。因采用**单步引擎**（一次 `ainvoke` 一个 step、driver 在外循环），所有字段都用 `"last"` 通道（reducer 取最新值）——每个节点返回完整状态字段而非增量 append。

- **"last" 覆盖式通道**：`workflow`、`attempt_ctx`、`step_index`、`previous_observation`、`wrote_file`、`step_journal`、`web_enabled`、`effective_max_steps`、`session_history`、`attachments`、`terminal`、`pending_action`、`pre_generated_thought`、`_gate_retry`、`_retryable`、`step_duration_seconds`。

迁移是**纯机械替换**：字段名/类型保持不变，仅把"就地可变对象"改为"不可变 State + reducer 返回新值"。

## 7. 事件与持久化保真（不可让步）

- 事件顺序/字节/offset 由**节点内部** `_persist_and_notify` 保持，图中不做任何事件改写。
- `plan_created` / `step_completed` / `tool_started` / `tool_completed` / `visible_thought_*` / `answer_*` / `run_*` 事件原样透传。
- DB 持久化、retry 租约、事件溯源（`agent_run_events_seq`）、双通道推送**不影响、不迁移**——图只是编排决策，这些仍是管线负责。

## 8. 外部行为契约（保真清单）

以下**逐字节保真**，断言一个不改：
- SSE 开关时序（事件序列 + 每事件 payload）。
- usage 计费数值（`llm_tokens` 累加、末 chunk usage 采集）。
- JSON 结构（`create_plan` 截断修复、`plan_created` payload）。
- research / quality / stage / save 门禁的**触发条件与提示文案**。
- save intent 强制、`save_readback_mismatch` 校验、`_enforce_answer_truthfulness`。
- retry 状态机（图外）与其事件。
- 每步事件序列、最终 answer（含 fallback 文案）。

## 9. 测试策略

### 9.1 差分保真器（P0 交付物，最高价值工件）
- 同输入 → 旧 while + 新图**双跑** → 逐字节 diff 事件流（事件名/顺序/payload/offset）。
- 断言：两轨事件流完全一致，最终 answer 一致。
- 产出等价性报告（`docs/langgraph-eval/`），或内联断言。
- **不触碰任何现有测试**即证明等价。

### 9.2 现有测试的取舍（形态B）
- 外部可观察行为（事件序列、最终回答、DB 行、SSE 输出、计费）断言**一条不改**。
- 仅放宽**只耦合内部结构**的断言：直接断言 `st.stage`/`st.verified_save_receipts` 内部收据、`_wf_states` 字典、`_AttemptContext` 字段、代理属性 `_workflow_*`、`step_index` 内部值等 → 改为断言外部可观察行为。
- 迁移逐个核对，迁移一个收敛一个，不批量。

### 9.3 新增图单元测试
- 节点单测（全 mock）：`plan`/`execute`/`finalize` 各自的输入→输出。
- 边路由单测：`route_after_plan`（可纠正 gate→`end`）/`route_after_execute`（finish→finalize、工具→end、terminal 清 pending_action→end）。
- 状态单测：`build_state` 全字段、st↔wf 双向 sync。
- driver 端到端：finish plan 到达 finalize 并 `_persist_successful_completion`；gate-retry 与 enforce-gate 走 `_gate_retry` 不失败。

## 10. 错误处理

- 框架无关原语内部异常（`RetryableToolError`/`RetryableStreamingError`/`RetryablePlannerError`/`TimeoutError`/`httpx.HTTPError`）继续走原调度语义，映射到 attempt 层 retryable/terminal（图外）。
- gate 可纠正异常 → 图内 `_gate_retry`（driver 记 observation + journal 后重新规划，step+1，不消耗 attempt）。
- 普通异常 → 图内 `except Exception` → attempt 层 retryable 调度（`_retryable` 停止本 attempt）。
- 图定义/编译必须在服务初始化完成，失败即启动报错，不进热路径。

## 11. 实现分批（P0 → P3）

| 批 | 内容 | 验证 |
|---|---|---|
| **P0 基建** | `LangGraphRunner` 抽象 + `compile` + feature flag + `plan`/`execute`/`finalize` 三最小节点驱动一条最简路径；**旧 while 仍并行**；`diff_event_streams` 差分原语 | langgraph 单元测试 + live-loop 回归全绿 |
| **P1 状态迁移** | `_RunWorkflowState`+`_AttemptContext` → typed State + "last" 通道；收敛内部耦合断言为外部行为断言 | 迁移逐个核对，现有测试全绿 |
| **P2 单步引擎** | driver `_do_process_attempt_graph` 复刻 attempt 层编排，单步 `ainvoke` + st↔wf 双向 sync；`_gate_retry`/`_retryable`/`max_steps_exceeded` 处理 | 全量回归 + gate/enforce/retry driver 测试 |
| **P3 对齐** | `langgraph_enabled` 翻默认（默认新图）**推迟至今**: 需要真实 LLM/DB 双跑 diff_zero 才可确认 | 差分保真器对真实样本零差异 |

每步有可验证增量，避免一次性把 60+ 测试全打红，且**等价性由差分装置独立证明**而非靠人工陪跑。**注意**：P3 的"翻默认"需真实 LLM/DB 环境双跑证明为零差后才能执行；当前 `langgraph_enabled` 保持默认 `False`（由 `_maybe_run_graph_or_loop` 门控），差分保真器 `scripts/langgraph_differential.py` 为后续接入真实样本的脚手架。

## 12. 收益/成本

| | 收益 | 成本 |
|---|---|---|
| 满足"必须用 LangGraph"的团队/组织要求 | ✅ 真实需求 | — |
| 可复用状态图、checkpointer 可选、可视化、未来多智能体 | ✅ 附加 | — |
| 学习价值（同 LangChain 动机） | ✅ | — |
| 外部行为字节保真 | ✅ 由差分保真器保证 | — |
| 重写风险 | — | ⚠️ 高：2454 行状态机 → 图；已通过 P0-P3 分批 + 差分保真器 + attempt 层留图外三重降险 |
| 运行时/可维护性提升 | ⚠️ 无（原循环已 TDD 打磨，图主要带来标准化与可演进性） | — |

## 13. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 字节级事件顺序在节点边界丢失 | 节点内部原样调用 `_persist_and_notify`；差分保真器逐字节证明 |
| 流式穿插与图节点模型不兼容 | 保持 `execute` 胖节点；流式走 EventBus（正交于 LangGraph），不需变成 LangGraph stream |
| 状态迁移引入回归 | 纯机械替换；P1 逐步收敛；现有测试全绿后再进 P2 |
| LangGraph 依赖版本兼容（pydantic v2） | 安装前核对；冲突则暂停并报告，不升级生产依赖 |
| "顺手把 attempt 层也改掉"的蔓延 | 明确的"不做清单" + 差分保真器作唯一决策依据 |
| await_question 语义漂移 | 明确不用 `interrupt`，保持现有 DB pause + 事件语义 |
