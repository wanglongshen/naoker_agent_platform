# 蓝图驱动的 Agent 执行引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the agent execute tasks strictly per the blueprint workflow — code-driven rule steps (task classification, admission judgment, versioning, red-line checks) and LLM-driven content steps (recap, research, strategy/creative/execution) — with a pending-question/answer-resume lifecycle, and remove the distill-summary layer entirely (blueprint original text is the single source of truth).

**Architecture:** New `workflow_rules.py` parses the blueprint (task-type table Step 0, admission table Step 0.5, workflow step graph, red-line checklist Step 8, capability references) with sha256 fingerprint caching. `workflow_policy.py` loses all distill machinery (summary read/schedule/lock/version/write-hooks) and instead returns parsed rules + full blueprint text for plan-class tasks. `loop.py` gains a stage state machine (classify → admission → recap → version → research → strategy/creative/execution → redline → done) layered on the existing planner loop. Run lifecycle gains `awaiting_question` (pending_questions JSON column, answer endpoint, worker resume). Validation layer (`plan_structure.py`/`tool_executor.py`) is untouched — it already reads blueprint original text.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / alembic / pytest / TypeScript / Next.js / Vitest.

## Global Constraints

- 蓝图原文是唯一权威；摘要机制（workflow_doc_summaries 读取/蒸馏调度/_DISTILL_PROMPT/_DISTILL_VERSION/单飞锁/write 钩子/ensure_summary）全部删除，表保留不删
- `_DOC_CONTENT_LIMIT=12000` 限制蓝图会截断（蓝图 15342 字符）：workflow_policy 加载核心蓝图文档时使用更高的全文限制（20000），路由规范文档仍可截断——具体见 Task 2
- 校验器（plan_structure.py/tool_executor.py）**零改动**
- 步骤推进由代码验证前置条件驱动，不由 LLM 声明阶段
- 追问 ≤5 问；run 恢复不产生新 attempt；恢复后跳过已完成阶段
- 现有测试必须全部通过（后端 777 passed 基线）；删除的摘要测试同步清理
- commit 从仓库根 C:\01_agent_loop_pro 执行，仓库根相对路径
- 共享 Postgres 测试 DB：同一时刻只允许一个 pytest 进程（先 `Get-Process python -ErrorAction SilentlyContinue`）

---

### Task 1: workflow_rules.py — 蓝图条件图解析器（新文件）

**Files:**
- Create: `backend/app/services/agent/workflow_rules.py`
- Test: `backend/tests/test_workflow_rules.py`（新建）

**Interfaces:**
- Consumes: 无（纯函数 + 内部指纹缓存）
- Produces:
  - `TaskTypeRule(type_name, features, default_action, route_doc)`
  - `AdmissionRule(branch, applies, next_step)`
  - `WorkflowStep(step_id, title, body, kind, condition)`
  - `WorkflowGraph(steps, task_type_edges)`
  - `ParsedRules(sha256, task_types, admission_rules, graph, red_lines, structure)`
  - `parse_task_types(text) -> list[TaskTypeRule]`
  - `parse_admission_rules(text) -> list[AdmissionRule]`
  - `parse_workflow_graph(text) -> WorkflowGraph`
  - `parse_red_lines(text) -> list[str]`
  - `parse_structure_section(text) -> list[str]`（复用蓝图 `## 3` 解析，供状态机使用）
  - `classify_task_type(goal, rules) -> TaskTypeRule`（关键词匹配 8 类）
  - `admission_judgment(goal, files_read_ok, missing_constraints) -> AdmissionRule`（规则判定 4 分支）
  - `resolve_capability(tool_ref) -> str | None`（能力映射）
  - `WorkflowRulesCache`：`get(blueprint_text) -> ParsedRules`（sha256 指纹缓存）

- [ ] **Step 1: Write the failing tests**（新建 `backend/tests/test_workflow_rules.py`）

