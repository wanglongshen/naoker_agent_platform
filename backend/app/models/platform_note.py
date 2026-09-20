from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PlatformNote(Base):
    """平台笔记样本（小红书/抖音采集）。project_id 为项目隔离预留，本轮恒 NULL（无 FK，项目表未建）。"""

    __tablename__ = "platform_notes"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "url", name="uq_platform_notes_owner_url"),
        Index("ix_platform_notes_owner_platform", "owner_user_id", "platform"),
        Index("ix_platform_notes_owner_keyword", "owner_user_id", "keyword"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collect_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    topic_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
