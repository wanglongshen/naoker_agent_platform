# 写文件任务可靠性加固：wrote_file 成功判定 + 动态蓝图校验与骨架 — Design

> Date: 2026-08-04
> Status: Approved by user (2026-08-04)

## 背景与问题

用户在同一 session 中连续发起三次 run 才完成"读取 brief_test.md → 生成方案 → 保存到 brief/ → 告知结果"的任务（2026-08-03 日志）：

| Run | 时间 | 行为链 | 结果 |
|---|---|---|---|
| RUN1 | 18:10 | read ✓ → write_file 被拒（缺 5 模块）→ read → write_file 被拒（缺失模块完全相同，未补全）→ finish | **幻觉最终回答**："当前对话中没有提供该文件的内容，我也无法直接访问本地文件系统"（实际 read 已成功） |
| RUN2 | 18:14 | read ×2 → write_file 被拒（缺 6 模块）→ finish | 把完整 8 模块内容贴在聊天里，**未保存文件** |
| RUN3 | 18:19 | read ✓ → write_file 一次成功 | 正常完成 |

### 根因（证据链）

1. **wrote_file 记为"尝试过"而非"成功"**：`loop.py:1434-1436` 只要计划中出现 `write_file`/`edit_file` 就置 `wrote_file=True`，即使工具返回 `{"error": "plan_structure_incomplete"}`。导致 RUN1/2 中：write_file 被拒 → 模型再次 plan finish → `_enforce_save_intent`（loop.py:405-419）看到"已写过"→ 放行 finish → 残缺结果收尾。
2. **校验失败反馈太弱**：`tool_executor.py:432-440` 的 hint 只说"请按蓝图 8 模块结构补全"，模型自由发挥仍缺模块（RUN1 两次拒绝的缺失列表完全一致）。没有给模型可"填空"的标准骨架。
3. **蓝图模块清单被蒸馏 prompt 锁死**：`workflow_policy.py:129-141` 的 `_DISTILL_PROMPT` 硬编码"8 模块清单：Brief Recap、前策调研、本品表现、用户分析、创意与传播规划、投流策略、Roadmap、附录"。即使蓝图原文结构变化（增删模块、改名），重新蒸馏后摘要仍按指令输出这 8 个，校验器与骨架永远看不到蓝图变化——校验与模型行为分裂的隐患。

### 非目标（本次不做）

- 跨轮意图继承（用户澄清消息当作新 goal 的问题）——已识别，另立 spec
- 幻觉收尾加固（最终回答注入动作事实摘要）——已识别，另立 spec
- 重复 read_file 问题（规划提示约束）——已识别，另立 spec
- 校验阈值调整（缺 ≥3 拒绝维持现状）

## 设计

### 变更 1：wrote_file 成功判定（loop.py）

**现状**：`loop.py:1434-1436` 计划阶段即置位。

**改动**：
- 删除计划阶段置位：
  ```python
  # 删除
  if action_type_check := plan.get("action", {}).get("type"):
      if action_type_check in {"write_file", "edit_file"}:
          wrote_file = True
  ```
- 在工具执行成功后置位：`_stream_visible_thought_with_tool_interleave` 返回的 `observation_or_answer` 无 `error` 字段且 action 类型为 `write_file`/`edit_file` 时，`wrote_file = True`。实现位置：`_do_process_attempt` 主循环中 `observation_or_answer` 获取后（loop.py:1442-1465 之后）。

**效果**：
- write_file 被拒（observation 带 error）→ `wrote_file` 保持 False → 模型再次 plan finish → `_enforce_save_intent` 抛 `RetryablePlannerError("save_intent_requires_write_tool")`（loop.py:419）→ 模型必须继续写文件
- write_file 成功 → finish 正常放行
- 步数耗尽兜底：`max_steps_exceeded` run_failed（loop.py:1528），不会死循环

### 变更 2：模块清单从蒸馏摘要动态解析（plan_structure.py 重构）

**目标**：校验标记与骨架模板都从"当前蒸馏摘要"派生，蓝图变化自动传导。

**新增接口**：

```python
def parse_module_list_from_summary(summary: str) -> list[str] | None:
    """从蒸馏摘要解析模块清单；失败返回 None（调用方回退默认）。"""

DEFAULT_MODULES = ["Brief Recap", "前策调研", "本品表现", "用户分析",
                   "创意与传播规划", "投流策略", "Roadmap", "附录"]
```

**解析逻辑**（`parse_module_list_from_summary`）：
- 摘要中"正式方案 N 模块"段为编号列表（`1. Brief Recap`、`2. 前策调研`…）
- 按行匹配 `^\d+\.\s+\S` 提取；过滤说明行（含"保存到文件/逐节输出/不可自创/必须/请/需"等指令词且非编号列表行）
- 取连续编号段，编号从 1 开始且递增 → 返回模块名列表
- 模块名少于 3 个或解析异常 → 返回 None

