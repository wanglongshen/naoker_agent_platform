"""RAG API：检索（全登录用户/平台 token）+ 文档管理（super_admin）。"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BACKEND_ROOT
from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user, require_super_admin
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.rag import RagChunk, RagDocument, RagJob, RagLibrary
from app.models.rbac import Role, User, UserRole
from app.repositories.rag_repository import LibraryNameConflict, RagRepository
from app.schemas.common import success
from app.schemas.rag import (
    RagDocumentItem,
    RagDocumentListResponse,
    RagImportRequest,
    RagLibraryCreate,
    RagLibraryItem,
    RagLibraryListResponse,
    RagLibraryStats,
    RagLibraryUpdate,
    RagSearchHit,
    RagSearchRequest,
)
from app.services.file_service import _detect_mime_type, _validate_filename
from app.services.rag.embedding import build_embedding_provider
from app.services.rag.ingest import filter_manifest_items, load_manifest_items
from app.services.rag.search import RagSearchService
from app.services.rag.store import NumpyVectorStore

router = APIRouter(tags=["rag"])

logger = logging.getLogger(__name__)

UPLOAD_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv", ".html", ".htm"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
BINARY_PARSER_MODULES = {".pdf": "pypdf", ".docx": "docx", ".xlsx": "openpyxl", ".pptx": "pptx"}

REPO_ROOT = Path(__file__).resolve().parents[3]

_search_service: RagSearchService | None = None


def rag_upload_root() -> Path:
    return BACKEND_ROOT / "var" / "rag" / "uploads"


def _remove_uploaded_file(file_key: str | None) -> None:
    """删除文档时清理其上传文件（仅限 RAG 上传目录内，缺失即忽略）。"""
    if not file_key:
        return
    try:
        candidate = Path(file_key).resolve()
        root = rag_upload_root().resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            candidate.unlink()
    except OSError:  # noqa: BLE001 - 清理失败不应影响删除结果
        logger.warning("rag_upload_file_cleanup_failed file_key=%s", file_key)


def kb_industry_root() -> Path:
    return REPO_ROOT / "var" / "kb_industry"


def kb_manifest_path(scope: str) -> Path:
    name = "manifest-core.json" if scope == "core" else "manifest.json"
    return kb_industry_root() / "manifest" / name


def missing_parser_module(suffix: str) -> str | None:
    module = BINARY_PARSER_MODULES.get(suffix)
    if module is not None and importlib.util.find_spec(module) is None:
        return module
    return None


class _SessionRepo:
    """按需开新 session 的轻量仓储：常驻 store 的 loader / 签名校验用。

    请求级 `RagRepository` 的 session 会随请求关闭，而 store 缓存跨请求存活，
    因此这里每次操作都从 session 工厂新开一个 session，避免闭包捕获失效 session。
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    @property
    def session(self) -> Any:
        raise RuntimeError("_SessionRepo 不暴露常驻 session")

    async def iter_embeddings(self) -> list[tuple[uuid.UUID, bytes]]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RagChunk.id, RagChunk.embedding).order_by(RagChunk.id)
            )
            return [(row.id, row.embedding) for row in result.all()]

    async def get_chunks_by_ids(self, chunk_ids: list[uuid.UUID]) -> list[RagChunk]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RagChunk).where(RagChunk.id.in_(chunk_ids))
            )
            return list(result.scalars().all())

    async def list_chunk_ids_for_library(self, library_id: uuid.UUID) -> list[uuid.UUID]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RagChunk.id)
                .join(RagDocument, RagDocument.id == RagChunk.doc_id)
                .where(RagDocument.library_id == library_id)
            )
            return list(result.scalars().all())

    async def get_documents_by_ids(self, doc_ids: list[uuid.UUID]) -> list[RagDocument]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RagDocument).where(RagDocument.id.in_(doc_ids))
            )
            return list(result.scalars().all())

    async def get_libraries_by_ids(self, library_ids: list[uuid.UUID]) -> list[RagLibrary]:
        if not library_ids:
            return []
        async with self._session_factory() as session:
            result = await session.execute(
                select(RagLibrary).where(RagLibrary.id.in_(library_ids))
            )
            return list(result.scalars().all())

    async def chunk_signature(self) -> tuple[int, Any]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count(RagChunk.id), func.max(RagChunk.created_at))
            )
            count, latest = result.one()
            return (int(count or 0), latest)


