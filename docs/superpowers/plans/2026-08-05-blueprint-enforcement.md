# 蓝图强制校验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make write_file structure validation strictly enforce the blueprint: any missing module (≥1) from the dynamically-resolved blueprint/spec-doc module list rejects the write; placeholder words (概要/待补充/待检索/初稿/待确认) also reject it (delivery-cleanliness red line); and the alias-matching bug that silently skipped modules is fixed. The model is then forced to write per the blueprint skeleton.

**Architecture:** Three fixes in the existing validation chain (`tool_executor._write_file` → `validate_plan_structure` → `_MODULE_ALIASES` / `_resolve_active_structure`):
1. Rejection threshold `len(missing) >= 3` → `>= 1` (any missing module rejects; works for any dynamic module count 8/9/10).
2. Fix `_MODULE_ALIASES` key mismatch: alias table keyed by short names (`本品表现`, `用户分析`, `前策调研`) while `validate_plan_structure` looks up by full module names (`本品表现与机会下探`...) — the `.get()` always misses. Restructure to lookup both full name and short-name variants.
3. New delivery-cleanliness check: content containing placeholder words (概要/待补充/待检索/待确认/初稿/待完善) is rejected with `error: plan_has_placeholders` — the model must remove them (blueprint red line: 客户版不写待补充/待确认).

**Tech Stack:** Python 3.11 / FastAPI / pytest.

## Global Constraints

- 模块清单保持动态：`_resolve_active_structure` 继续从蓝图 `## 3` / 矩阵号 / UGC 文档原文解析，**不硬编码模块数量**
- 拒绝阈值 `>= 1`（缺任何模块都拒，适配任意蓝图结构）
- 占位词黑名单：概要、待补充、待检索、待确认、初稿、待完善、待定（严格按此清单）
- 占位词校验只对**方案类**文档生效（`is_plan_like_content` 判定后），普通笔记不受影响
- 现有测试必须全部通过（后端 762 passed 基线）
- commit 从仓库根 C:\01_agent_loop_pro 执行，仓库根相对路径
- 共享 Postgres 测试 DB：同一时刻只允许一个 pytest 进程（先 `Get-Process python -ErrorAction SilentlyContinue`）

---

### Task 1: 阈值收紧 + 别名修复（plan_structure.py）

**Files:**
- Modify: `backend/app/services/agent/plan_structure.py`
- Test: `backend/tests/test_plan_structure.py`

**Interfaces:**
- Consumes: 现有 `validate_plan_structure(content, modules=None) -> list[str]`、`_MODULE_ALIASES`
- Produces: `validate_plan_structure` 行为不变（返回缺失列表）；`_MODULE_ALIASES` 重构为「完整名 → 别名变体」映射（含短名匹配）；新增 `has_placeholder_words(content) -> list[str]`（返回命中的占位词）

- [ ] **Step 1: Write the failing tests**（追加到 `backend/tests/test_plan_structure.py`）

```python
def test_alias_matches_short_variant_of_full_module_name():
    content = "## 本品表现\n- 品牌现状分析\n## 用户分析\n- 人群画像"
    modules = ["本品表现与机会下探", "用户分析与达人类型"]
    missing = validate_plan_structure(content, modules=modules)
    assert missing == []


def test_alias_matches_synonym_of_full_module_name():
    content = "## 竞品调研\n- 行业研究\n## 目标用户\n- 画像"
    modules = ["前策调研与思考", "用户分析与达人类型"]
    missing = validate_plan_structure(content, modules=modules)
    assert missing == []


def test_placeholder_words_detected():
    from app.services.agent.plan_structure import has_placeholder_words
    hits = has_placeholder_words("本方案为初稿，数据待补充，创意待确认")
    assert set(hits) == {"初稿", "待补充", "待确认"}


def test_placeholder_words_clean_content():
    from app.services.agent.plan_structure import has_placeholder_words
    assert has_placeholder_words("完整方案，含全部数据与结论") == []
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_plan_structure.py -q
```
Expected: 前两个 FAIL（别名查不到→missing 非空）、后两个 FAIL（函数不存在）

- [ ] **Step 3: Implement**

**3a.** 重构 `_MODULE_ALIASES`——key 改为**完整模块名**，value 含短名变体与同义词：

```python
_MODULE_ALIASES: dict[str, tuple[str, ...]] = {
    "Brief Recap": ("brief recap", "brief 复述", "brief回述", "brief 概述"),
    "前策调研与思考": ("前策调研", "调研", "前策", "竞品", "行业研究"),
    "本品表现与机会下探": ("本品表现", "本品", "品牌表现", "品牌现状", "机会下探"),
    "用户分析与达人类型": ("用户分析", "目标用户", "人群画像", "用户画像", "达人类型"),
    "创意与传播规划": ("创意", "传播规划", "创意方向", "传播策略"),
    "投流策略": ("投流", "投放", "media", "kfs", "关键词"),
    "Roadmap": ("roadmap", "road map", "路线图", "执行节奏", "时间表"),
    "附录": ("附录",),
}
```

注意：key 必须与 `DEFAULT_MODULES` 及蓝图解析出的模块名**完全一致**（`validate_plan_structure` 用 `_MODULE_ALIASES.get(name)` 精确匹配 key）。蓝图/矩阵号/UGC 解析出的模块名若不在表中，则无别名（仅子串匹配）——可接受，不额外扩展。

**3b.** 新增占位词检测（放在 `validate_plan_structure` 之后）：

