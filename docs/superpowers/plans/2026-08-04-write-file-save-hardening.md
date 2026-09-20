# write_file 保存加固（成功判定 + 动态蓝图校验与骨架）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让"读取 brief → 生成方案 → 保存文件"任务在同一次 run 内完成：write_file 被结构校验拒绝后，模型能基于骨架补全并成功保存，且被拒后不允许直接 finish 收尾。

**Architecture:** 三层改动：(1) `loop.py` 的 `wrote_file` 只在工具**成功**（observation 无 error）时置位，堵住"被拒后 finish"路径；(2) `plan_structure.py` 从蒸馏摘要动态解析模块清单、生成骨架模板，校验失败时连同 `skeleton` 一起返回给模型"填空"；(3) `workflow_policy.py` 蒸馏 prompt 改为跟随蓝图实际结构 + `_DISTILL_VERSION` 版本机制强制重蒸馏。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / alembic / pytest / pytest-anyio

## Global Constraints

- 校验失败**不抛异常**——以观察结果 `{"error": "plan_structure_incomplete", ...}` 返回，模型才能重试
- 方案类判定：content 含 `brief`/`方案`/`策划`/`创意建议`/`提案` 任一关键词（`is_plan_like_content` 现状不变）
- 缺失 ≥3 个模块 → 拒绝；非方案类文档直接保存不校验
- 模块清单解析失败 → 静默回退 `DEFAULT_MODULES`（现有 8 模块），不报错不影响 run
- 现有测试必须通过（`test_plan_structure.py`、`test_agent_tool_files.py`、`test_workflow_policy.py`、`test_agent_loop.py` 等）
- 工作目录：`C:\01_agent_loop_pro\backend`（所有 pytest 命令在该目录下运行）

---

### Task 1: plan_structure.py — 动态模块解析、骨架生成、参数化校验

**Files:**
- Modify: `C:\01_agent_loop_pro\backend\app\services\agent\plan_structure.py`
- Test: `C:\01_agent_loop_pro\backend\tests\test_plan_structure.py`

**Interfaces:**
- Consumes: 无（纯函数模块）
- Produces:
  - `DEFAULT_MODULES: list[str]` — 回退默认 8 模块（现 `_MODULE_MARKERS` 的模块名）
  - `parse_module_list_from_summary(summary: str) -> list[str] | None` — 从蒸馏摘要解析模块清单；失败/无摘要返回 None
  - `build_skeleton(modules: list[str]) -> str` — 生成 `## 一、{模块名}` 标题序列 + 指引
  - `validate_plan_structure(content: str, modules: list[str] | None = None) -> list[str]` — modules 为 None 时用 DEFAULT_MODULES（向后兼容现有调用）

- [ ] **Step 1: Write the failing tests**

在 `C:\01_agent_loop_pro\backend\tests\test_plan_structure.py` 追加：

