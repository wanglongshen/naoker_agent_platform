from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GenerationLog(Base):
    __tablename__ = "generation_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("file_folders.id"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_sessions.id"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    final_md_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("file_objects.id"), nullable=True
    )
    final_answer: Mapped[str] = mapped_column(Text, default="")
    feishu_doc_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str] = mapped_column(Text, default="")
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_review_rounds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
