"""生成知识库分配报告：每篇素材 → 归属库 → 命中规则。

用法（在 backend 目录下运行）：
    python -m scripts.rag_library_report
输出：docs/rag-eval/library-assignment.md
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "var" / "kb_industry" / "manifest" / "manifest.json"
OUTPUT = REPO_ROOT / "docs" / "rag-eval" / "library-assignment.md"


@dataclass(frozen=True)
class ReportRow:
    title: str
    library_name: str
    matched_rule: str


def build_report(items: list[dict]) -> list[ReportRow]:
    from app.services.rag.library_routing import LIBRARY_SEEDS, route_library

    order = {seed.name: index for index, seed in enumerate(LIBRARY_SEEDS)}
    rows = []
    for item in items:
        route = route_library(item)
        rows.append(
            ReportRow(
                title=str(item.get("title") or ""),
                library_name=route.library_name,
                matched_rule=route.matched_rule,
            )
        )
    rows.sort(key=lambda row: (order.get(row.library_name, 99), row.title))
    return rows


def render_markdown(rows: list[ReportRow]) -> str:
    lines = [
        "# 知识库分配报告",
        "",
        "由 `backend/scripts/rag_library_report.py` 生成，规则见 "
        "`docs/superpowers/specs/2026-09-17-knowledge-library-split-design.md` §5。",
        "",
        f"共 {len(rows)} 篇。",
        "",
        "| 篇名 | 归属库 | 命中规则 |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        title = row.title.replace("|", "\\|")
        lines.append(f"| {title} | {row.library_name} | `{row.matched_rule}` |")
    lines.append("")
    return "\n".join(lines)


async def _print_stats() -> None:
    from sqlalchemy import text

    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT l.name, count(d.id), coalesce(sum(d.chunk_count), 0)"
                    " FROM rag_libraries l"
                    " LEFT JOIN rag_documents d ON d.library_id = l.id AND d.status = 'ready'"
                    " GROUP BY l.name ORDER BY count(d.id) DESC"
                )
            )
        ).all()
        statuses = (
            await session.execute(
                text("SELECT status, count(*) FROM rag_documents GROUP BY status")
            )
        ).all()
    print("[统计] 各库就绪文档/块数：")
    for name, docs, chunks in rows:
        print(f"  {name}: {docs} 篇 / {chunks} 块")
    print("[统计] 文档状态分布：")
    for status, count in statuses:
        print(f"  {status}: {count}")


def main() -> int:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="生成知识库分配报告 / 打印分库统计")
    parser.add_argument("--stats", action="store_true", help="只打印数据库中各库统计，不写报告")
    args = parser.parse_args()
    if args.stats:
        asyncio.run(_print_stats())
        return 0

    from app.services.rag.ingest import load_manifest_items

    rows = build_report(load_manifest_items(MANIFEST))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_markdown(rows), encoding="utf-8")
    print(f"[报告] {len(rows)} 篇 → {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