```python
import pytest

from app.services.agent.workflow_rules import (
    classify_task_type,
    parse_admission_rules,
    parse_red_lines,
    parse_task_types,
    parse_workflow_graph,
    resolve_capability,
    WorkflowRulesCache,
)

BLUEPRINT = """
### Step 0：判断任务类型

收到用户需求后，先判断它属于哪一类：

| 任务类型 | 特征 | 默认动作 |
| --- | --- | --- |
| 纯框架问题 | 用户问方法论、策略逻辑、创意思路 | 直接用脑壳儿心智模型回答 |
| 事实研究问题 | 涉及具体品牌、平台、数据、竞品、案例 | 先做外部研究，再给判断 |
| 混合策略问题 | 具体品牌 + 需要建议 | brief 复述 + 快速研究 + 案例类比 |
| 完整方案需求 | 明确要方案、策划、规划、提案 | 先生成本地版本化源稿，再创建或更新飞书客户方案 |
| 完整 UGC 种草方案 | 明确是 UGC/KOC/素人种草、双平台、H2/季度内容投放 | 进入 `脑壳儿_UGC种草方案输出规范.md` |
| 小红书种草方案 | 明确是小红书种草、新品种草、达人种草、红书投放 | 进入 Word 文字版标准结构 |
| 矩阵号代运营方案 | 明确是矩阵号、代运营、年度运营、品牌官号、创始人 IP | 进入 `脑壳儿_矩阵号代运营方案输出规范.md` |
| 修改/扩写需求 | 用户要求优化已有方案、文案或结构 | 先识别原方案意图，再局部重写 |

### Step 0.5：Brief 与附件准入分析

| 判断结果 | 适用情况 | 下一步 |
| --- | --- | --- |
| 可直接产出 | 任务、交付和关键约束清楚 | 不要求二次确认，直接进入研究与产出 |
| 带假设产出 | 缺口不改变主方向 | 写明必要假设，继续产出 |
| 先追问 | 缺口会改变策略方向、预算规模、平台任务 | 集中提出不超过 5 个关键问题 |
| 材料异常 | 关键文件无法读取、附件缺失 | 说明具体文件和冲突，要求补传 |

### Step 1：Brief 复述

先在内部用 5-8 句话重构用户 brief。

### Step 1.1：版本判断

新项目/新 brief：默认 `V1`。用户说"根据反馈重出"：查找最高版本并输出下一版。

### Step 1.5：小红书种草内部 7 模块检查链路

当 brief 明确是"小红书种草方案"时，脑壳儿内部按 7 模块串行推理。

### Step 1.6：矩阵号代运营内部检查链路

当 brief 明确是"矩阵号代运营"时，脑壳儿优先调用 `脑壳儿_矩阵号代运营方案输出规范.md`。

### Step 1.7：完整 UGC 种草方案检查链路

当 brief 明确是完整 UGC/KOC/素人种草时。

### Step 2：缺口追问

仅当 Step 0.5 判断为"先追问"时触发。

### Step 3：实时外部研究

默认允许联网研究。优先使用 Agent-Reach。

### Step 3.1：交付前文字去 AI 味

使用 `$humanizer-zh` 完成最终润色。

### Step 4：案例库调用

### Step 5：策略判断

### Step 6：创意方向生成

### Step 7：执行拆解

### Step 8：风险校验

- 有没有编造数据。
- 有没有跳过竞品和平台现状。
- 有没有只给概念不讲执行。
- 有没有缺少强记忆点创意切口。
- 有没有忽略甲方 brief 里的硬性要求。

## 3. 正式方案默认结构

1. Brief Recap：复述背景、推广主体、核心任务、目标心智/效果。
2. 前策调研与思考：行业/平台现状、竞品拆解、demo 链接、前端小结。
3. 本品表现与机会下探：本品资产、平台表现、用户原生表达、卖点转译。
4. 用户分析与达人类型：人群画像、内容偏好、达人类型、内容任务。
5. 创意与传播规划：传播 TAG、核心创意内容、达人类型、Message House、Content Demo。
6. 投流策略：阶段、预算比例、投放形式、关键词、人群包、效果口径。
7. Roadmap：阶段、时间、核心目标、传播信息、达人、内容、投流、KPI。
8. 附录：达人筛选、团队、案例。
"""


def test_parse_task_types_returns_eight():
    types = parse_task_types(BLUEPRINT)
    assert len(types) == 8
    assert [t.type_name for t in types] == [
        "纯框架问题", "事实研究问题", "混合策略问题", "完整方案需求",
        "完整 UGC 种草方案", "小红书种草方案", "矩阵号代运营方案", "修改/扩写需求",
    ]


def test_parse_task_types_route_doc():
    types = parse_task_types(BLUEPRINT)
    by_name = {t.type_name: t for t in types}
    assert by_name["矩阵号代运营方案"].route_doc == "脑壳儿_矩阵号代运营方案输出规范.md"
    assert by_name["完整 UGC 种草方案"].route_doc == "脑壳儿_UGC种草方案输出规范.md"
    assert by_name["完整方案需求"].route_doc is None


def test_classify_task_type_matches_plan_keywords():
    types = parse_task_types(BLUEPRINT)
    rule = classify_task_type("读取 brief_test.md 然后写一份创意建议的方案，保存到 brief/文件夹中", types)
    assert rule.type_name == "完整方案需求"


def test_classify_task_type_matches_ugc():
    types = parse_task_types(BLUEPRINT)
    rule = classify_task_type("做一份 UGC 种草方案，双平台投放", types)
    assert rule.type_name == "完整 UGC 种草方案"


def test_classify_task_type_framework_question():
    types = parse_task_types(BLUEPRINT)
    rule = classify_task_type("什么是品牌心智模型？", types)
    assert rule.type_name == "纯框架问题"


def test_parse_admission_rules_four_branches():
    rules = parse_admission_rules(BLUEPRINT)
    assert [r.branch for r in rules] == ["可直接产出", "带假设产出", "先追问", "材料异常"]


def test_parse_workflow_graph_all_steps():
    graph = parse_workflow_graph(BLUEPRINT)
    ids = [s.step_id for s in graph.steps]
    for expected in ["0", "0.5", "1", "1.1", "1.5", "1.6", "1.7", "2", "3", "3.1", "4", "5", "6", "7", "8"]:
        assert expected in ids


def test_parse_workflow_graph_kinds():
    graph = parse_workflow_graph(BLUEPRINT)
    by_id = {s.step_id: s for s in graph.steps}
    assert by_id["0"].kind == "rule"       # 分类表
    assert by_id["0.5"].kind == "rule"     # 准入表
    assert by_id["1"].kind == "content"    # 复述
    assert by_id["3"].kind == "content"    # 研究
    assert by_id["8"].kind == "rule"       # 红线清单
    assert by_id["2"].condition is not None  # 仅当先追问


def test_parse_workflow_graph_task_type_edges():
    graph = parse_workflow_graph(BLUEPRINT)
    assert "完整方案需求" in graph.task_type_edges
    assert graph.task_type_edges["完整方案需求"] == ["0", "0.5", "1", "1.1", "3", "5", "6", "7", "8"]
    assert "矩阵号代运营方案" in graph.task_type_edges
    assert "1.6" in graph.task_type_edges["矩阵号代运营方案"]


def test_parse_red_lines():
    red = parse_red_lines(BLUEPRINT)
    assert len(red) >= 5
    assert any("编造数据" in line for line in red)


def test_resolve_capability_mapping():
    assert resolve_capability("$agent-reach") == "web_search"
    assert resolve_capability("$humanizer-zh") is None
    assert resolve_capability("案例库") == "read_file"
    assert resolve_capability("unknown_tool") is None


def test_rules_cache_fingerprint():
    cache = WorkflowRulesCache()
    r1 = cache.get(BLUEPRINT)
    r2 = cache.get(BLUEPRINT)
    assert r1 is r2  # 同一指纹命中缓存
    r3 = cache.get(BLUEPRINT + "\n### Step 9：新步骤\n")
    assert r3 is not r1  # 蓝图变 → 新解析
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_workflow_rules.py -q
```
Expected: FAIL（模块不存在 ImportError）