```python
from app.services.agent.plan_structure import (
    DEFAULT_MODULES,
    build_skeleton,
    parse_module_list_from_summary,
    validate_plan_structure,
)


class TestParseModuleListFromSummary:
    def test_parses_standard_8_modules(self):
        summary = (
            "2. 正式方案 8 模块\n"
            "保存到文件的方案/建议类文档正文，必须按下述 8 模块逐节输出，不可自创结构：\n"
            "1. Brief Recap\n2. 前策调研\n3. 本品表现\n4. 用户分析\n"
            "5. 创意与传播规划\n6. 投流策略\n7. Roadmap\n8. 附录\n"
        )
        modules = parse_module_list_from_summary(summary)
        assert modules == DEFAULT_MODULES

    def test_parses_9_modules_dynamically(self):
        summary = (
            "模块清单：\n"
            "1. Brief Recap\n2. 前策调研\n3. 本品表现\n4. 用户分析\n"
            "5. 创意与传播规划\n6. 投流策略\n7. Roadmap\n8. 附录\n9. 传播预算\n"
        )
        modules = parse_module_list_from_summary(summary)
        assert modules is not None
        assert len(modules) == 9
        assert modules[-1] == "传播预算"

    def test_returns_none_on_drifted_format(self):
        assert parse_module_list_from_summary("没有编号列表的自然语言摘要") is None
        assert parse_module_list_from_summary("") is None

    def test_returns_none_when_too_few(self):
        assert parse_module_list_from_summary("1. A\n2. B") is None


class TestBuildSkeleton:
    def test_skeleton_contains_standard_headings(self):
        skeleton = build_skeleton(DEFAULT_MODULES)
        assert "## 一、Brief Recap" in skeleton
        assert "## 八、附录" in skeleton

    def test_skeleton_includes_guide_for_known_module(self):
        skeleton = build_skeleton(DEFAULT_MODULES)
        assert "竞品必查" in skeleton  # 前策调研的指引

    def test_skeleton_no_guide_for_unknown_module(self):
        skeleton = build_skeleton(["Brief Recap", "传播预算"])
        assert "传播预算" in skeleton
        assert skeleton.count("## ") == 2

    def test_skeleton_is_self_compliant(self):
        skeleton = build_skeleton(DEFAULT_MODULES)
        assert validate_plan_structure(skeleton, modules=DEFAULT_MODULES) == []


class TestValidateWithModules:
    def test_dynamic_9_modules_validate(self):
        modules = DEFAULT_MODULES + ["传播预算"]
        content = build_skeleton(modules)
        assert validate_plan_structure(content, modules=modules) == []

    def test_missing_dynamic_module_reported(self):
        modules = DEFAULT_MODULES + ["传播预算"]
        content = build_skeleton(DEFAULT_MODULES)
        assert validate_plan_structure(content, modules=modules) == ["传播预算"]

    def test_default_modules_when_none_passed(self):
        content = build_skeleton(DEFAULT_MODULES)
        assert validate_plan_structure(content) == []

    def test_aliases_still_match(self):
        content = (
            "# 方案\n\n## Brief Recap\n\n## 竞品分析\n\n## 本品表现\n\n"
            "## 用户画像\n\n## 传播策略\n\n## 投放计划\n\n## 执行节奏\n\n## 附录\n\n"
        )
        assert validate_plan_structure(content) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plan_structure.py -v`
Expected: FAIL（`parse_module_list_from_summary`/`build_skeleton` 不存在，`validate_plan_structure` 不接受 `modules` 参数）

- [ ] **Step 3: Rewrite `plan_structure.py`**

将 `C:\01_agent_loop_pro\backend\app\services\agent\plan_structure.py` 全部内容替换为：

