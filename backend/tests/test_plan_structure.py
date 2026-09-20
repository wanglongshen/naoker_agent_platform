from app.services.agent.plan_structure import is_plan_like_content, validate_plan_structure


class TestPlanLike:
    def test_plan_keywords_detected(self):
        assert is_plan_like_content("GAP 2026 创意建议（初稿）") is True
        assert is_plan_like_content("Brief Recap 一、品牌背景") is True
        assert is_plan_like_content("2026 秋季 Campaign 方案") is True
        assert is_plan_like_content("策划提案 v1") is True

    def test_non_plan_content_exempt(self):
        assert is_plan_like_content("今天的会议记录：讨论了预算") is False
        assert is_plan_like_content("待办清单\n- 买牛奶") is False


class TestValidatePlanStructure:
    def test_full_8_modules_pass(self):
        content = (
            "# 方案\n\n"
            "## 一、Brief Recap\n\n"
            "## 二、前策调研\n\n"
            "## 三、本品表现\n\n"
            "## 四、用户分析\n\n"
            "## 五、创意与传播规划\n\n"
            "## 六、投流策略\n\n"
            "## 七、Roadmap\n\n"
            "## 八、附录\n\n"
        )
        assert validate_plan_structure(content) == []

    def test_missing_modules_reported(self):
        content = (
            "# 创意建议（初稿）\n\n"
            "## 一、Brief Recap\n\n"
            "## 二、创意方向\n\n"
            "## 三、线上内容与玩法\n\n"
        )
        missing = validate_plan_structure(content)
        assert "前策调研" in missing
        assert "投流策略" in missing
        assert "Roadmap" in missing or "执行节奏" in missing

    def test_english_variant_recognized(self):
        content = (
            "# 方案\n\n"
            "## Brief Recap\n\n"
            "## Research 调研\n\n"
            "## 用户分析\n\n"
            "## 创意传播\n\n"
            "## Media 投放\n\n"
            "## Roadmap\n\n"
            "## 本品表现\n\n"
            "## 附录\n\n"
        )
        assert validate_plan_structure(content) == []

    def test_partial_modules_rejected_by_threshold(self):
        content = (
            "# 方案\n\n"
            "## 一、Brief Recap\n\n"
            "## 二、创意主题\n\n"
            "## 三、内容玩法\n\n"
        )
        assert len(validate_plan_structure(content)) >= 3


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

    def test_numbered_list_stops_at_sequence_break(self):
        doc = (
            "## 2. 正式结构\n\n"
            "1. 目标回顾\n"
            "2. 市场与友商调研\n"
            "3. 社媒平台生态概览\n"
            "4. 品牌资产与账号机会梳理\n"
            "5. 矩阵账号策略总纲\n"
            "6. 品牌官号内容策划\n"
            "7. 创始人 IP 号内容策划\n"
            "8. 投流与增长规划\n"
            "9. 3 个月 Roadmap 与交付保障\n\n"
            "## 3. 内部检查清单\n\n"
            "1. 是否拆了 3-4 个具体友商\n"
            "2. 是否说明平台角色\n"
        )
        modules = parse_structure_from_doc(doc)
        assert modules == ["目标回顾", "市场与友商调研", "社媒平台生态概览",
                           "品牌资产与账号机会梳理", "矩阵账号策略总纲", "品牌官号内容策划",
                           "创始人 IP 号内容策划", "投流与增长规划", "3 个月 Roadmap 与交付保障"]

    def test_table_only_collects_module_table(self):
        doc = (
            "| 模块 | 必须回答的问题 | 必须形成的输出 |\n"
            "| --- | --- | --- |\n"
            "| Brief Recap | 为什么做 | 核心任务 |\n"
            "| 市场与赛道 | 品类变化 | 品类机会 |\n"
            "| 竞品 | 谁占据心智 | 心智地图 |\n"
            "| 用户 | 谁值得争取 | 人群分层 |\n"
            "| 产品卖点 | 哪些点解决 | 卖点转译 |\n"
            "| 平台 | 平台任务 | 平台角色 |\n"
            "| 策略与创意 | 什么主张 | 核心策略 |\n"
            "| 内容与达人 | 谁来讲 | 内容支柱 |\n"
            "| 投流 | 如何放大 | 阶段预算 |\n"
            "| Roadmap | 如何推进 | 节点联动 |\n\n"
            "## 竞品分析表\n\n"
            "| 竞品 | 价格带 | 核心心智 |\n"
            "| --- | --- | --- |\n"
            "| 品牌A | 中端 | 基础款 |\n"
            "| 品牌B | 高端 | 生活方式 |\n\n"
            "## 人群映射表\n\n"
            "| 核心人群 | 场景 | 痛点 |\n"
            "| --- | --- | --- |\n"
            "| 年轻女性 | 通勤 | 搭配难 |\n"
        )
        modules = parse_structure_from_doc(doc)
        assert modules == ["Brief Recap", "市场与赛道", "竞品", "用户", "产品卖点",
                           "平台", "策略与创意", "内容与达人", "投流", "Roadmap"]


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

    def test_non_structure_docs_not_routed(self):
        assert resolve_structure_doc("请对方案进行评分") is None
        assert resolve_structure_doc("做一下竞品调研") is None


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


