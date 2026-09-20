from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkflowDocSummary(Base):
    __tablename__ = "workflow_doc_summaries"

    doc_path: Mapped[str] = mapped_column(String(500), primary_key=True)
    file_updated_at: Mapped[str] = mapped_column(String(64), default="")
    file_sha256: Mapped[str] = mapped_column(String(64), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="ready")
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    distill_version: Mapped[int] = mapped_column(Integer, default=0)
    distilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
