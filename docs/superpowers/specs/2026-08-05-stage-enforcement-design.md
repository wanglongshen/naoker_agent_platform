# 方案类任务强制状态机（阶段序列强制）— 设计文档

日期：2026-08-05
状态：已确认

## 背景与问题

蓝图驱动的 Agent 执行引擎已落地（蓝图解析、全文注入、结构校验、追问挂起），但实测发现**状态机是提示型而非强制型**：

1. 阶段推进只是 prompt 注入文本（`当前工作流阶段：xxx`），模型不遵守也没有任何强制——9 步 run 里模型自由决策：read_file 重复 3 次、web_search 只做 2 次就写文件
2. 模型写文件名时版本号飘移（思考里判断"V2"，实际写 `创意建议方案.md` 无版本号）
3. 最终回答与文件事实不符（描述的结构与实际保存的 8 模块不一致）
4. 内容深度不足（2111 字符骨架级，非完整方案）

用户核心诉求：**方案类任务必须完全按蓝图原文一步步执行——蓝图说要做什么就做什么**；普通问答不经过这套系统，直接给出结果。

## 决策

1. **双轨架构**：`classify_task_type`（代码，从蓝图 Step 0 解析）命中方案类 → 蓝图引擎轨道（强制状态机）；命中普通类（纯框架/事实研究/混合策略）→ 快速直答轨道（现有 fast path，直接流式回答，模型自行决定是否调 web_search，不注入蓝图、不走状态机、不受闸门）
2. **阶段序列强制**：代码控制阶段序列，模型被锁在阶段里必须一步步走完——每个阶段有明确的前置条件与产物，未满足不放行
3. **阶段内动作限制**：每个阶段有允许的动作集（research 阶段禁止 write_file/finish；write 阶段禁止 web_search）
4. **蓝图变动跟随**：阶段序列、结构、红线、版本规则全部从蓝图原文动态解析（已实现）；分类关键词表与能力映射表为静态适配层（人工维护，蓝图改文案需微调代码）
5. **错误处理**：阶段违规/闸门拒绝 = `RetryablePlannerError` → 现有重试机制（模型换动作）→ 3 次耗尽才 run_failed
6. **演进边界**：结构化完成条件（蓝图步骤带"产出要求"固定格式）作为后续演进，本期不做

## 架构

```
goal 进入
→ classify_task_type（代码，蓝图 Step 0 分类表）
  ├─ 方案类（完整方案/UGC种草/小红书/矩阵号/修改扩写）
  │   → 蓝图引擎轨道（强制状态机）
  │     classify(代码) → admission(代码) → recap(模型) → version(代码)
  │     → research(模型+代码验≥1次搜索) → strategy/creative/execution(模型)
  │     → redline(代码) → deliver
  │     阶段内动作限制 + 闸门（研究/版本/结构/finish）
  └─ 普通类（纯框架/事实研究/混合策略）
      → 快速直答轨道（现有 _try_direct_answer，直接流式回答）
```

## 组件明细

### 1. 轨道判定（loop.py）

`_do_process_attempt` 开头（`_workflow_rules` 加载后）：

```python
task_type = classify_task_type(run.goal, self._workflow_rules.task_types) if self._workflow_rules else None
plan_class = task_type is not None and task_type.type_name in {
    "完整方案需求", "完整 UGC 种草方案", "小红书种草方案", "矩阵号代运营方案", "修改/扩写需求",
}
if not plan_class:
    # 快速直答轨道：现有 _try_direct_answer 路径（不进入 planner 循环）
```

方案类任务继续走现有 planner 循环 + 阶段强制。

### 2. 阶段序列（代码控制）

阶段序列从 `WorkflowGraph.task_type_edges` 解析（已实现）。阶段推进由 `_advance_workflow_stage` 控制（已实现 classify→admission），**新增**：

- `recap` 阶段：planner 产出 Brief Recap（模型生成，代码验证：方案类任务 finish 前必须已产出 recap——通过 run 内标记 `self._recap_done` 或检查 previous_observation）
- `version` 阶段：代码版本扫描（list_files 当前目录 → 最高版本 +1）——**由代码产出**，注入 prompt 供模型引用文件名
- `research` 阶段：模型可自由 web_search/read_file/list_files，**禁止 write_file/edit_file/finish**；完成后 `self._research_ok = True`
- `strategy/creative/execution` 阶段：模型产出内容，write_file/edit_file 可用（受闸门）
- `redline` 阶段：代码红线检查（复用 plan_structure.has_placeholder_words + 版本/结构检查），完成后才允许 finish

### 3. 阶段内动作限制（loop.py `_enforce_stage_gate`）

挂载点：`loop.py:1553`（plan 校验后、执行前）：

```python
_STAGE_ALLOWED_ACTIONS = {
    "classify": {"read_file", "list_files", "web_search"},
    "admission": {"read_file", "list_files", "web_search"},
    "recap": {"read_file", "list_files", "web_search"},  # 复述期可继续研究
    "version": {"read_file", "list_files", "web_search", "write_file", "edit_file"},
    "research": {"read_file", "list_files", "web_search"},  # 禁 write/finish
    "content": {"read_file", "list_files", "web_search", "write_file", "edit_file"},
    "redline": {"write_file", "edit_file", "finish"},  # 禁新搜索
    "done": {"finish"},
}
```

