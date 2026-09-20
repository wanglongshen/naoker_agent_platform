# 结构校验知识库化设计（Document-Source Structure Validation）

**日期：** 2026-08-04
**状态：** 已批准（brainstorming 完成，用户确认所有细节）

## 背景

### 问题链

1. **用户业务故障**（2026-08-03）：AI 写方案保存文件时连续 3 次任务失败（"未成功生成最终回答"），根因是 write_file 结构校验与模型行为脱节。
2. **已修复 3 个问题**（write-file-save-hardening，已落地、699 测试通过）：
   - `wrote_file` 只在实际保存成功时置位（堵住"被拒后直接 finish"）
   - 校验失败返回 8 模块骨架模板（模型照填）
   - 蒸馏 prompt 跟随蓝图结构 + `_DISTILL_VERSION` 版本机制
3. **当前未解决的问题**：结构校验依据**蒸馏摘要**，而摘要经 LLM 压缩（700 token 上限）会**截断结构清单**——真实蓝图体系有 5+ 套结构，摘要只保留了 2 套（默认 8 模块、矩阵号 9 模块），**UGC 10 模块、小红书内部 7 模块等被丢弃**。

### 蓝图体系实测（探索确认）

| 结构 | 来源文档 | 模块数 |
|---|---|---|
| 默认正式方案 | 蓝图 `## 3. 正式方案默认结构` | 8 |
| 矩阵号代运营 | 蓝图 `Step 1.6` + `脑壳儿_矩阵号代运营方案输出规范.md` | 9（编号列表） |
| UGC 种草 | `脑壳儿_UGC种草方案输出规范.md` | 10（表格 `\| 模块 \| 必须回答的问题 \| 必须形成的输出 \|`） |
| 小红书种草内部检查 | 蓝图 `Step 1.5` | 7 |
| 方案模板变体 | `脑壳儿_方案输出模板.md` | 5/8/10 |

文档物理位置：超管（4c40bada-b2e6-45ea-b1b2-a2e43e663072）文件夹 `00_Agent规范与模板/` 下，18 个文件全部未删除、可读。

## 设计

### 核心思路

**校验结构来源从"蒸馏摘要"改为"原始规范文档"**，与模型注入同源（`workflow_route_rules` 已按 goal 关键词路由文档全文给模型，校验器复用同一路由与同一文档）。摘要仍用于模型注入，不再承担结构校验职责。

### 架构

```
goal ──workflow_route_rules 关键词路由──→ 规范文档路径（复用现有配置）
                                              │ 读文档（file_objects → storage_key → 文件）
                                              ▼
                                    parse_structure_from_doc（表格 / 编号列表）
                                              │
                无路由命中 ──→ 读蓝图原文 → parse_default_structure_from_blueprint（## 3 段）
                                              │
                          解析失败 → 缓存上次成功结果 → 硬编码 DEFAULT_MODULES 兜底
                                              │
                                    write_file 校验 + 骨架用该结构
```

### 组件

#### 1. `parse_structure_from_doc(text: str) -> list[str] | None`（plan_structure.py 新增）

路由文档通用解析，支持两种格式：

- **表格格式**（UGC 规范）：行 `| Brief Recap | 为什么做… | 核心任务… |` → 首列即模块名
  - 匹配：行首 `|` 后首个非空单元，长度 ≤30 字符
- **编号列表**（矩阵号规范）：`1. 目标回顾` → 提取
- 过滤：`配置版本`/`生效日期`/非模块说明行；至少提取 3 个才返回；失败 → None

#### 2. `parse_default_structure_from_blueprint(blueprint_text: str) -> list[str] | None`（plan_structure.py 新增）

蓝图默认结构解析：

- 定位 `## 3. 正式方案默认结构` 段（到下一个 `## ` 标题行止）
- 段内编号列表：`1. Brief Recap：复述背景、推广主体…` → 模块名取**冒号前**部分
- 8 个模块全部提取成功才返回；失败 → None

#### 3. `resolve_structure_doc(goal: str) -> str | None`（新增）

- 复用 `workflow_route_rules` 关键词路由（config.py:28-33，与 `workflow_policy.get_instruction` 的 tier-2 路由同一解析函数 `_parse_route_rules`）
- goal 命中矩阵号规则 → 矩阵号规范文档；命中 UGC 规则 → UGC 规范文档；无命中 → None（走蓝图默认）

#### 4. tool_executor 接入

- `_resolve_active_structure(goal: str | None) -> list[str]`（替换 `_resolve_active_structures`）
  - 指纹缓存：`{doc_path: (sha256, modules)}`（规范文档与蓝图各一条缓存）
  - 路由命中 → 读规范文档 → 解析 → 缓存
  - 无命中 → 读蓝图（`workflow_core_doc_path` 指向文件）→ 解析默认段 → 缓存
  - 解析失败 → `cached[1] if cached else DEFAULT_MODULES`（用户确认：用上一次的编码情况）
- `_write_file`：`modules = await _resolve_active_structure(goal)` → `validate_plan_structure(content, modules=modules)` → 校验 + 骨架同现状

### 数据流

1. goal="矩阵号代运营方案" → 矩阵号规范.md → 9 模块校验 ✓
2. goal="UGC 双平台种草" → UGC 规范.md → 10 模块校验 ✓
3. goal="小红书种草方案"（无路由）→ 蓝图 `## 3` 段 → 8 模块（动态，蓝图改则跟随）✓
4. 文档更新 → sha256 变 → 缓存失效 → 重读重解析 ✓
5. 解析失败 → 缓存旧值 → 无缓存 → 硬编码 DEFAULT_MODULES 兜底 ✓

### 性能

- 缓存命中：纯内存 dict 查找（~0.001ms），不查 DB（旧实现每次校验查 `workflow_doc_summaries`）
- 文档变更后首次：读文件（蓝图 15KB / 矩阵号 7.7KB / UGC 3.3KB）+ 正则解析 ≈ 2ms
- 文档每 run 已被模型注入读取一次，检查器复用同源加载，边际成本≈0

### 错误处理

- 路由文档缺失 / 读文件失败 / 解析失败 → 缓存旧值 → 硬编码兜底（静默降级，不报错不影响 run）
- 蓝图缺失 / 默认段解析失败 → 同上
- 不新增网络调用；解析是纯文本正则

### 测试（tests/test_plan_structure.py + tests/test_agent_tool_files.py）

1. 表格格式解析（UGC 10 模块样例）
2. 编号列表解析（矩阵号 9 模块样例）
3. 蓝图默认段解析（`1. Brief Recap：…` 冒号截断 → `Brief Recap`）
4. 蓝图默认段改 9 模块 → 解析出 9 个（动态性验证）
5. 解析失败 → None；空文本 → None
6. goal 路由命中/未命中（复用 route_rules 样例）
7. tool_executor 集成：fake 文档路由到对应结构；解析失败回退缓存 → 硬编码

### 范围外（YAGNI）

- 不引入向量知识库 / embedding（关键词路由 + 全文注入已覆盖需求）
- 不做新表、不改蒸馏管线、不动 DB schema
- 方案输出模板.md（无 route_rules 指向）不纳入校验——保持"校验与注入同源"
