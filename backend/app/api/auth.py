from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.csrf import issue_csrf_token, require_csrf
from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.rbac import User
from app.schemas.auth import LoginRequest
from app.schemas.common import success
from app.services.auth_service import authenticate_user, get_assignable_roles, get_user_permissions, get_user_roles
from app.services.avatar_service import avatar_url_for

router = APIRouter(tags=["认证管理"])
me_router = APIRouter(tags=["认证管理"])
settings = get_settings()


class SyncFeishuRequest(BaseModel):
    enabled: bool


@router.post("/login", summary="用户登录")
async def login(request: Request, data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, data.username, data.password)
    token = create_access_token(user)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.jwt_expire_minutes * 60,
    )
    return success(request, {"message": "Login successful"})


@router.post("/logout", summary="用户登出")
async def logout(response: Response):
    response.delete_cookie(key="access_token")
    response.status_code = 204
    return response


@router.get("/me", summary="获取当前用户信息")
async def me(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    roles = await get_user_roles(db, current_user.id)
    permissions = await get_user_permissions(db, current_user.id)

    result = {
        "id": str(current_user.id),
        "username": current_user.username,
        "display_name": current_user.display_name,
        "roles": roles,
        "permissions": permissions,
        "menu_permissions": permissions,
        "avatar_url": avatar_url_for(current_user),
        "sync_feishu_enabled": current_user.sync_feishu_enabled,
    }

    if "user:assign_role" in permissions:
        result["assignable_roles"] = await get_assignable_roles(db, current_user)

    return success(request, result)


@router.get("/csrf", summary="获取 CSRF Token")
async def get_csrf_token(request: Request, current_user: User = Depends(get_current_user)):
    token = issue_csrf_token(str(current_user.id))
    return success(request, {"token": token})


@me_router.put("/me/sync-feishu", summary="切换生成记录同步到飞书")
async def update_sync_feishu(
    request: Request,
    data: SyncFeishuRequest,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    current_user.sync_feishu_enabled = data.enabled
    await db.commit()
    return success(request, {"sync_feishu_enabled": data.enabled})
