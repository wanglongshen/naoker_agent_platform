import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

AgentRunStatus = Literal[
    "queued", "running", "retry_wait", "awaiting_question", "succeeded", "failed", "cancel_requested", "cancelled"
]
AgentAttemptStatus = Literal["queued", "running", "paused", "succeeded", "failed", "cancelled"]
AgentAttachmentExtractionStatus = Literal["pending_scan", "ready", "rejected"]


class AgentSessionCreate(BaseModel):
    title: str | None = None
    project_folder_id: uuid.UUID | None = None


class SessionProjectUpdate(BaseModel):
    project_folder_id: uuid.UUID | None = None


class AgentSessionRename(BaseModel):
    title: str


class AgentSessionPin(BaseModel):
    pinned: bool


class AgentSessionResponse(BaseModel):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    owner_display_name: str = ""
    title: str | None
    last_run_id: uuid.UUID | None
    is_pinned: bool = False
    project_folder_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentSessionListResponse(BaseModel):
    items: list[AgentSessionResponse]
    page: int
    page_size: int
    total: int


class AgentRunCreate(BaseModel):
    goal: str
    network_enabled: bool = True
    attachment_ids: list[uuid.UUID] = []


class AgentRunAnswerRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class AgentRunResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    owner_user_id: uuid.UUID
    goal: str
    mode: str
    network_enabled: bool
    status: str
    max_steps: int
    current_attempt_id: uuid.UUID | None
    result: dict[str, Any] | None = None
    pending_questions: list[dict[str, Any]] | None = None
    terminal_evidence: Literal[
        "persisted_terminal", "run_succeeded_event", "answer_completed_event", "none"
    ] = "none"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentRunListResponse(BaseModel):
    items: list[AgentRunResponse]
    page: int
    page_size: int
    total: int


class AgentAttemptResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    attempt_number: int
    status: str
    worker_id: str | None
    claimed_at: datetime | None
    lease_expires_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None
    retry_of_attempt_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentStepResponse(BaseModel):
    id: uuid.UUID
    attempt_id: uuid.UUID
    step_number: int
    thought_summary: str | None
    action_type: str | None
    action_payload: dict | None
    observation: dict[str, Any] | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRunEventResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    attempt_id: uuid.UUID | None
    seq: int
    event_type: str
    payload: dict
    created_at: datetime

    @computed_field
    @property
    def type(self) -> str:
        return self.event_type

    @computed_field
    @property
    def timestamp(self) -> str:
        return self.created_at.isoformat().replace("+00:00", "Z")

    model_config = {"from_attributes": True}


class AgentAuditEvent(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    attempt_id: uuid.UUID | None
    seq: int
    event_type: str
    payload: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentRunEventListResponse(BaseModel):
    items: list[AgentRunEventResponse]
    page: int
    page_size: int
    total: int


class AgentAttachmentResponse(BaseModel):
    id: uuid.UUID
    owner_user_id: uuid.UUID
    session_id: uuid.UUID
    filename: str
    original_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    extraction_status: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentAttemptListResponse(BaseModel):
    items: list[AgentAttemptResponse]
    page: int
    page_size: int
    total: int


class AgentStepListResponse(BaseModel):
    items: list[AgentStepResponse]
    page: int
    page_size: int
    total: int


class AgentAttachmentListResponse(BaseModel):
    items: list[AgentAttachmentResponse]
    page: int
    page_size: int
    total: int


class AgentAuditCursorPage(BaseModel):
    items: list[AgentAuditEvent]
    next_seq: int | None


class AuditOwnerSummary(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    roles: list[str]


class AuditTranscriptTurn(BaseModel):
    run: AgentRunResponse
    steps: list[AgentStepResponse]
    events: list[AgentRunEventResponse]


class AuditSessionTranscriptResponse(BaseModel):
    session: AgentSessionResponse
    owner: AuditOwnerSummary
    turns: list[AuditTranscriptTurn]
