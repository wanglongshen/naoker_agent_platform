# Multi-Structure Blueprint Routing Design

**日期：** 2026-08-04
**状态：** 已批准（brainstorming 完成）

## 背景

write-file-save-hardening 实施中，蒸馏摘要重蒸馏到 v5 后，其"正式方案默认结构"段从单一编号列表（`1. Brief Recap`…）变成了**多套按任务类型区分的结构清单**：

```
- 小红书种草（8 模块）：Brief Recap；前策调研与思考；本品表现与机会下探；
  用户分析与达人类型；创意与传播规划（传播 TAG、核心创意内容、达人类型、
  Message House、Content Demo）；投流策略；Roadmap；附录。
- 矩阵号代运营（9 模块）：目标回顾；市场与友商调研；社媒平台生态概览；
  品牌资产与账号机会梳理；矩阵账号策略总纲；品牌官号内容策划；
  创始人 IP 号内容策划；投流与增长规划；3 个月 Roadmap 与交付保障。
```

现有 `parse_module_list_from_summary` 只识别旧编号列表格式 → 对新摘要返回 None → 校验静默回退 DEFAULT 8 模块。后果：矩阵号代运营任务（蓝图要求 9 模块结构）会被按 DEFAULT 8 模块校验和生成骨架——**校验/骨架强制的是旧结构，与蓝图不一致**。

本设计解决：解析多套结构，按 run 的 goal 路由到对应结构，使校验与骨架跟随蓝图实际结构。

## 设计

### 架构总览

```
蒸馏摘要（含多套结构清单）→ parse_structures_from_summary → {任务类型: 模块清单}
                                                            │
                    goal（run 任务描述）──pick_structure──→ 选中对应结构
                                                            │
                                   write_file 校验 + 骨架用选中结构；无匹配 → DEFAULT
```

### 组件

#### 1. `parse_structures_from_summary(summary) -> dict[str, list[str]] | None`（plan_structure.py 新增）

- 逐行正则匹配新格式：`^- (.+?)（(\d+) 模块）：(.+)$`
- 模块名按 `；`（中文分号）分割，兼容 `,`/`,`；保留括号尾注原名（如 `创意与传播规划（传播 TAG、核心创意内容、达人类型、Message House、Content Demo）` 整体作为模块名）
- 返回 `{"小红书种草": [...], "矩阵号代运营": [...]}`
- **兼容旧格式**：若新格式一行都匹配不到，尝试旧编号列表解析（`^\d+\.\s+\S`，复用现有逻辑）→ 返回 `{"默认": [8 模块]}`
- 解析失败 → None（调用方静默 fallback 到 DEFAULT_MODULES）

#### 2. `pick_structure(structures: dict[str, list[str]] | None, goal: str) -> list[str]`（plan_structure.py 新增）

- `structures` 为 None 或空 → 返回 DEFAULT_MODULES
- 关键词匹配：对每个任务类型名做子串匹配 + 预置别名变体映射：

| 类型名 | 匹配变体 |
|---|---|
| 小红书种草 | 小红书、种草 |
| 矩阵号代运营 | 矩阵号、代运营、年度运营、品牌官号、创始人IP |
| UGC 种草 | UGC、KOC、素人 |
| 默认（旧格式） | 任意 |

- 匹配到 → 返回对应模块清单；无匹配 → DEFAULT_MODULES
- 多类型同时命中时按别名变体表的顺序取第一个命中

#### 3. tool_executor 接入

- `ToolExecutor.execute()` 增加参数 `goal: str | None = None`（默认 None，不破坏其他调用点）
- loop.py 的 `tool_executor.execute(...)` 调用处传 `goal=run.goal`
- `_resolve_active_modules` 改为 `_resolve_active_structures`：缓存整个 `{任务类型: 清单}` 映射（指纹 `f"{file_sha256}:{distilled_at}"` 不变逻辑）；再经 `pick_structure` 取当前 goal 对应结构
- `_write_file` 校验流程：

```python
if is_plan_like_content(content):
    structures = await self._resolve_active_structures()
    modules = pick_structure(structures, goal) if goal else DEFAULT_MODULES
    missing_modules = validate_plan_structure(content, modules=modules)
    if len(missing_modules) >= 3:
        return {"error": "plan_structure_incomplete", "missing_modules": missing_modules,
                "skeleton": build_skeleton(modules),
                "hint": "请保留你已写的内容，仅按骨架补全缺失模块后重新 write_file，不要重写全文。"}
```

### 数据流

1. 蓝图更新 → 文件 sha 变化 → 重新蒸馏 → 新摘要含多套结构 → 解析器读新映射（指纹缓存失效后重解析一次）
2. goal="请生成小红书种草方案" → pick_structure 路由到小红书 8 模块结构 → 校验缺失按该结构算
3. goal 无匹配（如"写个文案"）→ DEFAULT_MODULES（现状行为不变）
4. 摘要缺失/格式漂移/解析失败 → None → DEFAULT_MODULES

### 错误处理

- 摘要缺失 / 行格式漂移 / 解析失败 → 静默 fallback DEFAULT_MODULES，不报错不影响 run
- 结构映射解析成功但 goal 无匹配 → DEFAULT_MODULES
- 不新增网络调用；解析是纯文本正则

### 测试（tests/test_plan_structure.py + tests/test_agent_tool_files.py）

1. 新格式解析：多套结构、括号尾注、`；` 分隔
2. 旧格式兼容：编号列表 → `{"默认": [...]}`
3. 解析失败：乱格式 → None
4. pick_structure：goal 含类型名 → 对应结构；含别名 → 对应结构；无匹配 → DEFAULT
5. tool_executor：goal="小红书种草" → 校验按小红书 8 模块；goal=None/无匹配 → DEFAULT；FakeSession 路径不回归

### 范围外（YAGNI）

- 不做任务分类的 LLM 调用——仅关键词路由
- 不把结构映射落库——派生数据，内存缓存即可
- 不改 workflow_policy（蒸馏 prompt 已正确，多套结构是蓝图原文内容）
