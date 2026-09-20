import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_permissions
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.rbac import User
from app.schemas.common import success
from app.services import avatar_service

router = APIRouter(tags=["头像管理"])


@router.post("/me")
async def upload_own_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await avatar_service.upload_avatar(db, current_user, file)
    await db.commit()
    return success(request, result)


@router.delete("/me")
async def clear_own_avatar(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await avatar_service.clear_avatar(db, current_user)
    await db.commit()
    return success(request, result)


async def _target_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(
        select(User).where(User.id == user_id, User.is_deleted == False)
    )
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在")
    return user


@router.post("/{user_id}")
async def upload_avatar_for_user(
    request: Request,
    user_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = require_permissions("user:update"),
    db: AsyncSession = Depends(get_db),
):
    target = await _target_user(db, user_id)
    result = await avatar_service.upload_avatar(db, target, file)
    await db.commit()
    return success(request, result)


@router.delete("/{user_id}")
async def clear_avatar_for_user(
    request: Request,
    user_id: uuid.UUID,
    current_user: User = require_permissions("user:update"),
    db: AsyncSession = Depends(get_db),
):
    target = await _target_user(db, user_id)
    result = await avatar_service.clear_avatar(db, target)
    await db.commit()
    return success(request, result)


@router.get("/{user_id}")
async def get_avatar(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await _target_user(db, user_id)
    data = await avatar_service.read_avatar(target)
    if data is None:
        raise ApiError(404, "AVATAR_NOT_FOUND", "该用户未设置头像")
    content, mime = data
    return Response(
        content=content,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=3600"},
    )
