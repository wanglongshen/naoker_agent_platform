from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaskChainCreateRequest(BaseModel):
    goal: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    attachments: list[uuid.UUID] = Field(default_factory=list)


class TaskChainStageResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    stage: str
    seq: int
    status: str
    attempt: int
    output_payload: dict[str, Any] | None = None
    error: str = ""
    tokens: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskChainResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    goal: str
    status: str
    current_stage: str = ""
    input_payload: dict[str, Any] = Field(default_factory=dict)
    result_file_id: uuid.UUID | None = None
    feishu_doc_url: str = ""
    final_answer: str = ""
    error: str = ""
    total_tokens: int = 0
    points_cost: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    stages: list[TaskChainStageResponse] = Field(default_factory=list)


class TaskChainListResponse(BaseModel):
    items: list[TaskChainResponse]
    page: int
    page_size: int
    total: int
