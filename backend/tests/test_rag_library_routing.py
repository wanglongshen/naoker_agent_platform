import json
from pathlib import Path

from app.services.rag.library_routing import (
    FALLBACK_SLUG,
    LIBRARY_SEEDS,
    route_library,
)

MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "var"
    / "kb_industry"
    / "manifest"
    / "manifest.json"
)

EXPECTED_DISTRIBUTION = {
    "qianchuan": 80,
    "live": 21,
    "short-video": 25,
    "mall": 37,
    "influencer": 65,
    "industry-case": 57,
    "platform-rules": 254,
    "general": 62,
}


def test_eight_libraries_with_unique_ids_and_names():
    assert len(LIBRARY_SEEDS) == 8
    assert len({seed.id for seed in LIBRARY_SEEDS}) == 8
    assert len({seed.name for seed in LIBRARY_SEEDS}) == 8


def test_rules_category_goes_to_platform_rules():
    item = {"title": "商家申诉举证标准", "tags": ["规则解读"]}
    assert route_library(item).slug == "platform-rules"


def test_industry_case_tag_wins_over_business_tags():
    item = {
        "title": "差异化选品提升竞争力，短视频+直播助推618生意突围",
        "tags": ["案例-直播运营", "案例-短视频运营", "案例-商城运营", "案例-生鲜"],
    }
    assert route_library(item).slug == "industry-case"


def test_business_tag_priority_qianchuan_before_live():
    item = {"title": "直播间运营白皮书", "tags": ["商品推广(千川)", "直播间运营"]}
    assert route_library(item).slug == "qianchuan"


def test_title_fallback_when_no_tag_matches():
    item = {"title": "巨量千川直播全域投放使用宝典", "tags": []}
    result = route_library(item)
    assert result.slug == "qianchuan"
    assert result.matched_rule.startswith("title:")


def test_doudian_title_keyword_routes_to_mall():
    item = {"title": "服务商抖店服务市场入驻与合作指南", "tags": ["头部作者"]}
    result = route_library(item)
    assert result.slug == "mall"
    assert result.matched_rule.startswith("title:")


def test_unknown_item_falls_back_to_general():
    item = {"title": "2022新版创作者口碑分解读-合集", "tags": []}
    result = route_library(item)
    assert result.slug == FALLBACK_SLUG
    assert result.matched_rule == "fallback"


def test_all_601_manifest_items_routed_with_expected_distribution():
    items = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))["items"]
    assert len(items) == 601
    distribution: dict[str, int] = {}
    for item in items:
        slug = route_library(item).slug
        distribution[slug] = distribution.get(slug, 0) + 1
    assert distribution == EXPECTED_DISTRIBUTION
