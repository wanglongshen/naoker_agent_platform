import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_super_admin
from app.core.csrf import require_csrf
from app.db.session import get_db
from app.models.agent import (
    AgentRun,
    AgentRunAttempt,
    AgentRunEvent,
    AgentSession,
    AgentStep,
)
from app.models.rbac import User, Role, UserRole
from app.repositories.agent_repository import AgentRepository
from app.schemas.agent import (
    AgentAttemptListResponse,
    AgentAttemptResponse,
    AgentAuditCursorPage,
    AgentAuditEvent,
    AgentRunEventResponse,
    AgentRunResponse,
    AgentSessionListResponse,
    AgentSessionResponse,
    AgentStepListResponse,
    AgentStepResponse,
    AuditOwnerSummary,
    AuditSessionTranscriptResponse,
    AuditTranscriptTurn,
)
from app.schemas.common import success

router = APIRouter(tags=["Agent Audit"])

SENSITIVE_PAYLOAD_KEYS = {
    "authorization",
    "token",
    "secret",
    "cookie",
    "password",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "attachment_content",
    "attachment_text",
    "raw_prompt",
    "raw_response",
    "raw_content",
    "system_prompt",
    "user_prompt",
    "messages",
    "content",
    "model_output",
    "tool_content",
}


def _redact_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return payload
    redacted = {}
    for key, value in payload.items():
        if key in SENSITIVE_PAYLOAD_KEYS:
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = _redact_payload(value)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_payload(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted


def to_audit_event(event: AgentRunEvent) -> AgentAuditEvent:
    return AgentAuditEvent(
        id=event.id,
        run_id=event.run_id,
        attempt_id=event.attempt_id,
        seq=event.seq,
        event_type=event.event_type,
        payload=_redact_payload(event.payload),
        created_at=event.created_at,
    )


@router.get("/sessions")
async def list_audit_sessions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    count_stmt = select(func.count()).select_from(AgentSession)
    items_stmt = select(
        AgentSession, func.coalesce(User.display_name, "").label("owner_display_name")
    ).join(
        User, AgentSession.owner_user_id == User.id, isouter=True
    ).order_by(AgentSession.updated_at.desc())
    if user_id is not None:
        count_stmt = count_stmt.where(AgentSession.owner_user_id == user_id)
        items_stmt = items_stmt.where(AgentSession.owner_user_id == user_id)

    total = (await db.execute(count_stmt)).scalar_one()

    items_stmt = items_stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(items_stmt)
    rows = result.all()
    items = []
    for session, display_name in rows:
        session.owner_display_name = display_name
        items.append(session)

    return success(
        request,
        AgentSessionListResponse(
            items=[AgentSessionResponse.model_validate(s) for s in items],
            page=page,
            page_size=page_size,
            total=total,
        ).model_dump(mode="json"),
    )


@router.get("/sessions/{session_id}")
async def get_audit_session(
    request: Request,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    session_obj = await db.get(AgentSession, session_id)
    data = AgentSessionResponse.model_validate(session_obj).model_dump(mode="json") if session_obj else None
    return success(request, data)


@router.get("/sessions/{session_id}/runs")
async def list_audit_session_runs(
    request: Request,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    repo = AgentRepository(db)
    runs = await repo.list_runs_for_session(session_id)
    return success(
        request,
        [AgentRunResponse.model_validate(run).model_dump(mode="json") for run in runs],
    )


@router.get("/runs/{run_id}/attempts")
async def list_audit_run_attempts(
    request: Request,
    run_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    repo = AgentRepository(db)
    all_attempts = await repo.list_attempts(run_id)
    total = len(all_attempts)
    start = (page - 1) * page_size
    items = all_attempts[start : start + page_size]
    return success(
        request,
        AgentAttemptListResponse(
            items=[AgentAttemptResponse.model_validate(a) for a in items],
            page=page,
            page_size=page_size,
            total=total,
        ).model_dump(mode="json"),
    )


@router.get("/runs/{run_id}")
async def get_audit_run(
    request: Request,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    run = await db.get(AgentRun, run_id)
    data = AgentRunResponse.model_validate(run).model_dump(mode="json") if run else None
    return success(request, data)


@router.get("/runs/{run_id}/attempts/{attempt_id}/steps")
async def list_audit_steps(
    request: Request,
    run_id: uuid.UUID,
    attempt_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    count_stmt = (
        select(func.count())
        .select_from(AgentStep)
        .where(AgentStep.attempt_id == attempt_id)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    result = await db.execute(
        select(AgentStep)
        .where(AgentStep.attempt_id == attempt_id)
        .order_by(AgentStep.step_number.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(result.scalars().all())

    return success(
        request,
        AgentStepListResponse(
            items=[AgentStepResponse.model_validate(s) for s in items],
            page=page,
            page_size=page_size,
            total=total,
        ).model_dump(mode="json"),
    )


@router.get("/runs/{run_id}/events")
async def list_audit_events(
    request: Request,
    run_id: uuid.UUID,
    after_seq: int | None = Query(None, alias="cursor"),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    stmt = select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)
    if after_seq is not None:
        stmt = stmt.where(AgentRunEvent.seq > after_seq)
    stmt = stmt.order_by(AgentRunEvent.seq.asc()).limit(page_size)
    result = await db.execute(stmt)
    events = list(result.scalars().all())

    items = [to_audit_event(e).model_dump(mode="json") for e in events]
    next_seq = events[-1].seq if events else None

    return success(request, {"items": items, "next_seq": next_seq})


@router.get("/sessions/{session_id}/transcript")
async def get_audit_session_transcript(
    request: Request,
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    session_obj = await db.get(AgentSession, session_id)
    if session_obj is None:
        from app.core.errors import ApiError
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="资源不存在")

    owner = await db.get(User, session_obj.owner_user_id)
    if owner is None:
        from app.core.errors import ApiError
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="资源不存在")

    roles_result = await db.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == owner.id,
            Role.status == "active",
            Role.is_deleted.is_(False),
        )
    )
    owner_roles = list(roles_result.scalars().all())

    repo = AgentRepository(db)
    runs = await repo.list_runs_for_session(session_id)

    turns: list[AuditTranscriptTurn] = []
    for run in runs:
        attempts = await repo.list_attempts(run.id)
        all_steps: list[AgentStep] = []
        for attempt in attempts:
            steps = await repo.list_steps(attempt.id)
            all_steps.extend(steps)

        events = await repo.list_events(run.id)
        redacted_events = [
            AgentRunEventResponse(
                id=e.id,
                run_id=e.run_id,
                attempt_id=e.attempt_id,
                seq=e.seq,
                event_type=e.event_type,
                payload=_redact_payload(e.payload),
                created_at=e.created_at,
            )
            for e in events
        ]

        turns.append(
            AuditTranscriptTurn(
                run=AgentRunResponse.model_validate(run),
                steps=[AgentStepResponse.model_validate(s) for s in all_steps],
                events=redacted_events,
            )
        )

    data = AuditSessionTranscriptResponse(
        session=AgentSessionResponse.model_validate(session_obj),
        owner=AuditOwnerSummary(
            id=owner.id,
            username=owner.username,
            display_name=owner.display_name,
            roles=owner_roles,
        ),
        turns=turns,
    )

    return success(request, data.model_dump(mode="json"))