def _build_search_service() -> RagSearchService:
    from app.db.session import async_session_factory

    repo = _SessionRepo(async_session_factory)
    return RagSearchService(
        repo,
        build_embedding_provider(),
        NumpyVectorStore(
            loader=repo.iter_embeddings, version_probe=repo.chunk_signature
        ),
    )


def get_search_service() -> RagSearchService:
    global _search_service
    if _search_service is None:
        _search_service = _build_search_service()
    return _search_service


async def _is_super_admin(db: AsyncSession, user: User) -> bool:
    stmt = select(
        exists().where(
            UserRole.user_id == user.id,
            UserRole.role_id == Role.id,
            Role.code == "super_admin",
            Role.status == "active",
            Role.is_deleted.is_(False),
        )
    )
    return bool(await db.scalar(stmt))


def _hit_payload(hit: Any) -> RagSearchHit:
    return RagSearchHit(
        chunk_id=hit.chunk_id,
        doc_id=hit.doc_id,
        title=hit.title,
        section_path=hit.section_path,
        content=hit.content,
        source_url=hit.source_url,
        publisher=hit.publisher,
        score=hit.score,
        library_id=hit.library_id,
        library_name=hit.library_name,
    )


def _library_item(lib: RagLibrary, stats: dict[str, Any]) -> RagLibraryItem:
    return RagLibraryItem(
        id=lib.id,
        name=lib.name,
        description=lib.description,
        kind=lib.kind,
        visibility=lib.visibility,
        retrieval_enabled=lib.retrieval_enabled,
        created_at=lib.created_at,
        updated_at=lib.updated_at,
        stats=RagLibraryStats(**stats),
    )


