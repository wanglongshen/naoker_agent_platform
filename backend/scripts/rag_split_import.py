"""把采集素材按归类器分派到 8 个专业库。

用法（在 backend 目录下运行）：
    python -m scripts.rag_split_import --scope all --dry-run
    python -m scripts.rag_split_import --scope all
    python -m scripts.rag_split_import --scope core --category methodology

说明：真正的入库由 rag_ingest_worker 消费本命令创建的路由导入任务完成，
进度可在「知识库管理 → 库详情 → 数据集」查看；重复执行按 sha256 幂等。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KB_ROOT = REPO_ROOT / "var" / "kb_industry"
MANIFESTS = {
    "all": KB_ROOT / "manifest" / "manifest.json",
    "core": KB_ROOT / "manifest" / "manifest-core.json",
}
MARKDOWN_ROOT = KB_ROOT / "markdown"


def _load_items(scope: str, category: str | None, limit: int | None) -> list[dict]:
    from app.services.rag.ingest import filter_manifest_items, load_manifest_items

    manifest = MANIFESTS[scope]
    if not manifest.exists():
        raise SystemExit(f"[错误] 素材清单不存在：{manifest}")
    items = filter_manifest_items(load_manifest_items(manifest), category)
    if limit is not None:
        items = items[: max(limit, 0)]
    return items


def _print_distribution(items: list[dict]) -> None:
    from app.services.rag.library_routing import route_library

    counter: Counter[str] = Counter()
    for item in items:
        route = route_library(item)
        counter[f"{route.library_name}（{route.slug}）"] += 1
    print(f"[路由] 素材 {len(items)} 篇：")
    for name, count in counter.most_common():
        print(f"  {name}: {count} 篇")


async def _create_job(items: list[dict], scope: str, category: str | None) -> str:
    from app.db.session import async_session_factory
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.library_routing import SLUG_TO_SEED

    async with async_session_factory() as session:
        repo = RagRepository(session)
        library = await repo.get_library(SLUG_TO_SEED["general"].id)
        if library is None:
            raise SystemExit("[错误] 「课程与通用」库不存在，请先执行 alembic upgrade head")
        job = await repo.create_job(
            library_id=library.id,
            kind="import",
            status="queued",
            total=len(items),
            payload={
                "scope": scope,
                "category": category,
                "routed": True,
                "markdown_root": str(MARKDOWN_ROOT),
                "items": items,
            },
            created_by=None,
        )
        return str(job.id)


def main() -> int:
    parser = argparse.ArgumentParser(description="按归类器分派采集素材到 8 个专业库")
    parser.add_argument("--scope", choices=sorted(MANIFESTS), default="all")
    parser.add_argument("--category", default=None, choices=[None, "methodology", "rules", "other"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="只打印路由分布，不创建任务")
    args = parser.parse_args()

    items = _load_items(args.scope, args.category, args.limit)
    if not items:
        print("[错误] 没有符合条件的素材")
        return 1
    _print_distribution(items)
    if args.dry_run:
        print("[干跑] 未创建任务")
        return 0

    job_id = asyncio.run(_create_job(items, args.scope, args.category))
    print(f"[任务] 已创建路由导入任务 job_id={job_id}（共 {len(items)} 篇，由 rag_ingest_worker 消费）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
