# 蓝图原文驱动的骨架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the write_file rejection skeleton reflect the blueprint/spec-doc ORIGINAL text (module descriptions from the blueprint `## 3` section, 矩阵号 numbered list, and UGC table), replacing the static hardcoded `_SKELETON_GUIDES` as the primary guide. The skeleton the model receives after a rejection must show the blueprint's actual requirements, not auxiliary static hints.

**Architecture:** `parse_default_structure_from_blueprint` and `parse_structure_from_doc` currently return `list[str]` (names only), discarding descriptions. Change them to also extract per-module descriptions (blueprint: text after `：`; UGC table: 必须回答的问题 column; 矩阵号 list: text after the module name if present). `build_skeleton` gains an optional `guides: dict[str, str] | None` parameter — when provided, each module's skeleton line includes the blueprint-original description; `_SKELETON_GUIDES` becomes fallback only (used when no description was parsed, e.g. DEFAULT_MODULES hardcoded path). `_resolve_active_structure` in tool_executor.py returns the module list as before (signature unchanged), and the validation rejection in `_write_file` builds the skeleton with the blueprint-derived guides via a new helper.

**Tech Stack:** Python 3.11 / FastAPI / pytest.

## Global Constraints

- 解析函数返回值**不变**：`parse_default_structure_from_blueprint` / `parse_structure_from_doc` 仍返回 `list[str]`（现有调用方零改动）；新增**独立辅助函数**提取描述映射
- 骨架指引优先级：蓝图原文描述 > 静态 `_SKELETON_GUIDES` > 无指引（仅标题）
- 蓝图 `## 3` 节描述 = 冒号（`：`或`:`）后的原文；UGC 表格描述 = "必须回答的问题" 列；矩阵号编号列表描述 = 行内模块名后若存在冒号则取其后，无冒号则无描述
- 模块名提取逻辑（冒号前部分、`_clean_module_name`、编号连续校验）**不变**
- 现有测试必须全部通过（后端 769 passed 基线）
- commit 从仓库根 C:\01_agent_loop_pro 执行，仓库根相对路径
- 共享 Postgres 测试 DB：同一时刻只允许一个 pytest 进程（先 `Get-Process python -ErrorAction SilentlyContinue`）

---

### Task 1: plan_structure.py — 描述提取函数 + build_skeleton 参数化

**Files:**
- Modify: `backend/app/services/agent/plan_structure.py`
- Test: `backend/tests/test_plan_structure.py`

**Interfaces:**
- Consumes: 现有 `_LIST_ITEM_RE`、`_clean_module_name`、`_SKELETON_GUIDES`、`_CN_NUMERALS`
- Produces:
  - `extract_blueprint_guides(blueprint_text: str) -> dict[str, str]`（蓝图 `## 3` 节：模块名 → 冒号后原文描述；解析失败返回空 dict）
  - `extract_doc_guides(doc_text: str) -> dict[str, str]`（规范文档：表格"必须回答的问题"列或编号列表冒号后描述；失败返回空 dict）
  - `build_skeleton(modules: list[str], guides: dict[str, str] | None = None) -> str`（新参数：有描述用描述，无描述回退 `_SKELETON_GUIDES`，再无则仅标题）

- [ ] **Step 1: Write the failing tests**（追加到 `backend/tests/test_plan_structure.py`）

