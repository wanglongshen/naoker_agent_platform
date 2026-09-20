# 方案生成质量优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 方案生成质量闭环：写入前（骨架预填/蓝图双阶段/调研门）→ 写入时（规则质检）→ 写入后（自审门）→ 度量（质量分入库 + 治理中心）。

**Architecture:** 全部在 Agent 循环内扩展——messages 组装注入（loop.py `_build_merged_messages`）、write_file 工具路径校验（tool_executor + plan_structure）、自审为新模块（quality_review.py）复用 LLM 调用 + 事件流（quality_review_started/completed）。修订复用现有 step 循环（评审结果作为 observation 注入，模型自己 edit_file 修订），不新增状态机。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, React + AntD

**Spec:** `docs/superpowers/specs/2026-08-08-plan-quality-design.md` (d61fefe)

## Global Constraints

- 已核实事实：`build_skeleton(modules, guides)` 在 plan_structure.py:90；`parse_module_list_from_summary` 在 :66；`is_plan_goal(goal, rules)` 判断方案类；`llm.stream_text(messages, usage_sink)` 流式调用（llm.py:160，可收集全文当非流式用）；`_build_merged_messages(...)` 在 loop.py:1544（merged_system 注入点）；`wrote_file` 标志在 loop.py:2031 步骤循环；`GenerationLog` 由前端 POST /api/generations 创建（api/generations.py:104，`_find_plan_file` 从 run 找产物）；审计 run 详情页 `frontend/src/app/(agent)/agent/audit/runs/[runId]/page.tsx`
- 事件类型走 agent_run_events.event_type（字符串，无枚举约束——确认 DB 无 CHECK 约束）
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；后端测试 workdir `C:\01_agent_loop_pro\backend`
- **git 纪律**：只 `git add` 本任务精确路径，禁 `git add -A`；提交前 `git status --short`；仓库有并行会话改动（loop.py 常被碰）
- 测试 DB 冲突：用 `$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_<suffix>"` 隔离
- 前端测试：禁页面级 byRole（jsdom 病理），querySelectorAll + textContent

---

### Task 1: 骨架预填前置 + 蓝图双阶段注入

**Files:**
- Modify: `backend/app/services/agent/plan_structure.py`
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_plan_quality_injection.py`（新建）

**Interfaces:**
- Consumes: `build_skeleton`（现有）、`parse_module_list_from_summary`（现有）、`is_plan_goal`（现有，workflow_rules.py）
- Produces:
  - `plan_structure.build_plan_summary(blueprint: str) -> str`（模块清单 + 章节标题提取，失败返回 ""）
  - loop `_AttemptContext.blueprint_injected: bool = False`、`_AttemptContext.skeleton_injected: bool = False`
  - `loop._build_merged_messages` 注入逻辑（见步骤）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_plan_quality_injection.py`：

```python
import pytest


class TestPlanSummary:
    @pytest.mark.anyio
    async def test_build_plan_summary_extracts_modules_and_sections(self):
        from app.services.agent.plan_structure import build_plan_summary

        blueprint = (
            "# 矩阵号规范\n"
            "## 3. 正式方案默认结构\n"
            "方案必须包含以下模块：\n"
            "- 项目背景与目标\n"
            "- 竞品与市场分析\n"
            "- 预算与排期\n"
        )
        summary = build_plan_summary(blueprint)
        assert "矩阵号规范" in summary
        assert "项目背景与目标" in summary
        assert "预算与排期" in summary
        assert len(summary) < 600

    @pytest.mark.anyio
    async def test_build_plan_summary_empty_returns_empty(self):
        from app.services.agent.plan_structure import build_plan_summary
        assert build_plan_summary("") == ""
        assert build_plan_summary("   \n  ") == ""
```