**运行时装配**（改造 `validate_plan_structure` / 新增骨架函数）：
- 模块清单来源优先级：`get_instruction` 的摘要缓存（复用 `workflow_policy` 现有缓存，无额外 LLM 调用）→ 解析成功用动态清单 → 失败/缺失回退 `DEFAULT_MODULES`
- 校验标记：模块名本体（小写匹配）+ 预置别名变体映射（如 调研/前策/竞品→前策调研，投流/投放/media→投流策略，roadmap→Roadmap）；别名映射对动态模块名也适用（按名称片段匹配）
- 骨架生成：`build_skeleton(modules) -> str`，输出 `## 一、{模块名}` 标准标题序列 + 每模块一句内容指引（静态指引映射，见下）

**骨架内容指引**（静态映射：模块名→指引；新模块名无映射时仅标题）：

| 模块（命中片段） | 指引 |
|---|---|
| 前策调研 | 竞品必查，不得跳过竞品与平台现状 |
| 本品表现 | 基于 brief 与公开信息，标注估算锚点与边界 |
| 创意与传播规划 | 拆到平台/内容形态/达人/节奏/物料/KPI |
| 投流策略 | 预算/周期/资源超限必须标注假设 |
| 附录 | 数据来源、假设与边界 |

### 变更 3：蒸馏 prompt 跟随蓝图结构（workflow_policy.py）

**现状**：`_DISTILL_PROMPT` 硬编码"8 模块清单：…附录"。

**改动**：将第 2 条要求改为：

```
2. 正式方案默认结构（模块清单：以蓝图原文实际列出的模块为准，完整保留其名称与数量，
逐条列出结构名）；并注明：任何保存到文件模块的方案/建议类文档正文，必须完整按此模块
结构逐节输出，不可自创结构
```

**注意**：`workflow_policy.py:22` 的 `_DISTILL_VERSION = 4` 目前**只声明未实现**——DB `workflow_doc_summaries` 表无 version 列，重新蒸馏仅由 `file_updated_at`/`file_sha256` 变化触发。因此修改 prompt 后蓝图文件未变时，旧摘要（硬编码 8 模块）会残留。需实现版本机制：
- `workflow_doc_summaries` 表加 `distill_version` 列（alembic migration）
- `_needs_distill` 判定增加：`cached.distill_version != _DISTILL_VERSION` → 强制重蒸馏
- 修改 `_DISTILL_PROMPT` 时递增 `_DISTILL_VERSION`（4 → 5）
- 无缓存或版本不符时重蒸馏，成功后写新版本号

这样部署即自动传导，无需人工触发。

### 错误处理

- 校验失败仍是**观察结果**（不抛异常、不落盘、不建 DB 行），行为契约不变
- 摘要解析失败 → 静默回退默认 8 模块，不报错不影响 run
- wrote_file 判定只在 observation 无 error 时置位；`finish` 动作本身不置位

## 测试计划

**新增 test_plan_structure.py 用例**：
1. 摘要含 8 模块编号列表 → 解析出 8 个正确名称
2. 摘要含 9 个模块 → 解析出 9 个（验证动态性）
3. 摘要无编号列表（漂移）→ 返回 None
4. 模块名含中文+英文混合 → 正常解析
5. `build_skeleton` 输出包含 `## 一、{模块名}` 全部标题
6. `build_skeleton` 输出的骨架本身通过 `validate_plan_structure`（回环自洽）
7. 动态模块清单（9 个）下 `validate_plan_structure` 按 9 模块校验

**test_agent_tool_files.py 新增用例**：
8. 残缺方案返回 `skeleton` 字段且包含全部标准标题；`missing_modules` 与骨架一致
9. 完整方案（动态清单下）正常保存

**test_agent_tools.py / test_agent_loop.py 新增用例**：
10. write_file 返回 error observation → `wrote_file` 为 False → plan finish → `_enforce_save_intent` 抛 `save_intent_requires_write_tool`
11. write_file 成功 → `wrote_file` 为 True → finish 放行

**workflow_policy 测试**：
12. 蒸馏 prompt 不再含硬编码 8 模块名（断言 prompt 文本变化）

## 验收标准

- 复现场景：同一 session 内"读取 brief → 生成方案 → 保存到 brief"任务，write_file 被拒后模型能基于骨架补全并在同一次 run 内成功保存（人工验证或集成测试）
- 全部后端测试通过（`python -m pytest tests/ -q`）
- 蓝图新增模块（模拟 9 模块摘要）→ 校验与骨架自动按 9 模块工作
