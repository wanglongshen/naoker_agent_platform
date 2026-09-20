# Doc-Source Structure Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make write_file structure validation read the actual blueprint/spec documents (routed by goal) instead of the distilled summary, so validation follows the real document structures (矩阵号 9 模块 / UGC 10 模块 / 蓝图默认 8 模块) and auto-tracks document edits.

**Architecture:** plan_structure.py gains two pure parsers (`parse_structure_from_doc` for table + numbered-list formats, `parse_default_structure_from_blueprint` for the blueprint's `## 3` section) and `resolve_structure_doc` routes a goal to a spec document via the existing `workflow_route_rules` keyword routing. tool_executor replaces `_resolve_active_structures` with `_resolve_active_structure(goal)` which loads the routed doc (or blueprint default) through `workflow_policy._load_doc`, caches by sha256 fingerprint, and falls back to cached-then-`DEFAULT_MODULES`.

**Tech Stack:** Python 3.11 / FastAPI / pytest / SQLAlchemy async / PostgreSQL (test DB shared — one pytest process at a time).

## Global Constraints

- 校验失败不抛异常——以观察结果 `{"error": "plan_structure_incomplete", ...}` 返回，模型才能重试
- 缺失 ≥3 个模块 → 拒绝；非方案类文档直接保存不校验
- 文档加载/解析失败 → 静默回退：先缓存旧值，无缓存 → `DEFAULT_MODULES`，不报错不影响 run
- 结构来源从蒸馏摘要改为原始文档；蒸馏摘要仍用于模型注入，不再承担结构校验职责
- 不新增网络调用；解析是纯文本正则；不新增 DB 表/迁移
- 现有测试必须全部通过（全量 699 passed 基线）
- 每个任务独立提交，commit 从仓库根 C:\01_agent_loop_pro 执行，路径用仓库根相对路径
- 测试 DB 共享：同一时刻只允许一个 pytest 进程（先 `Get-Process python -ErrorAction SilentlyContinue` 确认无占用）

---

### Task 1: plan_structure.py — doc parsers + structure router

**Files:**
- Modify: `backend/app/services/agent/plan_structure.py`（append 新函数；保留现有全部函数与常量）
- Test: `backend/tests/test_plan_structure.py`（append 测试类）

**Interfaces:**
- Consumes: 现有 `DEFAULT_MODULES` 常量（本文件 14-23 行，保留不动，作兜底）
- Produces:
  - `parse_structure_from_doc(text: str) -> list[str] | None` — 路由文档解析，支持表格（`| Brief Recap | 为什么做… |` 首列）与编号列表（`1. 目标回顾`）两种格式；模块名 ≤30 字符；提取 ≥3 个才返回，否则 None
  - `parse_default_structure_from_blueprint(blueprint_text: str) -> list[str] | None` — 定位 `## 3. 正式方案默认结构` 段（到下一个 `## ` 标题止），段内编号列表 `1. Brief Recap：复述背景…` 模块名取冒号前部分；提取 8 个全成功才返回，否则 None
  - `resolve_structure_doc(goal: str) -> str | None` — 复用 `workflow_route_rules` 关键词路由返回规范文档路径；无命中 → None

- [ ] **Step 1: Write the failing tests**（append 到 `backend/tests/test_plan_structure.py` 末尾）

```python
from app.services.agent.plan_structure import (
    parse_structure_from_doc,
    parse_default_structure_from_blueprint,
    resolve_structure_doc,
)

UGC_DOC_SAMPLE = (
    "| 模块 | 必须回答的问题 | 必须形成的输出 |\n"
    "| --- | --- | --- |\n"
    "| Brief Recap | 为什么做、对谁做 | 核心任务、目标心智 |\n"
    "| 市场与赛道 | 品类正发生什么变化 | 品类机会与传播命题 |\n"
    "| 竞品 | 谁占据什么心智 | 竞品心智地图 |\n"
    "| 用户 | 谁最值得优先争取 | 人群分层、痛点 |\n"
    "| 产品卖点 | 哪些产品点能解决真实问题 | 卖点转译与证据 |\n"
    "| 平台 | 平台承担什么任务 | 平台角色与卖点优先级 |\n"
    "| 策略与创意 | 用什么主张连接 | 核心策略、传播 TAG |\n"
    "| 内容与达人 | 谁来讲、讲什么 | 达人类型、内容支柱 |\n"
    "| 投流 | 如何放大优质内容 | 阶段、预算、KPI |\n"
    "| Roadmap | 如何持续推进 | 节点、内容、投流联动 |\n"
)

MATRIX_DOC_SAMPLE = (
    "## 1. 适用范围\n\n"
    "本规范适用于矩阵号代运营方案。\n\n"
    "## 2. 正式结构\n\n"
    "1. 目标回顾\n"
    "2. 市场与友商调研\n"
    "3. 社媒平台生态概览\n"
    "4. 品牌资产与账号机会梳理\n"
    "5. 矩阵账号策略总纲\n"
    "6. 品牌官号内容策划\n"
    "7. 创始人 IP 号内容策划\n"
    "8. 投流与增长规划\n"
    "9. 3 个月 Roadmap 与交付保障\n"
)

BLUEPRINT_DEFAULT_SECTION = (
    "## 3. 正式方案默认结构\n\n"
    "1. Brief Recap：复述背景、推广主体、核心任务、目标心智/效果。\n"
    "2. 前策调研与思考：行业/平台现状、竞品拆解、demo 链接、前端小结。\n"
    "3. 本品表现与机会下探：本品资产、平台表现、用户原生表达、卖点转译。\n"
    "4. 用户分析与达人类型：人群画像、内容偏好、达人类型、内容任务。\n"
    "5. 创意与传播规划：传播 TAG、核心创意内容、达人类型、Message House、Content Demo。\n"
    "6. 投流策略：阶段、预算比例、投放形式、关键词、人群包、效果口径。\n"
    "7. Roadmap：阶段、时间、核心目标、节点、物料、投放、KPI。\n"
    "8. 附录：链接筛选、团队、假设。\n\n"
    "## 4. 其他内容\n\n"
    "以下是无关内容。\n"
)


class TestParseStructureFromDoc:
    def test_table_format_ugc_10_modules(self):
        modules = parse_structure_from_doc(UGC_DOC_SAMPLE)
        assert modules is not None
        assert len(modules) == 10
        assert modules[0] == "Brief Recap"
        assert modules[-1] == "Roadmap"

    def test_numbered_list_matrix_9_modules(self):
        modules = parse_structure_from_doc(MATRIX_DOC_SAMPLE)
        assert modules is not None
        assert len(modules) == 9
        assert modules[0] == "目标回顾"
        assert modules[-1] == "3 个月 Roadmap 与交付保障"

    def test_returns_none_on_empty_or_garbage(self):
        assert parse_structure_from_doc("") is None
        assert parse_structure_from_doc("没有结构的自然语言") is None

    def test_returns_none_when_too_few(self):
        assert parse_structure_from_doc("1. A\n2. B") is None


class TestParseDefaultStructureFromBlueprint:
    def test_parses_default_8_modules(self):
        modules = parse_default_structure_from_blueprint(BLUEPRINT_DEFAULT_SECTION)
        assert modules is not None
        assert len(modules) == 8
        assert modules[0] == "Brief Recap"
        assert modules[1] == "前策调研与思考"
        assert modules[-1] == "附录"

    def test_stops_at_next_heading(self):
        modules = parse_default_structure_from_blueprint(BLUEPRINT_DEFAULT_SECTION)
        assert modules is not None
        assert len(modules) == 8  # 不含 "## 4" 之后的内容

    def test_blueprint_with_9_modules_tracks_change(self):
        text = BLUEPRINT_DEFAULT_SECTION.replace("8. 附录", "8. 附录：链接筛选。\n9. 传播预算：阶段与分配。")
        modules = parse_default_structure_from_blueprint(text)
        assert modules is not None
        assert len(modules) == 9
        assert modules[-1] == "传播预算"

    def test_returns_none_on_missing_section(self):
        assert parse_default_structure_from_blueprint("没有默认结构段") is None


class TestResolveStructureDoc:
    def test_matrix_goal_routes_to_matrix_doc(self):
        path = resolve_structure_doc("请生成矩阵号代运营年度方案")
        assert path is not None
        assert "矩阵号代运营" in path

    def test_ugc_goal_routes_to_ugc_doc(self):
        path = resolve_structure_doc("UGC 种草双平台投放方案")
        assert path is not None
        assert "UGC" in path

    def test_no_match_returns_none(self):
        assert resolve_structure_doc("写个文案") is None
```

注意：`resolve_structure_doc` 需要读取 `workflow_route_rules` 配置——测试用真实默认值（config.py:28-33）。若测试环境 `get_settings()` 返回不同值，Step 3 实现时用 `from app.core.config import get_settings` 读取（与 workflow_policy._parse_route_rules 同一来源）。

- [ ] **Step 2: Run tests to verify they fail**

```
cd C:\01_agent_loop_pro\backend
python -m pytest tests/test_plan_structure.py -q
```
Expected: FAIL with `ImportError: cannot import name 'parse_structure_from_doc'`

- [ ] **Step 3: Implement**（append 到 `backend/app/services/agent/plan_structure.py` 末尾）

```python
_TABLE_ROW_RE = re.compile(r"^\|\s*([^|]+)\s*\|")
_LIST_ITEM_RE = re.compile(r"^(\d{1,2})[\.、]\s*(.+)$")
_NON_MODULE_WORDS_DOC = ("配置版本", "生效日期", "适用范围", "核心推导链", "正式结构")


def _clean_module_name(raw: str) -> str | None:
    name = raw.strip()
    if not name or len(name) > 30:
        return None
    if any(w in name for w in _NON_MODULE_WORDS_DOC):
        return None
    return name


def parse_structure_from_doc(text: str) -> list[str] | None:
    """从规范文档解析模块结构：表格首列（UGC）或编号列表（矩阵号）。"""
    if not text:
        return None
    # 表格格式：取表格数据行的首列
    table_modules: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        m = _TABLE_ROW_RE.match(stripped)
        if not m:
            continue
        name = _clean_module_name(m.group(1))
        if name and name != "模块" and "---" not in name:
            table_modules.append(name)
    if len(table_modules) >= 3:
        return table_modules
    # 编号列表格式
    list_modules: list[str] = []
    for line in text.splitlines():
        m = _LIST_ITEM_RE.match(line.strip())
        if not m:
            continue
        name = _clean_module_name(m.group(2))
        if name:
            list_modules.append(name)
    if len(list_modules) >= 3:
        return list_modules
    return None


def parse_default_structure_from_blueprint(blueprint_text: str) -> list[str] | None:
    """从蓝图 '## 3. 正式方案默认结构' 段解析默认模块（冒号前为模块名）。"""
    if not blueprint_text:
        return None
    section_match = re.search(r"^##\s*3\.\s*正式方案默认结构[^\n]*\n(.*?)(?=^##\s|\Z)", blueprint_text, re.M | re.S)
    if not section_match:
        return None
    section = section_match.group(1)
    modules: list[str] = []
    for line in section.splitlines():
        m = _LIST_ITEM_RE.match(line.strip())
        if not m:
            continue
        name = _clean_module_name(m.group(2))
        if name is None:
            continue
        name = name.split("：")[0].split(":")[0].strip()
        if name:
            modules.append(name)
    if len(modules) >= 3:
        return modules
    return None


def resolve_structure_doc(goal: str) -> str | None:
    """按 goal 关键词路由到规范文档路径（复用 workflow_route_rules）；无命中返回 None。"""
    from app.core.config import get_settings
    rules = get_settings().workflow_route_rules
    for keywords, path in _parse_route_rules(rules):
        if any(keyword in goal for keyword in keywords):
            return path
    return None


def _parse_route_rules(raw: str) -> list[tuple[list[str], str]]:
    """与 workflow_policy._parse_route_rules 同逻辑的本地副本（避免循环依赖）。"""
    rules: list[tuple[list[str], str]] = []
    for group in raw.split("|"):
        group = group.strip()
        if not group or "=>" not in group:
            continue
        keywords_part, _, path_part = group.partition("=>")
        keywords = [k.strip() for k in keywords_part.split(";;") if k.strip()]
        path = path_part.strip()
        if keywords and path:
            rules.append((keywords, path))
    return rules
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\01_agent_loop_pro\backend
python -m pytest tests/test_plan_structure.py -q
```
Expected: PASS（旧测试 + 新增 11 个全部通过）

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add backend/app/services/agent/plan_structure.py backend/tests/test_plan_structure.py
git commit -m "feat: parse structure from spec docs + route goal to spec doc"
```

---

### Task 2: tool_executor — load structure from routed doc / blueprint

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`（替换 `_resolve_active_structures` → `_resolve_active_structure(goal)`；更新 import；`_write_file` 调用处）
- Test: `backend/tests/test_agent_tool_files.py`（append 到 `TestWriteFileStructureValidation` 类）

**Interfaces:**
- Consumes: Task 1 的 `parse_structure_from_doc(text)`, `parse_default_structure_from_blueprint(text)`, `resolve_structure_doc(goal)`, `DEFAULT_MODULES`, `validate_plan_structure(content, modules=None)`, `build_skeleton(modules)`；现有 `get_settings()`, `async_session_factory()`, `WorkflowDocSummary` import（可移除若不再使用）；`workflow_policy` 模块（`workflow_policy._load_doc`, `workflow_policy._resolve_super_admin_id`）
- Produces: `async def _resolve_active_structure(goal: str | None) -> list[str]`（模块级函数）

- [ ] **Step 1: Check current imports & call sites** — 读 `backend/app/services/agent/tool_executor.py` 顶部 import 块（确认 `WorkflowDocSummary`/`select`/`get_settings` 现状）与 `_resolve_active_modules`（当前 222-248 行附近，**注意：当前代码状态是 `_resolve_active_modules` + `_module_cache: dict[str, tuple[str, list[str]]]`，且 `execute()`/`_write_file` 尚无 `goal` 参数**——multi-structure-routing 计划未执行）及 `_write_file` 校验块（当前 468-477 行附近）。确认后进入 Step 2。

- [ ] **Step 2: Write the failing tests**（append 到 `backend/tests/test_agent_tool_files.py` 的 `TestWriteFileStructureValidation` 类内；`self.owner_user_id` 属性已存在于该类）

```python
    async def test_write_file_uses_routed_doc_structure(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod

        async def fake_structure(goal):
            return ["目标回顾", "市场与友商调研", "社媒平台生态概览",
                    "品牌资产与账号机会梳理", "矩阵账号策略总纲", "品牌官号内容策划",
                    "创始人 IP 号内容策划", "投流与增长规划", "3 个月 Roadmap 与交付保障"]

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/矩阵号代运营方案.md",
                       "content": "# 矩阵号代运营方案\n\n## 一、目标回顾\n\n## 二、投流策略\n\n"}},
            owner_user_id=self.owner_user_id,
            goal="请生成矩阵号代运营方案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "市场与友商调研" in result["missing_modules"]
        assert "## 一、市场与友商调研" in result["skeleton"]

    async def test_write_file_default_structure_when_no_goal(self, monkeypatch):
        from app.services.agent import tool_executor as te_mod

        async def fake_structure(goal):
            return ["目标回顾"]

        monkeypatch.setattr(te_mod, "_resolve_active_structure", fake_structure)
        executor = te_mod.ToolExecutor()
        result = await executor.execute(
            {"type": "write_file",
             "input": {"path": "brief/普通方案.md",
                       "content": "# 方案\n\n## 一、Brief Recap\n\n## 二、创意方向\n\n"}},
            owner_user_id=self.owner_user_id,
            goal="写个文案",
        )
        assert result["error"] == "plan_structure_incomplete"
        assert "目标回顾" in result["missing_modules"]
```

注意：`TestWriteFileStructureValidation` 类已有 `self.owner_user_id` fixture/setup——先读该类现有测试确认属性名，若不同则用现有属性名。

- [ ] **Step 3: Run tests to verify they fail**

```
cd C:\01_agent_loop_pro\backend
python -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation -q
```
Expected: FAIL with `AttributeError: module ... has no attribute '_resolve_active_structure'`

- [ ] **Step 4: Implement**

在 `backend/app/services/agent/tool_executor.py` 中：

**4a.** 更新 import 块：把 `parse_module_list_from_summary`（当前 import 块内）替换为 `parse_structure_from_doc`、`parse_default_structure_from_blueprint`、`resolve_structure_doc`。改后该 import 块为：

```python
from app.services.agent.plan_structure import (
    DEFAULT_MODULES,
    build_skeleton,
    is_plan_like_content,
    parse_default_structure_from_blueprint,
    parse_structure_from_doc,
    resolve_structure_doc,
    validate_plan_structure,
)
```

同时确认 `WorkflowDocSummary`/`select` 是否仍被文件其他位置使用（`_resolve_active_modules` 替换后若不再使用，删除相关 import；`get_settings` 大概率仍被其他工具使用，保留）。

**4b.** 把 `_module_cache` 与 `_resolve_active_modules`（当前 222-248 行附近）整体替换为：

```python
_structure_cache: dict[str, tuple[str, list[str]]] = {}


async def _load_doc_text(doc_path: str) -> str:
    """按文档路径读超管文件库中的规范文档/蓝图全文；失败返回空串。"""
    from app.services.agent.workflow_policy import workflow_policy
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.workflow_docs_enabled:
        return ""
    async with async_session_factory() as session:
        owner_id = await workflow_policy._resolve_super_admin_id(session)
        if owner_id is None:
            return ""
        return await workflow_policy._load_doc(session, owner_id, doc_path)


async def _resolve_active_structure(goal: str | None) -> list[str]:
    """按 goal 路由规范文档（或蓝图默认段）解析模块清单；失败回退缓存 → DEFAULT_MODULES。"""
    settings = get_settings()
    if not settings.workflow_docs_enabled:
        return DEFAULT_MODULES
    doc_path: str | None = None
    if goal:
        doc_path = resolve_structure_doc(goal)
    if doc_path is None:
        doc_path = settings.workflow_core_doc_path
    cached = _structure_cache.get(doc_path)
    text = await _load_doc_text(doc_path)
    if not text:
        return cached[1] if cached else DEFAULT_MODULES
    try:
        import hashlib
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except Exception:
        fingerprint = ""
    if cached and cached[0] == fingerprint:
        return cached[1]
    if doc_path == settings.workflow_core_doc_path:
        parsed = parse_default_structure_from_blueprint(text)
    else:
        parsed = parse_structure_from_doc(text)
    if parsed is None:
        return cached[1] if cached else DEFAULT_MODULES
    _structure_cache[doc_path] = (fingerprint, parsed)
    return parsed
```

**4c.** `_write_file` 签名（当前 `def _write_file(self, payload, owner_user_id)`）加 goal 参数：

```python
    async def _write_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None,
        goal: str | None = None,
    ) -> dict[str, Any]:
```

`execute()` 签名（当前 `async def execute(self, action, web_enabled=True, owner_user_id=None, is_super_admin=False)`）加 goal 参数：

```python
    async def execute(self, action: dict[str, Any], web_enabled: bool = True,
                      owner_user_id: uuid.UUID | None = None,
                      is_super_admin: bool = False,
                      goal: str | None = None) -> dict[str, Any]:
```

`execute()` 内 `write_file` 分支改为传 goal：

```python
        if action_type == "write_file":
            return await self._write_file(payload, owner_user_id, goal)
```

`_write_file` 校验块（当前 468-477 行附近）改为：

```python
        if is_plan_like_content(content):
            modules = await _resolve_active_structure(goal)
            missing_modules = validate_plan_structure(content, modules=modules)
            if len(missing_modules) >= 3:
                return {
                    "error": "plan_structure_incomplete",
                    "missing_modules": missing_modules,
                    "skeleton": build_skeleton(modules),
                    "hint": "请保留你已写的内容，仅按 skeleton 中的模块结构补全缺失模块后重新 write_file，不要重写全文。",
                }
```

**4d.** `backend/app/services/agent/loop.py` 的 `tool_executor.execute(` 调用处（`_stream_visible_thought_with_tool_interleave` 内，当前传 `web_enabled=web_enabled, owner_user_id=owner_user_id, is_super_admin=is_super_admin`）加 `goal=run.goal`。先确认该作用域 `run` 变量可用（同函数内 `run.goal` 已在其他位置使用）。

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
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: validate write_file against routed spec doc structure"
```

---

### Task 3: Integration verification

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: Run full backend suite**（仅一个 pytest 进程；先 `Get-Process python -ErrorAction SilentlyContinue` 确认无占用）

```
cd C:\01_agent_loop_pro\backend
python -m pytest tests/ -q
```
Expected: 699+ passed（新增测试全部通过，零失败）

- [ ] **Step 2: Live smoke — resolve real structures from real docs**（读超管文件库真实文档验证端到端路由+解析；不改任何数据）

```
cd C:\01_agent_loop_pro\backend
python -c "import asyncio; exec('''\nimport sys\nsys.path.insert(0, r\"C:\\01_agent_loop_pro\\backend\")\nfrom sqlalchemy import text\n\nasync def main():\n    from app.db.session import async_session_factory\n    from app.services.agent.tool_executor import _load_doc_text, _resolve_active_structure\n    from app.services.agent.plan_structure import resolve_structure_doc\n\n    goals = [\"请生成矩阵号代运营年度方案\", \"UGC 种草双平台投放方案\", \"写个文案\"]\n    for g in goals:\n        doc = resolve_structure_doc(g)\n        modules = await _resolve_active_structure(g)\n        print(g)\n        print(\"  doc:\", doc)\n        print(\"  modules:\", modules[:5], \"... total\", len(modules))\n\nasyncio.run(main())\n''')"
```
Expected: 矩阵号 goal → doc 含 "矩阵号代运营"、modules[0]=="目标回顾" 且共 9 个；UGC goal → doc 含 "UGC"、modules 含 "Brief Recap"（表格首列）且共 10 个；"写个文案" → doc=None（走蓝图默认）、modules[0]=="Brief Recap" 且共 8 个。

- [ ] **Step 3: Report** — 无提交；把冒烟输出追加到 `C:\01_agent_loop_pro\.superpowers\sdd\progress.md`，并回报给用户：全量测试数 + 冒烟验证结果