```python
def test_extract_blueprint_guides_keeps_original_descriptions():
    blueprint = (
        "## 3. 正式方案默认结构\n\n"
        "1. Brief Recap：复述背景、推广主体、核心任务、目标心智/效果。\n"
        "2. 前策调研与思考：行业/平台现状、竞品拆解、demo 链接、前端小结。\n"
        "3. 本品表现与机会下探：本品资产、平台表现、用户原生表达、卖点转译。\n"
        "4. 用户分析与达人类型：人群画像、内容偏好、达人类型、内容任务。\n"
        "5. 创意与传播规划：传播 TAG、核心创意内容、达人类型、Message House、Content Demo。\n"
        "6. 投流策略：阶段、预算比例、投放形式、关键词、人群包、效果口径。\n"
        "7. Roadmap：阶段、时间、核心目标、传播信息、达人、内容、投流、KPI。\n"
        "8. 附录：达人筛选、团队、案例。\n"
    )
    guides = extract_blueprint_guides(blueprint)
    assert guides["Brief Recap"] == "复述背景、推广主体、核心任务、目标心智/效果。"
    assert guides["本品表现与机会下探"] == "本品资产、平台表现、用户原生表达、卖点转译。"
    assert guides["附录"] == "达人筛选、团队、案例。"


def test_extract_doc_guides_from_table():
    doc = (
        "| 模块 | 必须回答的问题 | 必须形成的输出 |\n"
        "| --- | --- | --- |\n"
        "| Brief Recap | 为什么做、对谁做 | 核心任务 |\n"
        "| 市场与赛道 | 品类正发生什么变化 | 品类机会 |\n"
    )
    guides = extract_doc_guides(doc)
    assert guides["Brief Recap"] == "为什么做、对谁做"
    assert guides["市场与赛道"] == "品类正发生什么变化"


def test_extract_doc_guides_from_numbered_list():
    doc = "1. 目标回顾：复盘上季度目标与完成度\n2. 市场与友商调研\n3. 社媒平台生态概览：平台角色与优先级\n"
    guides = extract_doc_guides(doc)
    assert guides["目标回顾"] == "复盘上季度目标与完成度"
    assert "市场与友商调研" not in guides  # 无冒号 → 无描述
    assert guides["社媒平台生态概览"] == "平台角色与优先级"


def test_build_skeleton_uses_blueprint_guides_over_static():
    modules = ["Brief Recap", "附录"]
    guides = {"Brief Recap": "复述背景、推广主体。", "附录": "达人筛选、团队。"}
    skeleton = build_skeleton(modules, guides=guides)
    assert "> 复述背景、推广主体。" in skeleton
    assert "> 达人筛选、团队。" in skeleton


def test_build_skeleton_falls_back_to_static_guides():
    skeleton = build_skeleton(["前策调研", "附录"], guides={})
    assert "竞品必查" in skeleton  # _SKELETON_GUIDES 兜底


def test_build_skeleton_without_guides_unchanged():
    old = build_skeleton(["Brief Recap", "附录"])
    assert old == build_skeleton(["Brief Recap", "附录"], guides=None)
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_plan_structure.py -q
```
Expected: 前 3 个 FAIL（函数不存在）、后 3 个 FAIL（build_skeleton 无 guides 参数）

- [ ] **Step 3: Implement**

**3a.** 新增 `extract_blueprint_guides`（放在 `parse_default_structure_from_blueprint` 之后）：

```python
def extract_blueprint_guides(blueprint_text: str) -> dict[str, str]:
    """从蓝图 '## 3. 正式方案默认结构' 段提取 模块名 → 冒号后原文描述；失败返回空 dict。"""
    if not blueprint_text:
        return {}
    section_match = re.search(
        r"^##\s*3\.\s*正式方案默认结构[^\n]*\n(.*?)(?=^##\s|\Z)",
        blueprint_text, re.M | re.S,
    )
    if not section_match:
        return {}
    guides: dict[str, str] = {}
    for line in section_match.group(1).splitlines():
        m = _LIST_ITEM_RE.match(line.strip())
        if not m:
            continue
        raw = m.group(2)
        for sep in ("：", ":"):
            if sep in raw:
                name_part, _, desc = raw.partition(sep)
                name = _clean_module_name(name_part.strip())
                if name is not None:
                    guides[name] = desc.strip()
                break
    return guides
```

**3b.** 新增 `extract_doc_guides`（放在 `parse_structure_from_doc` 之后）：

