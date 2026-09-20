# Multi-Structure Blueprint Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse the distilled blueprint summary's multi-structure module lists (小红书种草 8 模块 / 矩阵号代运营 9 模块 / …) and route write_file validation + skeleton by the run's goal, so validation follows the blueprint's actual structures.

**Architecture:** plan_structure.py gains two pure functions — `parse_structures_from_summary` (summary → `{任务类型: 模块清单}`, legacy numbered-list fallback to `{"默认": DEFAULT_MODULES}`) and `pick_structure` (structures + goal → chosen module list, alias matching). tool_executor replaces `_resolve_active_modules` with `_resolve_active_structures` (caches the full map, same fingerprint logic) and passes `goal` through `execute()` → `_write_file()`; loop.py passes `run.goal`.

**Tech Stack:** Python 3.11 / FastAPI / pytest / SQLAlchemy async / PostgreSQL (test DB shared — one pytest process at a time).

## Global Constraints

- 校验失败不抛异常——以观察结果 `{"error": "plan_structure_incomplete", ...}` 返回，模型才能重试
- 缺失 ≥3 个模块 → 拒绝；非方案类文档直接保存不校验
- 模块清单解析失败 → 静默回退 DEFAULT_MODULES，不报错不影响 run
- 摘要缺失/格式漂移/解析失败 → None → DEFAULT_MODULES
- 不新增网络调用；解析是纯文本正则
- 现有测试必须全部通过（全量 699 passed 基线）
- 每个任务独立提交，commit 从仓库根 C:\01_agent_loop_pro 执行，路径用仓库根相对路径

---

### Task 1: plan_structure.py — parse_structures_from_summary + pick_structure

**Files:**
- Modify: `backend/app/services/agent/plan_structure.py`（append 两个函数 + 正则常量；保留现有全部函数）
- Test: `backend/tests/test_plan_structure.py`（append 两个测试类）

**Interfaces:**
- Consumes: 现有 `DEFAULT_MODULES`（模块级常量）、`parse_module_list_from_summary(summary)`（本文件 57-78 行，保留不动）
- Produces:
  - `parse_structures_from_summary(summary: str) -> dict[str, list[str]] | None` — 新格式 `- 小红书种草（8 模块）：Brief Recap；前策调研与思考；…` → `{"小红书种草": ["Brief Recap", "前策调研与思考", …], "矩阵号代运营": […]}`；新格式一行都匹配不到时回退旧编号列表解析 → `{"默认": DEFAULT_MODULES}`；两者都失败 → None
  - `pick_structure(structures: dict[str, list[str]] | None, goal: str) -> list[str]` — 返回 goal 命中的模块清单；structures 为 None/空 → DEFAULT_MODULES；先精确匹配类型名子串，再按别名变体表匹配，无匹配 → DEFAULT_MODULES

- [ ] **Step 1: Write the failing tests**（append 到 `backend/tests/test_plan_structure.py` 末尾）

```python
from app.services.agent.plan_structure import (
    DEFAULT_MODULES,
    build_skeleton,
    parse_module_list_from_summary,
    parse_structures_from_summary,
    pick_structure,
    validate_plan_structure,
)


class TestParseStructuresFromSummary:
    def test_parses_multi_structure_new_format(self):
        summary = (
            "2. 正式方案默认结构\n"
            "任何保存到文件的方案/建议类文档正文，必须按下述对应结构逐节输出，不可自创结构。\n"
            "- 小红书种草（8 模块）：Brief Recap；前策调研与思考；本品表现与机会下探；"
            "用户分析与达人类型；创意与传播规划（传播 TAG、核心创意内容、达人类型、Message House、Content Demo）；"
            "投流策略；Roadmap；附录。\n"
            "- 矩阵号代运营（9 模块）：目标回顾；市场与友商调研；社媒平台生态概览；"
            "品牌资产与账号机会梳理；矩阵账号策略总纲；品牌官号内容策划；"
            "创始人 IP 号内容策划；投流与增长规划；3 个月 Roadmap 与交付保障。\n"
        )
        structures = parse_structures_from_summary(summary)
        assert structures is not None
        assert "小红书种草" in structures
        assert "矩阵号代运营" in structures
        assert len(structures["小红书种草"]) == 8
        assert len(structures["矩阵号代运营"]) == 9
        assert "创意与传播规划（传播 TAG、核心创意内容、达人类型、Message House、Content Demo）" in structures["小红书种草"]

    def test_legacy_numbered_list_falls_back_to_default(self):
        summary = (
            "2. 正式方案 8 模块\n"
            "保存到文件的方案/建议类文档正文，必须按下述 8 模块逐节输出，不可自创结构：\n"
            "1. Brief Recap\n2. 前策调研\n3. 本品表现\n4. 用户分析\n"
            "5. 创意与传播规划\n6. 投流策略\n7. Roadmap\n8. 附录\n"
        )
        structures = parse_structures_from_summary(summary)
        assert structures == {"默认": DEFAULT_MODULES}

    def test_returns_none_on_unparseable(self):
        assert parse_structures_from_summary("随便一段没有结构的摘要") is None
        assert parse_structures_from_summary("") is None


class TestPickStructure:
    def test_picks_by_exact_type_name(self):
        structures = {"小红书种草": ["A", "B", "C"], "矩阵号代运营": ["D", "E", "F", "G"]}
        assert pick_structure(structures, "请生成小红书种草方案") == ["A", "B", "C"]
        assert pick_structure(structures, "矩阵号代运营年度规划") == ["D", "E", "F", "G"]

    def test_picks_by_alias(self):
        structures = {"小红书种草": ["A", "B"], "UGC 种草": ["C", "D", "E"]}
        assert pick_structure(structures, "请写一份 KOC 种草方案") == ["C", "D", "E"]
        assert pick_structure(structures, "素人双平台投放方案") == ["C", "D", "E"]

    def test_default_when_no_match(self):
        structures = {"小红书种草": ["A"]}
        assert pick_structure(structures, "写个文案") == DEFAULT_MODULES

    def test_default_on_none_or_empty(self):
        assert pick_structure(None, "任意") == DEFAULT_MODULES
        assert pick_structure({}, "任意") == DEFAULT_MODULES
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\01_agent_loop_pro\backend
python -m pytest tests/test_plan_structure.py -q
```
Expected: FAIL with `ImportError: cannot import name 'parse_structures_from_summary'`

