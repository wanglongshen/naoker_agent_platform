from app.services.agent.workflow_rules import (
    classify_task_type,
    parse_admission_rules,
    parse_red_lines,
    parse_task_types,
    parse_version_rule,
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


def test_classify_xiaohongshu_plan_goal():
    types = parse_task_types(BLUEPRINT)
    rule = classify_task_type("写一份小红书种草方案", types)
    assert rule.type_name == "小红书种草方案"


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
    assert resolve_capability("$agent-reach") == "fetch_platform_search"
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


def test_parse_version_rule_from_blueprint():
    rule = parse_version_rule(BLUEPRINT)
    assert rule.search("brief/GAP_V1_创意建议.md") is not None
    assert rule.search("brief/创意建议方案.md") is None
    assert rule.search("brief/GAP_2026秋季_V2_方案.md") is not None


def test_parse_version_rule_fallback():
    rule = parse_version_rule("### Step 1.1：版本判断\n没有版本规则描述")
    assert rule.search("brief/创意建议方案.md") is None
    assert rule.search("brief/GAP_V1_创意建议.md") is not None


def test_parse_version_rule_missing_section():
    rule = parse_version_rule("### Step 2：缺口追问\n没有版本节")
    assert rule.search("brief/xxx_V1.md") is not None


def test_capability_map_routes_agent_reach_to_platform_search():
    from app.services.agent.workflow_rules import _CAPABILITY_MAP

    assert _CAPABILITY_MAP["$agent-reach"] == "fetch_platform_search"
    assert _CAPABILITY_MAP["agent-reach"] == "fetch_platform_search"


def test_detect_missing_constraints_flags_plan_goal_gaps():
    from app.services.agent.workflow_rules import detect_missing_constraints

    missing = detect_missing_constraints("帮我写一份新品上市方案")
    assert len(missing) >= 2
    assert "预算" in missing
    assert "时间周期" in missing


def test_detect_missing_constraints_complete_goal_below_ask_threshold():
    from app.services.agent.workflow_rules import detect_missing_constraints

    missing = detect_missing_constraints("预算 50 万、周期 3 个月、目标 GMV 1000 万")
    assert len(missing) < 2


def test_detect_missing_constraints_is_exemption_agnostic():
    """豁免语判断只在调用方（loop），纯函数对任何文本都按约束关键词判定。"""
    from app.services.agent.workflow_rules import detect_missing_constraints

    missing = detect_missing_constraints("基于已有资料直接产出，不用问")
    assert len(missing) == 5
