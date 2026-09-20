from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user
from app.core.errors import ApiError
from app.models.rbac import User
from app.schemas.common import success
from app.services.agent.web_cookie_store import (
    delete_user_cookie,
    list_user_cookies,
    save_user_cookie,
)

router = APIRouter(tags=["Agent Cookies"])


class CookieSaveRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=256)
    cookie_string: str = Field(min_length=1, max_length=10000)


class CookieImportItem(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=8192)
    domain: str = Field(min_length=1, max_length=256)


class CookieImportRequest(BaseModel):
    cookies: list[CookieImportItem] = Field(min_length=1, max_length=500)


_ALLOWED_COOKIE_HOSTS = ("douyin.com", "xiaohongshu.com")


def _platform_for_domain(domain: str) -> str | None:
    d = domain.strip().lower().lstrip(".")
    if d == "douyin.com" or d.endswith(".douyin.com"):
        return "douyin"
    if d == "xiaohongshu.com" or d.endswith(".xiaohongshu.com"):
        return "xiaohongshu"
    return None


@router.post("/cookies/import")
async def import_cookies(
    request: Request,
    data: CookieImportRequest,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    from app.services.agent.login_session import DOMAIN_BY_PLATFORM, cookies_to_string

    grouped: dict[str, list[dict]] = {}
    for c in data.cookies:
        platform = _platform_for_domain(c.domain)
        if platform is None:
            continue
        grouped.setdefault(platform, []).append({"name": c.name, "value": c.value})
    if not grouped:
        raise ApiError(
            status_code=422,
            code="INVALID_COOKIES",
            message="未找到有效的抖音/小红书 Cookie（检查 domain 是否包含 douyin.com 或 xiaohongshu.com）",
        )
    saved: dict[str, int] = {}
    for platform, pairs in grouped.items():
        cookie_str = cookies_to_string(pairs)
        await save_user_cookie(current_user.id, DOMAIN_BY_PLATFORM[platform], cookie_str)
        saved[platform] = len(pairs)
    return success(request, {"saved": saved})


@router.put("/cookies")
async def save_cookie(
    request: Request,
    data: CookieSaveRequest,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    domain = data.domain.strip().lower()
    if " " in domain or "/" in domain:
        raise ApiError(status_code=422, code="INVALID_DOMAIN", message="域名格式不正确")
    await save_user_cookie(current_user.id, domain, data.cookie_string)
    return success(request, {"saved": True, "domain": domain})


@router.get("/cookies")
async def get_cookies(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    cookies = await list_user_cookies(current_user.id)
    return success(request, {"items": cookies})


@router.delete("/cookies/{domain}")
async def delete_cookie(
    request: Request,
    domain: str,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    deleted = await delete_user_cookie(current_user.id, domain)
    return success(request, {"deleted": deleted})
