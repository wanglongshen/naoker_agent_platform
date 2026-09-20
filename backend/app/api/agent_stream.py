from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from jose import JWTError
from pydantic import ValidationError
from sqlalchemy import select as sa_select

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.messages import Messages
from app.core.security import decode_access_token
from app.db.session import async_session_factory
from app.models.agent import AgentRun, AgentRunEvent
from app.models.rbac import User
from app.schemas.agent import AgentRunEventResponse
from app.services.agent.event_bus import event_bus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent Stream"])

settings = get_settings()

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "completed"}
HEARTBEAT_INTERVAL = 30.0
CATCH_UP_LIMIT = 200


def _parse_after_seq(cursor: str | None) -> int | None:
    if cursor is None:
        return None
    try:
        return int(cursor)
    except ValueError:
        raise ApiError(
            status_code=400,
            code="INVALID_CURSOR",
            message="无效的事件游标",
        )


def _encode_sse_event(event: object) -> str | None:
    try:
        payload = AgentRunEventResponse.model_validate(event).model_dump(mode="json")
    except ValidationError:
        return None
    return f"id: {payload['seq']}\nevent: {payload['event_type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _validate_origin(request: Request) -> None:
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    allowed = [o.strip() for o in settings.cors_origins.split(",")]
    parsed_origin = None
    allowed_origins = set()
    try:
        origin_parts = urlsplit(origin)
        parsed_origin = (
            origin_parts.scheme,
            origin_parts.hostname,
            origin_parts.port,
        )
    except ValueError:
        pass

    for allowed_origin in allowed:
        try:
            parts = urlsplit(allowed_origin)
            if parts.scheme and parts.hostname:
                allowed_origins.add((parts.scheme, parts.hostname, parts.port))
        except ValueError:
            continue

    if parsed_origin not in allowed_origins:
        raise ApiError(
            status_code=403,
            code="CSRF_VALIDATION_FAILED",
            message="无效的请求来源",
        )


async def _authenticate_and_authorize(request: Request, run_id: uuid.UUID) -> AgentRun:
    token = request.cookies.get("access_token")
    if not token:
        raise ApiError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message=Messages.AUTH_EXPIRED,
        )

    try:
        payload = decode_access_token(token)
    except (JWTError, ValueError):
        raise ApiError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message=Messages.AUTH_EXPIRED,
        )

    user_id = uuid.UUID(payload.sub)

    async with async_session_factory() as session:
        user = await session.scalar(
            sa_select(User).where(
                User.id == user_id,
                User.is_deleted == False,
                User.status == "active",
            )
        )
        if user is None:
            raise ApiError(
                status_code=401,
                code="AUTHENTICATION_REQUIRED",
                message=Messages.ACCOUNT_DISABLED,
            )

        run = await session.scalar(
            sa_select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.owner_user_id == user_id,
            )
        )
        if run is None:
            raise ApiError(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                message="资源不存在",
            )

        return run


async def _events_after(
    run_id: uuid.UUID, after_seq: int | None, limit: int = CATCH_UP_LIMIT
) -> list[AgentRunEvent]:
    async with async_session_factory() as session:
        result = await session.execute(
            sa_select(AgentRunEvent)
            .where(
                AgentRunEvent.run_id == run_id,
                AgentRunEvent.seq > after_seq if after_seq is not None else True,
            )
            .order_by(AgentRunEvent.seq.asc())
            .limit(limit)
        )
        return list(result.scalars().all())


@router.get("/runs/{run_id}/stream")
async def stream_run_events(
    request: Request,
    run_id: uuid.UUID,
) -> StreamingResponse:
    run = await _authenticate_and_authorize(request, run_id)
    _validate_origin(request)

    last_event_id = request.headers.get("last-event-id")
    after_seq = request.query_params.get("after_seq")
    after_seq_val = _parse_after_seq(last_event_id or after_seq)

    async def event_generator():
        last_seen_seq = after_seq_val
        subscriber_id = None

        try:
            subscriber_id, queue = await event_bus.subscribe(run_id)

            replay_events = await _events_after(run_id, after_seq_val)
            replay_count = len(replay_events)
            for i, event in enumerate(replay_events):
                encoded = _encode_sse_event(event)
                if encoded is None:
                    continue
                last_seen_seq = event.seq
                yield encoded
                print(f"[SSE-DIAG] sent event seq={event.seq} type={event.event_type} at {datetime.now(timezone.utc).isoformat()}", flush=True)
                if i < replay_count - 1:
                    await asyncio.sleep(0.012)

            has_pending = False
            try:
                item = queue.get_nowait()
                has_pending = True
            except asyncio.QueueEmpty:
                pass

            if has_pending:
                while True:
                    if item is not None:
                        item_seq = getattr(item, "seq", None)
                        if item_seq is not None and (last_seen_seq is None or item_seq > last_seen_seq):
                            encoded = _encode_sse_event(item)
                            if encoded is not None:
                                last_seen_seq = item_seq
                                yield encoded
                                print(f"[SSE-DIAG] live event seq={item_seq} at {datetime.now(timezone.utc).isoformat()}", flush=True)
                    item = None
                    try:
                        item = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

            while True:
                while True:
                    try:
                        item = queue.get_nowait()
                        item_seq = getattr(item, "seq", None)
                        if item_seq is None or (last_seen_seq is not None and item_seq <= last_seen_seq):
                            continue
                        encoded = _encode_sse_event(item)
                        if encoded is None:
                            continue
                        last_seen_seq = item_seq
                        yield encoded
                    except asyncio.QueueEmpty:
                        break

                async with async_session_factory() as session:
                    result = await session.execute(
                        sa_select(AgentRun.status).where(AgentRun.id == run_id)
                    )
                    status = result.scalar_one_or_none()
                if status is None or status in TERMINAL_STATUSES:
                    while True:
                        events = await _events_after(run_id, last_seen_seq)
                        advanced = False
                        for event in events:
                            encoded = _encode_sse_event(event)
                            if encoded is None: continue
                            last_seen_seq = event.seq
                            advanced = True
                            yield encoded
                        if not events or not advanced:
                            break
                    break

                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
                except asyncio.TimeoutError:
                    yield ":keepalive\n\n"
                    events = await _events_after(run_id, last_seen_seq)
                    for event in events:
                        encoded = _encode_sse_event(event)
                        if encoded is None: continue
                        last_seen_seq = event.seq
                        yield encoded
                    continue

                item_seq = getattr(item, "seq", None)
                if item_seq is None or (last_seen_seq is not None and item_seq <= last_seen_seq):
                    continue
                encoded = _encode_sse_event(item)
                if encoded is None: continue
                last_seen_seq = item_seq
                yield encoded

                while True:
                    try:
                        extra = queue.get_nowait()
                        extra_seq = getattr(extra, "seq", None)
                        if extra_seq is None or (last_seen_seq is not None and extra_seq <= last_seen_seq):
                            continue
                        encoded = _encode_sse_event(extra)
                        if encoded is None: continue
                        last_seen_seq = extra_seq
                        yield encoded
                    except asyncio.QueueEmpty:
                        break

                events = await _events_after(run_id, last_seen_seq)
                for event in events:
                    encoded = _encode_sse_event(event)
                    if encoded is None: continue
                    last_seen_seq = event.seq
                    yield encoded
        finally:
            if subscriber_id is not None:
                await event_bus.unsubscribe(run_id, subscriber_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

