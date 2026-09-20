# 蓝图驱动的 Agent 执行引擎 — 设计文档

日期：2026-08-05
状态：已确认

## 背景与问题

用户要求 Agent 完全按照《脑壳儿_Agent运行蓝图_v1.1.md》执行任务——蓝图规定做什么就做什么，而不是模型自由发挥、写完后靠校验兜底。

当前系统的缺陷：
1. **蓝图只被当校验标准**（write_file 结构校验 + 摘要注入），Agent 主循环是单层 `while step_index < effective_max_steps` 自由决策循环，没有蓝图阶段概念
2. **蒸馏摘要（Tier 1）信息有损**：蓝图 8 类分类被压成 5 类、准入判断表整个丢失、Step 序列丢失；代码规则基于二手数据 = 规则失真
3. **一致性风险**：蓝图变 → 重蒸馏 → 摘要更新，中间窗口期模型和规则各用一份不同数据
4. **维护成本**：蒸馏 prompt、版本盐、缓存失效、重蒸馏调度、单飞锁——整套机制只为省 token（实际每 run 全量注入成本 ~0.0007 元，可忽略）

## 决策

1. **单一事实源**：蓝图原文是唯一权威。代码规则直接解析蓝图原文（确定性、零失真、蓝图改即生效），不再依赖 LLM 蒸馏摘要
2. **摘要删除**：`workflow_doc_summaries` 表、`_DISTILL_PROMPT`、`_DISTILL_VERSION`、蒸馏调度、单飞锁、write 钩子全部移除；模型注入改为方案类任务注入蓝图全文
3. **代码强制状态机**：规则步骤（分类/准入/版本/红线校验）由后端代码执行；内容步骤（复述/研究/策略/创意/拆解）由 LLM + 工具执行
4. **蓝图可变**：状态机步骤定义从蓝图文件解析（`### Step N：标题` 结构 + 条件边），蓝图改步骤 → 状态机跟着变，代码只认识"前置条件模式"
5. **能力映射**：蓝图引用系统没有的工具（$agent-reach/$humanizer-zh/案例库）时走降级策略
6. **run 级蓝图快照**：run 启动时解析一次蓝图并锁定（记录 blueprint_sha256），避免 run 中途蓝图被修改导致流程错乱
7. **追问挂起/恢复**：准入判断=先追问时，run 进入 `awaiting_question` 状态，输出 ≤5 问，前端显示追问卡片，用户回答后恢复同一 run

## 架构

```
蓝图原文（00_Agent规范与模板/脑壳儿_Agent运行蓝图_v1.1.md，15342 字符）—— 唯一权威
 │
 ├─→ workflow_rules.py（新）：条件图解析器
 │    任务分类表(Step 0, 8类)、准入判断表(Step 0.5, 4分支)、
 │    步骤条件图(Step 0-8 含 1.5/1.6/1.7 类型分支、Step 2 条件触发)、
 │    默认结构(## 3)、红线清单(Step 8, 15+ 条)、能力引用映射
 │
 ├─→ 状态机引擎（loop.py 主循环改造）
 │    run 启动 → 蓝图快照锁定 → Step 0 分类 → Step 0.5 准入 →
 │    Step 1 复述 → Step 1.1 版本 → Step 3 研究 →
 │    Step 5-7 策略/创意/拆解 → Step 8 红线校验 → 交付
 │
 ├─→ 追问挂起（新增 awaiting_question 状态）
 │    准入=先追问 → 输出 ≤5 问 → run 挂起 → 前端追问卡片
 │    → 用户回答 → 同一 run 恢复 → 继续执行
 │
 ├─→ 校验器（现有，零改动）：write_file 结构校验直读蓝图原文
 │
 └─→ 模型注入（改 workflow_policy.py）：删摘要 → 方案类任务注入蓝图全文
```

## 组件明细

### 1. workflow_rules.py（新文件，纯函数 + 解析器）

与现有 `plan_structure.py` 的解析模式保持一致（markdown 表格/编号列表解析 + sha256 指纹缓存）。

**`parse_task_types(blueprint_text) -> list[TaskTypeRule]`**

解析 Step 0 任务分类表（8 类）：

