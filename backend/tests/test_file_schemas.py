import uuid

import pytest
from pydantic import ValidationError
from app.schemas.file import (
    BatchDeleteRequest,
    FileFolderCreate,
    FileFolderUpdate,
    FileMoveRequest,
    FileRenameRequest,
    LinkAttachmentRequest,
)


class TestFileFolderCreate:
    def test_valid_create(self):
        data = FileFolderCreate(name="my folder")
        assert data.name == "my folder"
        assert data.parent_folder_id is None

    def test_with_parent(self):
        parent_id = uuid.uuid4()
        data = FileFolderCreate(name="sub", parent_folder_id=parent_id)
        assert data.parent_folder_id == parent_id

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            FileFolderCreate(name="")


class TestFileFolderUpdate:
    def test_valid_update(self):
        data = FileFolderUpdate(name="renamed")
        assert data.name == "renamed"


class TestFileMoveRequest:
    def test_move_to_root(self):
        data = FileMoveRequest(target_folder_id=None)
        assert data.target_folder_id is None

    def test_move_to_folder(self):
        fid = uuid.uuid4()
        data = FileMoveRequest(target_folder_id=fid)
        assert data.target_folder_id == fid


class TestFileRenameRequest:
    def test_valid_rename(self):
        data = FileRenameRequest(name="new name.pdf")
        assert data.name == "new name.pdf"

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            FileRenameRequest(name="")


class TestBatchDelete:
    def test_valid_batch(self):
        ids = [uuid.uuid4(), uuid.uuid4()]
        data = BatchDeleteRequest(ids=ids)
        assert len(data.ids) == 2

    def test_empty_rejected(self):
        with pytest.raises(ValidationError):
            BatchDeleteRequest(ids=[])


class TestLinkAttachment:
    def test_valid_link(self):
        aid = uuid.uuid4()
        data = LinkAttachmentRequest(attachment_id=aid)
        assert data.attachment_id == aid
        assert data.folder_id is None
