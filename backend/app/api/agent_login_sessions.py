from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user
from app.core.errors import ApiError
from app.models.rbac import User
from app.schemas.common import success

router = APIRouter(tags=["Agent Login Sessions"])


class LoginSessionStartRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=50)


def _worker_url() -> str:
    return get_settings().web_renderer_url.rstrip("/")


def _map_status(status_code: int, detail: str) -> ApiError:
    if status_code == 409:
        return ApiError(status_code=409, code="ACTIVE_SESSION", message="已有进行中的登录，请先完成或取消")
    if status_code == 403:
        return ApiError(status_code=403, code="FORBIDDEN", message="无权访问该登录会话")
    if status_code == 404:
        return ApiError(status_code=404, code="SESSION_NOT_FOUND", message="登录会话不存在或已结束")
    if status_code == 422:
        msg = detail
        if msg.startswith("verify_rejected:"):
            msg = msg[len("verify_rejected:") :]
        return ApiError(status_code=422, code="INVALID_REQUEST", message=msg or "请求参数错误")
    return ApiError(status_code=422, code="INVALID_REQUEST", message=detail or "请求参数错误")


@router.post("/login-sessions")
async def start_login_session(
    request: Request,
    data: LoginSessionStartRequest,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{_worker_url()}/login-sessions",
                json={"platform": data.platform, "owner_user_id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())


@router.get("/login-sessions/{session_id}/frame")
async def get_login_frame(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{_worker_url()}/login-sessions/{session_id}/frame",
                headers={"X-Owner-User-Id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())


@router.get("/login-sessions/{session_id}/status")
async def get_login_status(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{_worker_url()}/login-sessions/{session_id}/status",
                headers={"X-Owner-User-Id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())


@router.post("/login-sessions/{session_id}/phone")
async def submit_login_phone(
    request: Request,
    session_id: str,
    data: dict,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    phone = str(data.get("phone", "")).strip()
    if not phone:
        raise ApiError(status_code=422, code="INVALID_REQUEST", message="手机号不能为空")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{_worker_url()}/login-sessions/{session_id}/phone",
                json={"phone": phone},
                headers={"X-Owner-User-Id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())


@router.post("/login-sessions/{session_id}/verify")
async def submit_login_code(
    request: Request,
    session_id: str,
    data: dict,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    code = str(data.get("code", "")).strip()
    if not code:
        raise ApiError(status_code=422, code="INVALID_REQUEST", message="验证码不能为空")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{_worker_url()}/login-sessions/{session_id}/verify",
                json={"code": code},
                headers={"X-Owner-User-Id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())


@router.post("/login-sessions/{session_id}/refresh")
async def refresh_login_session(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{_worker_url()}/login-sessions/{session_id}/refresh",
                headers={"X-Owner-User-Id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())


@router.delete("/login-sessions/{session_id}")
async def delete_login_session(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.delete(
                f"{_worker_url()}/login-sessions/{session_id}",
                headers={"X-Owner-User-Id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())