（planning messages 注入测试在 Task 1 Step 5 用 loop 级断言——若 loop 注入点难直接测，用 helper 函数测试：`_quality_injection_hints(project_name, blueprint_injected, skeleton, goal) -> str` 返回追加文本——**实现时把注入文本构造抽成纯函数**，见 Step 3。）

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_plan_quality_injection.py -q --no-header`
Expected: FAIL（build_plan_summary 不存在）

- [ ] **Step 3: 实现 build_plan_summary + 注入纯函数**

`backend/app/services/agent/plan_structure.py` 加：

```python
_SECTION_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)

def build_plan_summary(blueprint: str, max_chars: int = 500) -> str:
    """从蓝图原文提取结构化摘要：文档标题 + 章节标题 + 模块清单。失败返回空串。"""
    if not blueprint or not blueprint.strip():
        return ""
    lines: list[str] = []
    first_line = blueprint.strip().splitlines()[0].strip()
    if first_line.startswith("#"):
        lines.append(f"蓝图：{first_line.lstrip('#').strip()}")
    modules = parse_module_list_from_summary(blueprint)
    if modules:
        lines.append("方案必须包含以下模块（不可增删改）：" + "、".join(modules))
    sections = [
        m.group(1).strip()
        for m in _SECTION_HEADING_RE.finditer(blueprint)
        if "正式方案默认结构" not in m.group(1)
    ]
    if sections:
        lines.append("文档章节：" + "、".join(sections[:12]))
    summary = "\n".join(lines)
    return summary[:max_chars]
```

`loop.py` 加（模块级函数，供测试）：

```python
def _quality_injection_hints(
    goal: str,
    project_name: str,
    skeleton: str,
    researched: bool,
) -> str:
    parts: list[str] = []
    if project_name:
        parts.append(
            f"当前会话绑定项目「{project_name}」：文件操作（读/写/改/列）仅限该项目内，"
            "不得访问或引用其他项目的文件。"
        )
    if skeleton:
        parts.append(
            "写入方案文件时必须严格基于以下骨架填充内容，"
            "不得删除/合并/重命名任何模块标题：\n" + skeleton
        )
    if not researched:
        parts.append("方案类任务必须先调研（web_search/read_file/fetch_web_content）再撰写，禁止直接凭记忆写方案。")
    return "\n\n".join(parts)
```

- [ ] **Step 4: 双阶段蓝图——planning 注入摘要**

loop.py `_do_process_attempt` 里 instruction 组装处（`st.instruction` 现有逻辑在 :1564 附近消费）改造：

在 `_do_process_attempt` 开头（`st = self._wf(run.id)` 后）：
```python
        if not st.instruction and settings.workflow_docs_enabled:
            # 双阶段：规划阶段用摘要（全文在首次 write_file 时注入）
            try:
                if getattr(run, "project_folder_id", None) is not None or is_plan_goal(run.goal, st.rules):
                    from app.services.agent.plan_structure import build_plan_summary
                    from app.services.agent.workflow_policy import WorkflowPolicy
                    policy = self.workflow_policy
                    owner_id = await policy._resolve_super_admin_id(repo.session)
                    blueprint = (
                        await policy._load_doc(
                            repo.session, owner_id,
                            settings.workflow_core_doc_path,
                            limit=settings.workflow_blueprint_full_limit,
                        )
                        if owner_id else ""
                    )
                    if blueprint:
                        summary = build_plan_summary(blueprint)
                        if summary:
                            st.instruction = f"蓝图摘要（写入阶段会提供完整蓝图）：\n{summary}"
            except Exception:
                logger.warning("plan_summary_injection_failed", exc_info=True)