from app.services.agent.plan_structure import extract_blueprint_guides, extract_doc_guides


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


from app.services.agent.plan_structure import parse_subitems, validate_plan_subitems


def test_parse_subitems_splits_on_commas():
    items = parse_subitems("阶段、预算比例、投放形式、关键词、人群包、效果口径")
    assert items == ["阶段", "预算比例", "投放形式", "关键词", "人群包", "效果口径"]


def test_parse_subitems_filters_long_phrases():
    items = parse_subitems("阶段、预算比例、需结合品牌资产与目标人群综合判断投放节奏")
    assert items == ["阶段", "预算比例"]  # 长句被过滤


def test_parse_subitems_strips_trailing_punctuation():
    items = parse_subitems("阶段、预算比例、投放形式、关键词、人群包、效果口径。")
    assert items == ["阶段", "预算比例", "投放形式", "关键词", "人群包", "效果口径"]  # 尾部句号去除


def test_validate_subitems_last_item_with_period_matches():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径。"}
    content = "## 六、投流策略\n- 阶段：预热期\n- 预算比例：40/40/20\n- 投放形式：信息流\n- 关键词：成毅同款\n- 人群包：粉丝人群\n- 效果口径：曝光互动转化"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert missing == {}


def test_validate_subitems_all_present():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}
    content = "## 六、投流策略\n- 阶段：预热期\n- 预算比例：40/40/20\n- 投放形式：信息流\n- 关键词：成毅同款\n- 人群包：粉丝人群\n- 效果口径：曝光互动转化"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert missing == {}


def test_validate_subitems_missing_two():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}
    content = "## 六、投流策略\n- 阶段：预热期\n- 预算比例：40/40/20"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert "投流策略" in missing
    assert "投放形式" in missing["投流策略"]  # 缺 ≥2：投放形式/关键词/人群包/效果口径


def test_validate_subitems_missing_one_tolerated():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}
    content = "## 六、投流策略\n- 阶段：预热期\n- 预算比例：40/40/20\n- 投放形式：信息流\n- 关键词：成毅同款\n- 人群包：粉丝人群"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert missing == {}  # 只缺 1 个（效果口径）→ 容忍


def test_validate_subitems_alias_tolerated():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}
    content = "## 六、投流策略\n- 阶段：预热期\n- 预算分配：40/40/20\n- 投放形式：信息流\n- 关键词：成毅同款\n- 人群包：粉丝人群\n- 效果指标：曝光互动转化"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert missing == {}  # 预算分配→预算比例、效果指标→效果口径（别名）


def test_validate_subitems_empty_guides_skipped():
    missing = validate_plan_subitems("随便什么内容", ["投流策略"], None)
    assert missing == {}


def test_validate_subitems_no_headers_not_checked():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}
    content = "普通笔记，没有方案结构"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert missing == {}  # 模块标题不存在 → 子项不查（结构校验已兜底）


class TestValidatePlanContentDepth:
    def test_empty_section_after_heading_is_shallow(self):
        from app.services.agent.plan_structure import validate_plan_content_depth

        content = "# 方案\n\n## 一、Brief Recap\n\n## 二、市场调研\n\n内容在这里"
        assert validate_plan_content_depth(content, ["Brief Recap", "市场调研"]) == ["Brief Recap"]

    def test_section_with_body_passes(self):
        from app.services.agent.plan_structure import validate_plan_content_depth

        content = "# 方案\n\n## 一、Brief Recap\n\n复述背景与推广主体。\n\n## 二、市场调研\n\n竞品拆解。"
        assert validate_plan_content_depth(content, ["Brief Recap", "市场调研"]) == []

    def test_title_only_skeleton_flagged(self):
        from app.services.agent.plan_structure import validate_plan_content_depth

        content = "# 方案\n\n## 一、目标回顾\n\n\n## 二、投流策略\n\n"
        assert validate_plan_content_depth(content, ["目标回顾", "投流策略"]) == ["目标回顾", "投流策略"]

    def test_alias_heading_with_body_not_shallow(self):
        from app.services.agent.plan_structure import validate_plan_content_depth

        content = (
            "# 方案\n\n"
            "## 一、目标回顾\n\n复述背景与推广主体。\n\n"
            "## 二、前策调研\n\n竞品拆解与行业现状梳理，含平台趋势。"
        )
        assert validate_plan_content_depth(content, ["目标回顾", "前策调研与思考"]) == []
