import uuid

import pytest
from app.models.file import FileFolder, FileObject


class TestFileFolder:
    def test_create_root_folder(self):
        folder = FileFolder(
            owner_user_id=uuid.uuid4(),
            name="  my docs  ",
            path="/",
            depth=0,
        )
        assert folder.name == "  my docs  "
        assert folder.path in ("/", None)
        assert folder.depth in (0, None)
        assert folder.is_deleted in (False, None)
        assert folder.child_file_count in (0, None)

    def test_create_nested_folder(self):
        parent_id = uuid.uuid4()
        folder = FileFolder(
            owner_user_id=uuid.uuid4(),
            parent_folder_id=parent_id,
            name="subfolder",
            path="/root/subfolder/",
            depth=2,
        )
        assert folder.parent_folder_id == parent_id
        assert folder.depth == 2

    def test_default_values(self):
        folder = FileFolder(owner_user_id=uuid.uuid4(), name="test")
        assert folder.path in ("", None)
        assert folder.depth in (0, None)
        assert folder.child_file_count in (0, None)
        assert folder.total_size_bytes in (0, None)
        assert folder.is_deleted in (False, None)


class TestFileObject:
    def test_create_file_object(self):
        obj = FileObject(
            owner_user_id=uuid.uuid4(),
            folder_id=None,
            storage_key="files/abc123",
            filename="report.pdf",
            original_filename="report.pdf",
            media_type="application/pdf",
            size_bytes=1024,
            sha256="a" * 64,
        )
        assert obj.filename == "report.pdf"
        assert obj.size_bytes == 1024
        assert obj.preview_status in ("none", None)
        assert obj.is_deleted in (False, None)

    def test_file_object_with_attachment_link(self):
        attachment_id = uuid.uuid4()
        obj = FileObject(
            owner_user_id=uuid.uuid4(),
            storage_key="files/abc123",
            filename="doc.txt",
            original_filename="doc.txt",
            media_type="text/plain",
            size_bytes=100,
            sha256="b" * 64,
            source_attachment_id=attachment_id,
        )
        assert obj.source_attachment_id == attachment_id