```

（注意：`st.instruction` 现有完整赋值逻辑（:1943 附近 workflow_docs_enabled 分支）——**保留现状**，本步骤只对 `st.instruction` 为空时注入摘要；若现有逻辑总赋值 instruction，则改为：现状 instruction 保留全文→**改为摘要优先**：在现有赋值处将 full instruction 换成摘要版——**以实际代码为准**：读 :1940-1960 区段，把"蓝图原文"部分替换为摘要，required docs 部分保留。Task 1 验证：run 时 st.instruction 含"蓝图摘要"字样。）

- [ ] **Step 5: 骨架注入 + 蓝图全文注入（write_file 首次）**

loop.py `_build_merged_messages`（merged_system 组装处）——把现有 project_hint 逻辑替换为调用纯函数 + 双阶段控制。上下文对象传 `ctx`（含 run/wf）：

```python
        # 骨架 + 调研门 + 项目提示（纯函数构造）
        skeleton = ""
        if not ctx.skeleton_injected and is_plan_goal(goal, self._wf(run_id).rules):
            # 模块清单必须从蓝图原文解析（与校验器同源）——_load_blueprint_full 取原文
            blueprint_full = await self._load_blueprint_full(repo, run_id)
            modules = parse_module_list_from_summary(blueprint_full or "")
            if modules:
                from app.services.agent.plan_structure import build_skeleton
                skeleton = build_skeleton(modules)
                ctx.skeleton_injected = True
        hints = _quality_injection_hints(
            goal=goal,
            project_name=ctx.project_name,
            skeleton=skeleton,
            researched=ctx.researched,
        )
        if hints:
            merged_system = merged_system + "\n\n" + hints
        # 首次 write_file 时注入蓝图全文
        if (
            not ctx.blueprint_injected
            and self._wf(run_id).instruction
            and "蓝图摘要" in self._wf(run_id).instruction
        ):
            # 全文注入：_load_doc 取全文（同 Task 1 Step 4 模式）→ merged_system 追加
            ctx.blueprint_injected = True
```

（_AttemptContext 加字段：`blueprint_injected: bool = False`、`skeleton_injected: bool = False`、`researched: bool = False`。蓝图全文获取若复杂，Task 1 允许：**摘要注入用 instruction（已含 required docs + 摘要），全文注入单独 _load_doc**——用 helper `async def _load_blueprint_full(self, repo, run_id) -> str` 封装，供本处与 Task 3 复用。）

- [ ] **Step 6: 测试通过 + 回归**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_plan_quality_injection.py -q --no-header`
Expected: 3 通过
回归：`& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_loop.py tests/test_plan_structure.py -q --no-header`

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/agent/plan_structure.py backend/app/services/agent/loop.py backend/tests/test_plan_quality_injection.py
git commit -m "feat: skeleton prefill and two-stage blueprint injection"
```

---

### Task 2: 规则质检 + 强制调研门

**Files:**
- Modify: `backend/app/services/agent/plan_structure.py`（quality_check）
- Modify: `backend/app/services/agent/tool_executor.py`（_write_file 校验后跑质检）
- Modify: `backend/app/services/agent/loop.py`（调研门拦截 + ctx.researched 置位）
- Modify: `backend/app/core/config.py`（Settings 加配置）
- Test: `backend/tests/test_plan_quality_injection.py` 扩展

**Interfaces:**
- Consumes: Task 1 的 `ctx.researched`（Task 1 已加字段）、`is_plan_goal`
- Produces:
  - `plan_structure.quality_check(content: str, modules: list[str], min_chars: int = 200) -> list[str]`（返回失败项中文描述列表，空 = 通过）
  - 调研门拒绝观察：`{"error": "research_required", "hint": "方案类任务必须先调研（搜索或读取资料）再撰写，请先使用 web_search / read_file / fetch_web_content 收集资料"}`（匹配 _write_file 现有 error 返回格式）

- [ ] **Step 1: 写失败测试**

`tests/test_plan_quality_injection.py` 加：

```python
class TestQualityCheck:
    @pytest.mark.anyio
    async def test_quality_check_flags_short_module_and_missing_budget(self):
        from app.services.agent.plan_structure import quality_check
        content = (
            "# 方案\n"
            "## 项目背景\n太短了。\n"
            "## 预算与排期\n"  # 标题含预算但无数字
            "根据实际情况调整。\n"
        )
        fails = quality_check(content, ["项目背景", "预算与排期"], min_chars=20)
        joined = "\n".join(fails)
        assert any("字数" in f or "太短" in f or "项目背景" in f for f in fails), joined
        assert any("预算" in f and ("数字" in f or "数据" in f) for f in fails), joined

    @pytest.mark.anyio
    async def test_quality_check_passes_good_content(self):
        from app.services.agent.plan_structure import quality_check
        content = (
            "# 方案\n"
            "## 项目背景\n" + "这是一段足够长的背景描述。" * 20 + "\n"
            "## 预算与排期\n首月预算 50000 元，排期 3 周。\n"
        )
        fails = quality_check(content, ["项目背景", "预算与排期"], min_chars=50)
        assert fails == []

    @pytest.mark.anyio
    async def test_quality_check_detects_hollow_phrases(self):
        from app.services.agent.plan_structure import quality_check
        content = "## 执行策略\n本方案将全面赋能业务增长，实现跨越式发展。\n"
        fails = quality_check(content, ["执行策略"], min_chars=10)
        assert any("空洞" in f or "套话" in f or "赋能" in f for f in fails)
