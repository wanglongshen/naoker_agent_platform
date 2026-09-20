import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class FileFolder(Base):
    __tablename__ = "file_folders"
    __table_args__ = (
        Index("ix_file_folders_owner", "owner_user_id"),
        Index("ix_file_folders_parent", "parent_folder_id"),
        Index("ix_file_folders_path", "path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    parent_folder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("file_folders.id"))
    name: Mapped[str] = mapped_column(String(256))
    path: Mapped[str] = mapped_column(Text, default="")
    depth: Mapped[int] = mapped_column(Integer, default=0)
    child_file_count: Mapped[int] = mapped_column(BigInteger, default=0)
    total_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    owner = relationship("User", back_populates="file_folders")
    parent = relationship("FileFolder", remote_side="FileFolder.id", back_populates="children")
    children = relationship("FileFolder", back_populates="parent")
    files = relationship("FileObject", back_populates="folder")


class FileObject(Base):
    __tablename__ = "file_objects"
    __table_args__ = (
        Index("ix_file_objects_owner", "owner_user_id"),
        Index("ix_file_objects_folder", "folder_id"),
        Index("ix_file_objects_media_type", "media_type"),
        Index("ix_file_objects_sha256", "sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("file_folders.id"))
    storage_key: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    preview_status: Mapped[str] = mapped_column(String(32), default="none")
    preview_path: Mapped[str | None] = mapped_column(String(512))
    source_attachment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_attachments.id"))
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    owner = relationship("User")
    folder = relationship("FileFolder", back_populates="files")
