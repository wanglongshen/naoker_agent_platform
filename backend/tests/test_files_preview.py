import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.file import FileObject

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _insert_file(test_engine, *, media_type: str, filename: str, content: bytes, owner: uuid.UUID, tmp_path) -> str:
    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        f = FileObject(
            owner_user_id=owner,
            storage_key="",
            filename=filename,
            original_filename=filename,
            media_type=media_type,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        s.add(f)
        await s.flush()
        storage = tmp_path / f"preview_{f.id.hex}.bin"
        storage.write_bytes(content)
        f.storage_key = str(storage)
        await s.commit()
        return str(f.id)


@pytest.mark.asyncio
async def test_preview_docx_returns_extracted_text(admin_client, test_engine, monkeypatch, tmp_path) -> None:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        owner_id = owner.id

    docx_bytes = b"PK\x03\x04 fake docx content"
    file_id = await _insert_file(test_engine, media_type=_DOCX, filename="报告.docx", content=docx_bytes, owner=owner_id, tmp_path=tmp_path)

    import app.services.agent.file_reader as file_reader
    monkeypatch.setattr(
        file_reader,
        "extract_file_text",
        lambda media_type, content: {"text": "这是文档提取的文字", "truncated": False},
    )

    resp = await admin_client.get(f"/api/files/{file_id}/preview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["type"] == "text"
    assert data["content"] == "这是文档提取的文字"


@pytest.mark.asyncio
async def test_preview_docx_extract_failure_returns_fallback(admin_client, test_engine, monkeypatch, tmp_path) -> None:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        owner_id = owner.id

    file_id = await _insert_file(test_engine, media_type=_DOCX, filename="坏文档.docx", content=b"broken", owner=owner_id, tmp_path=tmp_path)

    import app.services.agent.file_reader as file_reader
    monkeypatch.setattr(file_reader, "extract_file_text", lambda media_type, content: (_ for _ in ()).throw(RuntimeError("boom")))

    resp = await admin_client.get(f"/api/files/{file_id}/preview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["type"] == "text"
    assert data["content"] == "无法读取文档内容。"


@pytest.mark.asyncio
async def test_preview_markdown_returns_raw_text(admin_client, test_engine, tmp_path) -> None:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        owner_id = owner.id

    md = "# 标题\n\n正文内容"
    file_id = await _insert_file(test_engine, media_type="text/markdown", filename="note.md", content=md.encode("utf-8"), owner=owner_id, tmp_path=tmp_path)

    resp = await admin_client.get(f"/api/files/{file_id}/preview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["type"] == "text"
    assert "标题" in data["content"]


@pytest.mark.asyncio
async def test_preview_pdf_stays_stream(admin_client, test_engine, tmp_path) -> None:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        owner_id = owner.id

    file_id = await _insert_file(test_engine, media_type="application/pdf", filename="doc.pdf", content=b"%PDF-1.4 fake", owner=owner_id, tmp_path=tmp_path)

    resp = await admin_client.get(f"/api/files/{file_id}/preview")
    assert resp.status_code == 200
    assert resp.json()["data"]["type"] == "stream"


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "filename", "extracted"),
    [
        (_XLSX, "报表.xlsx", "单元格数据"),
        (_PPTX, "演示.pptx", "幻灯片文字"),
    ],
)
async def test_preview_office_documents_returns_extracted_text(
    admin_client, test_engine, monkeypatch, tmp_path, media_type, filename, extracted
) -> None:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        owner_id = owner.id

    file_id = await _insert_file(test_engine, media_type=media_type, filename=filename, content=b"PK\x03\x04 fake content", owner=owner_id, tmp_path=tmp_path)

    import app.services.agent.file_reader as file_reader
    monkeypatch.setattr(
        file_reader,
        "extract_file_text",
        lambda mt, content: {"text": extracted, "truncated": False},
    )

    resp = await admin_client.get(f"/api/files/{file_id}/preview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["type"] == "text"
    assert data["content"] == extracted