- [ ] **Step 3: Implement**（append 到 `backend/app/services/agent/plan_structure.py` 末尾，`validate_plan_structure` 之后）

```python
_STRUCTURE_LINE_RE = re.compile(r"^- (.+?)（(\d+) 模块）：(.+)$")

# 任务类型 → 关键词变体（goal 匹配用；类型名本体匹配优先于别名。
# 注意：通用词"种草/KOC/素人"只放 UGC，避免抢走小红书/矩阵号的精确路由）
_STRUCTURE_ALIASES: dict[str, tuple[str, ...]] = {
    "小红书种草": ("小红书",),
    "矩阵号代运营": ("矩阵号", "代运营", "年度运营", "品牌官号", "创始人IP", "创始人ip"),
    "UGC 种草": ("UGC", "KOC", "素人", "种草", "双平台", "季度投放"),
}


def parse_structures_from_summary(summary: str) -> dict[str, list[str]] | None:
    """从蒸馏摘要解析 {任务类型: 模块清单} 映射。

    新格式：'- 小红书种草（8 模块）：Brief Recap；前策调研与思考；…'
    无新格式行时回退旧编号列表 → {'默认': 清单}；都失败返回 None。
    """
    if not summary:
        return None
    structures: dict[str, list[str]] = {}
    for line in summary.splitlines():
        m = _STRUCTURE_LINE_RE.match(line.strip())
        if not m:
            continue
        type_name = m.group(1).strip()
        modules = [part.strip() for part in m.group(3).split("；") if part.strip()]
        if type_name and len(modules) >= 3:
            structures[type_name] = modules
    if structures:
        return structures
    legacy = parse_module_list_from_summary(summary)
    if legacy is not None:
        return {"默认": legacy}
    return None


def pick_structure(structures: dict[str, list[str]] | None, goal: str) -> list[str]:
    """按 goal 路由到对应任务类型的模块清单；无匹配回退 DEFAULT_MODULES。

    优先精确匹配类型名子串，其次按 _STRUCTURE_ALIASES 关键词匹配（取第一个命中）。
    """
    if not structures:
        return DEFAULT_MODULES
    lowered_goal = goal.lower()
    for type_name in structures:
        if type_name.lower() in lowered_goal:
            return structures[type_name]
    for type_name, aliases in _STRUCTURE_ALIASES.items():
        if type_name not in structures:
            continue
        if any(alias.lower() in lowered_goal for alias in aliases):
            return structures[type_name]
    return DEFAULT_MODULES
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\01_agent_loop_pro\backend
python -m pytest tests/test_plan_structure.py -q
```
Expected: PASS（旧测试 + 新增 7 个全部通过）

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add backend/app/services/agent/plan_structure.py backend/tests/test_plan_structure.py
git commit -m "feat: parse multi-structure blueprint summary + pick structure by goal"
```

---

### Task 2: tool_executor — route validation by goal

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`（`_resolve_active_modules` → `_resolve_active_structures`；`execute()` 加 `goal` 参数；`_write_file` 传 goal 并按结构路由）
- Modify: `backend/app/services/agent/loop.py`（`tool_executor.execute(...)` 调用处传 `goal=run.goal`）
- Test: `backend/tests/test_agent_tool_files.py`（append 到 `TestWriteFileStructureValidation` 类）

