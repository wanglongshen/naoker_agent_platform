import uuid
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Any

from app.models.base import Base

agent_run_events_seq = Sequence("agent_run_events_seq_seq")


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint("id", "owner_user_id", name="uq_agent_sessions_id_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str | None] = mapped_column(Text)
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    project_folder_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    owner = relationship("User")

    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="session", foreign_keys="AgentRun.session_id"
    )
    attachments: Mapped[list["AgentAttachment"]] = relationship(
        back_populates="session", foreign_keys="AgentAttachment.session_id"
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "owner_user_id"],
            ["agent_sessions.id", "agent_sessions.owner_user_id"],
            name="fk_agent_runs_session_owner",
        ),
        CheckConstraint(
            "status IN ('queued','running','retry_wait','awaiting_question','succeeded','failed','cancel_requested','cancelled')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint(
            "max_steps > 0 AND max_steps <= 200",
            name="ck_agent_runs_max_steps",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    goal: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16), default="quick")
    network_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    max_steps: Mapped[int] = mapped_column(Integer, default=30)
    project_folder_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    current_attempt_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pending_questions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    session: Mapped["AgentSession"] = relationship(
        back_populates="runs", foreign_keys=[session_id]
    )
    attempts: Mapped[list["AgentRunAttempt"]] = relationship(back_populates="run")
    events: Mapped[list["AgentRunEvent"]] = relationship(back_populates="run")
    run_attachments: Mapped[list["AgentRunAttachment"]] = relationship(
        back_populates="run"
    )


class AgentRunAttempt(Base):
    __tablename__ = "agent_run_attempts"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "attempt_number", name="uq_agent_run_attempts_run_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_of_attempt_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    run: Mapped["AgentRun"] = relationship(back_populates="attempts")
    steps: Mapped[list["AgentStep"]] = relationship(back_populates="attempt")
    events: Mapped[list["AgentRunEvent"]] = relationship(back_populates="attempt")


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "step_number", name="uq_agent_steps_attempt_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_run_attempts.id", ondelete="CASCADE"), index=True
    )
    step_number: Mapped[int] = mapped_column(Integer)
    thought_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    observation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    attempt: Mapped["AgentRunAttempt"] = relationship(back_populates="steps")


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"
    __table_args__ = (
        Index("ix_agent_run_events_run_seq", "run_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_run_attempts.id", ondelete="SET NULL"), nullable=True
    )
    seq: Mapped[int] = mapped_column(
        BigInteger,
        agent_run_events_seq,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    run: Mapped["AgentRun"] = relationship(back_populates="events")
    attempt: Mapped["AgentRunAttempt"] = relationship(back_populates="events")


class AgentAttachment(Base):
    __tablename__ = "agent_attachments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    storage_key: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(512))
    media_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    extraction_status: Mapped[str] = mapped_column(
        String(32), default="pending_scan"
    )
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    session: Mapped["AgentSession"] = relationship(
        back_populates="attachments", foreign_keys=[session_id]
    )
    owner = relationship("User")
    run_attachments: Mapped[list["AgentRunAttachment"]] = relationship(
        back_populates="attachment"
    )


class AgentRunAttachment(Base):
    __tablename__ = "agent_run_attachments"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    attachment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_attachments.id", ondelete="CASCADE"), primary_key=True
    )

    run: Mapped["AgentRun"] = relationship(back_populates="run_attachments")
    attachment: Mapped["AgentAttachment"] = relationship(
        back_populates="run_attachments"
    )


class AgentRetentionJob(Base):
    __tablename__ = "agent_retention_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid4)
    job_type: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