```python
def extract_doc_guides(doc_text: str) -> dict[str, str]:
    """从规范文档提取 模块名 → 描述：优先表格'必须回答的问题'列，其次编号列表冒号后文字。"""
    if not doc_text:
        return {}
    guides: dict[str, str] = {}
    lines = doc_text.splitlines()
    # 表格格式：表头首列为"模块"、第二列为"必须回答的问题"
    table_col = None
    for i, line in enumerate(lines):
        m = _TABLE_ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if table_col is None and cells and cells[0] == "模块" and len(cells) > 1 and "必须回答的问题" in cells[1]:
            table_col = 1
            continue
        if table_col is not None and cells and "---" not in cells[0]:
            name = _clean_module_name(cells[0])
            if name is not None and len(cells) > table_col and cells[table_col] != "---":
                guides[name] = cells[table_col]
    if guides:
        return guides
    # 编号列表格式：模块名后冒号文字
    for line in lines:
        m = _LIST_ITEM_RE.match(line.strip())
        if not m:
            continue
        raw = m.group(2)
        for sep in ("：", ":"):
            if sep in raw:
                name_part, _, desc = raw.partition(sep)
                name = _clean_module_name(name_part.strip())
                if name is not None:
                    guides[name] = desc.strip()
                break
    return guides
```

**3c.** `build_skeleton` 加 `guides` 参数：

```python
def build_skeleton(modules: list[str], guides: dict[str, str] | None = None) -> str:
    """生成标准标题序列（## 一、模块名）+ 每模块指引：蓝图原文描述 > 静态映射 > 无。"""
    lines: list[str] = []
    for i, name in enumerate(modules, start=1):
        numeral = _CN_NUMERALS[i - 1] if i <= len(_CN_NUMERALS) else str(i)
        lines.append(f"## {numeral}、{name}")
        guide = (guides or {}).get(name) or _SKELETON_GUIDES.get(name)
        if guide:
            lines.append(f"> {guide}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_plan_structure.py -q
```
Expected: PASS（含 6 新测试）

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add backend/app/services/agent/plan_structure.py backend/tests/test_plan_structure.py
git commit -m "feat: extract blueprint-original module descriptions for skeleton guides"
```

---

### Task 2: tool_executor.py — 校验拒绝时用蓝图原文骨架

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`
- Test: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Consumes: Task 1 的 `extract_blueprint_guides`、`extract_doc_guides`、`build_skeleton(modules, guides)`；现有 `_resolve_active_structure`、`_load_doc_text`
- Produces: `_write_file` 拒绝 response 的 `skeleton` 字段含蓝图原文描述；新增内部辅助 `_skeleton_with_blueprint(goal, modules) -> str`（读对应文档原文 → 提取 guides → build_skeleton）

- [ ] **Step 1: Write the failing tests**（追加到 `backend/tests/test_agent_tool_files.py` 的 TestWriteFileStructureValidation 类）

```python
    async def test_rejection_skeleton_includes_blueprint_descriptions(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES, extract_blueprint_guides

        blueprint = (
            "## 3. 正式方案默认结构\n\n"
            "1. Brief Recap：复述背景、推广主体、核心任务。\n"
            "2. 附录：达人筛选、团队、案例。\n"
        )

        async def fake_structure(goal):
            return DEFAULT_MODULES

        async def fake_load(doc_path):
            return blueprint

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        monkeypatch.setattr(te_mod, "_load_doc_text", fake_load)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/缺模块.md",
                       "content": "## 一、Brief Recap\n\n只有一章"}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "> 复述背景、推广主体、核心任务。" in result["skeleton"]
```

