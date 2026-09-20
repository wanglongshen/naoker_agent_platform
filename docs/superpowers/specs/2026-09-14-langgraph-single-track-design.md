# LangGraph 单轨化（切轨 + 差分校准）设计（2026-09-14）

- 关联计划：`docs/superpowers/plans/2026-08-27-langgraph-orchestration.md`（图轨实现与逐字节保真验收线）
- 关联记忆：#583（外部可观察行为逐字节保真）、#589（execute 保持单胖节点）
- 后续子项目：SP2 三期任务链（调研→初稿→审校→交付→计费，DSH 作执行层）——本设计不含

## 1. 背景与现状（证据）

- 系统内**双轨并行**：旧 while 循环轨与 LangGraph 轨；`settings.langgraph_enabled: bool = False`（`backend/app/core/config.py:40`）默认走旧轨。
- 分派点：`backend/app/services/agent/loop.py:2214` `_maybe_run_graph_or_loop` → 图轨 `_do_process_attempt_graph`（:3003 起，调 `LangGraphRunner`）/ 旧轨 `_do_process_attempt`。
- 图轨已实现：`backend/app/services/agent/langgraph_runner.py`（节点 `plan → execute → finalize`，条件边路由；`diff_event_streams` 在 :160）；测试 10 个文件 22 用例（`backend/tests/test_langgraph_*.py`）。
- 2026-08-27 计划遗留（ledger 记录）：
  - T8 保真项：attachment 格式、plan 节点内 `_commit_repo`、`pre_generated_thought` 线程测试；
  - T10：`langgraph_enabled` 保持 False；**翻默认值需要真实 LLM/DB 差分**；`backend/scripts/langgraph_differential.py` 仍是占位（`raise NotImplementedError`）。
- 相关 LLM 客户端：`backend/app/services/agent/llm.py` 的 `DeepSeekClient.create_plan`（:47）/ `stream_text`（:160，带 `stream_options.include_usage`）/ `complete`（:200）。
- 事件溯源表：`agent_run_events`（`backend/app/models/agent.py:180`），全局 seq 可全量回放。

## 2. 目标与非目标

**目标**：生产默认 LangGraph（唯一活跃执行轨道）；用录制回放逐字节差分证明与旧轨等价；旧轨代码保留、一行环境变量可回退。

**非目标**（本次不做）：
- 不删除旧轨代码（保留回退能力，按用户选择 B）；
- 不改图外机制：attempt 层（重试/租约/事件溯源）、双通道 SSE、计费、审计、前端；
- 不做三期任务链（SP2）、不动 DSH/RAG。

## 3. 验收线

1. **录制回放逐字节差分**：10 条场景矩阵全部 0 差异（归一化规则显式化，见 4.1）。
2. **既有测试全绿**：外部行为断言不变；内部结构断言按 #583 已放宽为外部行为断言。
3. **真实任务抽查**（用户手测）：fast path / 方案类全流程 / 门禁触发 / 附件引用，行为与旧轨一致。
4. 事件序列、SSE 开关时序、计费数值、审计语义不变。

## 4. 技术设计

### 4.1 差分器（`backend/scripts/langgraph_differential.py` 实现化）

- **录制模式**（env `LANGGRAPH_DIFF_RECORD=1` + fixture 路径）：在 `DeepSeekClient` 三个方法外套 Recorder（新模块 `backend/app/services/agent/llm_recorder.py`，默认直通、仅 env 生效），按调用序号存 `(method, messages, kwargs) → (JSON 响应 / 流式 chunk 列表)` 到 `docs/langgraph-eval/fixtures/<scenario>.json`。
- **回放模式**（env `LANGGRAPH_DIFF_REPLAY=<fixture>`）：Recorder 变 Replayer，按序号返回录制内容（逐 chunk 回放、零延迟），分别以旧轨（`langgraph_enabled=False`）与图轨（`True`）驱动同一 fixture，各跑一次独立 run。
- **采集与比对**：跑完按 seq 全量读 `agent_run_events`；先做易变字段归一化（`run_id` / `attempt_id` / 事件主键 / 时间戳 / 内嵌 uuid 的 `stream_id` → 占位符；归一化规则在报告里逐条列出，不允许掩盖语义差异），再 `diff_event_streams` 逐字节比对；输出 `docs/langgraph-eval/report.md`（每条场景：LLM 调用数、事件数、差异列表；0 差异才通过）。
- **副作用隔离**：每条场景独立测试用户/会话/run；报告记录 run id；数据可清理。

### 4.2 场景矩阵（10 条 fixture，覆盖所有分支）

| # | 场景 | 覆盖点 |
|---|---|---|
| 1 | 普通问答 | `plan_class` 非方案类 → fast path，零状态机零闸门 |
| 2 | 方案类全流程（无附件） | 8 阶段折叠、调研门、保存、质检 |
| 3 | 必读文件未读 | admission「先追问」挂起（awaiting_question） |
| 4 | 研究前置门禁 | `research_required` 拦截与补救 |
| 5 | 版本规则 | version 阶段与版本号 |
| 6 | 结构校验拒稿 | write_file 拒稿 → 骨架补全 |
| 7 | 重试耗尽 | `RetryablePlannerError` 3 次 → `run_failed` |
| 8 | 附件引用 | 附件格式与读附件回执 |
| 9 | 质检闭环 | quality_review fail → 修订 → pass |
| 10 | 计费/usage | token 累加与扣点数值 |

### 4.3 切轨

- `backend/app/core/config.py:40` 默认值 `False → True`；`.env.example` 增加 `LANGGRAPH_ENABLED=false` 回退说明。
- 差分暴露差异时：**修图轨，旧轨不动**（旧轨是基准）。
- 补齐 T8 遗留保真项（attachment 格式 / plan 节点 `_commit_repo` / `pre_generated_thought` 线程测试）。
- 提交顺序：差分器 → 矩阵全绿 → 翻默认值 → 真实任务抽查 → 文档（差分报告 + 回退说明）。

## 5. 风险与回滚

- **流式分段保真**：回放必须逐 chunk（SSE delta 分段受影响），差分可抓到；若图轨 chunk 处理与旧轨不同即修图轨。
- **图轨缺口**：场景矩阵即发现机制；发现即修，不改旧轨。
- **归一化掩盖差异**：归一化规则必须在报告中显式列出并接受审查。
- **回滚**：`LANGGRAPH_ENABLED=false` 一行环境变量即回旧轨（旧轨代码保留的价值）。

## 6. 交付物清单

- `backend/app/services/agent/llm_recorder.py`（新：录制/回放包装器，env 门控）
- `backend/scripts/langgraph_differential.py`（实现：录制/回放/比对/报告）
- `docs/langgraph-eval/fixtures/*.json`（10 条场景）+ `docs/langgraph-eval/report.md`
- `backend/app/core/config.py` 默认值翻转 + `backend/.env.example`
- 图轨保真项补齐（attachment / `_commit_repo` / `pre_generated_thought`）与差分器单测
- `docs/verification/langgraph-single-track-checklist.md`（真实任务抽查清单）
