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

# 每个模块的可接受别名（命中任一即算存在）；key 与 DEFAULT_MODULES 及
# 蓝图/矩阵号/UGC 解析出的完整模块名精确匹配，动态模块名不在表中时仅本体匹配。
# 同一模块同时挂「完整名」与「默认短名」两把 key（别名表跟随蓝图完整名，
# DEFAULT_MODULES 仍是短名，两者都需命中）。
_MODULE_ALIASES: dict[str, tuple[str, ...]] = {
    "Brief Recap": ("brief recap", "brief 复述", "brief回述", "brief 概述"),
    "前策调研与思考": ("前策调研", "调研", "前策", "竞品", "行业研究"),
    "前策调研": ("调研", "前策", "竞品", "行业研究"),
    "本品表现与机会下探": ("本品表现", "本品", "品牌表现", "品牌现状", "机会下探"),
    "本品表现": ("本品", "品牌表现", "品牌现状"),
    "用户分析与达人类型": ("用户分析", "目标用户", "人群画像", "用户画像", "达人类型"),
    "用户分析": ("目标用户", "人群画像", "用户画像"),
    "创意与传播规划": ("创意", "传播规划", "创意方向", "传播策略"),
    "投流策略": ("投流", "投放", "media", "kfs", "关键词"),
    "Roadmap": ("roadmap", "road map", "路线图", "执行节奏", "时间表"),
    "附录": ("附录",),
}

