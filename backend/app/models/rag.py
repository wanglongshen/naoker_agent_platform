from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RagLibrary(Base):
    __tablename__ = "rag_libraries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="custom")
    visibility: Mapped[str] = mapped_column(String(16), default="admins_only")
    retrieval_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RagDocument(Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        Index("ix_rag_documents_status", "status"),
        Index("ix_rag_documents_library_id", "library_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(64), default="industry_methodology")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(200), nullable=True)
    license_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rag_libraries.id", ondelete="CASCADE"), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class RagChunk(Base):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_index", name="ix_rag_chunks_doc_chunk"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RagEvalSet(Base):
    __tablename__ = "rag_eval_set"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_doc_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RagJob(Base):
    __tablename__ = "rag_jobs"
    __table_args__ = (Index("ix_rag_jobs_status", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    library_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rag_libraries.id", ondelete="CASCADE"), nullable=False
    )
    doc_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="upload")
    status: Mapped[str] = mapped_column(String(16), default="queued")
    total: Mapped[int] = mapped_column(Integer, default=1)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
