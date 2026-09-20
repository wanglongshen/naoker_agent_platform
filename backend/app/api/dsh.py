from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user, require_super_admin
from app.db.session import get_db
from app.models.dsh import DshSession
from app.models.rbac import User
from app.schemas.common import success
from app.schemas.dsh import (
    DshInstanceStatus,
    DshSessionAuditItem,
    DshSessionAuditListResponse,
    DshSessionListResponse,
    DshSessionMeta,
)
from app.services.dsh import get_manager

router = APIRouter(tags=["DSH"])


async def _page_sessions(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    page: int,
    page_size: int,
    with_owner: bool = False,
) -> dict:
    stmt = select(DshSession)
    if with_owner:
        stmt = select(
            DshSession,
            func.coalesce(
                User.display_name, User.username, ""
            ).label("display_name"),
            func.coalesce(User.username, "").label("username"),
        ).join(User, DshSession.user_id == User.id, isouter=True)
    if user_id is not None:
        stmt = stmt.where(DshSession.user_id == user_id)
    stmt = stmt.order_by(DshSession.last_activity_at.desc().nulls_last())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(
        stmt.offset((page - 1) * page_size).limit(page_size)
    )
    if with_owner:
        items = []
        for session, display_name, username in result.all():
            session.display_name = display_name
            session.username = username
            items.append(session)
    else:
        items = list(result.scalars().all())
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": int(total or 0),
    }


@router.get("/sessions")
async def list_my_sessions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await _page_sessions(
        db, user_id=current_user.id, page=page, page_size=page_size
    )
    return success(
        request,
        DshSessionListResponse(
            items=[DshSessionMeta.model_validate(r) for r in result["items"]],
            page=result["page"],
            page_size=result["page_size"],
            total=result["total"],
        ).model_dump(mode="json"),
    )


@router.get("/sessions/audit")
async def list_all_sessions(
    request: Request,
    user_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await _page_sessions(
        db, user_id=user_id, page=page, page_size=page_size, with_owner=True
    )
    return success(
        request,
        DshSessionAuditListResponse(
            items=[DshSessionAuditItem.model_validate(r) for r in result["items"]],
            page=result["page"],
            page_size=result["page_size"],
            total=result["total"],
        ).model_dump(mode="json"),
    )


@router.get("/instances/me")
async def my_instance(
    request: Request,
    current_user: User = Depends(get_current_user),
    manager=Depends(get_manager),
    db: AsyncSession = Depends(get_db),
):
    instance = await manager.check_alive(current_user.id, db)
    if instance is None:
        return success(
            request,
            {
                "state": "stopped",
                "port": None,
                "pid": None,
                "last_active_at": None,
                "error_hint": None,
            },
        )
    return success(
        request,
        DshInstanceStatus.model_validate(instance).model_dump(mode="json"),
    )


@router.post("/instances/me/restart")
async def restart_my_instance(
    request: Request,
    current_user: User = Depends(get_current_user),
    manager=Depends(get_manager),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    await manager.stop(current_user.id, db)
    instance = await manager.ensure_running(current_user.id, db)
    return success(
        request,
        DshInstanceStatus.model_validate(instance).model_dump(mode="json"),
    )