```

（调研门测试放 loop 级——见 Step 5。）

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_plan_quality_injection.py -q --no-header`
Expected: FAIL（quality_check 不存在）

- [ ] **Step 3: 实现 quality_check + 配置**

`backend/app/core/config.py` Settings 加：

```python
    quality_module_min_chars: int = 200
    quality_review_max_rounds: int = 2
    quality_hollow_phrases: str = "本方案将全面赋能,根据实际情况进行调整,助力,赋能,众所周知,综上所述"
```

`plan_structure.py` 加：

```python
def _hollow_phrase_list(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def quality_check(content: str, modules: list[str], min_chars: int = 200) -> list[str]:
    """确定性内容质检。返回失败项中文描述；空列表 = 通过。"""
    from app.core.config import get_settings
    fails: list[str] = []
    for mod in modules:
        pattern = re.compile(rf"^#{1,6}\s+{re.escape(mod)}\s*$", re.MULTILINE)
        m = pattern.search(content)
        if m is None:
            continue
        seg_start = m.end()
        seg_end = len(content)
        nxt = pattern.search(content, seg_start)
        if nxt is not None:
            seg_end = nxt.start()
        segment = content[seg_start:seg_end].strip()
        if len(segment) < min_chars:
            fails.append(f"模块「{mod}」内容过短（{len(segment)} 字符 < {min_chars}）")
        if ("预算" in mod or "费用" in mod or "报价" in mod) and not re.search(r"\d", segment):
            fails.append(f"模块「{mod}」缺少具体数字（预算/费用必须给出金额）")
    settings = get_settings()
    for phrase in _hollow_phrase_list(settings.quality_hollow_phrases):
        if phrase and phrase in content:
            fails.append(f"检测到空洞套话「{phrase}」，请替换为具体可执行的描述")
    return fails
```

- [ ] **Step 4: tool_executor 接入质检**

`tool_executor.py` `_write_file` 成功路径（结构校验通过后、写盘前）加：

```python
                from app.services.agent.plan_structure import parse_module_list_from_summary, quality_check
                settings = get_settings()
                modules = parse_module_list_from_summary(summary or "")
                if modules:
                    qfails = quality_check(content, modules, min_chars=settings.quality_module_min_chars)
                    if qfails:
                        return {
                            "error": "quality_check_failed",
                            "hint": "内容质检未通过：\n- " + "\n- ".join(qfails),
                        }
```

（`summary` 变量名按 _write_file 实际（蒸馏摘要/蓝图原文——读现有校验代码取实际变量名；`get_settings` 已 import 则直接用。）

- [ ] **Step 5: 调研门（loop 拦截 + researched 置位）**

loop.py 步骤循环 execute 调用前（:1257 处）：

