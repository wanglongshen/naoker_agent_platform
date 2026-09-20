import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class RagSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    library_id: uuid.UUID | None = None
    library: str | None = Field(default=None, max_length=120, description="按知识库名称过滤")
    include_disabled: bool = False


class RagSearchHit(BaseModel):
    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    title: str
    section_path: str
    content: str
    source_url: str | None
    publisher: str | None
    score: float
    library_id: uuid.UUID | None = None
    library_name: str | None = None


class RagDocumentItem(BaseModel):
    id: uuid.UUID
    title: str
    doc_type: str
    source_url: str | None
    publisher: str | None
    status: str
    chunk_count: int
    library_id: uuid.UUID
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RagDocumentListResponse(BaseModel):
    items: list[RagDocumentItem]
    page: int
    page_size: int
    total: int


class RagImportRequest(BaseModel):
    scope: str = Field(default="core", pattern="^(core|all)$")
    category: str | None = Field(default=None, pattern="^(methodology|rules|other)$")
    limit: int | None = Field(default=None, ge=1, le=2000)


class RagLibraryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    kind: str = Field(default="custom", pattern="^(industry|rules|custom)$")


class RagLibraryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    visibility: str | None = Field(default=None, pattern="^(admins_only|all_members)$")
    retrieval_enabled: bool | None = None


class RagLibraryStats(BaseModel):
    doc_count: int
    chunk_count: int
    ready_count: int
    failed_count: int
    last_updated_at: datetime | None = None


class RagLibraryItem(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    kind: str
    visibility: str
    retrieval_enabled: bool
    created_at: datetime
    updated_at: datetime
    stats: RagLibraryStats

    model_config = {"from_attributes": True}


class RagLibraryListResponse(BaseModel):
    items: list[RagLibraryItem]
