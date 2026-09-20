from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_MANIFEST = REPO_ROOT / "var" / "kb_industry" / "manifest" / "manifest.json"


class FakeProvider:
    dim = 4

    async def embed(self, texts):
        return [np.ones(4, dtype=np.float32).tobytes() for _ in texts]


class FakeStore:
    def __init__(self) -> None:
        self.invalidated = 0

    def invalidate(self) -> None:
        self.invalidated += 1


def _write_delta_doc(path: Path, body: str) -> None:
    payload = {
        "version": 2,
        "deltas": {"d": {"ops": [{"insert": body}, {"insert": "\n"}]}},
        "attachments": [],
    }
    path.write_text(
        "# 标题\n\n来源：抖音电商官方学习中心\n\n"
        + json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_manifest(path: Path, items: list[dict]) -> None:
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")


@pytest.mark.anyio
async def test_ingest_is_idempotent_by_sha256(test_db, tmp_path: Path):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.ingest import ingest_manifest

    _write_delta_doc(tmp_path / "doc1.md", "投放方法正文。")
    manifest = tmp_path / "manifest-core.json"
    _write_manifest(
        manifest,
        [
            {
                "title": "投放方法",
                "file": "doc1.md",
                "sha256": "abc123",
                "source_url": "https://example.com/a",
                "source_site": "抖音电商官方学习中心",
            }
        ],
    )

    async with test_db() as db:
        repo = RagRepository(db)
        lib = await repo.create_library(name="幂等库")
        first = await ingest_manifest(
            repo, FakeProvider(), manifest, library_id=lib.id, source_dir=tmp_path
        )
        assert first.inserted == 1
        assert first.chunks >= 1
        assert first.failed == 0

        second = await ingest_manifest(
            repo, FakeProvider(), manifest, library_id=lib.id, source_dir=tmp_path
        )
        assert second.inserted == 0
        assert second.skipped == 1
        assert second.chunks == 0


@pytest.mark.anyio
async def test_ingest_skips_empty_body_without_creating_document(test_db, tmp_path: Path):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.ingest import ingest_manifest

    payload = {
        "version": 2,
        "deltas": {
            "d": {"ops": [{"insert": "\n", "attributes": {"IMAGE": {"src": "x.png"}}}]}
        },
        "attachments": [],
    }
    (tmp_path / "empty.md").write_text(
        "# 纯图片素材\n\n来源：抖音电商官方学习中心\n\n"
        + json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest-core.json"
    _write_manifest(
        manifest, [{"title": "纯图片素材", "file": "empty.md", "sha256": "empty-sha"}]
    )

    async with test_db() as db:
        repo = RagRepository(db)
        lib = await repo.create_library(name="空文库")
        report = await ingest_manifest(
            repo, FakeProvider(), manifest, library_id=lib.id, source_dir=tmp_path
        )
        assert report.inserted == 0
        assert report.skipped_empty == 1
        assert report.chunks == 0
        assert await repo.get_document_by_sha256("empty-sha") is None


@pytest.mark.anyio
async def test_ingest_records_failures_and_continues(test_db, tmp_path: Path):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.ingest import ingest_manifest

    _write_delta_doc(tmp_path / "good.md", "正常正文。")
    manifest = tmp_path / "manifest-core.json"
    _write_manifest(
        manifest,
        [
            {"title": "缺失素材", "file": "missing.md", "sha256": "miss-sha"},
            {"title": "正常素材", "file": "good.md", "sha256": "good-sha"},
        ],
    )

    async with test_db() as db:
        repo = RagRepository(db)
        lib = await repo.create_library(name="失败库")
        store = FakeStore()
        report = await ingest_manifest(
            repo,
            FakeProvider(),
            manifest,
            library_id=lib.id,
            source_dir=tmp_path,
            store=store,
        )
        assert report.inserted == 1
        assert report.failed == 1
        assert len(report.errors) == 1
        assert "missing.md" in report.errors[0]
        assert store.invalidated == 1


@pytest.mark.anyio
async def test_ingest_stores_metadata_and_honors_limit(test_db, tmp_path: Path):
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.ingest import LICENSE_NOTE, ingest_manifest

    _write_delta_doc(tmp_path / "doc1.md", "第一篇正文。" * 20)
    _write_delta_doc(tmp_path / "doc2.md", "第二篇正文。")
    manifest = tmp_path / "manifest-core.json"
    _write_manifest(
        manifest,
        [
            {
                "title": "第一篇",
                "file": "doc1.md",
                "sha256": "sha-1",
                "source_url": "https://example.com/a",
                "source_site": "抖音电商官方学习中心",
            },
            {"title": "第二篇", "file": "doc2.md", "sha256": "sha-2"},
        ],
    )

    async with test_db() as db:
        repo = RagRepository(db)
        lib = await repo.create_library(name="元数据库")
        report = await ingest_manifest(
            repo,
            FakeProvider(),
            manifest,
            library_id=lib.id,
            source_dir=tmp_path,
            limit=1,
        )
        assert report.inserted == 1
        assert await repo.get_document_by_sha256("sha-2") is None

        doc = await repo.get_document_by_sha256("sha-1")
        assert doc is not None
        assert doc.library_id == lib.id
        assert doc.title == "第一篇"
        assert doc.doc_type == "industry_methodology"
        assert doc.status == "ready"
        assert doc.source_url == "https://example.com/a"
        assert doc.publisher == "抖音电商官方学习中心"
        assert doc.license_note == LICENSE_NOTE
        assert doc.file_key == str(tmp_path / "doc1.md")
        assert doc.chunk_count == report.chunks


def test_classify_manifest_item_uses_title_and_tags():
    from app.services.rag.ingest import classify_manifest_item, is_method_item

    assert is_method_item({"title": "巨量千川投放宝典", "tags": []})
    assert classify_manifest_item({"title": "巨量千川投放宝典", "tags": []}) == "methodology"
    assert classify_manifest_item({"title": "精选联盟变更公示", "tags": []}) == "rules"
    assert classify_manifest_item({"title": "创作者服务中心功能介绍", "tags": []}) == "other"
    assert classify_manifest_item({"title": "无关键词标题", "tags": ["投放"]}) == "methodology"
    assert classify_manifest_item({"title": "无关键词标题", "tags": ["规则"]}) == "rules"
    assert classify_manifest_item({"title": "规则说明", "tags": []}) == "rules"


@pytest.mark.skipif(not REAL_MANIFEST.exists(), reason="真实素材清单不存在")
def test_real_manifest_category_counts():
    from app.services.rag.ingest import classify_manifest_item, load_manifest_items

    items = load_manifest_items(REAL_MANIFEST)
    counts = Counter(classify_manifest_item(item) for item in items)
    assert len(items) == 601
    assert counts == {"methodology": 226, "rules": 254, "other": 121}


@pytest.mark.anyio
async def test_ingest_pdf_routes_through_file_reader(test_db, tmp_path: Path, monkeypatch):
    from app.repositories.rag_repository import RagRepository
    from app.services.agent import file_reader
    from app.services.rag.ingest import ingest_one

    calls: list[tuple[str | None, bytes]] = []

    def fake_extract(media_type, content):
        calls.append((media_type, content))
        return {"text": "PDF 正文：投放方法与规则说明。", "truncated": False}

    monkeypatch.setattr(file_reader, "extract_file_text", fake_extract)
    pdf = tmp_path / "手册.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake pdf bytes")

    async with test_db() as db:
        repo = RagRepository(db)
        lib = await repo.create_library(name="PDF解析库")
        doc, chunks = await ingest_one(
            repo,
            FakeProvider(),
            library_id=lib.id,
            title="PDF手册",
            sha256="pdf-sha",
            path=pdf,
        )
        assert doc.status == "ready"
        assert chunks >= 1

    assert calls and calls[0][0] == "application/pdf"
    assert calls[0][1] == b"%PDF-1.4 fake pdf bytes"


@pytest.mark.anyio
async def test_ingest_pdf_without_text_raises_empty_document_error(
    test_db, tmp_path: Path, monkeypatch
):
    from app.repositories.rag_repository import RagRepository
    from app.services.agent import file_reader
    from app.services.rag.ingest import EmptyDocumentError, ingest_one

    monkeypatch.setattr(
        file_reader,
        "extract_file_text",
        lambda media_type, content: {
            "text": "(binary file, type: application/pdf, no text extracted)",
            "truncated": False,
            "error": True,
        },
    )
    pdf = tmp_path / "纯图片.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake pdf bytes")

    async with test_db() as db:
        repo = RagRepository(db)
        lib = await repo.create_library(name="空PDF库")
        with pytest.raises(EmptyDocumentError):
            await ingest_one(
                repo,
                FakeProvider(),
                library_id=lib.id,
                title="纯图片PDF",
                sha256="pdf-empty-sha",
                path=pdf,
            )