- [ ] **Step 3: Implement** — 新建 `backend/app/services/agent/workflow_rules.py`：

```python
from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel

from app.services.agent.plan_structure import _LIST_ITEM_RE  # 复用编号列表正则


class TaskTypeRule(BaseModel):
    type_name: str
    features: list[str]
    default_action: str
    route_doc: str | None = None


class AdmissionRule(BaseModel):
    branch: str
    applies: str
    next_step: str


class WorkflowStep(BaseModel):
    step_id: str
    title: str
    body: str
    kind: str  # "rule" | "content"
    condition: str | None = None


class WorkflowGraph(BaseModel):
    steps: list[WorkflowStep]
    task_type_edges: dict[str, list[str]]


class ParsedRules(BaseModel):
    sha256: str
    task_types: list[TaskTypeRule]
    admission_rules: list[AdmissionRule]
    graph: WorkflowGraph
    red_lines: list[str]
    structure: list[str]


# 任务分类关键词（Step 0 表格特征的确定性映射；蓝图特征列是描述文字，此处人工摘要）
_TASK_TYPE_KEYWORDS: dict[str, list[str]] = {
    "纯框架问题": ["什么是", "怎么理解", "方法论", "策略逻辑", "创意思路", "框架"],
    "事实研究问题": ["调研", "数据", "竞品", "案例", "趋势", "市场分析", "盘点"],
    "混合策略问题": ["结合", "品牌", "建议"],
    "完整方案需求": ["方案", "策划", "规划", "提案", "创意建议", "保存到", "写到"],
    "完整 UGC 种草方案": ["ugc", "koc", "素人种草", "种草方案", "双平台", "季度内容投放", "h2"],
    "小红书种草方案": ["小红书", "新品种草", "达人种草", "红书投放"],
    "矩阵号代运营方案": ["矩阵号", "代运营", "年度运营", "品牌官号", "创始人", "多平台账号"],
    "修改/扩写需求": ["修改", "优化", "扩写", "重出", "再出一版", "调整"],
}

_RULE_STEP_IDS = {"0", "0.5", "1.1", "8"}  # 表格/清单 → 代码执行
_CONTENT_STEP_IDS = {"1", "3", "3.1", "4", "5", "6", "7"}

_CAPABILITY_MAP = {
    "$agent-reach": "web_search",
    "agent-reach": "web_search",
    "案例库": "read_file",
    "案例库调用": "read_file",
}


def _section(text: str, title: str) -> str:
    match = re.search(rf"^### {re.escape(title)}[^\n]*\n(.*?)(?=^### |^## |\Z)", text, re.M | re.S)
    return match.group(1) if match else ""


def _parse_table(rows: list[str]) -> list[list[str]]:
    cells = []
    for line in rows:
        if "|" not in line or re.match(r"^\s*\|[\s\-|]+\|\s*$", line):
            continue
        parts = [c.strip() for c in line.strip().strip("|").split("|")]
        if parts and parts[0] != "任务类型" and parts[0] != "判断结果" and parts[0] != "模块":
            cells.append(parts)
    return cells


def parse_task_types(blueprint_text: str) -> list[TaskTypeRule]:
    section = _section(blueprint_text, "Step 0：判断任务类型")
    rules: list[TaskTypeRule] = []
    for row in _parse_table(section.splitlines()):
        if len(row) < 3:
            continue
        default_action = row[2]
        route_match = re.search(r"`([^`]+\.md)`", default_action)
        route_doc = route_match.group(1) if route_match else None
        rules.append(
            TaskTypeRule(
                type_name=row[0],
                features=_TASK_TYPE_KEYWORDS.get(row[0], []),
                default_action=default_action,
                route_doc=route_doc,
            )
        )
    return rules


def parse_admission_rules(blueprint_text: str) -> list[AdmissionRule]:
    section = _section(blueprint_text, "Step 0.5：Brief 与附件准入分析")
    rules: list[AdmissionRule] = []
    for row in _parse_table(section.splitlines()):
        if len(row) < 3:
            continue
        rules.append(AdmissionRule(branch=row[0], applies=row[1], next_step=row[2]))
    return rules


def parse_workflow_graph(blueprint_text: str) -> WorkflowGraph:
    steps: list[WorkflowStep] = []
    step_re = re.compile(r"^### Step ([\d.]+)[：:]\s*(.+)$")
    matches = list(step_re.finditer(blueprint_text, re.M))
    for i, m in enumerate(matches):
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(blueprint_text)
        body = blueprint_text[m.end():body_end].strip()
        step_id = m.group(1)
        title = m.group(2).strip()
        kind = "rule" if step_id in _RULE_STEP_IDS else ("content" if step_id in _CONTENT_STEP_IDS else "content")
        condition = None
        if step_id == "2":
            condition = "准入判断=先追问"
        if step_id in {"1.5", "1.6", "1.7"}:
            condition = "按任务类型路由"
        steps.append(WorkflowStep(step_id=step_id, title=title, body=body, kind=kind, condition=condition))

    types = parse_task_types(blueprint_text)
    type_names = [t.type_name for t in types]
    base_path = ["0", "0.5", "1", "1.1", "3", "5", "6", "7", "8"]
    edges: dict[str, list[str]] = {}
    for type_name in type_names:
        path = list(base_path)
        if "UGC" in type_name:
            path = ["0", "0.5", "1", "1.1", "1.7", "3", "5", "6", "7", "8"]
        elif "矩阵号" in type_name:
            path = ["0", "0.5", "1", "1.1", "1.6", "3", "5", "6", "7", "8"]
        elif "小红书" in type_name:
            path = ["0", "0.5", "1", "1.1", "1.5", "3", "5", "6", "7", "8"]
        elif type_name == "纯框架问题":
            path = ["0"]
        edges[type_name] = path
    return WorkflowGraph(steps=steps, task_type_edges=edges)


def parse_red_lines(blueprint_text: str) -> list[str]:
    section = _section(blueprint_text, "Step 8：风险校验")
    lines = [ln.strip().lstrip("- ") for ln in section.splitlines() if ln.strip().startswith("-")]
    return [ln for ln in lines if ln]


def parse_structure_section(blueprint_text: str) -> list[str]:
    from app.services.agent.plan_structure import parse_default_structure_from_blueprint
    return parse_default_structure_from_blueprint(blueprint_text) or []


def classify_task_type(goal: str, rules: list[TaskTypeRule]) -> TaskTypeRule:
    lowered = goal.lower()
    best: TaskTypeRule | None = None
    best_score = 0
    for rule in rules:
        score = sum(1 for kw in rule.features if kw.lower() in lowered)
        if score > best_score:
            best, best_score = rule, score
    return best if best else TaskTypeRule(type_name="纯框架问题", features=[], default_action="直接用脑壳儿心智模型回答")


def admission_judgment(
    goal: str,
    files_read_ok: bool,
    missing_constraints: list[str],
) -> AdmissionRule:
    if not files_read_ok:
        return AdmissionRule(branch="材料异常", applies="关键文件无法读取", next_step="说明具体文件，要求补传")
    critical = [c for c in missing_constraints if c in ("预算", "时间周期", "核心目标", "必讲信息", "成功指标")]
    if critical:
        return AdmissionRule(branch="先追问", applies="缺口会改变策略方向", next_step="集中提出不超过 5 个关键问题")
    return AdmissionRule(branch="可直接产出", applies="任务、交付和关键约束清楚", next_step="直接进入研究与产出")


def resolve_capability(tool_ref: str) -> str | None:
    return _CAPABILITY_MAP.get(tool_ref.strip())


class WorkflowRulesCache:
    def __init__(self) -> None:
        self._cache: dict[str, ParsedRules] = {}

    def get(self, blueprint_text: str) -> ParsedRules:
        sha = hashlib.sha256(blueprint_text.encode("utf-8")).hexdigest()
        cached = self._cache.get(sha)
        if cached is not None:
            return cached
        rules = ParsedRules(
            sha256=sha,
            task_types=parse_task_types(blueprint_text),
            admission_rules=parse_admission_rules(blueprint_text),
            graph=parse_workflow_graph(blueprint_text),
            red_lines=parse_red_lines(blueprint_text),
            structure=parse_structure_section(blueprint_text),
        )
        self._cache[sha] = rules
        return rules

    def invalidate(self) -> None:
        self._cache.clear()


workflow_rules_cache = WorkflowRulesCache()
```

注意：`_section` 的正则对 `### Step 1.5` 会匹配到 `### Step 1.6` 前——`(?=^### |^## |\Z)` 前视适用于所有 `### ` 开头，正确。`parse_workflow_graph` 的 step_re 对 `Step 1.5` 的 `[\d.]+` 匹配 "1.5" 正确。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_workflow_rules.py -q
```
Expected: PASS（10 测试）

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add backend/app/services/agent/workflow_rules.py backend/tests/test_workflow_rules.py
git commit -m "feat: blueprint workflow rules parser with fingerprint cache"
```

---

### Task 2: workflow_policy.py — 删摘要、返回规则 + 蓝图全文注入

**Files:**
- Modify: `backend/app/services/agent/workflow_policy.py`
- Modify: `backend/tests/test_workflow_policy.py`
- Modify: `backend/app/core/config.py`

**Interfaces:**
- Consumes: Task 1 的 `workflow_rules_cache`、`classify_task_type`、`ParsedRules`
- Produces:
  - `WorkflowPolicy.get_rules(session, goal) -> ParsedRules | None`（加载蓝图 → 解析 → 缓存）
  - `WorkflowPolicy.get_instruction(session, goal) -> str`（签名不变；内容改为：方案类任务注入蓝图全文 + 路由文档；非方案类仅路由文档）
  - 删除全部蒸馏机制（`_DISTILL_PROMPT`/`_DISTILL_VERSION`/`_schedule_distill`/`_run_distill_task`/`flush_tasks`/`ensure_summary`/`notify_doc_written`/`_distill_core_doc`/`_read_persisted_summary`/`_file_version` 蒸馏相关部分/`_distill_lock`/`_distill_tasks`/`_pending_dirty`）
  - config.py 新增 `workflow_blueprint_full_limit: int = 20000`

- [ ] **Step 1: Write the failing tests**（重写 `backend/tests/test_workflow_policy.py` 的摘要相关测试；先读该文件现有测试确认 mock 模式）

```python
@pytest.mark.anyio
async def test_get_instruction_injects_full_blueprint_for_plan_class(monkeypatch):
    from app.services.agent.workflow_policy import workflow_policy

    # mock: super admin 存在、核心蓝图文件可读（内容 >12000 字符验证不再截断）
    # mock: classify 命中"完整方案需求"
    instruction = await workflow_policy.get_instruction(session, "写一份方案保存到 brief/")
    assert "【系统工作流约束" in instruction
    assert "脑壳儿_Agent运行蓝图" in instruction  # 蓝图全文已注入
```

**关键**：先读 test_workflow_policy.py 现有测试（`monkeypatch` 什么 seam：`_resolve_super_admin_id` / `_resolve_file` / `_load_doc`），按现有模式重写。摘要相关测试（test_distill_* / test_ensure_summary / test_notify_doc_written）**删除**。断言蓝图全文注入（含 Step 8 红线文本出现）。

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_workflow_policy.py -q
```
Expected: FAIL（get_instruction 仍返回摘要路径；无 get_rules）

- [ ] **Step 3: Implement**

**3a.** `backend/app/core/config.py` 加配置（放在 workflow_docs_enabled 附近）：

```python
    workflow_blueprint_full_limit: int = 20000  # 核心蓝图全文加载上限（蓝图 15342 字符，须大于此）
```

**3b.** `workflow_policy.py` 重写为（保留 `_resolve_super_admin_id`/`_resolve_file`/`_parse_route_rules`/`_load_doc` 缓存逻辑，`_DOC_CONTENT_LIMIT` 用于路由文档）：

```python
from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.file import FileFolder, FileObject
from app.models.rbac import Role, User, UserRole
from app.services.agent.workflow_rules import (
    ParsedRules,
    classify_task_type,
    workflow_rules_cache,
)

logger = logging.getLogger("workflow_policy")

_DOC_CONTENT_LIMIT = 12000  # 路由规范文档上限


class WorkflowPolicy:
    def __init__(self) -> None:
        self._cache: dict[str, dict[str, str]] = {}
        self._super_admin_id: UUID | None = None

    async def _resolve_super_admin_id(self, session: AsyncSession) -> UUID | None:
        # 保持不变（Task 原逻辑）
        ...

    async def _resolve_file(self, session, owner_id, doc_path) -> FileObject | None:
        # 保持不变
        ...

    async def _load_doc(self, session, owner_id, doc_path, limit=None) -> str:
        # 与现有相同；limit 参数允许覆盖上限
        ...

    def _parse_route_rules(self, raw: str) -> list[tuple[list[str], str]]:
        # 保持不变
        ...

    async def get_rules(self, session: AsyncSession, goal: str) -> ParsedRules | None:
        """加载核心蓝图原文 → 解析规则集；失败返回 None。"""
        settings = get_settings()
        if not settings.workflow_docs_enabled:
            return None
        owner_id = await self._resolve_super_admin_id(session)
        if owner_id is None:
            return None
        blueprint = await self._load_doc(
            session, owner_id, settings.workflow_core_doc_path,
            limit=settings.workflow_blueprint_full_limit,
        )
        if not blueprint:
            return None
        return workflow_rules_cache.get(blueprint)

    async def get_instruction(self, session: AsyncSession, goal: str) -> str:
        settings = get_settings()
        if not settings.workflow_docs_enabled:
            return ""
        owner_id = await self._resolve_super_admin_id(session)
        if owner_id is None:
            return ""

        parts: list[str] = []
        rules = await self.get_rules(session, goal)
        task_type = classify_task_type(goal, rules.task_types) if rules else None
        plan_class = task_type is not None and task_type.type_name in {
            "完整方案需求", "完整 UGC 种草方案", "小红书种草方案", "矩阵号代运营方案",
        }
        if plan_class and rules is not None:
            blueprint = await self._load_doc(
                session, owner_id, settings.workflow_core_doc_path,
                limit=settings.workflow_blueprint_full_limit,
            )
            if blueprint:
                parts.append(f"【脑壳儿_Agent运行蓝图（完整原文，必须严格遵守）】\n{blueprint}")

        for keywords, path in self._parse_route_rules(settings.workflow_route_rules):
            if any(keyword in goal for keyword in keywords):
                content = await self._load_doc(session, owner_id, path)
                if content:
                    parts.append(f"【{path.split('/')[-1]}】\n{content}")

        if not parts:
            return ""
        return "【系统工作流约束（必须严格遵守，每次任务都必须执行）】\n" + "\n\n".join(parts)

    def invalidate(self) -> None:
        self._cache.clear()
        self._super_admin_id = None
        workflow_rules_cache.invalidate()


workflow_policy = WorkflowPolicy()
```

**3c.** 删除的方法：`_get_llm`、`_DISTILL_PROMPT`、`_file_version`（蒸馏部分）、`_read_persisted_summary`、`_distill_core_doc`、`_schedule_distill`、`_run_distill_task`、`flush_tasks`、`ensure_summary`、`_paths_match`、`notify_doc_written`。`_DOC_CONTENT_LIMIT` 保留给路由文档。

**3d.** `backend/app/services/agent/loop.py` 顶部（`self._workflow_instruction` 加载处，~line 1335-1340）改用 `get_rules`：

```python
        self._workflow_instruction = ""
        self._workflow_rules = None
        if settings.workflow_docs_enabled:
            try:
                self._workflow_rules = await self.workflow_policy.get_rules(repo.session, run.goal)
                self._workflow_instruction = await self.workflow_policy.get_instruction(repo.session, run.goal)
            except Exception:
                logger.warning("workflow_docs_load_failed", exc_info=True)
```

注意：loop.py 中 `self._workflow_rules` 属性需在 `AgentLoopService.__init__` 声明（或首次赋值即可——Python 动态属性，赋值即存在，无需声明；但显式在 `__init__` 加 `self._workflow_rules: ParsedRules | None = None` 更清晰，见 Task 3）。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_workflow_policy.py -q
```
Expected: PASS（重写后的测试）

- [ ] **Step 5: Regression — 相关测试**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py tests/test_agent_tools.py -q
```
Expected: PASS（无 workflow 相关失败；若有测试引用已删方法则清理）

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/services/agent/workflow_policy.py backend/app/core/config.py backend/tests/test_workflow_policy.py backend/app/services/agent/loop.py
git commit -m "feat: drop distill summaries, inject full blueprint for plan-class tasks"
```

---

### Task 3: 状态机引擎（loop.py 阶段推进）

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: Task 1 `ParsedRules`（task_types/admission_rules/graph/red_lines）、Task 2 `get_rules`
- Produces: `_do_process_attempt` 内阶段状态机；`_build_messages` 增加 `stage_context` 参数；`admission_judgment` 调用；run.result 记录 `blueprint_sha256`

- [ ] **Step 1: Write the failing tests**（追加到 `backend/tests/test_agent_loop.py`——先读该文件现有集成测试的 mock 模式）

```python
@pytest.mark.anyio
async def test_stage_machine_passes_stages_sequentially(self, ...):
    # 构造: rules mock（完整方案需求 → 路径 0,0.5,1,1.1,3,5,6,7,8）
    # attempt 主循环运行 → 断言 run.result["blueprint_sha256"] 已记录
    # 断言 planner prompt 中出现 "当前工作流阶段"
```

**关键**：先读 test_agent_loop.py 现有主循环测试（mock repo / planner / `_stream_planning` 等），复用模式。若集成测试过重，退化为单元级：
- `test_classify_stage_updates_workflow_stage`：构造 `AgentLoopService()`，mock `self._workflow_rules`，调用阶段推进辅助方法，断言 stage 变量推进

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py -q
```
Expected: 新测试 FAIL（无阶段机制）

- [ ] **Step 3: Implement**

**3a.** `AgentLoopService.__init__` 加：

```python
        self._workflow_rules: ParsedRules | None = None
        self._workflow_stage: str = "classify"
        self._workflow_stages_done: list[str] = []
```

**3b.** `_do_process_attempt` 主循环（`while step_index < effective_max_steps` 内、planner 决策前）插入阶段推进逻辑：

```python
            self._advance_workflow_stage(repo, run, step_index)
```

**3c.** 新增辅助方法（放在 `_run_policy` 附近）：

```python
    def _advance_workflow_stage(
        self, repo, run, step_index: int
    ) -> None:
        """代码驱动阶段推进：分类→准入→复述→版本→研究→策略→创意→拆解→红线→done。"""
        if self._workflow_rules is None:
            return
        stage = self._workflow_stage
        if stage == "classify":
            task_type = classify_task_type(run.goal, self._workflow_rules.task_types)
            self._workflow_task_type = task_type.type_name
            self._workflow_stage = self._next_stage_after("classify", task_type.type_name)
            self._workflow_stages_done.append("classify")
        elif stage == "admission":
            rule = admission_judgment(run.goal, files_read_ok=True, missing_constraints=[])
            self._workflow_admission = rule.branch
            if rule.branch == "先追问":
                # 追问逻辑由 Task 4 接入；此处先标记
                self._workflow_stage = "awaiting_question"
            else:
                self._workflow_stage = self._next_stage_after("admission", self._workflow_task_type)
            self._workflow_stages_done.append("admission")

    def _next_stage_after(self, stage_id: str, task_type: str | None) -> str:
        """按任务类型路径返回下一个内容阶段；rule 阶段由代码推进后调用。"""
        rules = self._workflow_rules
        if rules is None:
            return "content"
        path = rules.graph.task_type_edges.get(task_type or "", [])
        # 阶段名映射：step_id → 内部阶段名
        mapping = {
            "0": "classify", "0.5": "admission", "1": "recap", "1.1": "version",
            "1.5": "chain", "1.6": "chain", "1.7": "chain",
            "3": "research", "5": "strategy", "6": "creative", "7": "execution",
            "8": "redline",
        }
        if not path:
            return "done"
        next_id = path[min(path.index(stage_id) + 1, len(path) - 1)] if stage_id in path else path[0]
        return mapping.get(next_id, "content")
```

**3d.** `_build_messages`（loop.py ~959）签名加 `stage_context: str | None = None`，user_prompt 注入：

```python
            f"当前工作流阶段：{stage_context or '自由执行'}\n"
```

**3e.** 主循环两处 `_build_messages` 调用（~1379、~1390）传：

```python
                    stage_context=self._workflow_stage,
```

**3f.** 主循环 finish 分支（`_persist_successful_completion` 前，~1481 区域）记录蓝图版本：

```python
            if self._workflow_rules is not None:
                run.result = run.result or {}
                run.result["blueprint_sha256"] = self._workflow_rules.sha256
```

**3g.** redline 阶段校验（finish 前）：`self._workflow_rules.red_lines` 非空且阶段=redline 时，校验已生成的 answer 不含红线违规词（"待补充/待确认/待检索/初稿"等——复用 plan_structure.has_placeholder_words）——若违规在 finish 的 `_enforce_save_intent` 之后追加检查（保持轻量：仅提示，不拦截——write_file 校验已兜底）。此步骤**只做记录**：`self._workflow_stages_done.append("redline")`，不阻塞。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py -q
```
Expected: PASS（含新测试）

- [ ] **Step 5: Regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py tests/test_agent_tools.py tests/test_agent_worker.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: blueprint stage machine in agent main loop"
```

---

### Task 4: 追问挂起/恢复（DB 迁移 + API + worker + 前端）

**Files:**
- Create: `backend/alembic/versions/<generated>_add_pending_questions.py`
- Modify: `backend/app/models/agent.py`
- Modify: `backend/app/repositories/agent_repository.py`
- Modify: `backend/app/services/agent/loop.py`（追问挂起/恢复逻辑）
- Modify: `backend/app/services/agent/worker.py`
- Modify: `backend/app/api/agent.py`
- Modify: `backend/app/schemas/agent.py`
- Test: `backend/tests/test_agent_loop.py`、`backend/tests/test_agent_api.py`
- Modify: `frontend/src/lib/agent-api.ts`（answer 端点 + 类型）
- Modify: `frontend/src/components/agent/chat-composer.tsx`（或追问卡片组件，先读会话页确定挂载点）
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`（追问卡片渲染 + 提交）
- Test: `frontend/src/lib/agent-api.test.ts`

**Interfaces:**
- Consumes: Task 3 的 `self._workflow_stage` / admission 判定
- Produces:
  - `AgentRun.pending_questions: Mapped[list | None]`（JSON 列）
  - run status 枚举含 `awaiting_question`
  - `POST /api/agent/runs/{run_id}/answer`（body: `{answers: dict[str, str]}`）→ 回答合并 → run 状态 `queued` → worker 重新拾取
  - worker `claim_next_attempt` 支持 `awaiting_question` → `queued` 后的 run（run 状态 queued 即可，现有 claim 逻辑已含 queued——只需 answer 端点把 run 从 awaiting_question 改为 queued）
  - 前端追问卡片（问题列表 + 回答框 + 提交 → answer API）

- [ ] **Step 1: Write the failing tests**（后端 test_agent_loop.py + test_agent_api.py；前端 agent-api.test.ts）

```python
# test_agent_api.py
@pytest.mark.anyio
async def test_answer_pending_questions_resumes_run(client, ...):
    # 构造: run 处于 awaiting_question 且 pending_questions 非空
    # POST /runs/{id}/answer {"answers": {"预算": "50万"}}
    # 断言: 200；run 状态回 queued；result 含 answers
```

```python
# test_agent_loop.py
@pytest.mark.anyio
async def test_admission_questioning_hangs_run(..., ...):
    # 构造: rules mock 准入=先追问
    # 断言: run 状态 awaiting_question；pending_questions ≤5 条
```

```ts
// agent-api.test.ts
it("answers pending questions and resumes the run", async () => {
  // POST /agent/runs/{id}/answer body {answers: {...}}
  // 断言请求路径与 body
});
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_api.py tests/test_agent_loop.py -q
cd C:\01_agent_loop_pro\frontend
npx vitest run src/lib/agent-api.test.ts
```
Expected: FAIL（无端点/无状态）

- [ ] **Step 3: Implement**

**3a.** alembic 迁移（`backend/alembic/versions/xxxx_add_pending_questions.py`）：

```python
def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("pending_questions", sa.JSON(), nullable=True))
    op.drop_constraint("ck_agent_runs_status", "agent_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_runs_status",
        "agent_runs",
        "status IN ('queued','running','retry_wait','awaiting_question','succeeded','failed','cancel_requested','cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_runs_status", "agent_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_runs_status",
        "agent_runs",
        "status IN ('queued','running','retry_wait','succeeded','failed','cancel_requested','cancelled')",
    )
    op.drop_column("agent_runs", "pending_questions")
```

先读最新 alembic head（`Get-ChildItem backend\alembic\versions | sort LastWriteTime | select -last 1`）用 `alembic revision --autogenerate -m "add pending questions"` 或手动指定 down_revision=head。**注意 80072d92 merge head**——确认当前 head 后接。

**3b.** `backend/app/models/agent.py` AgentRun 加列 + 状态枚举更新（CheckConstraint 与迁移一致）。

**3c.** `backend/app/repositories/agent_repository.py`：

```python
    async def mark_run_awaiting_question(
        self, run: AgentRun, questions: list[dict[str, str]]
    ) -> None:
        run.pending_questions = questions
        run.status = "awaiting_question"
        run.updated_at = datetime.now(UTC)

    async def resume_run_from_answer(self, run: AgentRun, answers: dict[str, str]) -> None:
        run.pending_questions = None
        run.result = {**(run.result or {}), "answers": answers, "resumed_after_question": True}
        run.status = "queued"
        run.updated_at = datetime.now(UTC)
```

**3d.** `backend/app/services/agent/loop.py` 追问挂起（admission 分支替换 Task 3 的占位）：

```python
        elif stage == "admission":
            rule = admission_judgment(run.goal, files_read_ok=True, missing_constraints=[])
            self._workflow_admission = rule.branch
            if rule.branch == "先追问":
                questions = self._build_questions(run.goal)  # ≤5 问，从蓝图 Step 2 优先级提取
                await repo.mark_run_awaiting_question(run, questions)
                await self._persist_and_notify(
                    repo, ctx, "run_awaiting_question",
                    {"questions": questions},
                )
                self._workflow_stage = "awaiting_question"
                raise _QuestionHangSignal()
            ...
```

```python
    def _build_questions(self, goal: str) -> list[dict[str, str]]:
        """从蓝图 Step 2 追问优先级生成 ≤5 问。"""
        base = [
            {"question": "本次方案的预算级别是多少？", "affects": "达人矩阵、投流强度和执行规模"},
            {"question": "方案的时间周期是多久？", "affects": "节奏、节点和优先级"},
            {"question": "本次要达成的核心目标是什么（声量/心智/转化）？", "affects": "打法完全不同"},
            {"question": "有没有必讲信息或禁区（卖点/合规边界/竞品禁提）？", "affects": "交付边界与合规"},
            {"question": "成功指标是什么？", "affects": "方案收尾方向"},
        ]
        return base[:5]
```

- `_QuestionHangSignal`：内部异常类，被主循环 `except` 捕获 → 正常结束 attempt（run 保留 awaiting_question，不失败）。**实现**：在 `_do_process_attempt` 的循环外层 try/except 捕获，`return` 正常返回（attempt 状态改为 paused/queued？——更简单：attempt 保持 running 直到 answer 恢复时重新 claim？不行——attempt 生命周期与 run 分离，worker 已占用。**设计**：挂起时 attempt 标记 `paused`（新状态）或直接 `succeeded`？**推荐**：attempt 直接标 `paused` 状态（SQLAlchemy 枚举加 paused），answer 恢复时新建 attempt（attempt_number+1）继续。看现有 attempt 状态机（queued/running/retry_wait/succeeded/failed）——加 `paused` 状态枚举（迁移里 agent_run_attempts 的 CheckConstraint 也需更新）。**

**3e.** `backend/app/services/agent/worker.py`：`claim_next_attempt` 的 run 状态过滤加 `queued`（已有）；恢复时 `_process_attempt_with_renewal` 正常处理新 attempt。**无改动**（answer 端点把 run 置 queued 且新建 attempt 即可被现有 claim 拾取）——验证 claim_next_attempt 的 run 过滤 `["queued", "retry_wait"]` 已覆盖。

**3f.** `backend/app/api/agent.py` 新端点：

```python
@router.post("/runs/{run_id}/answer", status_code=200)
async def answer_pending_questions(
    run_id: uuid.UUID,
    body: AgentRunAnswerRequest,
    request: Request,
    repo: Annotated[AgentRepository, Depends(get_repo)],
):
    run = await repo.session.get(AgentRun, run_id)
    if run is None or run.status != "awaiting_question" or not run.pending_questions:
        raise HTTPException(status_code=404, detail="run_not_awaiting_question")
    # 新建 attempt 继续
    ...
    await repo.resume_run_from_answer(run, body.answers)
    await repo.create_resume_attempt(run)
    await repo.commit()
    publish_event("run_resumed", ...)
    return {"status": "queued"}
```

**3g.** `backend/app/schemas/agent.py`：

```python
class AgentRunAnswerRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
```

**3h.** 前端 `frontend/src/lib/agent-api.ts`：

```ts
export async function answerPendingQuestions(runId: string, answers: Record<string, string>): Promise<void> {
  await apiFetch(`/api/agent/runs/${runId}/answer`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });
}
```

**3i.** 前端追问卡片：先读 `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx` 确认 run 状态渲染位置，加追问卡片组件（问题列表 + textarea + 提交 → answerPendingQuestions → 刷新）。**简单实现**：新组件 `frontend/src/components/agent/question-card.tsx`，在 run 状态为 `awaiting_question` 时渲染。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_api.py tests/test_agent_loop.py -q
cd C:\01_agent_loop_pro\frontend
npx vitest run src/lib/agent-api.test.ts
```
Expected: PASS

- [ ] **Step 5: Regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py tests/test_agent_api.py tests/test_agent_tools.py tests/test_agent_repository.py -q
cd C:\01_agent_loop_pro\frontend
npx vitest run
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根；分 2 个 commit：后端迁移+逻辑、前端卡片）

```bash
git add backend/alembic/versions/ backend/app/models/agent.py backend/app/repositories/agent_repository.py backend/app/services/agent/loop.py backend/app/services/agent/worker.py backend/app/api/agent.py backend/app/schemas/agent.py backend/tests/test_agent_api.py backend/tests/test_agent_loop.py
git commit -m "feat: pending-question hang and answer-resume lifecycle for agent runs"
git add frontend/src/lib/agent-api.ts frontend/src/lib/agent-api.test.ts frontend/src/components/agent/question-card.tsx "frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx"
git commit -m "feat: question card UI for awaiting-question runs"
```

---

### Task 5: 集成验证

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: 迁移 head 检查**（新迁移是否单头）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m alembic heads
```
Expected: 单 head（新迁移）

- [ ] **Step 2: 后端全量**（仅一个 pytest 进程；先 `Get-Process python -ErrorAction SilentlyContinue`）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/ -q
```
Expected: 777+ passed（零失败；删除的蒸馏测试不计）

- [ ] **Step 3: 前端全量**

```
cd C:\01_agent_loop_pro\frontend
npx vitest run
```
Expected: 全绿（既存失败除外——与本计划无关的既存失败保持原样）

- [ ] **Step 4: 冒烟 — 蓝图规则解析真实蓝图**（直连验证）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import asyncio, sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); from app.services.agent.workflow_rules import workflow_rules_cache; import pathlib; t = pathlib.Path(r'C:\01_agent_loop_pro\backend\var\files\4c40bada-b2e6-45ea-b1b2-a2e43e663072\965ffc405ba740ea9f8772db166d2c55').read_text(encoding='utf-8'); r = workflow_rules_cache.get(t); print('types:', len(r.task_types)); print('steps:', len(r.graph.steps)); print('redlines:', len(r.red_lines)); print('structure:', len(r.structure)); print('edge 完整方案:', r.graph.task_type_edges.get('完整方案需求'))"
```
Expected: types=8, steps≥15, redlines≥15, structure=8, edge 完整方案含 0..8

- [ ] **Step 5: 冒烟 — 方案类任务注入蓝图全文**（直连验证 get_instruction）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import asyncio, sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); from app.services.agent.workflow_policy import workflow_policy; from app.db.session import async_session_factory; async def m():
    async with async_session_factory() as s:
        ins = await workflow_policy.get_instruction(s, '读取 brief_test.md 写一份创意建议的方案，保存到 brief/文件夹中')
        print('len:', len(ins)); print('has blueprint full:', '脑壳儿_Agent运行蓝图' in ins); print('has Step 8:', '风险校验' in ins)
import asyncio; asyncio.run(m())"
```
Expected: len 大（≥15000）、含蓝图标记与 Step 8

- [ ] **Step 6: Report** — 无提交；回报用户：迁移头、后端测试数、前端测试数、两个冒烟输出