```python
            if (
                action.get("type") == "write_file"
                and is_plan_goal(goal, st.rules)
                and not ctx.researched
                and not _RESEARCH_EXEMPT_GOAL_RE.search(goal or "")
            ):
                observation = {
                    "error": "research_required",
                    "hint": "方案类任务必须先调研（搜索或读取资料）再撰写，"
                            "请先使用 web_search / read_file / fetch_web_content 收集资料",
                }
                await self._persist_and_notify(repo, ctx, "tool_completed", self._tool_event_payload(step_index, action, observation))
                step_duration_seconds = (datetime.now(UTC) - started_at).total_seconds()
                ctx.step_journal.append(...)  # 照现有观察处理路径
                continue  # 结束本 step（照现有 tool 成功后的流程——读现有代码结构照抄）
```

模块级：
```python
_RESEARCH_EXEMPT_GOAL_RE = re.compile(r"基于已有资料|无需调研|不需要调研|使用以下资料|根据文档", re.IGNORECASE)
```

`ctx.researched` 置位：execute 返回后检查 `action.get("type") in {"web_search", "read_file", "fetch_web_content"}` → `ctx.researched = True`。

- [ ] **Step 6: 测试通过 + 回归**

`tests/test_plan_quality_injection.py` 加调研门测试（mock planner 产出 write_file action + FakeRun 带 goal）——照 test_agent_loop.py 现有 step 循环测试模式：
- 方案类 goal 未调研 → observation error research_required（工具未执行）
- 先 web_search 后 write_file → 放行
- goal 含"基于已有资料" → 放行
- 非方案类 → 放行

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_plan_quality_injection.py tests/test_agent_loop.py tests/test_agent_tool_files.py -q --no-header`
Expected: 全过

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/agent/plan_structure.py backend/app/services/agent/tool_executor.py backend/app/services/agent/loop.py backend/app/core/config.py backend/tests/test_plan_quality_injection.py
git commit -m "feat: deterministic quality check and research gate for plan goals"
```

---

### Task 3: 质量自审门（quality_review 模块 + loop 集成 + 事件）

**Files:**
- Create: `backend/app/services/agent/quality_review.py`
- Modify: `backend/app/services/agent/llm.py`（加非流式 `complete()`）
- Modify: `backend/app/services/agent/loop.py`（write_file 成功后触发自审）
- Modify: `backend/app/services/agent/tool_executor.py`（无需——自审在 loop 层）
- Test: `backend/tests/test_quality_review.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `_load_blueprint_full`（蓝图全文）、Task 2 的 `quality_check`
- Produces:
  - `quality_review.build_review_messages(goal: str, file_content: str, criteria: str, round_no: int) -> list[dict[str, str]]`
  - `quality_review.parse_review_result(text: str) -> dict`（{score: int, pass: bool, dims: [{name, pass, reason}], raw}）
  - `quality_review.extract_criteria(blueprint: str) -> str`（从蓝图「质量评分卡」章节提取，无则内置默认）
  - llm.complete(messages) -> str（非流式，收集 stream_text）
  - 事件：`quality_review_started`（payload: {file_id, round}）、`quality_review_completed`（payload: {file_id, rounds, score, pass, dims}）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_quality_review.py`：

