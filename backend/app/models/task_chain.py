from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TaskChain(Base):
    __tablename__ = "task_chains"
    __table_args__ = (Index("ix_task_chains_status_created", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    input_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    current_stage: Mapped[str] = mapped_column(String(50), default="")
    result_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("file_objects.id"), nullable=True
    )
    feishu_doc_url: Mapped[str] = mapped_column(Text, default="")
    final_answer: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    points_cost: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TaskChainStage(Base):
    __tablename__ = "task_chain_stages"
    __table_args__ = (
        UniqueConstraint("chain_id", "seq", name="ix_task_chain_stages_chain_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task_chains.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    input_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
