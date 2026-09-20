"""RAG 行业知识库入库 CLI。

用法（在 backend 目录下运行）：
    python -m scripts.rag_ingest --manifest-core --dry-run
    python -m scripts.rag_ingest --manifest-core [--limit N] [--library 行业知识库]
"""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_MANIFEST = REPO_ROOT / "var" / "kb_industry" / "manifest" / "manifest-core.json"
DEFAULT_SOURCE_DIR = REPO_ROOT / "var" / "kb_industry" / "markdown"
DEFAULT_LIBRARY = "行业知识库"


async def _resolve_library(repo, library_ref: str):
    try:
        library_id = uuid.UUID(library_ref)
    except ValueError:
        return await repo.get_library_by_name(library_ref)
    return await repo.get_library(library_id)


async def _run_ingest(
    manifest_path: Path, source_dir: Path, limit: int | None, library_ref: str
):
    from app.db.session import async_session_factory
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.embedding import build_embedding_provider
    from app.services.rag.ingest import ingest_manifest
    from app.services.rag.store import NumpyVectorStore

    provider = build_embedding_provider()
    print(f"[入库] embedding：{type(provider).__name__} dim={provider.dim}")
    async with async_session_factory() as session:
        repo = RagRepository(session)
        library = await _resolve_library(repo, library_ref)
        if library is None:
            print(f"[错误] 知识库不存在：{library_ref}")
            return None
        print(f"[入库] 目标知识库：{library.name}（{library.id}）")
        store = NumpyVectorStore(repo.iter_embeddings)
        return await ingest_manifest(
            repo,
            provider,
            manifest_path,
            library_id=library.id,
            source_dir=source_dir,
            limit=limit,
            store=store,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 行业知识库入库管线")
    parser.add_argument(
        "--manifest-core", action="store_true", help="使用核心集 manifest（226 篇）"
    )
    parser.add_argument("--manifest", type=Path, default=None, help="自定义 manifest 路径")
    parser.add_argument("--limit", type=int, default=None, help="最多处理 N 篇文档")
    parser.add_argument("--dry-run", action="store_true", help="只统计解析/切分结果，不写库")
    parser.add_argument(
        "--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="素材目录"
    )
    parser.add_argument(
        "--library",
        default=DEFAULT_LIBRARY,
        help=f"目标知识库名称或 ID（默认：{DEFAULT_LIBRARY}）",
    )
    args = parser.parse_args()

    if args.manifest is None and not args.manifest_core:
        parser.error("必须指定 --manifest-core 或 --manifest PATH")
    manifest_path = args.manifest or CORE_MANIFEST
    if not manifest_path.exists():
        print(f"[错误] manifest 不存在：{manifest_path}")
        return 1

    started = time.perf_counter()
    if args.dry_run:
        from app.services.rag.ingest import dry_run_manifest

        report = dry_run_manifest(
            manifest_path, source_dir=args.source_dir, limit=args.limit
        )
        elapsed = time.perf_counter() - started
        print(f"[干跑] manifest：{manifest_path}")
        print(
            f"[干跑] 文档：{report.items} 篇（有效 {report.documents}，"
            f"空文本 {report.skipped_empty}，失败 {report.failed}）"
        )
        print(f"[干跑] 正文字符：{report.total_chars}")
        print(f"[干跑] 切分块数：{report.chunks}")
        print(f"[干跑] 耗时：{elapsed:.1f}s")
        for err in report.errors:
            print(f"[干跑][错误] {err}")
        return 1 if report.failed else 0

    report = asyncio.run(
        _run_ingest(manifest_path, args.source_dir, args.limit, args.library)
    )
    if report is None:
        return 1
    elapsed = time.perf_counter() - started
    print(f"[入库] 插入文档：{report.inserted} 篇")
    print(f"[入库] 跳过（已存在）：{report.skipped} 篇")
    print(f"[入库] 跳过（空文本）：{report.skipped_empty} 篇")
    print(f"[入库] 失败：{report.failed} 篇")
    print(f"[入库] 新增块：{report.chunks}")
    print(f"[入库] 耗时：{elapsed:.1f}s")
    for err in report.errors:
        print(f"[入库][错误] {err}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