**关键**：先读 test_agent_tool_files.py 该类的既有测试——确认 `_load_doc_text` 是否可 monkeypatch（`_skeleton_with_blueprint` 内部调用它）；若 `_load_doc_text` 是模块级函数则 `monkeypatch.setattr(te_mod, "_load_doc_text", fake_load)` 可行（参考既有 test_resolve_structure_survives_load_exception 的模式）。若骨架构建函数改为不依赖 DB 的纯函数（接收 doc_text 参数），则测试更简单——**先读代码再定测试形态**。

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation -q
```
Expected: 新测试 FAIL（skeleton 无蓝图描述——仍是静态指引或仅有标题）

- [ ] **Step 3: Implement**

**3a.** tool_executor.py 顶部 plan_structure import 块加 `extract_blueprint_guides, extract_doc_guides`。

**3b.** 新增内部辅助（放在 `_resolve_active_structure` 附近）：

```python
    async def _skeleton_with_blueprint(self, goal: str, modules: list[str]) -> str:
        """按 goal 路由读对应规范文档/蓝图原文，用其模块描述构建骨架；读不到则回退静态指引。"""
        from app.services.agent.plan_structure import extract_blueprint_guides, extract_doc_guides
        doc_path = resolve_structure_doc(goal)
        guides: dict[str, str] = {}
        if doc_path is not None:
            doc_text = await _load_doc_text(doc_path)
            if doc_text:
                guides = extract_doc_guides(doc_text)
        if not guides:
            blueprint_text = await _load_doc_text(
                get_settings().workflow_core_doc_path
            ) if getattr(get_settings(), "workflow_core_doc_path", None) else ""
            if blueprint_text:
                guides = extract_blueprint_guides(blueprint_text)
        return build_skeleton(modules, guides=guides)
```

注意：`get_settings`、`resolve_structure_doc`、`_load_doc_text` 均已在模块中可用（`resolve_structure_doc` 需 import 或经 plan_structure 模块引用——先读 tool_executor.py 现有 import 确认；若 `resolve_structure_doc` 未 import 则加）。`workflow_core_doc_path` 字段名以 config.py 实际为准（先 grep 确认）。

**3c.** `_write_file` 拒绝分支（当前 ~line 508-519）的 skeleton 字段改为：

```python
            if missing_modules:
                skeleton = await self._skeleton_with_blueprint(goal, modules)
                return {
                    "error": "plan_structure_incomplete",
                    "missing_modules": missing_modules,
                    "skeleton": skeleton,
                    "hint": (
                        "请保留你已写的内容，仅按 skeleton 中的模块结构补全缺失模块后重新 write_file，不要重写全文。"
                        "若一次输出放不下全部模块内容：先写入包含全部章节标题与要点的骨架文件（通过校验），"
                        "再用 edit_file 逐章填充详细内容。"
                    ),
                }
```

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation -q
```
Expected: PASS（含新测试；既有测试若断言旧 skeleton 格式（纯标题/静态指引）受影响则核对调整——先跑看）

- [ ] **Step 5: Regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tool_files.py tests/test_plan_structure.py tests/test_agent_loop.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: build rejection skeleton from blueprint original descriptions"
```

---

### Task 3: 集成验证

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: 后端全量**（仅一个 pytest 进程；先 `Get-Process python -ErrorAction SilentlyContinue`）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/ -q
```
Expected: 769+ passed（零失败）

- [ ] **Step 2: 冒烟 — 真实蓝图骨架**（直连验证骨架含蓝图原文描述）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import asyncio, sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); from app.services.agent.plan_structure import extract_blueprint_guides; import pathlib; t = pathlib.Path(r'C:\01_agent_loop_pro\backend\var\files\4c40bada-b2e6-45ea-b1b2-a2e43e663072\965ffc405ba740ea9f8772db166d2c55').read_text(encoding='utf-8'); g = extract_blueprint_guides(t); print(list(g.items())[:3]); print('count:', len(g))"
```
Expected: 8 个模块均有描述（如 Brief Recap → 复述背景、推广主体、核心任务、目标心智/效果。）

- [ ] **Step 3: Report** — 无提交；回报用户：后端测试数 + 冒烟输出（蓝图 8 模块描述全部提取）
