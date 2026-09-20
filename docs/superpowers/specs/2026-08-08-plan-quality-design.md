# 方案生成质量优化 Design Spec

**Status:** Draft
**Date:** 2026-08-08

## 1. 目标与背景

**问题**：方案生成（矩阵号/UGC/代运营等）当前**只有结构校验，无内容质量环节**。实测数据：
- write_file 首轮被拒率 51%（结构不完整 22 / 子项不全 12 / 占位符 1，共 68 次调用）
- run 成功率 72%（196/271）
- 质量保障 = 校验器强制 + 骨架兜底（事后），**内容质量完全开放**

**目标**：把"一次写对"（结构）与"写得好"（内容）都变成系统保证，并让质量**可度量、可迭代**。

## 2. 七个优化点总览

| # | 优化点 | 环节 | 价值 | 成本 |
|---|---|---|---|---|
| 1 | 骨架预填前置 | 写入前 | 结构错误物理不可能（首轮被拒率 51%→<10%） | ~0 |
| 2 | 蓝图双阶段注入 | 规划/写入 | 省 ~90% 蓝图注入 token（~3500→~200/run） | ~0 |
| 3 | 规则质检 | 写入时 | 客观防放水（字数/预算/空洞语言） | 0 token |
| 4 | 质量自审门（4 维） | 写入后 | 内容质量兜底 | +1~3 次调用/文件 |
| 5 | 对抗式评审 | 自审内 | 防 LLM 自评放水 | ~0（prompt） |
| 6 | 强制调研门 | 写入前 | 数据支撑维度根本保证 | ~0（已有工具） |
| 7 | 质量分入库 + 展示 | 度量 | 持续优化的数据基础 | 小 |

## 3. 设计细节

### 3.1 骨架预填前置（写入前结构保证）

现状：write_file 失败后校验器才返回骨架模板（`build_skeleton`，plan_structure.py:90，8 标准模块 + 指引）。

改造：**write_file 前的 planning step 即注入骨架**——
- 模型在 write_file 之前的决策 step，系统检测到 `goal` 为方案类（`is_plan_goal`）且模型尚未获得骨架时，把骨架注入该 step 的 messages（`_build_merged_messages` 的 project_hint 同机制，新增 `skeleton_hint`）
- 骨架 = `build_skeleton(modules, guides)`（蓝图模块清单驱动，与校验器同源——复用现有 doc-source 解析）
- 提示词附加："必须严格基于以下骨架填充内容，不得删除/合并/重命名任何模块标题"

**效果**：模块结构由系统给定，模型只填内容——结构错误物理不可能。

### 3.2 蓝图双阶段注入（成本）

现状：`get_instruction` 每次 run 把蓝图全文（~12000 字符）注入 system。

改造：
- **规划阶段**：注入结构化摘要（模块清单 + 每模块一句话 + 关键规则，~500 字符）——从蓝图提取：优先复用**模块清单解析**（parse_module_list_from_summary 族）+ 章节标题提取；摘要生成失败回退现状全文
- **首次 write_file 出现的 step**：系统把蓝图全文追加进该 step 的 messages（该该全量时全量）
- 校验器不变（始终读原文）

### 3.3 规则质检（零成本客观层）

write_file 校验时并行跑确定性规则（纯 Python，0 token）：
- **模块字数下限**：每模块 ≥ 200 字符（可配置 `quality_module_min_chars=200`）
- **预算数字存在性**：模块含"预算/费用/报价"字样时必须有数字（`\d` 检测）
- **空洞语言检测**：关键词黑名单（"本方案将全面赋能""根据实际情况进行调整"等——可配置列表），命中即 fail
- 规则质检失败 → 与结构校验失败同路径（观察错误 + 修订提示）

### 3.4 质量自审门（写入后内容保证）

**数据流**：
```
write_file 成功落盘（结构 + 规则质检通过）
  → 触发自审步骤（新事件 quality_review_started）
  → 自审调用：system(质量标准清单 + 对抗式评审指令) + user(刚写入的文件全文)
  → 输出 checklist JSON（每项 pass/fail + 理由 + 总质量分 0-100）
  → 有 fail → 修订指令（fail 项 + 理由）→ 模型 edit_file 修订
     → 修订后再次自审（最多 2 轮）
  → 全 pass 或轮次耗尽 → 事件 quality_review_completed（含分数）→ 继续
```

**质量标准清单（4 维，可配置）**——超管在蓝图文件维护「质量评分卡」章节（改蓝图即生效）：