```python
_PLACEHOLDER_WORDS = ("概要", "待补充", "待检索", "待确认", "初稿", "待完善", "待定")


def has_placeholder_words(content: str) -> list[str]:
    """检测内容中的占位/未完成标记词，返回命中列表（空列表=洁净）。"""
    return [word for word in _PLACEHOLDER_WORDS if word in content]
```

**3c.** 不动 `validate_plan_structure` 主体（返回缺失列表的接口保持不变）。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_plan_structure.py -q
```
Expected: PASS（含 4 新测试；既有测试若因别名 key 变化受影响需核对——先跑看）

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add backend/app/services/agent/plan_structure.py backend/tests/test_plan_structure.py
git commit -m "fix: full-name alias table and placeholder-word detection"
```

---

### Task 2: 校验接入（tool_executor.py）

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`
- Test: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Consumes: Task 1 的 `has_placeholder_words`、`validate_plan_structure`、`_resolve_active_structure`（现有）
- Produces: `_write_file` 拒绝路径扩展：
  - `len(missing_modules) >= 1` → `plan_structure_incomplete`（缺任何模块都拒）
  - `has_placeholder_words(content)` 非空 → `error: "plan_has_placeholders"` + `placeholder_words` 列表 + hint 引导移除

- [ ] **Step 1: Write the failing tests**（追加到 `backend/tests/test_agent_tool_files.py` 的 TestWriteFileStructureValidation 类）

```python
    async def test_rejects_when_one_module_missing(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        async def fake_structure(goal):
            return DEFAULT_MODULES

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/缺一模块.md",
                       "content": "# 方案\n\n## 一、Brief Recap\n\n## 二、前策调研与思考\n\n## 三、本品表现与机会下探\n\n## 四、用户分析与达人类型\n\n## 五、创意与传播规划\n\n## 六、投流策略\n\n## 七、Roadmap\n"}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "附录" in result["missing_modules"]

    async def test_rejects_placeholder_words(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        async def fake_structure(goal):
            return DEFAULT_MODULES

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        content = "\n".join(
            [f"## {name}\n\n内容" for name in DEFAULT_MODULES[:4]]
        ) + "\n## 附录\n\n数据待补充"
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/占位.md", "content": content}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result["error"] == "plan_has_placeholders"
        assert "待补充" in result["placeholder_words"]

    async def test_clean_content_passes_both_checks(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod
        from app.services.agent.plan_structure import DEFAULT_MODULES

        async def fake_structure(goal):
            return DEFAULT_MODULES

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        content = "\n".join(
            [f"## {name}\n\n完整内容" for name in DEFAULT_MODULES]
        )
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/完整.md", "content": content}},
            owner_user_id="00000000-0000-0000-0000-0000000000aa",
            goal="写方案",
        )
        assert result.get("error") is None
```

**关键**：第三个测试（clean content）会真实写文件到测试 DB/磁盘——先读该文件既有测试如何 mock 文件仓储（FakeSession 模式），若该测试触碰真实 DB 导致环境依赖，改为断言前两个检查通过后进入写文件分支（mock `FileRepository` 或直接 monkeypatch `_write_file` 内部的存储调用）。**先读 test_agent_tool_files.py 现有测试模式再写。**

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation -q
```
Expected: 新测试 FAIL（阈值 3 放行缺 1 个 / 无占位词校验）

- [ ] **Step 3: Implement** — `_write_file` 校验块（当前 ~line 505-514）替换为：

```python
        if is_plan_like_content(content):
            modules = await _resolve_active_structure(goal)
            missing_modules = validate_plan_structure(content, modules=modules)
            if missing_modules:
                return {
                    "error": "plan_structure_incomplete",
                    "missing_modules": missing_modules,
                    "skeleton": build_skeleton(modules),
                    "hint": (
                        "请保留你已写的内容，仅按 skeleton 中的模块结构补全缺失模块后重新 write_file，不要重写全文。"
                        "若一次输出放不下全部模块内容：先写入包含全部章节标题与要点的骨架文件（通过校验），"
                        "再用 edit_file 逐章填充详细内容。"
                    ),
                }
            placeholder_hits = has_placeholder_words(content)
            if placeholder_hits:
                return {
                    "error": "plan_has_placeholders",
                    "placeholder_words": placeholder_hits,
                    "hint": (
                        "内容包含未完成标记词：" + "、".join(placeholder_hits) +
                        "。请移除这些词，把内容写成完整的正式交付版本（客户版不得出现待补充/待确认等字样），"
                        "然后重新 write_file。"
                    ),
                }
```

注意 import：`has_placeholder_words` 加入 tool_executor.py 顶部 plan_structure import 块。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation -q
```
Expected: PASS（含新测试 + 既有测试——注意既有 `test_write_file_*` 测试若用 8 模块完整内容则仍通过，若有测试内容含"初稿/概要"等词会新失败，逐一核对调整）

- [ ] **Step 5: Regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tool_files.py tests/test_plan_structure.py tests/test_agent_loop.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: enforce any-missing-module rejection and placeholder-word check"
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
Expected: 762+ passed（零失败；若出现已知 flaky 的 avatar/seed 测试单独重跑确认）

- [ ] **Step 2: 冒烟 — 真实文件校验**（直连验证，用刚才用户实际生成的违规模板文件）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); import asyncio; exec(open(r'C:\Users\Lenovo\AppData\Local\Temp\opencode\verify_validation.py', encoding='utf-8').read())"
```
Expected: `missing` 非空（缺 ≥1 模块被拒）或 placeholder 命中——与修复前对比，确认该文件现在**会被拒绝**

- [ ] **Step 3: Report** — 无提交；回报用户：后端测试数 + 冒烟确认（原通过的违规文件现在被拒）