```python
"""蓝图模块结构校验。

用于 write_file 写入方案类文档时的强制结构校验：
模块清单从蒸馏摘要动态解析（跟随蓝图变化），缺失模块以观察结果
反馈给模型重写，而非静默保存残缺文档。
"""

from __future__ import annotations

import re

_PLAN_KEYWORDS = ("brief", "方案", "策划", "创意建议", "提案")

DEFAULT_MODULES = [
    "Brief Recap",
    "前策调研",
    "本品表现",
    "用户分析",
    "创意与传播规划",
    "投流策略",
    "Roadmap",
    "附录",
]

# 每个模块的可接受别名（命中任一即算存在）；动态模块名不在表中时仅本体匹配
_MODULE_ALIASES: dict[str, tuple[str, ...]] = {
    "Brief Recap": ("brief recap", "brief 复述", "brief回述", "brief 概述"),
    "前策调研": ("调研", "前策", "竞品", "行业研究"),
    "本品表现": ("本品", "品牌表现", "品牌现状"),
    "用户分析": ("用户分析", "目标用户", "人群画像", "用户画像"),
    "创意与传播规划": ("创意", "传播规划", "创意方向", "传播策略"),
    "投流策略": ("投流", "投放", "media", "kfs", "关键词"),
    "Roadmap": ("roadmap", "road map", "路线图", "执行节奏", "时间表"),
    "附录": ("附录",),
}

# 骨架中每模块的内容指引（静态映射；无映射模块仅输出标题）
_SKELETON_GUIDES: dict[str, str] = {
    "前策调研": "竞品必查，不得跳过竞品与平台现状",
    "本品表现": "基于 brief 与公开信息，标注估算锚点与边界",
    "创意与传播规划": "拆到平台/内容形态/达人/节奏/物料/KPI",
    "投流策略": "预算/周期/资源超限必须标注假设",
    "附录": "数据来源、假设与边界",
}

_CN_NUMERALS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

# 编号列表行中出现这些词的说明行，不当作模块名
_NON_MODULE_WORDS = ("保存到", "逐节输出", "不可自创", "必须", "正文", "模块", "结构")


def is_plan_like_content(content: str) -> bool:
    lowered = content.lower()
    return any(keyword.lower() in lowered for keyword in _PLAN_KEYWORDS)


def parse_module_list_from_summary(summary: str) -> list[str] | None:
    """从蒸馏摘要解析模块清单；失败返回 None（调用方回退 DEFAULT_MODULES）。"""
    if not summary:
        return None
    modules: list[str] = []
    expect = 1
    for line in summary.splitlines():
        m = re.match(r"^(\d+)\.\s+(.+)$", line.strip())
        if not m:
            continue
        num = int(m.group(1))
        name = m.group(2).strip()
        if any(word in name for word in _NON_MODULE_WORDS):
            continue
        if len(name) > 30 or not name:
            continue
        if num == expect:
            modules.append(name)
            expect += 1
    if len(modules) >= 3:
        return modules
    return None


def build_skeleton(modules: list[str]) -> str:
    """生成标准标题序列（## 一、模块名）+ 每模块一句内容指引。"""
    lines: list[str] = []
    for i, name in enumerate(modules, start=1):
        numeral = _CN_NUMERALS[i - 1] if i <= len(_CN_NUMERALS) else str(i)
        lines.append(f"## {numeral}、{name}")
        guide = _SKELETON_GUIDES.get(name)
        if guide:
            lines.append(f"> {guide}")
    return "\n".join(lines)


def validate_plan_structure(content: str, modules: list[str] | None = None) -> list[str]:
    """返回缺失模块的中文名列表；空列表表示结构合规。"""
    if modules is None:
        modules = DEFAULT_MODULES
    lowered = content.lower()
    missing: list[str] = []
    for name in modules:
        aliases = _MODULE_ALIASES.get(name, ())
        if name.lower() in lowered:
            continue
        if any(alias in lowered for alias in aliases):
            continue
        missing.append(name)
    return missing
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plan_structure.py -v`
Expected: 全部 PASS（含原有 5 个测试 + 新增 12 个）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/plan_structure.py backend/tests/test_plan_structure.py
git commit -m "feat: dynamic module list parsing + skeleton builder for plan validation"
```

---

### Task 2: tool_executor — 校验失败返回骨架 + 模块清单解析接入

**Files:**
- Modify: `C:\01_agent_loop_pro\backend\app\services\agent\tool_executor.py`
- Test: `C:\01_agent_loop_pro\backend\tests\test_agent_tool_files.py`

**Interfaces:**
- Consumes: `parse_module_list_from_summary` / `build_skeleton` / `validate_plan_structure(content, modules)` / `DEFAULT_MODULES`（Task 1）
- Produces: `_write_file` 对方案类残缺文档返回 `{"error": "plan_structure_incomplete", "missing_modules": [...], "skeleton": "...", "hint": "..."}`；模块清单解析结果带进程级缓存

- [ ] **Step 1: Write the failing tests**

在 `C:\01_agent_loop_pro\backend\tests\test_agent_tool_files.py` 的 `TestWriteFileStructureValidation` 类中追加：

```python
    async def test_write_rejection_includes_skeleton(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        from pathlib import Path as FilePath
        from app.services.agent.tool_executor import ToolExecutor

        monkeypatch.setattr(FilePath, "write_bytes", MagicMock())
        monkeypatch.setattr(FilePath, "mkdir", MagicMock())

        saved = {"called": False}

        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def execute(self, stmt):
                return MagicMock(scalar_one_or_none=MagicMock(return_value=None))
            def add(self, obj):
                pass
            async def flush(self):
                return None
            async def commit(self):
                saved["called"] = True
                return None
            async def get(self, model, fid):
                return None

        monkeypatch.setattr("app.services.agent.tool_executor.async_session_factory", lambda: FakeSession())

        executor = ToolExecutor()
        result = await executor._write_file(
            {
                "path": "brief/残缺方案.md",
                "content": "# 创意建议（初稿）\n\n## 一、Brief Recap\n\n## 二、创意方向\n\n## 三、内容玩法\n\n",
                "overwrite": True,
            },
            "00000000-0000-0000-0000-0000000000aa",
        )

        assert result["error"] == "plan_structure_incomplete"
        assert "skeleton" in result
        assert "## 一、Brief Recap" in result["skeleton"]
        assert "## 八、附录" in result["skeleton"]
        assert "前策调研" in result["missing_modules"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation::test_write_rejection_includes_skeleton -v`
Expected: FAIL（result 无 `skeleton` 字段，`KeyError`）

- [ ] **Step 3: Implement module resolution + skeleton return**

在 `C:\01_agent_loop_pro\backend\app\services\agent\tool_executor.py` 中：

**3a. 顶部 import 区（现有 `from app.services.agent.plan_structure import ...` 附近，约第 30 行）：**

```python
from app.services.agent.plan_structure import (
    DEFAULT_MODULES,
    build_skeleton,
    is_plan_like_content,
    parse_module_list_from_summary,
    validate_plan_structure,
)
```

若原 import 为 `from app.services.agent.plan_structure import is_plan_like_content, validate_plan_structure`，直接替换为上面整块。

**3b. 模块级缓存与解析函数（放在 `class ToolExecutor` 定义之前）：**

```python
_module_cache: dict[str, tuple[str, list[str]]] = {}


async def _resolve_active_modules() -> list[str]:
    """从当前蒸馏摘要解析模块清单；失败回退默认。doc_path 为键，摘要指纹变化才重解析。"""
    settings = get_settings()
    if not settings.workflow_docs_enabled:
        return DEFAULT_MODULES
    doc_path = settings.workflow_core_doc_path
    cached = _module_cache.get(doc_path)
    try:
        async with async_session_factory() as session:
            row = await session.scalar(
                select(WorkflowDocSummary).where(WorkflowDocSummary.doc_path == doc_path)
            )
    except Exception:
        return cached[1] if cached else DEFAULT_MODULES
    if row is None or not row.summary:
        return cached[1] if cached else DEFAULT_MODULES
    fingerprint = f"{row.file_sha256}:{row.distilled_at}"
    if cached and cached[0] == fingerprint:
        return cached[1]
    parsed = parse_module_list_from_summary(row.summary)
    if parsed is None:
        return cached[1] if cached else DEFAULT_MODULES
    _module_cache[doc_path] = (fingerprint, parsed)
    return parsed
```

**3c. 确认 import**：`from app.models.workflow import WorkflowDocSummary` 加入 import 区（`select` 若未导入则一并加 `from sqlalchemy import select`——先检查文件顶部现有 import，若已从 sqlalchemy 导入 select 则跳过）。

**3d. `_write_file` 校验段替换（现约 432-440 行）：**

```python
        if is_plan_like_content(content):
            modules = await _resolve_active_modules()
            missing_modules = validate_plan_structure(content, modules=modules)
            if len(missing_modules) >= 3:
                return {
                    "error": "plan_structure_incomplete",
                    "missing_modules": missing_modules,
                    "skeleton": build_skeleton(modules),
                    "hint": "请保留你已写的内容，仅按 skeleton 中的模块结构补全缺失模块后重新 write_file，不要重写全文。",
                }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_agent_tool_files.py::TestWriteFileStructureValidation -v`
Expected: 3/3 PASS（原 2 个 + 新 1 个；FakeSession 的 execute 返回 None → 回退默认 8 模块，原断言不受影响）

- [ ] **Step 5: Run related suites**

Run: `python -m pytest tests/test_agent_tool_files.py tests/test_plan_structure.py tests/test_feishu_service.py -q`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/tests/test_agent_tool_files.py
git commit -m "feat: return plan skeleton template on write_file structure rejection"
```

---

### Task 3: loop.py — wrote_file 只在保存成功时置位

**Files:**
- Modify: `C:\01_agent_loop_pro\backend\app\services\agent\loop.py:1434-1436` 和 `loop.py:1498-1508` 附近
- Test: `C:\01_agent_loop_pro\backend\tests\test_agent_loop.py`

**Interfaces:**
- Consumes: 无
- Produces: 行为变更——write_file/edit_file 工具执行成功（observation 无 `error` 字段）才置 `wrote_file=True`；被拒后模型 plan finish 会被 `_enforce_save_intent`（loop.py:405-419）抛 `RetryablePlannerError("save_intent_requires_write_tool")` 拦截

- [ ] **Step 1: Write the failing test**

在 `C:\01_agent_loop_pro\backend\tests\test_agent_loop.py` 末尾追加：

```python
class TestSaveIntentEnforcement:
    async def test_write_rejected_then_finish_is_blocked(self, monkeypatch, test_db):
        from app.services.agent.loop import AgentLoopService
        from app.repositories.agent_repository import AgentRepository
        from app.models.agent import AgentSession
        from app.models.rbac import User
        from argon2 import PasswordHasher
        import uuid as _uuid

        uid = _uuid.uuid4().hex[:8]
        async with test_db() as s:
            ph = PasswordHasher()
            user = User(
                username=f"ft_user_{uid}",
                display_name="FT User",
                password_hash=ph.hash("Test1234"),
            )
            s.add(user)
            await s.flush()
            session_obj = AgentSession(owner_user_id=user.id, title="ft")
            s.add(session_obj)
            await s.flush()
            repo = AgentRepository(s)
            run, attempt, _ = await repo.create_run_with_attempt(
                session_obj,
                "读取 brief_test.md，然后写一份方案保存到 brief 文件夹中，最后把保存结果告诉我",
                "expert",
                True,
                [],
            )
            await s.commit()
            run_id = run.id
            attempt_id = attempt.id

        async with test_db() as s:
            claim_repo = AgentRepository(s)
            claimed = await claim_repo.claim_next_attempt("ft-worker")
            await s.commit()
            assert claimed is not None

        service = AgentLoopService()

        class FakeStream:
            def __init__(self):
                self.planner_calls = 0

            async def stream_text(self, messages):
                system = messages[0]["content"]
                if "【决策】" in system or "规划器" in system:
                    self.planner_calls += 1
                    if self.planner_calls == 1:
                        yield '【决策】{"thought_summary":"写入方案","action":{"type":"write_file","input":{"path":"brief/方案.md","content":"# 残缺方案\\n## 一、Brief Recap\\n"}}}\n'
                        yield "【说明】我正在写入方案文件。"
                    elif self.planner_calls == 2:
                        yield '【决策】{"thought_summary":"补全后重写","action":{"type":"write_file","input":{"path":"brief/方案.md","content":"# 完整方案\\n## 一、Brief Recap\\n## 二、前策调研\\n## 三、本品表现\\n## 四、用户分析\\n## 五、创意与传播规划\\n## 六、投流策略\\n## 七、Roadmap\\n## 八、附录\\n"}}}\n'
                        yield "【说明】已按骨架补全，重新写入。"
                    else:
                        yield '【决策】{"thought_summary":"保存成功","action":{"type":"finish","input":{"answer":"已保存"}}}\n'
                        yield "【说明】文件已保存。"
                elif "工具已执行完毕" in system:
                    yield "我继续处理。"
                elif "研究助理" in system:
                    yield "已完成。"
                else:
                    yield "我继续处理。"

        monkeypatch.setattr(service, "llm_client", FakeStream())

        from unittest.mock import MagicMock
        fake_execute_calls = []

        async def fake_execute(action, **kwargs):
            fake_execute_calls.append(action["type"])
            if action["type"] == "write_file":
                content = action["input"].get("content", "")
                if "## 八、附录" not in content:
                    return {
                        "error": "plan_structure_incomplete",
                        "missing_modules": ["前策调研", "本品表现", "用户分析", "投流策略", "Roadmap", "附录"],
                        "skeleton": "## 一、Brief Recap\n## 二、前策调研\n## 三、本品表现\n## 四、用户分析\n## 五、创意与传播规划\n## 六、投流策略\n## 七、Roadmap\n## 八、附录",
                    }
                return {
                    "file_id": "00000000-0000-0000-0000-000000000099",
                    "filename": "方案.md",
                    "folder_path": "brief",
                    "action": "created",
                }
            return {"final_answer": "已保存"}

        monkeypatch.setattr(service.tool_executor, "execute", fake_execute)

        import app.services.agent.loop as loop_module
        monkeypatch.setattr(loop_module, "async_session_factory", test_db)

        await service.process_attempt(attempt_id, "ft-worker")

        assert fake_execute_calls.count("write_file") == 2
        assert fake_execute_calls[-1] == "finish"

        async with test_db() as s:
            repo = AgentRepository(s)
            run = await repo.get_run(run_id)
            assert run is not None
            assert run.status == "succeeded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_loop.py::TestSaveIntentEnforcement -v`
Expected: FAIL——原因：当前实现计划阶段就置 `wrote_file=True`（loop.py:1434-1436），第一次 write_file 失败后 `_enforce_save_intent` 不拦截 finish，模型第二次直接 finish（`fake_execute_calls` 里 write_file 只有 1 次），断言 `== 2` 失败。

- [ ] **Step 3: Implement the fix**

在 `C:\01_agent_loop_pro\backend\app\services\agent\loop.py`：

**3a. 删除计划阶段置位（1434-1436 行）：**

```python
            if action_type_check := plan.get("action", {}).get("type"):
                if action_type_check in {"write_file", "edit_file"}:
                    wrote_file = True
```

替换为：

```python
            action_type_check = plan.get("action", {}).get("type")
```

**3b. 在工具执行成功后置位（`observation = observation_or_answer` 之后，1498 行附近）：**

```python
            observation = observation_or_answer
            if (
                action["type"] in {"write_file", "edit_file"}
                and isinstance(observation, dict)
                and not observation.get("error")
            ):
                wrote_file = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_loop.py::TestSaveIntentEnforcement -v`
Expected: PASS（write_file 被拒 → wrote_file=False → finish 被拦截 → 模型补全重写成功 → finish 放行）

- [ ] **Step 5: Run related suites**

Run: `python -m pytest tests/test_agent_loop.py tests/test_agent_worker.py tests/test_agent_tools.py -q`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "fix: wrote_file only set on successful save — block finish after rejected write"
```

---

### Task 4: workflow_policy — 蒸馏 prompt 跟随蓝图 + 版本机制

**Files:**
- Create: `C:\01_agent_loop_pro\backend\alembic\versions\<new_rev>_add_distill_version.py`
- Modify: `C:\01_agent_loop_pro\backend\app\models\workflow.py`
- Modify: `C:\01_agent_loop_pro\backend\app\services\agent\workflow_policy.py`
- Test: `C:\01_agent_loop_pro\backend\tests\test_workflow_policy.py`

**Interfaces:**
- Consumes: 无
- Produces: `WorkflowDocSummary.distill_version: int`（新列，默认 0）；`_DISTILL_VERSION` 从 4 → 5；`ensure_summary`/`get_instruction` 将版本不符视为陈旧并触发重蒸馏；`_distill_core_doc` 成功时写入当前版本

- [ ] **Step 1: Write the failing tests**

在 `C:\01_agent_loop_pro\backend\tests\test_workflow_policy.py` 追加：

```python
class TestDistillVersionBump:
    async def test_version_mismatch_triggers_redistill(self, test_db, monkeypatch):
        from app.db.seed import seed_rbac
        from app.models.workflow import WorkflowDocSummary
        from datetime import UTC, datetime

        async with test_db() as s:
            await seed_rbac(s)
            owner_id = await _make_super_admin(s)
            file_obj = await _write_doc(s, owner_id, "00_Agent规范与模板", "脑壳儿_Agent运行蓝图_v1.1.md", "蓝图内容")
            await s.commit()

        async with test_db() as s:
            s.add(WorkflowDocSummary(
                doc_path="00_Agent规范与模板/脑壳儿_Agent运行蓝图_v1.1.md",
                file_updated_at=(file_obj.updated_at.isoformat() if file_obj.updated_at else ""),
                file_sha256=file_obj.sha256,
                summary="旧版摘要（版本 3）",
                status="ready",
                distill_version=3,
                distilled_at=datetime.now(UTC),
            ))
            await s.commit()

        fake = _FakeLLM()
        monkeypatch.setattr("app.services.agent.llm.DeepSeekClient", lambda: fake)
        monkeypatch.setattr("app.services.agent.workflow_policy.async_session_factory", test_db)

        from app.services.agent.workflow_policy import _DISTILL_VERSION
        assert _DISTILL_VERSION == 5  # 本任务已递增

        policy = WorkflowPolicy()
        await policy.ensure_summary()
        await policy.flush_tasks()
        assert fake.calls >= 1  # 版本不符 → 强制重蒸馏

        async with test_db() as s:
            row = await s.scalar(select(WorkflowDocSummary).where(WorkflowDocSummary.doc_path == "00_Agent规范与模板/脑壳儿_Agent运行蓝图_v1.1.md"))
            assert row is not None
            assert row.distill_version == _DISTILL_VERSION
            assert row.summary != "旧版摘要（版本 3）"

    async def test_prompt_no_longer_hardcodes_8_modules(self):
        from app.services.agent.workflow_policy import WorkflowPolicy
        prompt = WorkflowPolicy._DISTILL_PROMPT
        assert "8 模块清单" not in prompt
        assert "以蓝图原文实际列出的模块为准" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_workflow_policy.py::TestDistillVersionBump -v`
Expected: FAIL——`distill_version` 列/属性不存在（AttributeError/UndefinedColumnError），prompt 仍含"8 模块清单"。

- [ ] **Step 3: Add the alembic migration**

生成 revision id（任选 32 位 hex，如 `b7e2f1a0c3d44b5e8f9a1b2c3d4e5f60`），创建 `C:\01_agent_loop_pro\backend\alembic\versions\b7e2f1a0c3d4_add_distill_version.py`：

```python
"""add distill_version to workflow_doc_summaries

Revision ID: b7e2f1a0c3d4
Revises: a6f8c3b21d4e
Create Date: 2026-08-04
"""
import sqlalchemy as sa
from alembic import op

revision = "b7e2f1a0c3d4"
down_revision = "a6f8c3b21d4e4f0a9b2c7d8e9f0a1b2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_doc_summaries",
        sa.Column("distill_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("workflow_doc_summaries", "distill_version")
```

**注意**：`down_revision` 必须与 `alembic/versions/a6f8c3b21d4e_add_workflow_doc_summaries.py` 中的 `revision` 值一致——先读取该文件的 `revision` 行确认（应为 `a6f8c3b21d4e4f0a9b2c7d8e9f0a1b2c`），若不同则用实际值。

- [ ] **Step 4: Update the model**

`C:\01_agent_loop_pro\backend\app\models\workflow.py` 追加：

```python
    distill_version: Mapped[int] = mapped_column(Integer, default=0)
```

（放在 `failure_count` 之后、`distilled_at` 之前。）

- [ ] **Step 5: Update workflow_policy.py**

**5a. `_DISTILL_VERSION` 递增（22 行）：**

```python
_DISTILL_VERSION = 5  # 蒸馏 prompt 变更时递增，强制重新蒸馏
```

**5b. `_DISTILL_PROMPT` 第 2 条替换（134-136 行）：**

原：
```python
        "2. 正式方案默认结构（8 模块清单：Brief Recap、前策调研、本品表现、用户分析、"
        "创意与传播规划、投流策略、Roadmap、附录，逐条列出结构名）；"
        "并注明：任何保存到文件模块的方案/建议类文档正文，必须完整按此 8 模块逐节输出，不可自创结构\n"
```

新：
```python
        "2. 正式方案默认结构（模块清单：以蓝图原文实际列出的模块为准，完整保留其名称与数量，"
        "逐条列出结构名）；"
        "并注明：任何保存到文件模块的方案/建议类文档正文，必须完整按此模块结构逐节输出，不可自创结构\n"
```

**5c. `_distill_core_doc` 成功落库时写版本（193-198 行附近，`row.status = "ready"` 之后）：**

```python
                row.status = "ready"
                row.distill_version = _DISTILL_VERSION
```

**5d. `ensure_summary` 版本判定（250 行）：**

原：
```python
            need = row is None or row.status == "failed" or row.file_sha256 != sha256
```
新：
```python
            need = (
                row is None
                or row.status == "failed"
                or row.file_sha256 != sha256
                or (row.distill_version or 0) != _DISTILL_VERSION
            )
```

**5e. `get_instruction` 陈旧判定（291 行）：**

原：
```python
            if row is not None and row.summary and row.file_sha256 == sha256 and row.status == "ready":
```
新：
```python
            if (
                row is not None
                and row.summary
                and row.file_sha256 == sha256
                and row.status == "ready"
                and (row.distill_version or 0) == _DISTILL_VERSION
            ):
```

（版本不符会落到 elif 陈旧分支：返回旧版 + `_schedule_distill` 后台重蒸馏——与现有行为一致。）

- [ ] **Step 6: Run the new tests**

Run: `python -m pytest tests/test_workflow_policy.py::TestDistillVersionBump -v`
Expected: 2/2 PASS

- [ ] **Step 7: Run the full related suites**

Run: `python -m pytest tests/test_workflow_policy.py tests/test_workflow_models.py tests/test_plan_structure.py tests/test_agent_tool_files.py -q`
Expected: 全部 PASS（既有测试的 `WorkflowDocSummary(...)` 构造不带 distill_version，模型 default=0 兼容；`_DISTILLED` fake 摘要不含编号列表，但旧测试不断言模块解析，不受影响）

- [ ] **Step 8: Commit**

```bash
git add backend/alembic/versions/b7e2f1a0c3d4_add_distill_version.py backend/app/models/workflow.py backend/app/services/agent/workflow_policy.py backend/tests/test_workflow_policy.py
git commit -m "feat: distill prompt follows blueprint structure + version-bump redistill"
```

---

### Task 5: 集成验证（人工冒烟）

**Files:**
- 无代码改动；运行验证

- [ ] **Step 1: 跑全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS（此前基线 676 passed）

- [ ] **Step 2: 应用 migration 并重启后端**

```bash
cd C:\01_agent_loop_pro\backend
alembic upgrade head
```

重启后端服务（uvicorn）。启动日志应出现 workflow 蒸馏（若版本不符触发重蒸馏）。

- [ ] **Step 3: 复现场景冒烟**

通过前端/API 发起与失败案例相同的任务："读取 brief_test.md，然后写一份 东西，保存到 brief/文件夹中，最后把保存结果告诉我"。

预期（与 RUN3 对照）：
- 单次 run 内完成；若首次 write_file 残缺，模型在 tool 观察的 `skeleton` 指引下补全重写
- run 结束时文件落盘 brief/ 且 final_answer 报告保存路径
- 若 write_file 被拒后模型尝试 finish → 被 `save_intent_requires_write_tool` 拦截，不会以残缺结果收尾

- [ ] **Step 4: 提交收尾（如有验证期修改）**

```bash
git status  # 确认无残留改动；如有验证期修复，按任务惯例提交
```

## Self-Review 记录

- **Spec 覆盖**：① wrote_file 成功判定 → Task 3；② 骨架模板反馈 → Task 2（返回 skeleton）+ Task 1（build_skeleton）；动态校验标记 → Task 1（parse/validate with modules）；蒸馏 prompt 跟随蓝图 → Task 4（5b）；版本机制 → Task 4（5a/5c/5d/5e）；缓存 → Task 2（`_resolve_active_modules` 指纹缓存）；测试计划各条 → 各任务 Step 1。
- **占位符扫描**：无 TBD/TODO；每个代码步骤含完整代码。
- **类型一致性**：`parse_module_list_from_summary` / `build_skeleton` / `validate_plan_structure(content, modules=None)` 三处签名在 Task 1 定义、Task 2 消费，一致；`DEFAULT_MODULES` 在 Task 1 定义、Task 2 引用；`_DISTILL_VERSION` 在 Task 4 定义、测试断言 5。
