from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel


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
    "小红书种草方案": ["小红书", "新品种草", "达人种草", "红书投放", "种草方案"],
    "矩阵号代运营方案": ["矩阵号", "代运营", "年度运营", "品牌官号", "创始人", "多平台账号"],
    "修改/扩写需求": ["修改", "优化", "扩写", "重出", "再出一版", "调整"],
}

_RULE_STEP_IDS = {"0", "0.5", "1.1", "8"}  # 表格/清单 → 代码执行
_CONTENT_STEP_IDS = {"1", "3", "3.1", "4", "5", "6", "7"}

_CAPABILITY_MAP = {
    "$agent-reach": "fetch_platform_search",
    "agent-reach": "fetch_platform_search",
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
    step_re = re.compile(r"^### Step ([\d.]+)[：:]\s*(.+)$", re.M)
    matches = list(step_re.finditer(blueprint_text))
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


# 方案类目标的五类关键约束（A1）：规则表为常量便于审计；判定只看关键词是否出现。
_CRITICAL_CONSTRAINT_PATTERNS: dict[str, tuple[str, ...]] = {
    "预算": ("预算", "费用", "投入", "roi 目标", "万元", "元/天"),
    "时间周期": ("周期", "时间", "排期", "上线时间", "个月", "周内", "天内"),
    "核心目标": ("目标", "要达成", "提升", "增长", "转化率目标"),
    "必讲信息": ("必须包含", "必讲", "卖点", "必须提及"),
    "成功指标": ("指标", "kpi", "gmv", "考核", "达标", "验收标准"),
}


def detect_missing_constraints(goal: str) -> list[str]:
    """返回目标文本中缺失的关键约束名（纯函数：不做豁免/方案类判断，由调用方决定）。"""
    text = (goal or "").lower()
    return [
        name
        for name, keys in _CRITICAL_CONSTRAINT_PATTERNS.items()
        if not any(k in text for k in keys)
    ]


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


def parse_version_rule(blueprint_text: str) -> "re.Pattern[str]":
    """从蓝图 Step 1.1 解析版本号规则；解析失败回退默认 `_V\d+`。"""
    section = _section(blueprint_text, "Step 1.1：版本判断")
    if section and ("V1" in section or "V1.0" in section):
        return re.compile(r"_V\d+")
    return re.compile(r"_V\d+")


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