# 骨架中每模块的内容指引（静态映射；无映射模块仅输出标题）。
# key 同时覆盖完整模块名与默认短名，保证 build_skeleton 两种来源都能命中。
_SKELETON_GUIDES: dict[str, str] = {
    "前策调研": "竞品必查，不得跳过竞品与平台现状",
    "前策调研与思考": "竞品必查，不得跳过竞品与平台现状",
    "本品表现": "基于 brief 与公开信息，标注估算锚点与边界",
    "本品表现与机会下探": "基于 brief 与公开信息，标注估算锚点与边界",
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


_PLACEHOLDER_WORDS = ("概要", "待补充", "待检索", "待确认", "初稿", "待完善", "待定")


def has_placeholder_words(content: str) -> list[str]:
    """检测内容中的占位/未完成标记词，返回命中列表（空列表=洁净）。"""
    return [word for word in _PLACEHOLDER_WORDS if word in content]


def _hollow_phrase_list(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def _module_heading_pattern(mod: str) -> re.Pattern[str]:
    """模块标题：`## 项目背景` 或骨架风格 `## 一、项目背景`（可带序号前缀）。"""
    return re.compile(
        rf"^#{{1,6}}\s+(?:[一二三四五六七八九十0-9]+[、.])?\s*{re.escape(mod)}\s*$",
        re.MULTILINE,
    )


def quality_check(content: str, modules: list[str], min_chars: int = 200) -> list[str]:
    """确定性内容质检。返回失败项中文描述；空列表 = 通过。"""
    from app.core.config import get_settings
    fails: list[str] = []
    for mod in modules:
        pattern = _module_heading_pattern(mod)
        m = pattern.search(content)
        if m is None:
            continue
        seg_start = m.end()
        nxt = re.search(r"^#{1,6}\s+", content[seg_start:], re.MULTILINE)
        seg_end = seg_start + nxt.start() if nxt is not None else len(content)
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
    # 表格格式：仅收集表头首列为“模块”的表格的数据行首列
    table_modules: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        header_match = _TABLE_ROW_RE.match(lines[i].strip())
        if header_match and header_match.group(1).strip() == "模块":
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                row_match = _TABLE_ROW_RE.match(lines[i].strip())
                if row_match:
                    name = _clean_module_name(row_match.group(1))
                    if name and name != "模块" and "---" not in name:
                        table_modules.append(name)
                i += 1
            break
        i += 1
    if len(table_modules) >= 3:
        return table_modules
    # 编号列表格式：仅收集从 1 开始连续递增的第一段编号列表
    list_modules: list[str] = []
    expect = 1
    collecting = False
    for line in text.splitlines():
        m = _LIST_ITEM_RE.match(line.strip())
        if not m:
            continue
        num = int(m.group(1))
        if not collecting:
            if num != 1:
                continue
            name = _clean_module_name(m.group(2))
            if not name:
                continue
            collecting = True
            list_modules.append(name)
            expect = 2
            continue
        if num != expect:
            break
        name = _clean_module_name(m.group(2))
        if name:
            list_modules.append(name)
        expect += 1
    if len(list_modules) >= 3:
        return list_modules
    return None


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
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
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
        name = m.group(2).split("：")[0].split(":")[0].strip()
        name = _clean_module_name(name)
        if name is None:
            continue
        modules.append(name)
    if len(modules) >= 3:
        return modules
    return None


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


_SECTION_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
_BULLET_MODULE_RE = re.compile(r"^[-*]\s+(.+)$", re.MULTILINE)


def _parse_bullet_modules(text: str) -> list[str] | None:
    """兜底：按 '- xxx' 列表行提取模块清单；不足 3 项返回 None。"""
    modules: list[str] = []
    for m in _BULLET_MODULE_RE.finditer(text):
        name = m.group(1).strip()
        if not name or len(name) > 30:
            continue
        if any(word in name for word in _NON_MODULE_WORDS):
            continue
        if "：" in name or ":" in name:
            continue
        modules.append(name)
    return modules if len(modules) >= 3 else None


def build_plan_summary(blueprint: str, max_chars: int = 500) -> str:
    """从蓝图原文提取结构化摘要：文档标题 + 章节标题 + 模块清单；失败返回空串。

    模块清单解析优先级与校验器同源：先取 '## 3. 正式方案默认结构' 段的编号列表，
    再退化为全文编号列表/摘要编号列表，最后兜底 '- ' 列表行。
    """
    if not blueprint or not blueprint.strip():
        return ""
    lines: list[str] = []
    first_line = blueprint.strip().splitlines()[0].strip()
    if first_line.startswith("#"):
        lines.append(f"蓝图：{first_line.lstrip('#').strip()}")
    modules = (
        parse_default_structure_from_blueprint(blueprint)
        or parse_module_list_from_summary(blueprint)
        or _parse_bullet_modules(blueprint)
    )
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


# 仅这些规范文档作为结构校验来源（白名单）；其余路由文档（评分/调研资料源等）
# 即使被 workflow_route_rules 命中，也不参与结构解析，避免将来误解析错误结构
_STRUCTURE_DOC_HINTS = ("矩阵号代运营", "UGC")


def resolve_structure_doc(goal: str) -> str | None:
    """按 goal 关键词路由到结构校验规范文档路径；无命中返回 None（走蓝图默认）。"""
    from app.core.config import get_settings
    rules = get_settings().workflow_route_rules
    for keywords, path in _parse_route_rules(rules):
        if any(keyword in goal for keyword in keywords):
            if any(hint in path for hint in _STRUCTURE_DOC_HINTS):
                return path
            return None
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


_SUBITEM_ALIASES: dict[str, tuple[str, ...]] = {
    "预算比例": ("预算比例", "预算分配", "预算结构", "预算构成", "预算占比"),
    "效果口径": ("效果口径", "效果预估", "效果指标", "效果评估", "效果衡量", "效果目标"),
    "人群包": ("人群包", "人群定向", "人群策略", "受众定向"),
    "KPI": ("KPI", "指标", "效果数字"),
    "投放形式": ("投放形式", "投放方式", "资源位", "媒介形式"),
    "关键词": ("关键词", "搜索词", "词包"),
}


def parse_subitems(desc: str) -> list[str]:
    """按顿号/逗号切分描述文本为子项清单；超长子项（>12 字符）过滤；去尾部标点。"""
    items: list[str] = []
    for raw in re.split(r"[、,，;；]", desc):
        item = raw.strip().rstrip("。.！？!?；;")
        if not item:
            continue
        if len(item) > 12:
            continue
        items.append(item)
    return items


def validate_plan_subitems(
    content: str,
    modules: list[str],
    guides: dict[str, str] | None,
) -> dict[str, list[str]]:
    """返回 {模块名: [缺失子项]}；每模块缺 ≥2 子项才算缺失；guides 为空跳过。"""
    if not guides:
        return {}
    lowered = content.lower()
    missing_by_module: dict[str, list[str]] = {}
    for name in modules:
        desc = guides.get(name)
        if not desc:
            continue
        if name.lower() not in lowered:
            continue  # 模块标题不存在 → 结构校验已兜底，不查子项
        items = parse_subitems(desc)
        if len(items) < 2:
            continue
        missing: list[str] = []
        for item in items:
            if item.lower() in lowered:
                continue
            aliases = _SUBITEM_ALIASES.get(item, (item,))
            if any(alias.lower() in lowered for alias in aliases):
                continue
            missing.append(item)
        if len(missing) >= 2:
            missing_by_module[name] = missing
    return missing_by_module


_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


def validate_plan_content_depth(content: str, modules: list[str] | None = None) -> list[str]:
    """返回"存在标题但章节正文为空壳"的模块中文名列表；空列表表示内容充实。

    判定：模块标题行到下一个 #/## 标题行之间的正文，必须含 ≥1 行非空内容；
    只有标题没有正文的骨架会被判定为空壳。
    """
    if modules is None:
        modules = DEFAULT_MODULES
    lowered = content.lower()
    shallow: list[str] = []
    for name in modules:
        aliases = _MODULE_ALIASES.get(name, ())
        needles = (name.lower(),) + tuple(a.lower() for a in aliases)
        title_hits = [
            m.start() for needle in needles for m in re.finditer(re.escape(needle), lowered)
        ]
        if not title_hits:
            continue  # 标题不存在 → 结构校验兜底
        # 找到该模块标题行之后、下一个标题之前的正文
        best_body = ""
        for hit in title_hits:
            line_start = lowered.rfind("\n", 0, hit) + 1
            line_end = content.find("\n", line_start)
            if line_end == -1:
                line_end = len(content)
            heading = _HEADING_RE.match(content[line_start:line_end].strip())
            if heading is None:
                continue
            head_len = len(heading.group(0))
            next_heading = re.search(r"^#{1,6}\s+", content[line_start + head_len:], re.MULTILINE)
            end = line_start + head_len + (next_heading.start() if next_heading else len(content) - line_start - head_len)
            body = content[line_start:end]
            body = re.sub(r"^#{1,6}\s+.*$", "", body, flags=re.MULTILINE).strip()
            if len(body) > len(best_body):
                best_body = body
        non_empty_lines = [ln for ln in best_body.splitlines() if ln.strip()]
        if not non_empty_lines:
            shallow.append(name)
    return shallow
