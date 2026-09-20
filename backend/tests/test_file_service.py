import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.file import FileFolder, FileObject
from app.repositories.file_repository import FileRepository
from app.services.file_service import FileService


async def _fake_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)


def _make_upload_file(filename, content=b"hello world", content_type="text/plain"):
    upload_file = MagicMock()
    upload_file.filename = filename
    upload_file.content_type = content_type
    upload_file.read = AsyncMock(side_effect=[content, b""])
    return upload_file


@pytest.fixture
def file_service():
    return FileService()


@pytest.fixture
async def folder_for_service(session, seeded_user):
    folder = FileFolder(
        owner_user_id=seeded_user.id,
        name="svc-folder",
        path="/svc-folder",
        depth=0,
    )
    session.add(folder)
    await session.flush()
    return folder


class TestUpload:
    async def test_upload_valid_text_file(self, file_service, session, seeded_user):
        upload_file = _make_upload_file("hello.txt", b"hello world", "text/plain")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            result = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

        assert result.filename == "hello.txt"
        assert result.media_type == "text/plain"
        assert result.size_bytes == 11
        assert result.preview_status == "ready"
        assert result.extracted_text == "hello world"
        assert result.owner_user_id == seeded_user.id

        repo = FileRepository(session)
        file_obj = await repo.get_file(result.id)
        assert file_obj is not None
        assert file_obj.filename == "hello.txt"

    async def test_upload_to_folder(self, file_service, session, seeded_user, folder_for_service):
        upload_file = _make_upload_file("in_folder.txt", b"content", "text/plain")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            result = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=folder_for_service.id,
                upload_file=upload_file,
                db_session=session,
            )

        assert result.folder_id == folder_for_service.id

    async def test_upload_reject_exe_mime(self, file_service, session, seeded_user):
        upload_file = _make_upload_file("bad.exe", b"MZ\x90\x00", "application/x-msdownload")

        with pytest.raises(ValueError, match="MIME type not allowed"):
            await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

    async def test_upload_reject_invalid_mime(self, file_service, session, seeded_user):
        upload_file = _make_upload_file("bad.bin", b"\x00\x01", "application/octet-stream")

        with pytest.raises(ValueError, match="MIME type not allowed"):
            await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

    async def test_upload_path_traversal_filename(self, file_service, session, seeded_user):
        upload_file = _make_upload_file("../../../etc/passwd", b"secret", "text/plain")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            result = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

        assert result.filename == "passwd"
        assert ".." not in result.filename

    async def test_upload_reject_empty_filename(self, file_service, session, seeded_user):
        upload_file = _make_upload_file("   ", b"data", "text/plain")

        with pytest.raises(ValueError, match="Empty filename"):
            await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

    async def test_upload_reject_invalid_filename_dots(self, file_service, session, seeded_user):
        upload_file = _make_upload_file("..secret.txt", b"data", "text/plain")

        with pytest.raises(ValueError, match="Invalid filename"):
            await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

    async def test_upload_image_file(self, file_service, session, seeded_user):
        upload_file = _make_upload_file("photo.png", b"\x89PNG\r\n\x1a\n", "image/png")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            result = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

        assert result.media_type == "image/png"
        assert result.preview_status == "none"

    async def test_upload_same_name_overwrites_same_record(self, file_service, session, seeded_user):
        upload_file = _make_upload_file("report.md", b"# v1", "text/markdown")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            first = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

        second_upload = _make_upload_file("report.md", b"# v2 content", "text/markdown")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            second = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=second_upload,
                db_session=session,
            )

        assert second.id == first.id
        assert second.size_bytes == len(b"# v2 content")
        assert second.created_at > first.created_at

        repo = FileRepository(session)
        file_obj = await repo.get_file(first.id)
        assert file_obj is not None
        assert file_obj.extracted_text == "# v2 content"

    async def test_upload_same_name_different_folder_keeps_both(
        self, file_service, session, seeded_user, folder_for_service
    ):
        upload_file = _make_upload_file("notes.md", b"root", "text/markdown")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            root_file = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=None,
                upload_file=upload_file,
                db_session=session,
            )

        folder_upload = _make_upload_file("notes.md", b"folder", "text/markdown")

        with patch("builtins.open", MagicMock()), \
             patch("asyncio.to_thread", side_effect=_fake_to_thread):
            folder_file = await file_service.upload(
                owner_user_id=seeded_user.id,
                folder_id=folder_for_service.id,
                upload_file=folder_upload,
                db_session=session,
            )

        assert folder_file.id != root_file.id
        repo = FileRepository(session)
        assert await repo.get_file(root_file.id) is not None
        assert await repo.get_file(folder_file.id) is not None


class TestDownload:
    async def test_download_owned_file(self, file_service, session, seeded_user):
        repo = FileRepository(session)
        file_obj = FileObject(
            owner_user_id=seeded_user.id,
            folder_id=None,
            storage_key="var/files/test.txt",
            filename="test.txt",
            original_filename="test.txt",
            media_type="text/plain",
            size_bytes=12,
            sha256="s" * 64,
            created_by=seeded_user.id,
        )
        session.add(file_obj)
        await session.flush()

        content = b"download data"

        with patch("pathlib.Path.is_file", return_value=True), \
             patch("builtins.open", MagicMock()) as mock_open:
            mock_open.return_value.__enter__.return_value.read.side_effect = [content, b""]
            chunks = []
            async for chunk in file_service.download(file_obj.id, seeded_user.id, session):
                chunks.append(chunk)

        assert b"".join(chunks) == content

    async def test_download_nonexistent(self, file_service, session, seeded_user):
        with pytest.raises(FileNotFoundError):
            async for _ in file_service.download(uuid.uuid4(), seeded_user.id, session):
                pass

    async def test_download_access_denied(self, file_service, session, seeded_user):
        repo = FileRepository(session)
        file_obj = FileObject(
            owner_user_id=seeded_user.id,
            folder_id=None,
            storage_key="var/files/private.txt",
            filename="private.txt",
            original_filename="private.txt",
            media_type="text/plain",
            size_bytes=10,
            sha256="t" * 64,
            created_by=seeded_user.id,
        )
        session.add(file_obj)
        await session.flush()

        other_user = uuid.uuid4()
        with pytest.raises(PermissionError, match="Access denied"):
            async for _ in file_service.download(file_obj.id, other_user, session):
                pass

    async def test_download_file_data_missing(self, file_service, session, seeded_user):
        repo = FileRepository(session)
        file_obj = FileObject(
            owner_user_id=seeded_user.id,
            folder_id=None,
            storage_key="var/files/missing.txt",
            filename="missing.txt",
            original_filename="missing.txt",
            media_type="text/plain",
            size_bytes=5,
            sha256="u" * 64,
            created_by=seeded_user.id,
        )
        session.add(file_obj)
        await session.flush()

        with patch("pathlib.Path.is_file", return_value=False):
            with pytest.raises(FileNotFoundError, match="File data not found"):
                async for _ in file_service.download(file_obj.id, seeded_user.id, session):
                    pass
