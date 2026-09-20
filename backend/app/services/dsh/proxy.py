from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Mapping

import httpx
import websockets
from fastapi import WebSocket
from fastapi.responses import StreamingResponse

logger = logging.getLogger("dsh.proxy")

# 标准 hop-by-hop 头，按 RFC 9110 剥离；Host/Origin 必须原样保留（NOTES §5）。
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)


def _strip_hop_by_hop(headers: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}


def _upstream_url(proto: str, port: int, path: str, query: str) -> str:
    target = path.lstrip("/")
    url = f"{proto}://127.0.0.1:{port}/{target}"
    if query:
        url = f"{url}?{query}"
    return url


async def http_proxy(
    *,
    user_id: str,
    port: int,
    path: str,
    query: str,
    method: str,
    request_headers: Mapping[str, str],
    body: bytes,
) -> StreamingResponse:
    """HTTP 转发（含 SSE 流式）。透传状态/头/流，Host/Origin 不改写。"""
    url = _upstream_url("http", port, path, query)
    fwd_headers = _strip_hop_by_hop(request_headers)
    fwd_headers["X-Dsh-Platform-User"] = user_id

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=600.0, write=600.0, pool=10.0)
    )
    req = client.build_request(method, url, headers=fwd_headers, content=body)
    try:
        upstream = await client.send(req, stream=True)
    except httpx.TransportError:
        # 实例刚通过健康检查但可能还在 accept 窗口，单次短重试
        await asyncio.sleep(0.4)
        try:
            req2 = client.build_request(method, url, headers=fwd_headers, content=body)
            upstream = await client.send(req2, stream=True)
        except httpx.TransportError as exc2:
            await client.aclose()
            raise exc2
    resp_headers = _strip_hop_by_hop(dict(upstream.headers))

    async def body_stream() -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body_stream(), status_code=upstream.status_code, headers=resp_headers
    )


async def ws_proxy(
    websocket: WebSocket,
    *,
    port: int,
    path: str,
    query: str,
) -> None:
    """WebSocket 双向搬运；Host/Origin 原样带给上游（DSH 信任围栏依赖它们一致）。"""
    url = _upstream_url("ws", port, path, query)
    extra_headers: dict[str, str] = {}
    if websocket.headers.get("host"):
        extra_headers["Host"] = websocket.headers["host"]
    if websocket.headers.get("origin"):
        extra_headers["Origin"] = websocket.headers["origin"]

    try:
        upstream = await websockets.connect(
            url,
            additional_headers=extra_headers or None,
            max_size=None,
        )
    except Exception:
        logger.warning("ws upstream connect failed uid=%s", url, exc_info=True)
        await websocket.close(code=1011)
        return

    await websocket.accept()

    async def client_to_upstream() -> None:
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("text") is not None:
                    await upstream.send(msg["text"])
                elif msg.get("bytes") is not None:
                    await upstream.send(msg["bytes"])
        except (websockets.exceptions.ConnectionClosed, RuntimeError):
            pass

    async def upstream_to_client() -> None:
        try:
            async for message in upstream:
                if isinstance(message, str):
                    await websocket.send_text(message)
                else:
                    await websocket.send_bytes(message)
        except (websockets.exceptions.ConnectionClosed, RuntimeError):
            pass

    done, pending = await asyncio.wait(
        {
            asyncio.create_task(client_to_upstream()),
            asyncio.create_task(upstream_to_client()),
        },
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    await upstream.close()
    try:
        await websocket.close()
    except RuntimeError:
        pass
