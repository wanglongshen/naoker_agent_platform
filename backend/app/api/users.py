import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_permissions
from app.core.errors import ApiError
from app.core.messages import Messages
from app.core.security import hash_password, validate_password, verify_password
from app.db.session import get_db
from app.models.rbac import User
from app.schemas.common import success
from app.schemas.user import (
    PasswordChangeRequest,
    PasswordReset,
    ProfileUpdate,
    UserCreate,
    UserStatusUpdate,
    UserUpdate,
)
from app.services import user_service
from app.services.auth_service import get_user_roles

router = APIRouter(tags=["用户管理"])


@router.get("", summary="查询用户列表")
async def list_users(
    request: Request,
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    role_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = require_permissions("user:read"),
):
    result = await user_service.list_users(
        db, keyword=keyword, status=status, role_id=role_id, page=page, page_size=page_size
    )
    return success(request, result)


@router.post("", status_code=201, summary="新建用户")
async def create_user(
    request: Request,
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_permissions("user:create"),
):
    result = await user_service.create_user(db, data, current_user)
    return success(request, result)


@router.put("/me/profile", summary="修改个人资料")
async def update_own_profile(
    request: Request,
    data: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.display_name is None and data.email is None and data.phone is None:
        raise ApiError(
            status_code=400,
            code="VALIDATION_ERROR",
            message="至少提供一个要更新的字段",
        )
    if data.email is not None:
        conflict = await db.scalar(
            select(User).where(
                User.email == data.email,
                User.id != current_user.id,
                User.is_deleted == False,
            )
        )
        if conflict:
            raise ApiError(
                status_code=409,
                code="EMAIL_CONFLICT",
                message=Messages.EMAIL_EXISTS,
            )
    if data.phone is not None:
        conflict = await db.scalar(
            select(User).where(
                User.phone == data.phone,
                User.id != current_user.id,
                User.is_deleted == False,
            )
        )
        if conflict:
            raise ApiError(
                status_code=409,
                code="PHONE_CONFLICT",
                message=Messages.PHONE_EXISTS,
            )
    if data.display_name is not None:
        current_user.display_name = data.display_name
    if data.email is not None:
        current_user.email = data.email
    if data.phone is not None:
        current_user.phone = data.phone
    await db.commit()
    roles = await get_user_roles(db, current_user.id)
    return success(request, user_service._user_to_response(current_user, roles))


@router.post("/me/password", summary="修改个人密码")
async def change_own_password(
    request: Request,
    data: PasswordChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(data.old_password, current_user.password_hash):
        raise ApiError(
            status_code=401,
            code="INVALID_PASSWORD",
            message="当前密码不正确",
        )
    try:
        validate_password(data.new_password)
    except ValueError as e:
        raise ApiError(status_code=400, code="VALIDATION_ERROR", message=str(e)) from e
    current_user.password_hash = hash_password(data.new_password)
    await db.commit()
    return success(request, {"message": "密码已更新"})


@router.put("/{user_id}", summary="修改用户信息")
async def update_user(
    request: Request,
    user_id: uuid.UUID,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_codes = getattr(current_user, "_permission_codes", set())
    if "user:update" not in user_codes:
        raise ApiError(
            status_code=403,
            code="PERMISSION_DENIED",
            message=Messages.PERMISSION_DENIED,
        )
    if data.role_ids is not None and "user:assign_role" not in user_codes:
        raise ApiError(
            status_code=403,
            code="PERMISSION_DENIED",
            message=Messages.PERMISSION_DENIED,
        )
    result = await user_service.update_user(db, user_id, data, current_user)
    return success(request, result)


@router.delete("/{user_id}", status_code=204, summary="删除用户")
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_permissions("user:delete"),
):
    await user_service.delete_user(db, user_id, current_user.id)
    return Response(status_code=204)


@router.patch("/{user_id}/status", summary="修改用户状态")
async def update_user_status(
    request: Request,
    user_id: uuid.UUID,
    data: UserStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_permissions("user:status"),
):
    result = await user_service.update_status(db, user_id, data.status, current_user.id)
    return success(request, result)


@router.post("/{user_id}/reset-password", summary="重置用户密码")
async def reset_user_password(
    request: Request,
    user_id: uuid.UUID,
    data: PasswordReset,
    db: AsyncSession = Depends(get_db),
    current_user: User = require_permissions("user:reset_password"),
):
    await user_service.reset_password(db, user_id, data.password)
    return success(request, {"message": "Password reset successful"})
