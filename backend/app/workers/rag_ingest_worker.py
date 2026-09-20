"""RAG 入库 worker：领取 rag_jobs 并执行解析/切分/向量化。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import signal
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db.session import async_session_factory
from app.models.rag import RagJob
from app.repositories.rag_repository import RagRepository
from app.services.rag.embedding import EmbeddingProvider, build_embedding_provider
from app.services.rag.ingest import EmptyDocumentError, ingest_one
from app.services.rag.library_routing import route_library

logger = logging.getLogger("rag_ingest_worker")

POLL_INTERVAL_SECONDS = 3


async def process_job(job_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        repo = RagRepository(db)
        job = await repo.get_job(job_id)
        if job is None or job.status == "superseded":
            return
        payload = job.payload or {}
        processed = job.processed or 0
        try:
            provider = build_embedding_provider()
            if job.kind == "import":
                await _process_import_job(repo, provider, job, payload, processed)
                return
            doc = await repo.get_document(job.doc_id) if job.doc_id is not None else None
            if doc is not None:
                await repo.set_document_status(doc.id, "processing")
            path = Path(str(payload.get("path"))) if payload.get("path") else None
            await ingest_one(
                repo,
                provider,
                library_id=job.library_id,
                title=str(payload.get("title") or "未命名文档"),
                sha256=str(payload.get("sha256") or uuid.uuid4().hex),
                path=path,
                source_url=payload.get("source_url"),
                publisher=payload.get("publisher"),
                doc_type=str(payload.get("doc_type") or "upload"),
                created_by=job.created_by,
                doc=doc,
            )
            await repo.update_job(
                job.id,
                status="succeeded",
                processed=processed + 1,
                finished_at=datetime.now(UTC),
            )
        except EmptyDocumentError as exc:
            await _fail(repo, job, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("rag_ingest_job_failed job=%s", job_id)
            await _fail(repo, job, str(exc))


async def _process_import_job(
    repo: RagRepository,
    provider: EmbeddingProvider,
    job: RagJob,
    payload: dict[str, Any],
    processed: int,
) -> None:
    items = payload.get("items") or []
    if not items:
        await repo.update_job(
            job.id,
            status="failed",
            error_message="导入任务没有可处理的条目",
            finished_at=datetime.now(UTC),
        )
        return
    markdown_root = Path(str(payload.get("markdown_root") or ""))
    failures = 0
    last_error: str | None = None
    routed = bool(payload.get("routed"))
    for item in items:
        file_name = str(item.get("file") or "")
        try:
            target_library_id = (
                route_library(item).library_id if routed else job.library_id
            )
            path = markdown_root / file_name
            sha256 = str(item.get("sha256") or "").strip()
            if not sha256:
                sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            existing = await repo.get_document_by_sha256(sha256)
            if existing is not None and existing.status == "ready":
                # 已入库且就绪：同库或他库都跳过（内容已在库里）
                processed += 1
                await repo.update_job(job.id, processed=processed, error_message=last_error)
                continue
            if existing is not None and existing.library_id == target_library_id:
                # 同库但未就绪（failed/processing/pending）：复用该文档重新入库，避免被 sha256 卡死
                await ingest_one(
                    repo,
                    provider,
                    library_id=target_library_id,
                    title=str(item.get("title") or file_name or "未命名文档"),
                    sha256=sha256,
                    path=path,
                    publisher=item.get("source_site"),
                    doc_type=str(item.get("category") or "industry_methodology"),
                    created_by=job.created_by,
                    doc=existing,
                )
            elif existing is None:
                await ingest_one(
                    repo,
                    provider,
                    library_id=target_library_id,
                    title=str(item.get("title") or file_name or "未命名文档"),
                    sha256=sha256,
                    path=path,
                    publisher=item.get("source_site"),
                    doc_type=str(item.get("category") or "industry_methodology"),
                    created_by=job.created_by,
                )
            # existing 属于其它库：跳过（sha256 全局唯一）
        except Exception as exc:  # noqa: BLE001
            failures += 1
            last_error = f"{file_name or '<unknown>'}: {exc}"
            logger.exception("rag_import_item_failed job=%s file=%s", job.id, file_name)
        processed += 1
        await repo.update_job(job.id, processed=processed, error_message=last_error)
    if failures == len(items):
        final_status = "failed"
    elif failures:
        final_status = "partial"
    else:
        final_status = "succeeded"
    await repo.update_job(
        job.id,
        status=final_status,
        processed=processed,
        error_message=last_error,
        finished_at=datetime.now(UTC),
    )


async def _fail(repo: RagRepository, job, message: str) -> None:
    if job.doc_id is not None:
        doc = await repo.get_document(job.doc_id)
        if doc is not None:
            doc.status = "failed"
            doc.error_message = message
            await repo.session.commit()
    await repo.update_job(
        job.id,
        status="failed",
        processed=(job.processed or 0) + 1,
        error_message=message,
        finished_at=datetime.now(UTC),
    )


async def run_cycle() -> bool:
    async with async_session_factory() as db:
        repo = RagRepository(db)
        job = await repo.claim_next_job()
    if job is None:
        return False
    logger.info("rag_ingest_claimed job=%s library=%s", job.id, job.library_id)
    await process_job(job.id)
    return True


async def main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())

    async with async_session_factory() as db:
        requeued = await RagRepository(db).requeue_stale_jobs()
    if requeued:
        logger.warning("rag_ingest_requeued_stale_jobs count=%s", requeued)

    logger.info("rag_ingest_worker_started")
    while not stop_event.is_set():
        try:
            ran = await run_cycle()
        except Exception:  # noqa: BLE001
            logger.exception("rag_ingest_cycle_failed")
            ran = False
        if ran:
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("rag_ingest_worker_stopped")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