```python
class TaskTypeRule(BaseModel):
    type_name: str        # "完整方案需求"
    features: list[str]   # 特征关键词（"明确要方案/策划/规划/提案"）
    default_action: str   # "先生成本地版本化源稿，再创建或更新飞书客户方案"
    route_doc: str | None # 路由规范文档路径（矩阵号→脑壳儿_矩阵号代运营方案输出规范.md）
```

表格格式：`| 任务类型 | 特征 | 默认动作 |`。feature 关键词从"特征"列人工摘要提取（解析器只取类型名与默认动作；关键词匹配在 `classify_task_type` 内用固定正则表——蓝图特征列是描述性文字，不适合直接做关键词）。

**`parse_admission_rules(blueprint_text) -> list[AdmissionRule]`**

解析 Step 0.5 准入判断表（4 分支）：

```python
class AdmissionRule(BaseModel):
    branch: str       # "可直接产出" / "带假设产出" / "先追问" / "材料异常"
    applies: str      # 适用情况
    next_step: str    # 下一步
```

**`parse_workflow_graph(blueprint_text) -> WorkflowGraph`**

解析步骤条件图：

```python
class WorkflowStep(BaseModel):
    step_id: str      # "0" / "0.5" / "1" / "1.1" / "1.2" / "1.5" / "1.6" / "1.7" / "2" / "3" / "3.1" / "4" / "5" / "6" / "7" / "8"
    title: str        # "判断任务类型"
    body: str         # 步骤正文（表格/文本）
    kind: str         # "rule"（代码执行）或 "content"（LLM 执行）
    condition: str | None  # 触发条件描述（如 Step 2 仅当准入=先追问）

class WorkflowGraph(BaseModel):
    steps: list[WorkflowStep]
    task_type_edges: dict[str, list[str]]  # 任务类型 → 步骤 id 序列（如 完整方案→[0,0.5,1,1.1,1.2,3,5,6,7,8]）
```

`kind` 判定规则：
- 步骤正文包含可代码验证的表格/清单（分类表、准入表、版本规则、红线清单）→ `rule`
- 步骤是内容生成（复述、研究、策略、创意、拆解）→ `content`

**`parse_red_lines(blueprint_text) -> list[str]`**

解析 Step 8 风险校验清单（15+ 条 bullet）。

**`resolve_capability(tool_ref: str) -> str | None`**

能力映射表（静态代码映射，不在蓝图里）：

| 蓝图引用 | 系统工具 | 降级 |
|---|---|---|
| `$agent-reach` / Agent-Reach | 无 | web_search（记录缺口） |
| `$humanizer-zh` | 无 | 跳过（交付前去 AI 味由模型自检） |
| 案例库 | read_file | list_files + read_file |

**缓存**：`_rules_cache: dict[str, tuple[str, ParsedRules]]`（key=sha256，蓝图变自动失效），与 `_structure_cache` 同模式。

### 2. 状态机引擎（loop.py 主循环改造）

**run 启动（`_do_process_attempt` 开头）**：

```python
self._workflow_instruction = ""
if settings.workflow_docs_enabled:
    try:
        rules = await self.workflow_policy.get_rules(repo.session, run.goal)
        # rules 含蓝图 sha256 + 解析出的 TaskTypeRules/AdmissionRules/Graph/RedLines
        self._workflow_rules = rules
        self._blueprint_sha = rules.sha256  # 记录到 run 审计
    except Exception:
        logger.warning("workflow_rules_load_failed", exc_info=True)
```

**run.result 记录蓝图版本**：`result["blueprint_sha256"] = self._blueprint_sha`（审计可追溯）。

**步骤推进模型**：

```
当前阶段 state = "classify"
while state != "done" and step_index < effective_max_steps:
    match state:
        "classify"    → 代码分类（classify_task_type(goal) → 8 类之一）
                        → 按 task_type_edges 得到步骤序列 → state = 下一步
        "admission"   → 代码准入判断（材料盘点 + 约束识别）
                        → 分支：先追问 → 进入追问挂起流程；其他 → 推进
        "recap"       → LLM 复述（Brief Recap 5-8 句）→ 校验非空 → 推进
        "version"     → 代码版本扫描（list_files 当前目录 → 最高版本 +1）
        "research"    → LLM 研究（planner 驱动工具）→ 校验证据数 > 0
        "strategy"    → LLM 策略/创意/拆解（planner 驱动）
        "redline"     → 代码红线校验（15 条逐条）→ 通过 → "done"
```

