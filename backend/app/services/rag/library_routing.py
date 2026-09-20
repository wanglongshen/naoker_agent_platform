"""知识库归类器：素材 → 8 个专业库的确定性路由（唯一事实源）。

规则优先级（spec 2026-09-17-knowledge-library-split-design.md §5）：
1. 规则类素材（classify_manifest_item == "rules"）→ 平台规则
2. 官方标签命中「案例-行业」→ 行业案例
3. 官方标签依次：千川投放 → 直播运营 → 短视频与内容 → 商城与商品卡 → 达人与大促
4. 标签未命中 → 标题关键词按同样顺序
5. 都不命中 → 课程与通用
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.services.rag.ingest import classify_manifest_item


@dataclass(frozen=True)
class LibrarySeed:
    slug: str
    id: uuid.UUID
    name: str
    description: str
    kind: str


LIBRARY_SEEDS: tuple[LibrarySeed, ...] = (
    LibrarySeed(
        "qianchuan",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000101"),
        "千川投放",
        "巨量千川投放、出价、流量获取与搜索运营方法论",
        "industry",
    ),
    LibrarySeed(
        "live",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000102"),
        "直播运营",
        "直播间运营方法与直播经营案例",
        "industry",
    ),
    LibrarySeed(
        "short-video",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000103"),
        "短视频与内容",
        "短视频/图文内容运营、素材制作与人设打造",
        "industry",
    ),
    LibrarySeed(
        "mall",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000104"),
        "商城与商品卡",
        "商城、店铺、商品卡与商品优化",
        "industry",
    ),
    LibrarySeed(
        "influencer",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000105"),
        "达人与大促",
        "达人合作、联盟、大促活动与消费者运营",
        "industry",
    ),
    LibrarySeed(
        "industry-case",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000106"),
        "行业案例",
        "分行业商家经营案例（生鲜/个护家清/食品饮料/珠宝文玩/智能家居/美妆/品牌商家）",
        "industry",
    ),
    LibrarySeed(
        "platform-rules",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000107"),
        "平台规则",
        "平台规则、协议、标准、细则与公示通知",
        "rules",
    ),
    LibrarySeed(
        "general",
        uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000108"),
        "课程与通用",
        "经营课程、操作指南与通用经营知识",
        "industry",
    ),
)

SLUG_TO_SEED: dict[str, LibrarySeed] = {seed.slug: seed for seed in LIBRARY_SEEDS}
FALLBACK_SLUG = "general"

TAG_RULES: tuple[tuple[str, str], ...] = (
    (
        "industry-case",
        r"案例-(生鲜|个护家清|食品饮料|珠宝文玩|智能家居|美妆|品牌商家|营销案例)|优秀案例",
    ),
    ("qianchuan", r"商品推广\(千川\)|流量获取|搜索运营|热点搜索优化|千川"),
    ("live", r"案例-直播运营|直播间运营"),
    ("short-video", r"案例-短视频运营|短视频运营|AIGC素材|人设打造|图文"),
    ("mall", r"店铺运营|商品优化|商城运营|案例-商城运营|货品运营|抖店运营"),
    ("influencer", r"案例-大促活动|案例-达人合作|达人合作|达人|消费者运营"),
)

TITLE_RULES: tuple[tuple[str, str], ...] = (
    ("qianchuan", r"千川|投放|出价|竞价|全域|流量|搜索|推广"),
    ("live", r"直播"),
    ("short-video", r"短视频|图文|内容|素材|种草|拍摄|剪辑|人设"),
    ("mall", r"商城|商品卡|店铺|商品|橱窗|货架|抖店"),
    ("influencer", r"达人|联盟|团长|大促|活动|会员|消费者"),
)


@dataclass(frozen=True)
class RouteResult:
    slug: str
    library_id: uuid.UUID
    library_name: str
    matched_rule: str


def _tags_text(item: dict[str, Any]) -> str:
    tags = item.get("tags") or []
    if isinstance(tags, str):
        return tags
    return " ".join(str(tag) for tag in tags)


def _result(slug: str, matched_rule: str) -> RouteResult:
    seed = SLUG_TO_SEED[slug]
    return RouteResult(
        slug=seed.slug,
        library_id=seed.id,
        library_name=seed.name,
        matched_rule=matched_rule,
    )


def route_library(item: dict[str, Any]) -> RouteResult:
    """把一条素材路由到 8 个库之一，并返回命中的规则（可审计）。"""
    title = str(item.get("title") or "")
    tags_text = _tags_text(item)
    if classify_manifest_item(item) == "rules":
        return _result("platform-rules", "category:rules")
    for slug, pattern in TAG_RULES:
        if re.search(pattern, tags_text):
            return _result(slug, f"tag:{pattern.split('|')[0]}")
    for slug, pattern in TITLE_RULES:
        if re.search(pattern, title):
            return _result(slug, f"title:{pattern.split('|')[0]}")
    return _result(FALLBACK_SLUG, "fallback")
