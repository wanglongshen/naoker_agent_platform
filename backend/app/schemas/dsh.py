import uuid
from datetime import datetime

from pydantic import BaseModel


class DshSessionMeta(BaseModel):
    model_config = {"from_attributes": True}

    dsh_session_id: str
    title: str | None = None
    turn_count: int
    last_activity_at: datetime | None = None
    synced_at: datetime | None = None


class DshSessionAuditItem(DshSessionMeta):
    user_id: uuid.UUID
    username: str = ""
    display_name: str = ""


class DshSessionListResponse(BaseModel):
    items: list[DshSessionMeta]
    page: int
    page_size: int
    total: int


class DshSessionAuditListResponse(BaseModel):
    items: list[DshSessionAuditItem]
    page: int
    page_size: int
    total: int


class DshInstanceStatus(BaseModel):
    model_config = {"from_attributes": True}

    state: str
    port: int | None = None
    pid: int | None = None
    last_active_at: datetime | None = None
    error_hint: str | None = None