plan.action.type 不在当前阶段允许集 → `RetryablePlannerError(f"stage_gate: 当前阶段 {stage} 不允许动作 {action_type}")`。

阶段映射：`_workflow_stage` 当前值为 classify/admission/recap/version/research/content/redline/done（`_next_stage_after` 已产出）。

### 4. 闸门（研究/版本/结构/finish）

| 闸门 | 规则 | 拒绝 |
|---|---|---|
| **研究闸门** | write_file/edit_file 前：`self._research_ok`（本 run 内 ≥1 次成功 web_search）为 True | `RetryablePlannerError("research_required")` |
| **版本闸门** | write_file 文件名必须匹配版本正则（从蓝图 Step 1.1 解析："版本号使用整数 V1、V2、V3" → `_V\d+`） | `RetryablePlannerError("version_required")` |
| **结构闸门** | 已有 ✅（plan_structure 校验） | 已有 |
| **finish 闸门** | 已有 ✅（_enforce_save_intent） | 已有 |

版本正则解析（workflow_rules.py 新增）：

```python
def parse_version_rule(blueprint_text: str) -> re.Pattern:
    """从蓝图 Step 1.1 解析版本号规则；解析失败回退默认 `_V\d+`。"""
```

### 5. 蓝图变动跟随（动态解析，已实现）

| 蓝图变什么 | 跟随机制 |
|---|---|
| 步骤增删/改序/改标题 | `parse_workflow_graph` 从 `### Step N` 解析（✅ 已实现） |
| 结构/红线/版本规则 | `parse_structure_section` / `parse_red_lines` / `parse_version_rule`（✅ 已实现） |
| 步骤内容要求 | 阶段描述文本注入 prompt（✅ 已实现） |
| 新增任务类型 | `parse_task_types` 动态；分类关键词表人工维护（⚠️ 静态适配层） |
| 新增工具引用 | `resolve_capability` 降级跳过（⚠️ 静态映射） |

### 6. 错误处理

| 场景 | 处理 |
|---|---|
| 阶段动作违规 | RetryablePlannerError → 重试（模型换动作）→ 3 次耗尽 run_failed |
| 闸门拒绝 | 同上 |
| 蓝图缺失/解析失败 | `get_rules` 返回 None → 轨道判定 fallback 现有自由执行（不中断） |
| 普通问答 | 快速直答轨道，不受任何闸门/状态机影响 |

## 测试策略

**test_agent_loop.py（扩展）**：
- 轨道判定：方案类 goal → 引擎轨道；事实研究 goal → fast path（mock classify）
- 阶段动作限制：research 阶段 write_file → RetryablePlannerError；research 阶段 web_search → 放行
- 研究闸门：直接 write_file 无搜索 → 拒；先搜索再写 → 过
- 版本闸门：`创意建议方案.md` → 拒；`GAP_V1_创意建议.md` → 过
- 普通问答不受闸门：直接回答，无蓝图注入

**test_workflow_rules.py（扩展）**：
- `parse_version_rule`：蓝图 Step 1.1 解析出 `_V\d+`；无规则回退默认

**集成**：完整方案 run 全链路（mock 蓝图 + fake repo）——分类→准入→复述→版本→研究→内容→红线→交付

## 范围边界

**本期做**：
- 轨道判定（方案类 vs 普通类）
- 阶段动作限制（`_STAGE_ALLOWED_ACTIONS`）
- 研究闸门（`_research_ok`）
- 版本闸门 + `parse_version_rule`
- 测试

**本期不做**：
- recap 阶段深度验证（只做存在性标记，不做内容质量评分）
- 结构化完成条件（蓝图步骤带"产出要求"格式——后续演进）
- 红线 18 条的完整代码化（只做占位词 + 结构 + 版本）
- 内容深度强制（2111 字符 vs 完整方案——模型产出质量由 prompt + 红线约束，不设长度闸门）
- 分类关键词表的蓝图自动派生（静态适配层保留）

## 数据流示例

```
用户: "读取 brief_test.md，然后写一份创意建议的方案，保存到 brief/文件夹中"
→ classify_task_type → "完整方案需求" → 引擎轨道
→ classify(代码): 完成 → admission(代码): 完成
→ recap: planner 生成 Brief Recap（模型产出）
→ version(代码): list_files brief/ → 最高 V2 → 产出 V3 注入 prompt
→ research: 模型 web_search（≥1 次成功 → _research_ok=True）
→ content: 模型 write_file brief/xxx_V3_创意建议.md
    → 研究闸门 ✅ → 版本闸门 ✅ → 结构闸门（8 模块校验）
    → 被拒 → 骨架提示 → 模型补全重写 → 通过
→ redline(代码): 占位词检查 → finish
→ run_succeeded

用户: "GAP 最近的营销动态是什么？"（事实研究）
→ classify → "事实研究问题" → 快速直答轨道
→ _try_direct_answer: 直接流式回答（模型自行决定 web_search）
→ 完成，无蓝图、无状态机、无闸门
```
