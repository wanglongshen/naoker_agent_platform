import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FileFolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    parent_folder_id: uuid.UUID | None = None


class FileFolderUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class FileFolderResponse(BaseModel):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    parent_folder_id: uuid.UUID | None
    name: str
    path: str
    depth: int
    child_file_count: int
    total_size_bytes: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FileObjectResponse(BaseModel):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    folder_id: uuid.UUID | None
    filename: str
    original_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    extracted_text: str | None
    preview_status: str
    source_attachment_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FileObjectListResponse(BaseModel):
    items: list[FileObjectResponse]
    page: int
    page_size: int
    total: int


class UserFolderGroup(BaseModel):
    user_id: uuid.UUID
    username: str
    display_name: str
    folders: list[FileFolderResponse]


class FileMoveRequest(BaseModel):
    target_folder_id: uuid.UUID | None


class FileRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=512)


class BatchDeleteRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1)


class BatchDeleteResponse(BaseModel):
    deleted: list[uuid.UUID]
    failed: list[dict[str, Any]]


class LinkAttachmentRequest(BaseModel):
    attachment_id: uuid.UUID
    folder_id: uuid.UUID | None = None
