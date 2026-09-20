import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user, get_owned_agent_session, get_owned_agent_run
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.agent import AgentAttachment
from app.models.file import FileFolder
from app.models.rbac import User
from app.repositories.agent_repository import AgentRepository
from app.schemas.agent import (
    AgentAttemptListResponse,
    AgentAttemptResponse,
    AgentRunAnswerRequest,
    AgentRunCreate,
    AgentRunEventListResponse,
    AgentRunEventResponse,
    AgentRunResponse,
    AgentSessionCreate,
    AgentSessionListResponse,
    AgentSessionPin,
    AgentSessionRename,
    AgentSessionResponse,
    AgentStepListResponse,
    AgentStepResponse,
    SessionProjectUpdate,
)
from app.schemas.common import success
from app.services.points import get_or_create_points

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent"])

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


async def _resolve_terminal_evidence(
    db: AsyncSession, run_id: uuid.UUID, raw_status: str
) -> str:
    if raw_status in TERMINAL_STATUSES:
        return "persisted_terminal"

    try:
        repo = AgentRepository(db)
        events = await repo.list_events(run_id)
    except Exception:
        logger.warning(
            "Failed to list events for terminal_evidence, run_id=%s",
            run_id,
            exc_info=True,
        )
        return "none"

    has_run_succeeded = any(e.event_type == "run_succeeded" for e in events)
    if has_run_succeeded:
        return "run_succeeded_event"

    has_answer_completed = any(
        e.event_type == "answer_completed"
        and isinstance(e.payload.get("text"), str)
        and e.payload["text"].strip()
        for e in events
    )
    if has_answer_completed:
        return "answer_completed_event"

    return "none"


async def _populate_run_result(db: AsyncSession, run_response: dict) -> dict:
    if run_response.get("result") is not None:
        return run_response

    try:
        repo = AgentRepository(db)
        events = await repo.list_events(run_response["id"])
        for event in reversed(events):
            if event.event_type == "run_succeeded" and "final_answer" in event.payload:
                run_response["result"] = {"final_answer": event.payload["final_answer"]}
                logger.warning(
                    "Populated result from legacy run_succeeded event for run_id=%s",
                    run_response["id"],
                )
                return run_response
            if event.event_type == "answer_completed" and "text" in event.payload:
                run_response["result"] = {"final_answer": event.payload["text"]}
                logger.warning(
                    "Populated result from legacy answer_completed event for run_id=%s",
                    run_response["id"],
                )
                return run_response
    except Exception:
        logger.warning(
            "Failed to populate result from events for run_id=%s",
            run_response["id"],
            exc_info=True,
        )
    return run_response


async def _resolve_project_folder(
    db: AsyncSession, folder_id: uuid.UUID | None, owner_user_id: uuid.UUID
) -> FileFolder | None:
    if folder_id is None:
        return None
    folder = await db.get(FileFolder, folder_id)
    if (
        folder is None
        or folder.is_deleted
        or folder.owner_user_id != owner_user_id
        or folder.parent_folder_id is not None
    ):
        raise ApiError(
            status_code=400,
            code="INVALID_PROJECT",
            message="项目无效：必须是自己的顶层文件夹",
        )
    return folder