def test_dry_run_counts_without_touching_db(tmp_path: Path):
    from app.services.rag.ingest import dry_run_manifest

    _write_delta_doc(tmp_path / "doc1.md", "第一篇正文。" * 20)
    payload = {"version": 2, "deltas": {"d": {"ops": []}}, "attachments": []}
    (tmp_path / "empty.md").write_text(
        "# 空素材\n\n" + json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    manifest = tmp_path / "manifest-core.json"
    _write_manifest(
        manifest,
        [
            {"title": "第一篇", "file": "doc1.md", "sha256": "sha-1"},
            {"title": "空素材", "file": "empty.md", "sha256": "sha-2"},
            {"title": "缺失", "file": "missing.md", "sha256": "sha-3"},
        ],
    )

    report = dry_run_manifest(manifest, source_dir=tmp_path)
    assert report.items == 3
    assert report.documents == 1
    assert report.total_chars > 0
    assert report.chunks >= 1
    assert report.skipped_empty == 1
    assert report.failed == 1


@pytest.mark.anyio
async def test_ingest_one_stores_resolvable_file_key_and_never_leaves_ready_without_chunks(
    test_db, tmp_path
):
    from pathlib import Path as _Path

    from app.repositories.rag_repository import RagRepository
    from app.services.rag.ingest import ingest_one

    async with test_db() as session:
        repo = RagRepository(session)
        lib = await repo.create_library(name="ingest-file-key")
        md = tmp_path / "doc.md"
        md.write_text("# 标题\n\n正文内容", encoding="utf-8")

        doc, chunks = await ingest_one(
            repo, FakeProvider(), library_id=lib.id, title="t", sha256="fk-1", path=md
        )
        assert chunks >= 1
        assert doc.file_key == str(md)
        assert _Path(doc.file_key).is_file()
        assert doc.status == "ready"

        class BoomProvider:
            dim = 4

            async def embed(self, texts):
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await ingest_one(
                repo, BoomProvider(), library_id=lib.id, title="boom", sha256="fk-2", path=md
            )
        assert await repo.get_document_by_sha256("fk-2") is None

        async def boom_add_chunks(*args, **kwargs):
            raise RuntimeError("store failed")

        original_add_chunks = repo.add_chunks
        repo.add_chunks = boom_add_chunks
        try:
            with pytest.raises(RuntimeError):
                await ingest_one(
                    repo, FakeProvider(), library_id=lib.id, title="half", sha256="fk-3", path=md
                )
        finally:
            repo.add_chunks = original_add_chunks

        half = await repo.get_document_by_sha256("fk-3")
        assert half is not None
        assert half.status == "processing"
        assert half.chunk_count == 0
