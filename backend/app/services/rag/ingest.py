"""入库管线：manifest → parse → chunk → embed → 幂等落库（T4）。

- 幂等键为 `sha256`：已入库的文档直接跳过（不区分状态，避免唯一约束冲突），
  重复执行 `ingest_manifest` 不会产生重复数据；
- 空正文（纯图片/附件类素材）跳过并计入 `skipped_empty`，不写空文档；
- 单篇失败不中断整体：异常记入 `errors`，继续处理后续文档；
- 入库完成后若传入 `store` 则调用 `store.invalidate()` 失效向量缓存。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models.rag import RagDocument
from app.repositories.rag_repository import RagRepository
from app.services.agent import file_reader
from app.services.rag.chunking import chunk_markdown
from app.services.rag.embedding import EmbeddingProvider
from app.services.rag.parsing import parse_source_file
from app.services.rag.store import VectorStore

LICENSE_NOTE = "抖音电商官方公开课程（公开网页），仅内部知识库使用，不公开再分发"

# 与 `var/kb_industry/_scripts/make_core.py` 一致的分类口径（title + tags）。
RULE_KW = re.compile(r"规则|细则|标准|公示|通知|协议|变更|公告|须知|规范|说明$")
METHOD_KW = re.compile(
    r"投放|运营|手册|白皮书|指南|宝典|秘籍|教程|经验|推荐|方法|策略|进阶|案例|大促|玩法|利器|地图"
)

# 二进制文档格式 → 解析用 media type（`file_reader.extract_file_text` 口径）。
BINARY_DOC_MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


class EmptyDocumentError(RuntimeError):
    """解析后没有正文（纯图片 PDF 等）。"""


def _category_text(item: dict[str, Any]) -> str:
    tags = " ".join(str(tag) for tag in item.get("tags") or [])
    return " " + str(item.get("title") or "") + " " + tags


def is_method_item(item: dict[str, Any]) -> bool:
    text = _category_text(item)
    return bool(METHOD_KW.search(text)) and not RULE_KW.search(text)


def classify_manifest_item(item: dict[str, Any]) -> str:
    """按 make_core.py 口径返回 methodology / rules / other。"""
    if is_method_item(item):
        return "methodology"
    if RULE_KW.search(_category_text(item)):
        return "rules"
    return "other"


def filter_manifest_items(
    items: list[dict[str, Any]], category: str | None
) -> list[dict[str, Any]]:
    if not category:
        return list(items)
    return [item for item in items if classify_manifest_item(item) == category]


@dataclass
class IngestReport:
    inserted: int = 0
    skipped: int = 0
    skipped_empty: int = 0
    failed: int = 0
    chunks: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class DryRunReport:
    items: int = 0
    documents: int = 0
    total_chars: int = 0
    chunks: int = 0
    skipped_empty: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def load_manifest_items(manifest_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError(f"manifest 缺少 items 列表：{manifest_path}")
    return [item for item in items if isinstance(item, dict)]


async def ingest_one(
    repo: RagRepository,
    provider: EmbeddingProvider,
    *,
    library_id: uuid.UUID,
    title: str,
    sha256: str,
    path: Path | None = None,
    markdown: str | None = None,
    source_url: str | None = None,
    publisher: str | None = None,
    license_note: str = LICENSE_NOTE,
    doc_type: str = "industry_methodology",
    created_by: uuid.UUID | None = None,
    store: VectorStore | None = None,
    doc: RagDocument | None = None,
) -> tuple[RagDocument, int]:
    """入库单篇文档。

    `doc` 非空时复用该文档（清空旧切块后重写，用于上传占位文档与重新切分），
    为空时新建文档。
    """
    if markdown is None:
        if path is None:
            raise ValueError("path 与 markdown 至少提供一个")
        path = Path(path)
        media_type = BINARY_DOC_MEDIA_TYPES.get(path.suffix.lower())
        if media_type is not None:
            content = path.read_bytes()
            if len(content) > file_reader.MAX_FILE_BYTES:
                raise EmptyDocumentError(
                    f"文件超过解析上限（{file_reader.MAX_FILE_BYTES} 字节）：{path.name}"
                )
            extracted = file_reader.extract_file_text(media_type, content)
            text = str(extracted.get("text") or "").strip()
            if extracted.get("error") or not text:
                raise EmptyDocumentError(f"未能从文档提取正文：{path.name}")
            markdown = text
        else:
            parsed = parse_source_file(path)
            markdown = parsed.markdown
            source_url = source_url or parsed.source_meta.get("source_url")
            publisher = publisher or parsed.source_meta.get("source")
            title = title or parsed.title
    text = (markdown or "").strip()
    if not text:
        raise EmptyDocumentError("未提取到正文")
    chunks = chunk_markdown(text)
    if not chunks:
        raise EmptyDocumentError("未提取到正文")
    embeddings = await provider.embed([chunk.content for chunk in chunks])
    if len(embeddings) != len(chunks):
        raise RuntimeError(f"embedding 数量不匹配：{len(embeddings)} != {len(chunks)}")

    if doc is None:
        doc = await repo.create_document(
            title=title,
            doc_type=doc_type,
            source_url=source_url,
            publisher=publisher,
            license_note=license_note,
            file_key=str(path) if path is not None else None,
            sha256=sha256,
            status="processing",
            library_id=library_id,
            created_by=created_by,
        )
    else:
        await repo.clear_chunks(doc.id)
        doc.title = title
        doc.doc_type = doc_type
        doc.source_url = source_url
        doc.publisher = publisher
        doc.license_note = license_note
        doc.sha256 = sha256
        doc.status = "processing"
        doc.error_message = None
        if path is not None:
            doc.file_key = str(path)
        await repo.session.commit()

    await repo.add_chunks(
        doc.id,
        [
            (chunk.section_path, chunk.content, embedding, provider.dim)
            for chunk, embedding in zip(chunks, embeddings)
        ],
    )
    doc.status = "ready"
    doc.error_message = None
    await repo.session.commit()
    if store is not None:
        store.invalidate()
    return doc, len(chunks)


async def ingest_manifest(
    repo: RagRepository,
    provider: EmbeddingProvider,
    manifest_path: Path,
    *,
    library_id: uuid.UUID,
    source_dir: Path,
    limit: int | None = None,
    doc_type: str = "industry_methodology",
    created_by: uuid.UUID | None = None,
    store: VectorStore | None = None,
) -> IngestReport:
    """把 manifest 中的素材批量入库，返回统计报告（不抛单篇异常）。"""
    items = load_manifest_items(manifest_path)
    if limit is not None:
        items = items[: max(limit, 0)]

    source_dir = Path(source_dir)
    report = IngestReport()

    for item in items:
        file_name = str(item.get("file") or "")
        try:
            sha256 = str(item.get("sha256") or "").strip()
            path = source_dir / file_name
            if not sha256:
                sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            if await repo.get_document_by_sha256(sha256) is not None:
                report.skipped += 1
                continue

            _, chunk_count = await ingest_one(
                repo,
                provider,
                library_id=library_id,
                title=str(item.get("title") or ""),
                sha256=sha256,
                path=path,
                source_url=item.get("source_url"),
                publisher=item.get("source_site"),
                doc_type=doc_type,
                created_by=created_by,
            )
            report.inserted += 1
            report.chunks += chunk_count
        except EmptyDocumentError:
            report.skipped_empty += 1
        except Exception as exc:
            report.failed += 1
            report.errors.append(f"{file_name or '<unknown>'}: {exc}")

    if store is not None:
        store.invalidate()
    return report


def dry_run_manifest(
    manifest_path: Path, *, source_dir: Path, limit: int | None = None
) -> DryRunReport:
    """只解析与切分，统计结果不落库（CLI `--dry-run` 使用）。"""
    items = load_manifest_items(manifest_path)
    if limit is not None:
        items = items[: max(limit, 0)]

    source_dir = Path(source_dir)
    report = DryRunReport(items=len(items))

    for item in items:
        file_name = str(item.get("file") or "")
        try:
            parsed = parse_source_file(source_dir / file_name)
            markdown = parsed.markdown.strip()
            if not markdown:
                report.skipped_empty += 1
                continue
            chunks = chunk_markdown(markdown)
            if not chunks:
                report.skipped_empty += 1
                continue
            report.documents += 1
            report.total_chars += len(markdown)
            report.chunks += len(chunks)
        except Exception as exc:
            report.failed += 1
            report.errors.append(f"{file_name or '<unknown>'}: {exc}")

    return report