```python
import pytest


REVIEW_TEXT = """```json
{"score": 62, "pass": false, "dims": [
  {"name": "完整性", "pass": true, "reason": "模块齐全"},
  {"name": "可落地性", "pass": false, "reason": "预算模块无具体金额"},
  {"name": "数据支撑", "pass": true, "reason": "引用调研数据"},
  {"name": "专业度", "pass": false, "reason": "存在空洞套话"}
]}
```"""


class TestReviewParse:
    def test_parse_review_result_extracts_score_and_dims(self):
        from app.services.agent.quality_review import parse_review_result
        result = parse_review_result(REVIEW_TEXT)
        assert result["score"] == 62
        assert result["pass"] is False
        assert len(result["dims"]) == 4
        assert result["dims"][1]["name"] == "可落地性"
        assert result["dims"][1]["pass"] is False

    def test_parse_review_result_fallback_on_garbage(self):
        from app.services.agent.quality_review import parse_review_result
        result = parse_review_result("完全不是 JSON 的输出")
        assert result["score"] == 0
        assert result["pass"] is False

    def test_extract_criteria_default_when_no_scorecard(self):
        from app.services.agent.quality_review import extract_criteria
        criteria = extract_criteria("# 普通文档\n无评分卡\n")
        assert "完整性" in criteria and "可落地性" in criteria
        assert "数据支撑" in criteria and "专业度" in criteria

    def test_extract_criteria_from_blueprint_scorecard(self):
        from app.services.agent.quality_review import extract_criteria
        blueprint = "# 规范\n## 质量评分卡\n完整性：全部模块有实质内容。\n可落地性：预算必须有数字。\n"
        criteria = extract_criteria(blueprint)
        assert "完整性" in criteria and "可落地性" in criteria

    def test_build_review_messages_contains_adversarial_role_and_content(self):
        from app.services.agent.quality_review import build_review_messages
        msgs = build_review_messages("写方案", "文件正文内容", "完整性：…", 1)
        system = msgs[0]["content"]
        assert "评审" in system and "找出所有问题" in system
        assert "文件正文内容" in msgs[-1]["content"]
```

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_quality_review.py -q --no-header`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 quality_review.py**

```python
"""方案质量自审门：写入后 LLM 对照质量评分卡评审，结果驱动修订。"""
from __future__ import annotations

import json
import re
from typing import Any

DEFAULT_CRITERIA = (
    "完整性：全部模块有实质内容（非一句话带过），每模块不少于 200 字。\n"
    "可落地性：有具体预算数字表；有时间线/执行节奏；步骤可操作（谁、何时、做什么）。\n"
    "数据支撑：关键结论有数据或来源；引用调研结果；无凭空编造的数字。\n"
    "专业度：术语与规范一致；格式统一；无空洞套话。"
)

_SCORECARD_RE = re.compile(r"^#{1,3}\s*质量评分卡\s*$", re.MULTILINE)


def extract_criteria(blueprint: str) -> str:
    """从蓝图「质量评分卡」章节提取评审标准；无该章节返回内置默认。"""
    if not blueprint:
        return DEFAULT_CRITERIA
    m = _SCORECARD_RE.search(blueprint)
    if m is None:
        return DEFAULT_CRITERIA
    return blueprint[m.end():].strip()[:2000] or DEFAULT_CRITERIA


def build_review_messages(
    goal: str, file_content: str, criteria: str, round_no: int
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是严苛的方案质量评审官。你的职责是找出所有问题，绝不放过任何不合格项。\n"
                "评审标准（质量评分卡）：\n" + criteria + "\n\n"
                "输出格式：只输出 JSON，结构："
                '{"score": 0-100, "pass": true/false, "dims": [{"name": "完整性", "pass": true/false, "reason": "依据（引用原文片段）"}, ...]}\n'
                "规则：score < 60 或任一维度未通过 → pass 为 false。"
                "禁止使用『基本合格』『大体符合』等模糊判定；每项必须给出依据。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"任务目标：{goal}\n"
                f"待评审方案全文（第 {round_no} 轮评审）：\n\n{file_content}"
            ),
        },
    ]


