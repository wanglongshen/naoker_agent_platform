from __future__ import annotations

import sys
import uuid
from typing import Any, Literal

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.agent.login_session import (
    LoginSessionManager,
    SessionConflictError,
    LoginSessionError,
    SessionNotFoundError,
    SessionNotOwnerError,
)
from app.services.agent.web_renderer import fetch_note_detail, render_page, search_platform

app = FastAPI(title="Web Renderer")
manager = LoginSessionManager()


class RenderRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    cookies: list[dict[str, Any]] | None = None
    timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)


@app.post("/render")
async def render(req: RenderRequest) -> dict:
    try:
        result = await render_page(req.url, req.cookies, req.timeout_seconds)
        result["error"] = None
        return result
    except Exception as exc:
        return {"title": "", "text": "", "url": req.url, "status_code": 0, "error": str(exc)[:500]}


class SearchRequest(BaseModel):
    platform: Literal["xiaohongshu", "douyin"]
    keyword: str = Field(min_length=1, max_length=50)
    max_results: int = Field(default=30, ge=1, le=50)
    cookies: list[dict[str, Any]] | None = None


class NoteDetailRequest(BaseModel):
    platform: str = Field(pattern="^(xiaohongshu|douyin)$")
    url: str = Field(min_length=1, max_length=2000)
    cookies: list[dict] | None = None


_ALLOWED_DETAIL_HOSTS = ("www.xiaohongshu.com", "www.douyin.com", "xiaohongshu.com", "douyin.com")


def _validate_detail_url(url: str) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("unsupported_url_scheme")
    host = (parsed.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in _ALLOWED_DETAIL_HOSTS):
        raise ValueError("unsupported_url_host")


@app.post("/search")
async def search(req: SearchRequest) -> dict:
    from app.core.config import get_settings

    timeout_seconds = get_settings().web_renderer_search_timeout_seconds
    try:
        result = await search_platform(
            req.platform,
            req.keyword,
            req.max_results,
            req.cookies,
            timeout_seconds=timeout_seconds,
        )
        result["error"] = None
        return result
    except Exception as exc:
        return {
            "samples": [],
            "sample_count": 0,
            "login_required": False,
            "platform": req.platform,
            "error": str(exc)[:500],
        }


@app.post("/detail")
async def note_detail(req: NoteDetailRequest) -> dict:
    from app.core.config import get_settings

    try:
        _validate_detail_url(req.url)
    except ValueError as exc:
        return {
            "platform": req.platform,
            "url": req.url,
            "title": None,
            "content": None,
            "published_at": None,
            "like_count": None,
            "collect_count": None,
            "comment_count": None,
            "topic_tags": [],
            "author": None,
            "image_urls": [],
            "login_required": False,
            "error": str(exc),
        }
    timeout = get_settings().web_renderer_search_timeout_seconds
    try:
        result = await fetch_note_detail(
            req.platform, req.url, req.cookies, timeout_seconds=timeout
        )
        result["error"] = result.get("error") or None
        return result
    except Exception as exc:
        return {
            "platform": req.platform,
            "url": req.url,
            "title": None,
            "content": None,
            "published_at": None,
            "like_count": None,
            "collect_count": None,
            "comment_count": None,
            "topic_tags": [],
            "author": None,
            "image_urls": [],
            "login_required": False,
            "error": f"internal: {type(exc).__name__}: {str(exc)[:200]}",
        }


class LoginSessionStartRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=50)
    owner_user_id: str = Field(min_length=1, max_length=64)


def _owner_id(x_owner_user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(x_owner_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_owner") from exc


@app.post("/login-sessions")
async def start_login_session(req: LoginSessionStartRequest) -> dict:
    try:
        record = await manager.start(_owner_id(req.owner_user_id), req.platform)
    except SessionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LoginSessionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"session_id": record.session_id, "status": record.status}


@app.get("/login-sessions/{session_id}/frame")
async def login_session_frame(session_id: str, x_owner_user_id: str = Header(...)) -> dict:
    try:
        image = await manager.frame(session_id, _owner_id(x_owner_user_id))
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotOwnerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"image": image}


@app.get("/login-sessions/{session_id}/status")
async def login_session_status(session_id: str, x_owner_user_id: str = Header(...)) -> dict:
    try:
        return await manager.status(session_id, _owner_id(x_owner_user_id))
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotOwnerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/login-sessions/{session_id}/refresh")
async def login_session_refresh(session_id: str, x_owner_user_id: str = Header(...)) -> dict:
    try:
        await manager.refresh(session_id, _owner_id(x_owner_user_id))
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotOwnerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"refreshed": True}


@app.post("/login-sessions/{session_id}/phone")
async def login_session_phone(
    session_id: str,
    payload: dict,
    x_owner_user_id: str = Header(...),
) -> dict:
    phone = str(payload.get("phone", "")).strip()
    if not phone:
        raise HTTPException(status_code=422, detail="phone_required")
    try:
        return await manager.submit_phone(session_id, _owner_id(x_owner_user_id), phone)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotOwnerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LoginSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/login-sessions/{session_id}/verify")
async def login_session_verify(
    session_id: str,
    payload: dict,
    x_owner_user_id: str = Header(...),
) -> dict:
    code = str(payload.get("code", "")).strip()
    if not code:
        raise HTTPException(status_code=422, detail="code_required")
    try:
        return await manager.submit_code(session_id, _owner_id(x_owner_user_id), code)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotOwnerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LoginSessionError as exc:
        detail = str(exc)
        if detail.startswith("verify_rejected:"):
            raise HTTPException(status_code=422, detail=detail) from exc
        raise HTTPException(status_code=404, detail=detail) from exc


@app.delete("/login-sessions/{session_id}")
async def login_session_delete(session_id: str, x_owner_user_id: str = Header(...)) -> dict:
    try:
        await manager.close(session_id, _owner_id(x_owner_user_id))
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotOwnerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"deleted": True}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    if sys.platform == "win32":
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # 0.0.0.0：容器内其他服务（backend/worker）需经 WEB_RENDERER_URL 访问本服务，
    # 127.0.0.1 只在单机本地可用，跨容器不可达（无宿主端口映射，外部仍不可访问）
    uvicorn.run(app, host="0.0.0.0", port=9001)