**实现方式**：不推翻现有 planner 循环。在现有 `while step_index` 循环外加一层**阶段状态变量**（`self._workflow_stage`），每个 planner 决策前代码先检查当前阶段的前置条件是否满足：
- 未满足 → 代码执行该阶段（分类/准入/版本/红线）
- 满足且该阶段是内容步骤 → 进入 planner 决策循环（现有逻辑）
- 阶段完成 → 推进状态，planner 的 prompt 注入当前阶段描述

**prompt 注入**：`_build_messages` 的 user_prompt 增加 `当前工作流阶段：{stage_title}\n阶段要求：{stage_body 摘要}\n已完成阶段：{已完成列表}`。

### 3. 追问挂起/恢复（run 生命周期扩展）

**DB 变更**（alembic 迁移）：
- `agent_runs` 加列 `pending_questions: JSON | None`（≤5 问，结构 `[{"question": str, "affects": str}]`）
- `agent_runs` 状态枚举扩展：`awaiting_question`（CheckConstraint 更新）
- `agent_run_attempts` 不变（追问挂起不产生新 attempt）

**流程**：
1. 准入判断=先追问 → 代码生成问题清单（模板：预算级别/时间周期/核心目标/必讲信息/成功指标——从蓝图 Step 2 追问优先级提取）
2. run 状态 → `awaiting_question`，`pending_questions` 写入
3. 前端显示追问卡片（问题列表 + 回答输入框 + 提交按钮）
4. 用户提交回答 → 新 API `POST /api/agent/runs/{id}/answer`（body: `{answers: {question: answer}}`）→ 回答合并进 run.goal 上下文 → run 状态 → `queued`（重新入队）
5. worker 拾取 → 同一 run 继续（跳过已完成的阶段，从追问后的步骤继续）

**上下文保存**：追问前的已完成阶段结果（复述/研究摘要）保存在 `run.result`（JSON）中，恢复时注入 prompt。

**恢复去重**：run 恢复后 `pending_questions` 清空，`result["resumed_after_question"] = True`。

### 4. 模型注入改造（workflow_policy.py）

**删除**：
- `_read_persisted_summary` / `workflow_doc_summaries` 读取逻辑
- `_schedule_distill` / 蒸馏任务 / `_DISTILL_PROMPT` / `_DISTILL_VERSION`
- 单飞锁 `_distill_lock`、`_pending_dirty`、`_distill_tasks`
- write_file/edit_file 写路径钩子（蒸馏失效钩子）
- 启动 bootstrap `ensure_summary`

**保留**：
- `_resolve_file`（超管文件夹解析）
- `_load_doc`（文档读取）
- `_parse_route_rules`（Tier 2 路由）
- `get_instruction` 改名/改逻辑：方案类任务（`classify_task_type` 判定含"完整方案/矩阵号/UGC/小红书"）注入蓝图全文 + 路由规范文档；非方案类注入路由文档（或无）

**新**：
- `get_rules(session, goal) -> ParsedRules`：加载蓝图原文 → sha256 → `_rules_cache` 命中返回 / 未命中解析 → 返回规则集（状态机使用）
- `get_instruction` 改为基于 `classify_task_type` 结果决定注入内容

**模型注入示例**（完整方案类）：

```
【系统工作流约束（必须严格遵守）】
以下是《脑壳儿_Agent运行蓝图》原文：
[蓝图全文 15K 字符]
【脑壳儿_矩阵号代运营方案输出规范.md】
[路由文档全文（如命中）]
```

### 5. 校验器（现有，零改动）

`plan_structure.py` / `tool_executor.py` 的 write_file 结构校验已直读蓝图原文（`_resolve_active_structure` → `resolve_structure_doc` → `_load_doc_text`），摘要不参与校验。摘要删除不影响校验。

## 错误处理