def parse_review_result(text: str) -> dict[str, Any]:
    """解析评审 JSON；失败返回 score=0/pass=False 的兜底结构。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {"score": 0, "pass": False, "dims": []}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"score": 0, "pass": False, "dims": []}
    score = int(data.get("score", 0))
    dims = data.get("dims", [])
    passed = bool(data.get("pass", False))
    if score < 60 or any(not d.get("pass", False) for d in dims):
        passed = False
    return {"score": score, "pass": passed, "dims": dims}
```

- [ ] **Step 4: llm.complete 非流式**

`llm.py` 加：

```python
    async def complete(self, messages: list[dict[str, str]]) -> str:
        """非流式完整响应（内部走流式收集）。"""
        chunks: list[str] = []
        async for chunk in self.stream_text(messages):
            chunks.append(chunk)
        return "".join(chunks)
```

- [ ] **Step 5: loop 集成自审门**

loop.py 步骤循环 write_file 成功路径（`wrote_file = True` 置位后）加：

```python
            if (
                wrote_file
                and is_plan_goal(goal, st.rules)
                and (st.quality_review_rounds or 0) < settings.quality_review_max_rounds
            ):
                review = await self._run_quality_review(repo, ctx, action, st)
                if review is not None:
                    # 评审 observation 注入下个 step（模型据此修订）
                    ...
```

（`_wf` 状态加 `quality_review_rounds: int = 0`——wf 是 dict 风格（_WF_ATTR_MAP）——核实 _wf 机制：`_maybe_reset_workflow_state` + `self._wf(run_id).xxx`——加字段 `quality_review_rounds: int = 0`。）

新增方法：

```python
    async def _run_quality_review(
        self, repo: AgentRepository, ctx: _AttemptContext, action: dict, st
    ) -> dict[str, Any] | None:
        """write_file 成功后执行质量自审。返回评审结果（失败返回 None 不阻塞）。"""
        from app.services.agent.quality_review import (
            build_review_messages, extract_criteria, parse_review_result,
        )
        file_id = (action.get("input") or {}).get("file_id") or (action.get("input") or {}).get("path")
        if file_id is None:
            return None
        try:
            # 读回刚写入的文件内容（复用 _read_file 或直接 repo 读——用 repo.get 取 FileObject + storage_key 读盘）
            content = await self._read_file_content_for_review(repo, ctx, file_id)
            if content is None:
                return None
            st.quality_review_rounds += 1
            blueprint = await self._load_blueprint_full(repo, ctx.run.id)
            criteria = extract_criteria(blueprint or "")
            await self._persist_and_notify(
                repo, ctx, "quality_review_started",
                {"file_id": str(file_id), "round": st.quality_review_rounds},
            )
            messages = build_review_messages(ctx.run.goal, content, criteria, st.quality_review_rounds)
            text = await self.llm.complete(messages)
            result = parse_review_result(text)
            result["round"] = st.quality_review_rounds
            result["file_id"] = str(file_id)
            await self._persist_and_notify(
                repo, ctx, "quality_review_completed", result,
            )
            if result["pass"]:
                return None
            return result
        except Exception:
            logger.warning("quality_review_failed", exc_info=True)
            return None
```

（`_read_file_content_for_review`：用 repo 取 FileObject（by id + owner 校验）→ storage_key 读盘 → 截断 50KB。`_load_blueprint_full`：Task 1 的 helper——若无则本任务实现（复用 workflow_policy._load_doc）。

**修订驱动**：评审不通过 → 把评审结果作为 observation 注入**下一个 step 的会话历史**（`session_history` 或 step_journal 追加：`"质量评审第N轮不通过：\n- 可落地性：预算无金额（原文：...）\n请用 edit_file 修订后再写入"`）——模型下个 step 自然选择 edit_file 修订——修订后 write_file/edit_file 成功再次触发自审（rounds 递增，达到 max 停止）。实现：`ctx` 或 st 存 `pending_review_hint: str | None`，`_build_merged_messages` 注入到 merged_system（与 Task 1 hints 同机制）或注入 next observation。**选择**：追加到 `st.step_journal` 不合适（journal 是用户可见说明）——**加到 `st.pending_review_hint` 并在 _build_merged_messages 注入 merged_system**。）

- [ ] **Step 6: 测试通过 + 回归**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_quality_review.py tests/test_plan_quality_injection.py -q --no-header`
Expected: 全过
回归：`& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_loop.py tests/test_agent_tool_files.py -q --no-header`

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/agent/quality_review.py backend/app/services/agent/llm.py backend/app/services/agent/loop.py backend/tests/test_quality_review.py
git commit -m "feat: post-write quality review gate with revision loop"
```

---

### Task 4: 质量分入库 + 治理中心展示

**Files:**
- Create: `backend/alembic/versions/<hex>_add_generation_quality_columns.py`
- Modify: `backend/app/models/generation_log.py`（+2 列）
- Modify: `backend/app/api/generations.py`（create_generation 回填）
- Modify: `frontend/src/app/(agent)/agent/audit/runs/[runId]/page.tsx`（质量区块）
- Test: `backend/tests/test_generations_api.py` 扩展 + 前端测试

**Interfaces:**
- Consumes: Task 3 的事件 `quality_review_completed`（payload: file_id/rounds/score/pass/dims）
- Produces: 无

- [ ] **Step 1: 迁移 + 模型**

`generation_log.py` 加：
```python
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_review_rounds: Mapped[int] = mapped_column(Integer, default=0)
```
迁移：`alembic heads` 核当前 head → 手写 `op.add_column('generation_logs', sa.Column('quality_score', sa.Integer(), nullable=True))` + `quality_review_rounds`（Integer, nullable=False, server_default='0'）。应用 `alembic upgrade head`。

- [ ] **Step 2: create_generation 回填**

`api/generations.py` `create_generation`（GenerationLog 构造后）加——查 run 的最新 quality_review_completed 事件：

```python
    quality_score: int | None = None
    quality_rounds = 0
    review_events = (
        await db.execute(
            select(AgentRunEvent)
            .where(
                AgentRunEvent.run_id == run.id,
                AgentRunEvent.event_type == "quality_review_completed",
            )
            .order_by(AgentRunEvent.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if review_events is not None:
        payload = review_events.payload or {}
        quality_score = payload.get("score")
        quality_rounds = int(payload.get("round") or 0)
```
（AgentRunEvent 模型名/字段核实——models/agent.py；payload 是 JSON。log 构造加 `quality_score=quality_score, quality_review_rounds=quality_rounds`。）

- [ ] **Step 3: 前端治理中心质量区块**

`audit/runs/[runId]/page.tsx`：run 详情加"质量审校"区块（数据来源：run 的 events 列表——该页已加载 events（过程稿）——从 events 过滤 quality_review_completed）：
- 分数徽章：`≥80 绿色 / 60-79 橙色 / <60 红色` 圆形徽章（如 `62 分`）
- 维度列表：每维度 pass ✓（绿）/ fail ✗（红）+ reason
- 修订轮数：`共 {rounds} 轮评审`
- 无评审事件 → 不渲染区块

测试：mock events 含 quality_review_completed → 断言徽章与维度渲染；无事件 → 区块不出现。照 audit 页现有测试模式（querySelectorAll + textContent）。

- [ ] **Step 4: 测试 + 前端验证**

后端：`& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_generations_api.py -q --no-header`（隔离 DB）
前端：`npx tsc --noEmit` + 目标测试文件

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/<hex>_add_generation_quality_columns.py backend/app/models/generation_log.py backend/app/api/generations.py frontend/src/app/"(agent)"/agent/audit/runs/"[runId]"/page.tsx + tests
git commit -m "feat: quality score persisted and shown in audit run detail"
```

---

### Task 5: 全量回归 + E2E

- [ ] **Step 1: 全量回归（隔离 DB）**

```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_quality"
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header
```
Expected: 全过或仅已知失败（pypdf 4 个 + 并行会话既有）

- [ ] **Step 2: 前端全量相关测试**

`npx vitest run src/app/"(agent)"/agent/audit`（或全量前端——并行会话文件可能挂，只看本计划相关文件）

- [ ] **Step 3: 用户实测清单**

1. 对话"生成一个矩阵号运营方案"（方案类 goal）→ 观察：模型先调研（web_search）→ 规划 messages 含蓝图摘要 + 骨架 → write_file → 规则质检/结构校验 → 自审（思考区"质量评审"或事件可见）→ 不达标自动 edit_file 修订
2. 治理中心 → 该 run 详情 → "质量审校"区块：分数徽章 + 维度 pass/fail + 轮数
3. 不满足调研门的 goal（新对话直接"写方案"不调研）→ 观察拒绝观察 research_required → 模型补调研
4. 文件页确认最终方案文件存在且模块齐全
5. 成本对比：同任务下 token 消耗（usage 事件）——自审轮数可见
