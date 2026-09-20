from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user, require_super_admin
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.feishu_token import FeishuToken
from app.models.rbac import User
from app.schemas.common import success
from app.services.feishu.client import FeishuClient
from app.services.feishu.config_service import FeishuConfigService
from app.services.feishu.credentials import get_feishu_credentials
from app.services.feishu.crypto import decrypt_token, derive_token_key, encrypt_token
from app.services.feishu.oauth import build_authorize_url

router = APIRouter(tags=["Feishu"])

logger = logging.getLogger("app.feishu")


class FeishuConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    app_id: str = Field(min_length=1, max_length=128)
    app_secret: str = Field(min_length=1, max_length=256)


class FeishuConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    app_id: str | None = Field(default=None, min_length=1, max_length=128)
    app_secret: str | None = Field(default=None, min_length=1, max_length=256)


def _config_view(config) -> dict:
    return {
        "id": str(config.id),
        "name": config.name,
        "app_id_mask": config.app_id[:6],
        "is_default": config.is_default,
    }


@router.get("/configs/status")
async def feishu_config_status(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    config = await FeishuConfigService.get_default(db)
    if config is None:
        return success(request, {"configured": False, "app_id": None})
    return success(request, {"configured": True, "app_id": config.app_id})


@router.get("/configs")
async def feishu_config_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    configs = await FeishuConfigService.list_all(db)
    return success(request, {"configs": [_config_view(c) for c in configs]})


@router.post("/configs")
async def feishu_config_create(
    request: Request,
    data: FeishuConfigCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
):
    config = await FeishuConfigService.create(db, data.name, data.app_id, data.app_secret)
    await db.commit()
    return success(request, _config_view(config))


@router.put("/configs/{config_id}")
async def feishu_config_update(
    request: Request,
    config_id: uuid.UUID,
    data: FeishuConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
):
    config = await FeishuConfigService.update(
        db, config_id, data.name, data.app_id, data.app_secret
    )
    if config is None:
        raise ApiError(status_code=404, code="CONFIG_NOT_FOUND", message="飞书配置不存在")
    await db.commit()
    return success(request, _config_view(config))


@router.delete("/configs/{config_id}")
async def feishu_config_delete(
    request: Request,
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
):
    ok = await FeishuConfigService.delete(db, config_id)
    if not ok:
        raise ApiError(status_code=404, code="CONFIG_NOT_FOUND", message="飞书配置不存在")
    await db.commit()
    return success(request, {"deleted": True})


@router.post("/configs/{config_id}/activate")
async def feishu_config_activate(
    request: Request,
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
):
    ok = await FeishuConfigService.activate(db, config_id)
    if not ok:
        raise ApiError(status_code=404, code="CONFIG_NOT_FOUND", message="飞书配置不存在")
    await db.commit()
    return success(request, {"activated": True})


@router.get("/oauth/start")
async def feishu_oauth_start(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    app_id, _ = await get_feishu_credentials()
    if not app_id:
        raise ApiError(status_code=503, code="FEISHU_NOT_CONFIGURED", message="飞书应用未配置")
    state = secrets.token_urlsafe(32)
    url = build_authorize_url(app_id, state)
    return success(request, {"authorize_url": url, "state": state})


@router.get("/oauth/callback")
async def feishu_oauth_callback(
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """OAuth 回调：飞书跳转回来，用 code 换 user_access_token 并存库。

    用户通过浏览器跳转访问此端点，携带 JWT cookie（get_current_user 自动识别用户）。
    无论成功失败都重定向回前端页面（前端读 ?feishu=connected / ?feishu=error 提示）。
    """
    settings = get_settings()
    frontend_base = (
        settings.cors_origins.split(",")[0].strip()
        if settings.cors_origins
        else "http://localhost:3000"
    )

    if not code:
        return RedirectResponse(
            url=f"{frontend_base}/agent?feishu=error=missing_code", status_code=302
        )
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        return RedirectResponse(
            url=f"{frontend_base}/agent?feishu=error=not_configured", status_code=302
        )

    client = FeishuClient()
    try:
        token_data = await client.exchange_code(code)
    except Exception:
        return RedirectResponse(
            url=f"{frontend_base}/agent?feishu=error=exchange_failed", status_code=302
        )

    data = token_data.get("data", token_data)
    access_token = data.get("access_token")
    if not access_token:
        return RedirectResponse(
            url=f"{frontend_base}/agent?feishu=error=no_token", status_code=302
        )

    key = derive_token_key(settings.feishu_token_encryption_key or settings.jwt_secret)

    existing = await db.scalar(
        select(FeishuToken).where(FeishuToken.owner_user_id == current_user.id)
    )
    now = datetime.now(UTC)
    expires_in = data.get("expires_in", 7200)

    if existing is None:
        existing = FeishuToken(
            owner_user_id=current_user.id,
            access_token=encrypt_token(access_token, key),
            refresh_token=encrypt_token(data["refresh_token"], key) if data.get("refresh_token") else None,
            expires_at=now + timedelta(seconds=expires_in),
            open_id=data.get("open_id"),
        )
        db.add(existing)
    else:
        existing.access_token = encrypt_token(access_token, key)
        if data.get("refresh_token"):
            existing.refresh_token = encrypt_token(data["refresh_token"], key)
        existing.expires_at = now + timedelta(seconds=expires_in)
        if data.get("open_id"):
            existing.open_id = data.get("open_id")
        existing.updated_at = now
        db.add(existing)

    await db.commit()

    return RedirectResponse(
        url=f"{frontend_base}/agent?feishu=connected=true", status_code=302
    )


@router.get("/status")
async def feishu_status(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token = await db.scalar(
        select(FeishuToken).where(FeishuToken.owner_user_id == current_user.id)
    )
    if token is None:
        return success(request, {"connected": False})
    return success(request, {"connected": True, "open_id": token.open_id})


@router.delete("/connection")
async def feishu_disconnect(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token = await db.scalar(
        select(FeishuToken).where(FeishuToken.owner_user_id == current_user.id)
    )
    if token is not None:
        settings = get_settings()
        key = derive_token_key(settings.feishu_token_encryption_key or settings.jwt_secret)
        client = FeishuClient()
        try:
            await client.revoke_token(decrypt_token(token.access_token, key))
        except Exception:
            logger.warning("feishu_revoke_failed", exc_info=True)
        await db.delete(token)
        await db.commit()
    return success(request, {"connected": False})
