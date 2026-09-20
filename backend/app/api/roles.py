import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_permissions
from app.core.errors import ApiError
from app.core.messages import Messages
from app.db.session import get_db
from app.models.rbac import User
from app.schemas.common import success
from app.schemas.role import RoleCreate, RoleStatusUpdate, RoleUpdate
from app.services import role_service

router = APIRouter(tags=["角色管理"])


@router.get("", summary="查询角色列表")
async def list_roles(
    request: Request,
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = require_permissions("role:read"),
):
    result = await role_service.list_roles(
        db, keyword=keyword, status=status, page=page, page_size=page_size
    )
    return success(request, result)


@router.get("/{role_id}", summary="查询角色详情")
async def get_role_detail(
    request: Request,
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_permissions("role:read"),
):
    result = await role_service.get_role_detail(db, role_id)
    return success(request, result)


@router.post("", status_code=201, summary="新建角色")
async def create_role(
    request: Request,
    data: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_codes = getattr(current_user, "_permission_codes", set())
    if "role:create" not in user_codes:
        raise ApiError(
            status_code=403,
            code="PERMISSION_DENIED",
            message=Messages.PERMISSION_DENIED,
        )
    if data.permission_ids and "role:assign_permission" not in user_codes:
        raise ApiError(
            status_code=403,
            code="PERMISSION_DENIED",
            message=Messages.PERMISSION_DENIED,
        )
    result = await role_service.create_role(db, data)
    return success(request, result)


@router.put("/{role_id}", summary="修改角色信息")
async def update_role(
    request: Request,
    role_id: uuid.UUID,
    data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_codes = getattr(current_user, "_permission_codes", set())
    if "role:update" not in user_codes:
        raise ApiError(
            status_code=403,
            code="PERMISSION_DENIED",
            message=Messages.PERMISSION_DENIED,
        )
    if data.permission_ids is not None and "role:assign_permission" not in user_codes:
        raise ApiError(
            status_code=403,
            code="PERMISSION_DENIED",
            message=Messages.PERMISSION_DENIED,
        )
    result = await role_service.update_role(db, role_id, data)
    return success(request, result)


@router.patch("/{role_id}/status", summary="修改角色状态")
async def update_role_status(
    request: Request,
    role_id: uuid.UUID,
    data: RoleStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = require_permissions("role:status"),
):
    result = await role_service.update_role_status(db, role_id, data.status)
    return success(request, result)


@router.delete("/{role_id}", status_code=204, summary="删除角色")
async def delete_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = require_permissions("role:delete"),
):
    await role_service.delete_role(db, role_id)
    return Response(status_code=204)


permissions_router = APIRouter(tags=["权限管理"])


@permissions_router.get("", summary="查询权限字典")
async def list_permissions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = require_permissions("role:read"),
):
    result = await role_service.list_permissions(db)
    return success(request, result)