**Interfaces:**
- Consumes: Task 1 的 `parse_structures_from_summary(summary) -> dict[str, list[str]] | None`、`pick_structure(structures, goal) -> list[str]`、`DEFAULT_MODULES`、`validate_plan_structure(content, modules=None)`、`build_skeleton(modules)`；现有 `_module_cache`、`get_settings()`、`async_session_factory()`、`WorkflowDocSummary`
- Produces: `ToolExecutor.execute(action, web_enabled=True, owner_user_id=None, is_super_admin=False, goal: str | None = None)`；`_resolve_active_structures() -> dict[str, list[str]] | None`（模块级函数）；`_write_file(payload, owner_user_id, goal: str | None = None)`

- [ ] **Step 1: Check loop.py call site** — find the `tool_executor.execute(` call inside `_stream_visible_thought_with_tool_interleave`（约 loop.py:1498，当前传 `web_enabled=`, `owner_user_id=`, `is_super_admin=`）。确认该作用域内 `run` 变量可用（同一函数内 `run.goal` 在其他地方已被使用）。确认后进入 Step 2。

- [ ] **Step 2: Write the failing tests**（append 到 `backend/tests/test_agent_tool_files.py` 的 `TestWriteFileStructureValidation` 类内）

```python
    async def test_write_file_routes_by_goal(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod

        async def fake_structures():
            return {
                "小红书种草": ["Brief Recap", "前策调研与思考", "本品表现与机会下探",
                              "用户分析与达人类型", "创意与传播规划", "投流策略", "Roadmap", "附录"],
            }

        monkeypatch.setattr(te_mod, "_resolve_active_structures", fake_structures)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/小红书种草方案.md",
                       "content": "# 小红书种草方案\n\n## 一、Brief Recap\n\n## 二、创意玩法\n\n"}},
            owner_user_id=self.owner_user_id,
            goal="请生成小红书种草方案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "前策调研与思考" in result["missing_modules"]
        assert "## 一、前策调研与思考" in result["skeleton"]

    async def test_write_file_without_goal_uses_default(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod

        async def fake_structures():
            return {"小红书种草": ["小红书专属模块"]}

        monkeypatch.setattr(te_mod, "_resolve_active_structures", fake_structures)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/普通方案.md",
                       "content": "# 方案\n\n## 一、Brief Recap\n\n## 二、创意方向\n\n"}},
            owner_user_id=self.owner_user_id,
            goal=None,
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "小红书专属模块" not in result["missing_modules"]
```

注意：`TestWriteFileStructureValidation` 类已有 `self.owner_user_id` fixture/setup——先读该类现有测试（约 800-870 行）确认属性名，若不同则用现有属性名替换。

- [ ] **Step 3: Run tests to verify they fail**

```
cd C:\01_agent_loop_pro\backend
python -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation -q
```
Expected: FAIL with `AttributeError: module ... has no attribute '_resolve_active_structures'`

- [ ] **Step 4: Implement**

在 `backend/app/services/agent/tool_executor.py` 中：

**4a.** 更新 import 块（当前约 27-33 行）：把 `parse_module_list_from_summary` 替换为 `parse_structures_from_summary`，并加 `pick_structure`。改后该 import 块为：

```python
from app.services.agent.plan_structure import (
    DEFAULT_MODULES,
    build_skeleton,
    is_plan_like_content,
    parse_structures_from_summary,
    pick_structure,
    validate_plan_structure,
)
```

**4b.** 把 `_module_cache` 类型与 `_resolve_active_modules`（当前 222-248 行）整体替换为：

```python
_module_cache: dict[str, tuple[str, dict[str, list[str]]]] = {}


async def _resolve_active_structures() -> dict[str, list[str]] | None:
    """从当前蒸馏摘要解析 {任务类型: 模块清单} 映射；失败返回 None（调用方回退默认）。"""
    settings = get_settings()
    if not settings.workflow_docs_enabled:
        return None
    doc_path = settings.workflow_core_doc_path
    cached = _module_cache.get(doc_path)
    try:
        async with async_session_factory() as session:
            row = await session.scalar(
                select(WorkflowDocSummary).where(WorkflowDocSummary.doc_path == doc_path)
            )
    except Exception:
        return cached[1] if cached else None
    if row is None or not row.summary:
        return cached[1] if cached else None
    fingerprint = f"{row.file_sha256}:{row.distilled_at}"
    if cached and cached[0] == fingerprint:
        return cached[1]
    parsed = parse_structures_from_summary(row.summary)
    if parsed is None:
        return cached[1] if cached else None
    _module_cache[doc_path] = (fingerprint, parsed)
    return parsed
```