| 场景 | 处理 |
|---|---|
| 蓝图文件缺失/读取失败 | `get_rules` 返回空规则集 + `logger.warning`；状态机退化为现有自由决策循环（不中断 run） |
| 解析失败（格式漂移） | 分类/准入/红线回退内置默认值（现有 DEFAULT_MODULES 模式）；步骤图回退线性执行 |
| 能力缺失（$agent-reach） | 降级 web_search + 在对话框说明缺口（蓝图 Step 3 硬规则"不足 150 条须说明原因"） |
| 追问后用户不回答 | run 保持 awaiting_question（无超时取消；用户可手动取消） |
| 追问后回答仍不足 | 回答注入上下文后重新准入判断（再次追问 ≤5 问） |
| run 中途蓝图被修改 | 不影响（快照已锁定；新 run 用新快照） |
| write_file 校验拒绝 | 现有机制（骨架 + hint 引导补全） |

## 测试策略

**test_workflow_rules.py（新）**：
- `parse_task_types`：解析出 8 类（完整方案/矩阵号/UGC/小红书/纯框架/事实研究/混合/修改扩写），类型名与默认动作正确
- `parse_admission_rules`：4 分支正确
- `parse_workflow_graph`：16 个步骤全部解析；Step 1.5/1.6/1.7 条件边正确；Step 2 条件触发正确
- `parse_red_lines`：15+ 条红线
- `resolve_capability`：$agent-reach→web_search 降级
- 缓存：指纹命中不重解析

**test_agent_loop.py（扩展）**：
- 状态机：分类→准入→复述→版本→研究→策略→红线→交付 全链路（mock 蓝图 + fake repo）
- 追问：准入=先追问 → run 挂起 awaiting_question → 回答 → 恢复继续
- 蓝图缺失：降级自由决策（现有行为）

**test_workflow_policy.py（重写）**：
- 摘要相关测试删除
- 方案类任务注入蓝图全文
- 非方案类不注入蓝图全文（或无注入）

**全量**：777+ passed 基线保持。

## 范围边界

**本期做**：
- workflow_rules.py 解析器 + 缓存
- 状态机阶段变量 + 阶段注入
- 追问挂起/恢复（DB 迁移 + API + worker 恢复）
- 摘要删除（workflow_policy 清理 + DB 表保留不删）
- 蓝图全文注入

**本期不做**：
- 前端阶段可见性指示器（阶段推进只通过现有 thought/事件流可见）
- 追问卡片的精美 UI（最小实现：问题列表 + 输入框 + 提交）
- 案例库工具（蓝图 Step 4 引用——能力映射为 read_file + list_files，不新增工具）
- $agent-reach / $humanizer-zh 工具实现（降级策略）
- `workflow_doc_summaries` 表删除（保留兼容；数据不再读写）
- 蓝图多角色区分（YAGNI，全用户同一蓝图）

## 数据流示例

```
用户: "读取 brief_test.md，然后写一份创意建议的方案，保存到 brief/文件夹中"
→ worker 拾取 run
→ 状态机: Step 0 分类 → classify_task_type("...创意建议...方案...保存到...") → "完整方案需求"
→ Step 0.5 准入 → 材料盘点（read brief_test.md 成功）→ 约束明确 → "可直接产出"
→ Step 1 复述 → LLM 生成 Brief Recap（5-8 句）
→ Step 1.1 版本 → list_files brief/ → 无历史 → V1
→ Step 3 研究 → planner 驱动 web_search（竞品/成毅/旅行趋势）
→ Step 5-7 策略/创意/拆解 → LLM 生成 8 模块内容
→ Step 8 红线校验 → 15 条逐条通过
→ write_file brief/xxx_V1_创意建议.md → 校验（蓝图结构）→ 保存成功
→ 最终回答（交付洁净度：无"待补充/AI 工作痕迹"）

用户: "预算不够，先问清楚" 的场景
→ Step 0.5 准入 → 缺口改变投流规模 → "先追问"
→ 生成 ≤5 问（预算/周期/核心目标/必讲信息/成功指标）
→ run → awaiting_question → 前端追问卡片
→ 用户回答 → POST answer → run 恢复 → 从 Step 1 继续
```