| 维度 | 检查点 |
|---|---|
| 完整性 | 全部模块有实质内容（非一句话带过）；每模块 ≥ 200 字 |
| 可落地性 | 具体预算数字表；时间线/执行节奏；步骤可操作（谁/何时/做什么） |
| 数据支撑 | 关键结论有数据或来源；引用调研结果；无凭空编造数字 |
| 专业度 | 术语与规范一致；格式统一；无空洞套话 |

- 无评分卡章节时用内置默认清单
- **对抗式评审**（3.5）：prompt 角色 = "严苛的质量评审官"，指令"你的职责是找出所有问题，绝不放过任何不合格项；不要因为这是你自己写的就宽容"

**成本**：每文件 +1~3 次 LLM 调用（自审 + 最多 2 轮修订再审）≈ +2~6k token/文件——可控上限（`quality_review_max_rounds=2`）。

### 3.5 对抗式评审（prompt 设计要点）

- 角色：独立第三方评审官（不提示"你写的"）
- 指令：逐维度找茬；每项必须给"依据"（引用文件原文片段）；不得使用"基本合格""大体符合"等模糊判定
- 分数规则：每维 0-25 分，<60 总分或任一维度 <15 → fail

### 3.6 强制调研门（数据支撑根本保证）

- `is_plan_goal` 的方案类目标：模型 **write_file 之前必须至少完成 1 次调研**（web_search / read_file / fetch_web_content 任一）
- 未调研直接 write_file → 工具观察错误："方案类任务必须先调研（搜索或读取资料）再撰写，请先调研"（调研过则通过——step 状态记 `researched` 标志）
- 例外：goal 明确"基于已有资料"或用户明确不需要调研（`no_research_required` 关键词）——避免过度强制

### 3.7 质量分入库与展示（度量闭环）

- 新事件：`quality_review_completed`（payload：file_id / rounds / score / dims: {dim: {pass, reason}}）
- `GenerationLog` 加列：`quality_score int | None`、`quality_review_rounds int default 0`——write_file 产物生成记录时回填（generation_logs 联动已存在）
- **治理中心**（audit 页 run 详情）：展示质量分徽章（≥80 绿 / 60-79 橙 / <60 红）+ 各维度 pass/fail 列表 + 修订轮数
- 数据驱动：超管可看到哪些维度/模块持续不达标 → 定向改蓝图或提示词

## 4. 数据模型变更

- `generation_logs` +2 列（quality_score / quality_review_rounds）——手写迁移
- 无新表；自审结果走 agent_run_events（新事件类型 quality_review_started / quality_review_completed）
- 配置（Settings）：`quality_module_min_chars=200`、`quality_review_max_rounds=2`、`quality_doc_required=true`、空洞语言黑名单（`quality_phrases`，默认内置 6 条）

## 5. 事件与前端

- 新增事件类型 2 个（agent_run_events.event_type）：`quality_review_started` / `quality_review_completed`
- SSE/DB 重放零改动（事件透传——前端按需消费）
- 治理中心 run 详情（audit/runs/[runId]）加"质量审校"区块（分数徽章 + 维度列表）——仅当 quality_review_completed 存在
- 自审过程对用户可见：思考区出现"正在审校方案质量…"（quality_review_started 渲染为普通状态文本）——复用现有 thought 面板文本流（可选，低优先）

## 6. 测试策略

- 规则质检：字数下限/预算数字/空洞语言各 2 例（纯函数，~6 测试）
- 骨架预填：plan 步骤注入骨架（断言 messages 含模块标题）；已注入不重复注入；非方案类不注入（~4）
- 双阶段蓝图：规划 messages 含摘要不含全文；首次 write_file step 含全文；未写文件不注入全文（~3）
- 调研门：方案类未调研 write_file → 拒绝观察；调研后通过；非方案类不受限（~3）
- 自审门：checklist 解析（pass/fail/score）；fail → 修订指令生成；轮次耗尽终止（~4）
- 质量分入库：generation_logs 回填 + 事件 payload（~2）
- 对抗评审 prompt 存在性（~1）
- 回归：既有工具/循环测试全量

## 7. 明确不做

- 分段生成（模块级分批写入）——成本敏感时后续再加
- 引用标注（方案内数据带来源格式）——后续
- 范围澄清（goal 模糊时反问用户）——后续（交互改动大）
- 双模型评审（评审用更贵模型）——后续按质量分数据决定
- 蓝图质量评分卡前端编辑器——超管直接编辑蓝图文件即可（markdown 章节）
