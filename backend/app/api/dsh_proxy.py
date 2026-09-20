from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.rbac import User
from app.services.dsh import get_manager
from app.services.dsh.proxy import http_proxy, ws_proxy

router = APIRouter(tags=["DSH proxy"])


def _raise_if_not_owner(user_id: str, current_user: User) -> None:
    if str(current_user.id) != user_id:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "资源不存在")


async def _running_instance(user_id: str, manager, db: AsyncSession):
    instance = await manager.check_alive(user_id, db)
    if instance is None or instance.state != "running":
        raise ApiError(404, "RESOURCE_NOT_FOUND", "资源不存在")
    return instance


@router.api_route(
    "/dsh-proxy/{user_id}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def dsh_http_proxy(
    user_id: str,
    path: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    manager=Depends(get_manager),
    db: AsyncSession = Depends(get_db),
):
    _raise_if_not_owner(user_id, current_user)
    instance = await _running_instance(current_user.id, manager, db)
    try:
        response = await http_proxy(
            user_id=user_id,
            port=instance.port,
            path=path,
            query=request.url.query,
            method=request.method,
            request_headers=dict(request.headers),
            body=await request.body(),
        )
    except httpx.HTTPError as exc:
        raise ApiError(502, "BAD_GATEWAY", "upstream unreachable") from exc
    await manager.touch(current_user.id, db)
    return response


@router.websocket("/dsh-proxy/{user_id}/{path:path}")
async def dsh_ws_proxy(
    websocket: WebSocket,
    user_id: str,
    path: str,
    manager=Depends(get_manager),
    db: AsyncSession = Depends(get_db),
):
    request = Request(websocket.scope, websocket.receive)
    try:
        user = await get_current_user(request, db)
    except ApiError:
        await websocket.close(code=1008)
        return
    if str(user.id) != user_id:
        await websocket.close(code=1008)
        return
    instance = await manager.check_alive(user.id, db)
    if instance is None or instance.state != "running":
        await websocket.close(code=1008)
        return
    await ws_proxy(websocket, port=instance.port, path=path, query=websocket.url.query)
    await manager.touch(user.id, db)
