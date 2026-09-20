import logging
import time
from uuid import uuid4

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("app")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._extract_forwarded_request_id(scope) or str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = time.perf_counter()

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"x-request-id"] = request_id.encode()
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_wrapper)

        if scope["type"] == "http":
            from urllib.parse import urlparse
            path = urlparse(scope.get("path", "")).path
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.info(
                "request_complete",
                extra={
                    "request_id": request_id,
                    "method": scope.get("method", ""),
                    "path": path,
                    "elapsed_ms": elapsed_ms,
                },
            )

    @staticmethod
    def _extract_forwarded_request_id(scope: Scope) -> str | None:
        for key, value in scope.get("headers", []):
            if key != b"x-request-id":
                continue
            try:
                raw = value.decode("utf-8")
            except UnicodeDecodeError:
                return None
            raw = raw.strip()
            if not raw or len(raw) > 128:
                return None
            if not all(ch.isalnum() or ch in "-_." for ch in raw):
                return None
            return raw
        return None