**4c.** `execute()` 签名（当前 252-254 行）改为：

```python
    async def execute(self, action: dict[str, Any], web_enabled: bool = True,
                      owner_user_id: uuid.UUID | None = None,
                      is_super_admin: bool = False,
                      goal: str | None = None) -> dict[str, Any]:
```

**4d.** `execute()` 内 `write_file` 分支（当前约 269-270 行 `if action_type == "write_file":`）传 goal：

```python
        if action_type == "write_file":
            return await self._write_file(payload, owner_user_id, goal)
```

**4e.** `_write_file` 签名（当前 455-457 行）与校验块（当前 468-477 行）改为：

```python
    async def _write_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None,
        goal: str | None = None,
    ) -> dict[str, Any]:
```

```python
        if is_plan_like_content(content):
            structures = await _resolve_active_structures()
            modules = pick_structure(structures, goal) if goal else DEFAULT_MODULES
            missing_modules = validate_plan_structure(content, modules=modules)
            if len(missing_modules) >= 3:
                return {
                    "error": "plan_structure_incomplete",
                    "missing_modules": missing_modules,
                    "skeleton": build_skeleton(modules),
                    "hint": "请保留你已写的内容，仅按 skeleton 中的模块结构补全缺失模块后重新 write_file，不要重写全文。",
                }
```

**4f.** `backend/app/services/agent/loop.py` 的 `tool_executor.execute(` 调用处（约 1498 行）加 `goal=run.goal`：

```python
                self.tool_executor.execute(action, web_enabled=web_enabled,
                                           owner_user_id=owner_user_id,
                                           is_super_admin=is_super_admin,
                                           goal=run.goal),
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd C:\01_agent_loop_pro\backend
python -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation -q
```
Expected: PASS（现有 + 新增 2 个）

- [ ] **Step 6: Run broader regression**（确认 FakeSession 路径与旧行为不回归）

```
cd C:\01_agent_loop_pro\backend
python -m pytest tests/test_agent_tool_files.py tests/test_plan_structure.py -q
```
Expected: PASS

- [ ] **Step 7: Commit**（从仓库根）

```bash
git add backend/app/services/agent/tool_executor.py backend/app/services/agent/loop.py backend/tests/test_agent_tool_files.py
git commit -m "feat: route write_file plan validation by goal to blueprint structure"
```

---

### Task 3: Integration verification

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: Confirm no other `execute(` callers break** — grep 确认 `tool_executor.execute(` 全仓只有 loop.py 一处调用（`goal` 参数有默认值 None，不破坏其他调用）：

```
cd C:\01_agent_loop_pro\backend
python -c "import re,glob;[print(f, re.findall(r'execute\(', open(f,encoding='utf-8').read())) for f in glob.glob('app/**/*.py', recursive=True)]"
```
Expected: 只有 tool_executor.py 定义处 + loop.py 调用处

- [ ] **Step 2: Run full backend suite**（仅一个 pytest 进程，先确认无其他 python 进程占用 test DB：`Get-Process python -ErrorAction SilentlyContinue`；若 39580 等旧进程仍在运行则等待其结束）

```
cd C:\01_agent_loop_pro\backend
python -m pytest tests/ -q
```
Expected: 699+ passed（新增测试全部通过，零失败）

- [ ] **Step 3: Live smoke — parse the real v5 summary**（用真实 DB 里的蒸馏摘要验证端到端解析 + 路由；不改任何数据）

```
cd C:\01_agent_loop_pro\backend
python -c "import asyncio; exec('''\nimport sys\nsys.path.insert(0, r\"C:\\01_agent_loop_pro\\backend\")\nfrom sqlalchemy import text\n\nasync def main():\n    from app.db.session import async_session_factory\n    from app.services.agent.plan_structure import parse_structures_from_summary, pick_structure\n    async with async_session_factory() as s:\n        summary = (await s.execute(text(\"SELECT summary FROM workflow_doc_summaries\"))).scalar()\n        structures = parse_structures_from_summary(summary)\n        print(\"structures:\", structures)\n        print(\"小红书 goal ->\", pick_structure(structures, \"请生成小红书种草方案\")[:3])\n        print(\"矩阵号 goal ->\", pick_structure(structures, \"矩阵号代运营方案\")[:3])\n\nasyncio.run(main())\n''')"
```
Expected: `structures:` 非 None 且含 "小红书种草"/"矩阵号代运营"（与真实摘要一致）；`小红书 goal ->` 以 "Brief Recap" 开头；`矩阵号 goal ->` 以 "目标回顾" 开头

- [ ] **Step 4: Report** — 无提交；把冒烟输出追加到 `C:\01_agent_loop_pro\.superpowers\sdd\progress.md`，并回报给用户：全量测试数 + 冒烟验证结果