@router.get("/libraries")
async def list_libraries(
    request: Request,
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    libs = await repo.list_libraries()
    stats = await repo.library_stats()
    empty = {"doc_count": 0, "chunk_count": 0, "ready_count": 0, "failed_count": 0, "last_updated_at": None}
    payload = RagLibraryListResponse(
        items=[_library_item(lib, stats.get(lib.id, empty)) for lib in libs]
    )
    return success(request, payload.model_dump(mode="json"))


@router.post("/libraries")
async def create_library(
    request: Request,
    data: RagLibraryCreate,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if await repo.get_library_by_name(data.name) is not None:
        raise ApiError(status_code=409, code="LIBRARY_NAME_EXISTS", message="知识库名称已存在")
    try:
        lib = await repo.create_library(
            name=data.name,
            description=data.description,
            kind=data.kind,
            created_by=current_user.id,
        )
    except LibraryNameConflict as exc:
        raise ApiError(
            status_code=409, code="LIBRARY_NAME_EXISTS", message="知识库名称已存在"
        ) from exc
    stats = {"doc_count": 0, "chunk_count": 0, "ready_count": 0, "failed_count": 0, "last_updated_at": None}
    return success(request, _library_item(lib, stats).model_dump(mode="json"))


@router.get("/libraries/{library_id}")
async def get_library(
    request: Request,
    library_id: uuid.UUID,
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    lib = await repo.get_library(library_id)
    if lib is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")
    stats = (await repo.library_stats()).get(lib.id) or {
        "doc_count": 0, "chunk_count": 0, "ready_count": 0, "failed_count": 0, "last_updated_at": None
    }
    return success(request, _library_item(lib, stats).model_dump(mode="json"))


@router.patch("/libraries/{library_id}")
async def update_library(
    request: Request,
    library_id: uuid.UUID,
    data: RagLibraryUpdate,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    lib = await repo.get_library(library_id)
    if lib is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")
    if data.name:
        existing = await repo.get_library_by_name(data.name)
        if existing is not None and existing.id != library_id:
            raise ApiError(status_code=409, code="LIBRARY_NAME_EXISTS", message="知识库名称已存在")
    fields = {
        key: value
        for key, value in data.model_dump(exclude_unset=True).items()
        if value is not None or key == "description"
    }
    try:
        await repo.update_library(library_id, **fields)
    except LibraryNameConflict as exc:
        raise ApiError(
            status_code=409, code="LIBRARY_NAME_EXISTS", message="知识库名称已存在"
        ) from exc
    await db.refresh(lib)
    stats = (await repo.library_stats()).get(lib.id) or {
        "doc_count": 0, "chunk_count": 0, "ready_count": 0, "failed_count": 0, "last_updated_at": None
    }
    return success(request, _library_item(lib, stats).model_dump(mode="json"))


@router.delete("/libraries/{library_id}")
async def delete_library(
    request: Request,
    library_id: uuid.UUID,
    force: bool = Query(default=False),
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    lib = await repo.get_library(library_id)
    if lib is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")
    stats = (await repo.library_stats()).get(lib.id) or {"doc_count": 0}
    if stats["doc_count"] > 0 and not force:
        raise ApiError(
            status_code=409,
            code="LIBRARY_NOT_EMPTY",
            message="知识库非空：请先清空文档或使用强制删除",
        )
    await repo.delete_library(library_id)
    return success(request, {"deleted": True})


@router.post("/search")
async def search(
    request: Request,
    data: RagSearchRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: RagSearchService = Depends(get_search_service),
):
    started = time.perf_counter()
    include_disabled_libraries = bool(data.include_disabled) and await _is_super_admin(
        db, current_user
    )
    repo = RagRepository(db)
    library_id = data.library_id
    if library_id is None and data.library:
        library = await repo.get_library_by_name(data.library)
        if library is None:
            raise ApiError(
                status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在"
            )
        library_id = library.id
    try:
        hits = await service.search(
            data.query,
            data.top_k,
            library_id=library_id,
            include_disabled_libraries=include_disabled_libraries,
        )
    except ValueError:
        raise ApiError(
            status_code=400, code="INVALID_QUERY", message="查询不能为空且不超过 500 字"
        )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return success(
        request,
        {"items": [_hit_payload(hit) for hit in hits], "elapsed_ms": elapsed_ms},
    )


@router.get("/documents")
async def list_documents(
    request: Request,
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    result = await repo.list_documents(
        status=status, keyword=keyword, page=page, page_size=page_size
    )
    payload = RagDocumentListResponse(
        items=[RagDocumentItem.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )
    return success(request, payload.model_dump(mode="json"))


@router.get("/libraries/{library_id}/documents")
async def list_library_documents(
    request: Request,
    library_id: uuid.UUID,
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if await repo.get_library(library_id) is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")
    result = await repo.list_documents(
        library_id=library_id, status=status, keyword=q, page=page, page_size=page_size
    )
    payload = RagDocumentListResponse(
        items=[RagDocumentItem.model_validate(item) for item in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
    )
    return success(request, payload.model_dump(mode="json"))


@router.post("/libraries/{library_id}/documents")
async def upload_document(
    request: Request,
    library_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if await repo.get_library(library_id) is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")

    try:
        filename = _validate_filename(file.filename or "")
    except ValueError:
        raise ApiError(status_code=400, code="INVALID_FILENAME", message="文件名不合法")
    suffix = Path(filename).suffix.lower()
    if suffix not in UPLOAD_EXTENSIONS:
        raise ApiError(
            status_code=400,
            code="UNSUPPORTED_FILE_TYPE",
            message=f"不支持的文件类型：{suffix}",
        )
    missing = missing_parser_module(suffix)
    if missing is not None:
        raise ApiError(
            status_code=400,
            code="PARSER_UNAVAILABLE",
            message=f"该格式需要安装解析依赖：{missing}",
        )

    declared_size = getattr(file, "size", None)
    if isinstance(declared_size, int) and declared_size > MAX_UPLOAD_BYTES:
        raise ApiError(status_code=400, code="FILE_TOO_LARGE", message="文件超过 20MB 限制")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ApiError(status_code=400, code="FILE_TOO_LARGE", message="文件超过 20MB 限制")
    detected = _detect_mime_type(content[:4096])
    if detected is None and suffix in {".pdf", ".docx", ".xlsx", ".pptx"}:
        raise ApiError(
            status_code=400, code="UNSUPPORTED_FILE_TYPE", message="文件内容与扩展名不匹配"
        )

    sha256 = hashlib.sha256(content).hexdigest()
    existing = await repo.get_document_by_sha256(sha256)
    if existing is not None:
        if existing.library_id == library_id:
            raise ApiError(
                status_code=409, code="DOCUMENT_EXISTS", message="该文件已在本知识库中"
            )
        other_library = await repo.get_library(existing.library_id)
        if other_library is not None:
            message = f"该文件已存在于知识库「{other_library.name}」中"
        else:
            message = "该文件已存在于其他知识库中"
        raise ApiError(status_code=409, code="DOCUMENT_EXISTS", message=message)

    target_dir = rag_upload_root() / str(library_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}{suffix}"
    target.write_bytes(content)

    doc = await repo.create_document(
        title=Path(filename).stem,
        doc_type="upload",
        file_key=str(target),
        sha256=sha256,
        status="pending",
        library_id=library_id,
        created_by=current_user.id,
    )
    job = await repo.create_job(
        library_id=library_id,
        doc_id=doc.id,
        kind="upload",
        status="queued",
        total=1,
        payload={"path": str(target), "title": Path(filename).stem},
        created_by=current_user.id,
    )
    return success(request, {"doc_id": str(doc.id), "job_id": str(job.id)})


@router.post("/documents/{doc_id}/reingest")
async def reingest_document(
    request: Request,
    doc_id: uuid.UUID,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    doc = await repo.get_document(doc_id)
    if doc is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="文档不存在")
    if not doc.file_key:
        raise ApiError(
            status_code=400, code="NO_SOURCE_FILE", message="该文档没有可重新解析的源文件"
        )
    await repo.set_document_status(doc.id, "pending")
    job = await repo.create_job(
        library_id=doc.library_id,
        doc_id=doc.id,
        kind="upload",
        status="queued",
        total=1,
        payload={"path": doc.file_key, "title": doc.title, "sha256": doc.sha256},
        created_by=current_user.id,
    )
    return success(request, {"doc_id": str(doc.id), "job_id": str(job.id)})


@router.delete("/documents/{doc_id}")
async def delete_document(
    request: Request,
    doc_id: uuid.UUID,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    doc = await repo.get_document(doc_id)
    if doc is None or not await repo.delete_document(doc_id):
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="文档不存在")
    _remove_uploaded_file(doc.file_key)
    get_search_service().store.invalidate()
    return success(request, {"deleted": True})


@router.get("/documents/{doc_id}/chunks")
async def list_document_chunks(
    request: Request,
    doc_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if await repo.get_document(doc_id) is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="文档不存在")
    chunks, total = await repo.list_chunks_page(doc_id, page=page, page_size=page_size)
    return success(
        request,
        {
            "items": [
                {
                    "id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "section_path": chunk.section_path,
                    "content": chunk.content,
                }
                for chunk in chunks
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


async def _set_status(
    request: Request,
    doc_id: uuid.UUID,
    status: str,
    db: AsyncSession,
) -> dict:
    repo = RagRepository(db)
    doc = await repo.set_document_status(doc_id, status)
    if doc is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="文档不存在")
    return success(request, RagDocumentItem.model_validate(doc).model_dump(mode="json"))


@router.post("/documents/{doc_id}/disable")
async def disable_document(
    request: Request,
    doc_id: uuid.UUID,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    return await _set_status(request, doc_id, "disabled", db)


@router.post("/documents/{doc_id}/enable")
async def enable_document(
    request: Request,
    doc_id: uuid.UUID,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    return await _set_status(request, doc_id, "ready", db)


@router.post("/libraries/{library_id}/import")
async def import_collected(
    request: Request,
    library_id: uuid.UUID,
    data: RagImportRequest,
    current_user=Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    if await repo.get_library(library_id) is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="知识库不存在")
    manifest = kb_manifest_path(data.scope)
    if not manifest.exists():
        raise ApiError(status_code=400, code="MANIFEST_NOT_FOUND", message=f"素材清单不存在：{manifest.name}")

    items = load_manifest_items(manifest)
    items = filter_manifest_items(items, data.category)
    if data.limit is not None:
        items = items[: data.limit]
    if not items:
        raise ApiError(status_code=400, code="NO_MATERIAL", message="没有符合条件的素材")

    job = await repo.create_job(
        library_id=library_id,
        kind="import",
        status="queued",
        total=len(items),
        payload={
            "scope": data.scope,
            "category": data.category,
            "markdown_root": str(kb_industry_root() / "markdown"),
            "items": items,
        },
        created_by=current_user.id,
    )
    return success(request, {"job_id": str(job.id), "queued": len(items)})


@router.get("/jobs/{job_id}")
async def get_job(
    request: Request,
    job_id: uuid.UUID,
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    job = await repo.get_job(job_id)
    if job is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="任务不存在")
    return success(request, _job_payload(job))


@router.get("/jobs")
async def list_jobs(
    request: Request,
    library_id: uuid.UUID | None = Query(default=None),
    active: bool = Query(default=False),
    current_user=Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = RagRepository(db)
    jobs = (
        await repo.list_active_jobs(library_id)
        if active
        else await repo.list_jobs(library_id)
    )
    return success(request, {"items": [_job_payload(job) for job in jobs]})


def _job_payload(job: RagJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "library_id": str(job.library_id),
        "doc_id": str(job.doc_id) if job.doc_id else None,
        "kind": job.kind,
        "status": job.status,
        "total": job.total,
        "processed": job.processed,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