@router.post("/sessions", status_code=201)
async def create_session(
    request: Request,
    data: AgentSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    repo = AgentRepository(db)
    await _resolve_project_folder(db, data.project_folder_id, current_user.id)
    session_obj = await repo.create_session(current_user.id, data.title)
    session_obj.project_folder_id = data.project_folder_id
    return success(
        request,
        AgentSessionResponse.model_validate(session_obj).model_dump(mode="json"),
    )


@router.get("/sessions")
async def list_sessions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = AgentRepository(db)
    result = await repo.list_owned_sessions(current_user.id, page, page_size)
    return success(
        request,
        AgentSessionListResponse(
            items=[AgentSessionResponse.model_validate(s) for s in result.items],
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        ).model_dump(mode="json"),
    )


@router.get("/sessions/{session_id}")
async def get_session(
    request: Request,
    session_obj=Depends(get_owned_agent_session),
):
    return success(
        request,
        AgentSessionResponse.model_validate(session_obj).model_dump(mode="json"),
    )


@router.put("/sessions/{session_id}/rename")
async def rename_session(
    request: Request,
    data: AgentSessionRename,
    session_obj=Depends(get_owned_agent_session),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    repo = AgentRepository(db)
    title = data.title.strip()
    if not title:
        raise ApiError(status_code=422, code="INVALID_TITLE", message="标题不能为空")
    session_obj.title = title
    session_obj.updated_at = datetime.now(UTC)
    db.add(session_obj)
    await db.commit()
    await db.refresh(session_obj)
    return success(
        request,
        AgentSessionResponse.model_validate(session_obj).model_dump(mode="json"),
    )


@router.put("/sessions/{session_id}/project")
async def update_session_project(
    request: Request,
    data: SessionProjectUpdate,
    session_obj=Depends(get_owned_agent_session),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    folder = await _resolve_project_folder(db, data.project_folder_id, current_user.id)
    session_obj.project_folder_id = data.project_folder_id
    session_obj.updated_at = datetime.now(UTC)
    db.add(session_obj)
    await db.commit()
    await db.refresh(session_obj)
    return success(
        request,
        {
            "project_folder_id": data.project_folder_id,
            "project_name": folder.name if folder else "",
        },
    )


@router.patch("/sessions/{session_id}/pin")
async def pin_session(
    request: Request,
    data: AgentSessionPin,
    session_obj=Depends(get_owned_agent_session),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    session_obj.is_pinned = data.pinned
    session_obj.updated_at = datetime.now(UTC)
    db.add(session_obj)
    await db.commit()
    await db.refresh(session_obj)
    return success(
        request,
        AgentSessionResponse.model_validate(session_obj).model_dump(mode="json"),
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    request: Request,
    session_obj=Depends(get_owned_agent_session),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    repo = AgentRepository(db)
    await repo.delete_session(session_obj.id, session_obj.owner_user_id)
    await db.commit()
    return None


@router.get("/sessions/{session_id}/runs")
async def list_session_runs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    session_obj=Depends(get_owned_agent_session),
):
    repo = AgentRepository(db)
    runs = await repo.list_runs_for_session(session_obj.id)
    run_dicts = [AgentRunResponse.model_validate(run).model_dump(mode="json") for run in runs]
    run_dicts = [await _populate_run_result(db, rd) for rd in run_dicts]
    for rd, run in zip(run_dicts, runs):
        rd["terminal_evidence"] = await _resolve_terminal_evidence(
            db, run.id, run.status
        )
    return success(
        request,
        run_dicts,
    )


@router.post("/sessions/{session_id}/runs", status_code=201)
async def create_run(
    request: Request,
    data: AgentRunCreate,
    session_obj=Depends(get_owned_agent_session),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    if not data.goal.strip():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="goal 不能为空",
        )

    points = await get_or_create_points(db, current_user.id)
    if points.balance <= 0:
        raise ApiError(status_code=400, code="INSUFFICIENT_POINTS", message="积点余额不足，请先充值")

    validated_ids: list[uuid.UUID] = []
    for attachment_id in data.attachment_ids:
        att = await db.scalar(
            select(AgentAttachment).where(
                AgentAttachment.id == attachment_id,
                AgentAttachment.owner_user_id == current_user.id,
                AgentAttachment.session_id == session_obj.id,
                AgentAttachment.extraction_status == "ready",
            )
        )
        if att is None:
            raise ApiError(
                status_code=422,
                code="INVALID_ATTACHMENT",
                message=f"附件 {attachment_id} 不存在、无权访问或未就绪",
            )
        validated_ids.append(attachment_id)

    repo = AgentRepository(db)
    run, _, _ = await repo.create_run_with_attempt(
        session_obj,
        data.goal,
        data.network_enabled,
        validated_ids,
    )
    run.project_folder_id = session_obj.project_folder_id
    await db.execute(func.pg_notify("new_run", str(run.id)))
    return success(
        request,
        AgentRunResponse.model_validate(run).model_dump(mode="json"),
    )


@router.get("/runs/{run_id}")
async def get_run(
    request: Request,
    db: AsyncSession = Depends(get_db),
    run=Depends(get_owned_agent_run),
):
    repo = AgentRepository(db)
    attempts = await repo.list_attempts(run.id)
    run_data = AgentRunResponse.model_validate(run).model_dump(mode="json")
    run_data = await _populate_run_result(db, run_data)
    run_data["terminal_evidence"] = await _resolve_terminal_evidence(
        db, run.id, run.status
    )
    run_data["attempts"] = [
        AgentAttemptResponse.model_validate(a).model_dump(mode="json")
        for a in attempts
    ]
    return success(request, run_data)


@router.get("/runs/{run_id}/attempts")
async def list_attempts(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    run=Depends(get_owned_agent_run),
):
    repo = AgentRepository(db)
    all_attempts = await repo.list_attempts(run.id)
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


@router.get("/runs/{run_id}/attempts/{attempt_id}/steps")
async def list_steps(
    request: Request,
    attempt_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    run=Depends(get_owned_agent_run),
):
    repo = AgentRepository(db)
    steps = await repo.get_steps_for_run_attempt(run.id, attempt_id)
    if steps is None:
        raise ApiError(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            message="运行尝试不存在",
        )
    total = len(steps)
    start = (page - 1) * page_size
    items = steps[start : start + page_size]
    return success(
        request,
        AgentStepListResponse(
            items=[AgentStepResponse.model_validate(s) for s in items],
            page=page,
            page_size=page_size,
            total=total,
        ).model_dump(mode="json"),
    )


@router.get("/runs/{run_id}/steps")
async def list_current_run_steps(
    request: Request,
    db: AsyncSession = Depends(get_db),
    run=Depends(get_owned_agent_run),
):
    if run.current_attempt_id is None:
        return success(request, [])

    repo = AgentRepository(db)
    steps = await repo.list_steps(run.current_attempt_id)
    return success(
        request,
        [AgentStepResponse.model_validate(step).model_dump(mode="json") for step in steps],
    )


@router.get("/runs/{run_id}/events")
async def list_events(
    request: Request,
    after_seq: int | None = Query(None),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    run=Depends(get_owned_agent_run),
):
    repo = AgentRepository(db)
    events = await repo.list_events_after_seq(run.id, after_seq, page_size)
    items = [AgentRunEventResponse.model_validate(e) for e in events]
    next_seq = events[-1].seq if events else None
    return success(
        request,
        {
            "items": [i.model_dump(mode="json") for i in items],
            "next_seq": next_seq,
        },
    )


@router.post("/runs/{run_id}/cancel")
async def request_cancel(
    request: Request,
    db: AsyncSession = Depends(get_db),
    run=Depends(get_owned_agent_run),
    _csrf=Depends(require_csrf),
):
    if run.status in TERMINAL_STATUSES:
        raise ApiError(
            status_code=409,
            code="INVALID_TRANSITION",
            message="运行已结束，无法取消",
        )

    repo = AgentRepository(db)
    if run.status in {"queued", "retry_wait"}:
        if await repo.cancel_queued_run(run):
            await repo.append_event(
                run,
                None,
                "run_cancelled",
                {"run_id": str(run.id), "status": "cancelled"},
            )
            return success(
                request,
                AgentRunResponse.model_validate(run).model_dump(mode="json"),
            )
    ok = await repo.request_cancel(run)
    if not ok:
        raise ApiError(
            status_code=409,
            code="INVALID_TRANSITION",
            message="无法取消当前状态的运行",
        )

    await repo.append_event(
        run,
        None,
        "run_cancel_requested",
        {"run_id": str(run.id), "status": run.status},
    )

    return success(
        request,
        AgentRunResponse.model_validate(run).model_dump(mode="json"),
    )


@router.post("/runs/{run_id}/answer")
async def answer_pending_questions(
    request: Request,
    body: AgentRunAnswerRequest,
    db: AsyncSession = Depends(get_db),
    run=Depends(get_owned_agent_run),
    _csrf=Depends(require_csrf),
):
    if run.status != "awaiting_question" or not run.pending_questions:
        raise ApiError(
            status_code=404,
            code="RUN_NOT_AWAITING_QUESTION",
            message="运行未在等待追问回答",
        )

    repo = AgentRepository(db)
    await repo.resume_run_from_answer(run, body.answers)
    attempt = await repo.create_resume_attempt(run)

    await repo.append_event(
        run,
        attempt,
        "run_resumed",
        {
            "run_id": str(run.id),
            "attempt_id": str(attempt.id),
            "answers": body.answers,
        },
    )
    await db.commit()
    await db.refresh(run)

    return success(
        request,
        AgentRunResponse.model_validate(run).model_dump(mode="json"),
    )


@router.post("/runs/{run_id}/retry", status_code=201)
async def retry_run(
    request: Request,
    db: AsyncSession = Depends(get_db),
    run=Depends(get_owned_agent_run),
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    if run.status not in TERMINAL_STATUSES:
        raise ApiError(
            status_code=409,
            code="INVALID_TRANSITION",
            message="仅已完成、失败或已取消的运行可重试",
        )

    points = await get_or_create_points(db, current_user.id)
    if points.balance <= 0:
        raise ApiError(status_code=400, code="INSUFFICIENT_POINTS", message="积点余额不足，请先充值")

    repo = AgentRepository(db)
    attempt = await repo.create_retry_attempt(run)

    session_obj = await repo.get_session(run.session_id)
    if session_obj is not None:
        run.project_folder_id = session_obj.project_folder_id

    await repo.append_event(
        run,
        attempt,
        "run_retried",
        {"run_id": str(run.id), "attempt_id": str(attempt.id)},
    )

    return success(
        request,
        AgentRunResponse.model_validate(run).model_dump(mode="json"),
    )


@router.get("/platform-notes")
async def list_platform_notes(
    request: Request,
    keyword: str = Query("", max_length=200),
    platform: str = Query("", max_length=32),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.repositories.platform_note_repository import list_notes

    rows, total = await list_notes(
        db,
        current_user.id,
        keyword or None,
        platform or None,
        limit,
        offset,
    )
    items = [
        {
            "id": str(n.id),
            "platform": n.platform,
            "keyword": n.keyword,
            "url": n.url,
            "title": n.title,
            "content": (n.content[:500] if n.content else None),
            "image_urls": n.image_urls or [],
            "like_count": n.like_count,
            "collect_count": n.collect_count,
            "comment_count": n.comment_count,
            "author": n.author,
            "published_at": n.published_at.isoformat() if n.published_at else None,
            "topic_tags": n.topic_tags or [],
            "collected_at": n.collected_at.isoformat(),
        }
        for n in rows
    ]
    return success(request, {"items": items, "total": total})
