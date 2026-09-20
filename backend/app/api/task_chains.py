from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.agent import AgentAttachment
from app.models.rbac import User
from app.models.task_chain import TaskChain
from app.repositories.task_chain_repository import TaskChainRepository
from app.schemas.common import success
from app.schemas.task_chain import (
    TaskChainCreateRequest,
    TaskChainListResponse,
    TaskChainResponse,
    TaskChainStageResponse,
)
from app.services.points import get_or_create_points

router = APIRouter(tags=["task-chains"])

CANCELLABLE_STATUSES = {"queued", "running"}


async def _get_owned_chain(
    repo: TaskChainRepository, chain_id: uuid.UUID, user_id: uuid.UUID
) -> TaskChain:
    chain = await repo.get_chain(chain_id, user_id=user_id)
    if chain is None:
        raise ApiError(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            message="资源不存在",
        )
    return chain


@router.post("")
async def create_task_chain(
    request: Request,
    data: TaskChainCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    if not data.goal.strip():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="goal 不能为空",
        )

    points = await get_or_create_points(db, current_user.id)
    if points.balance <= 0:
        raise ApiError(status_code=400, code="INSUFFICIENT_POINTS", message="积点余额不足，请先充值")

    payload = dict(data.input_payload or {})
    attachment_texts: list[str] = []
    for attachment_id in data.attachments:
        attachment = await db.scalar(
            select(AgentAttachment).where(
                AgentAttachment.id == attachment_id,
                AgentAttachment.owner_user_id == current_user.id,
                AgentAttachment.extraction_status == "ready",
            )
        )
        if attachment is None:
            raise ApiError(
                status_code=422,
                code="INVALID_ATTACHMENT",
                message=f"附件 {attachment_id} 不存在、无权访问或未就绪",
            )
        if attachment.extracted_text:
            attachment_texts.append(attachment.extracted_text)
    if attachment_texts:
        payload["attachment_texts"] = attachment_texts

    repo = TaskChainRepository(db)
    chain = await repo.create_chain(
        user_id=current_user.id,
        goal=data.goal.strip(),
        input_payload=payload,
    )
    return success(
        request,
        TaskChainResponse.model_validate(chain).model_dump(mode="json"),
    )


@router.get("")
async def list_task_chains(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = TaskChainRepository(db)
    result = await repo.list_chains(current_user.id, page=page, page_size=page_size)
    return success(
        request,
        TaskChainListResponse(
            items=[TaskChainResponse.model_validate(item) for item in result.items],
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        ).model_dump(mode="json"),
    )


@router.get("/{chain_id}")
async def get_task_chain(
    request: Request,
    chain_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = TaskChainRepository(db)
    chain = await _get_owned_chain(repo, chain_id, current_user.id)
    stages = await repo.list_stages(chain.id)
    data = TaskChainResponse.model_validate(chain).model_dump(mode="json")
    data["stages"] = [
        TaskChainStageResponse.model_validate(stage).model_dump(mode="json")
        for stage in stages
    ]
    return success(request, data)


@router.post("/{chain_id}/cancel")
async def cancel_task_chain(
    request: Request,
    chain_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    repo = TaskChainRepository(db)
    chain = await _get_owned_chain(repo, chain_id, current_user.id)
    if chain.status not in CANCELLABLE_STATUSES:
        raise ApiError(
            status_code=409,
            code="INVALID_TRANSITION",
            message="任务链已结束，无法取消",
        )
    updated = await repo.set_chain_status(
        chain.id, "cancelled", finished_at=datetime.now(UTC)
    )
    await db.refresh(updated)
    return success(
        request,
        TaskChainResponse.model_validate(updated).model_dump(mode="json"),
    )
