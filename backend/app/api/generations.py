from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.agent import AgentRun, AgentRunEvent, AgentSession
from app.models.file import FileFolder, FileObject
from app.models.generation_log import GenerationLog
from app.models.rbac import User
from app.schemas.common import success
from app.services.feishu.service import FeishuService

router = APIRouter(tags=["Generations"])


class GenerationCreateRequest(BaseModel):
    session_id: uuid.UUID
    run_id: uuid.UUID


def _log_view(log: GenerationLog, folder_name: str = "") -> dict:
    return {
        "id": str(log.id),
        "folder_id": str(log.folder_id) if log.folder_id else None,
        "folder_name": folder_name,
        "user_id": str(log.user_id),
        "session_id": str(log.session_id),
        "run_id": str(log.run_id),
        "input_text": log.input_text,
        "final_md_file_id": str(log.final_md_file_id) if log.final_md_file_id else None,
        "final_answer": log.final_answer,
        "feishu_doc_url": log.feishu_doc_url,
        "status": log.status,
        "error": log.error,
        "quality_score": log.quality_score,
        "quality_review_rounds": log.quality_review_rounds,
        "created_at": log.created_at.isoformat() if log.created_at else "",
    }


async def _find_plan_file(db: AsyncSession, run_id: uuid.UUID) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Return (file_id, folder_id) of the last successful write_file in the run."""
    result = await db.execute(
        select(AgentRunEvent)
        .where(
            AgentRunEvent.run_id == run_id,
            AgentRunEvent.event_type == "step_completed",
        )
        .order_by(AgentRunEvent.seq.desc())
    )
    for event in result.scalars().all():
        payload = event.payload or {}
        if payload.get("action_type") != "write_file":
            continue
        obs = payload.get("observation") or {}
        if obs.get("file_id") and "error" not in obs:
            try:
                file_id = uuid.UUID(str(obs["file_id"]))
            except (ValueError, TypeError):
                continue
            obj = await db.get(FileObject, file_id)
            if obj is not None and not obj.is_deleted:
                return file_id, obj.folder_id
    return None, None


async def _sync_feishu(
    db: AsyncSession, user: User, log: GenerationLog, project_name: str
) -> tuple[str, str]:
    """Create a feishu doc from the plan markdown. Returns (url, error)."""
    from datetime import UTC, datetime

    markdown = log.final_answer
    if log.final_md_file_id is not None:
        obj = await db.get(FileObject, log.final_md_file_id)
        if obj is not None and obj.storage_key:
            from pathlib import Path

            path = Path(obj.storage_key)
            try:
                markdown = path.read_text(encoding="utf-8", errors="replace")[:200_000]
            except OSError:
                pass
    title = f"{project_name or '方案'} - 方案 - {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
    try:
        result = await FeishuService().create_document(user.id, title, markdown)
        return result["url"], ""
    except ValueError as exc:
        msg = str(exc)
        if "feishu_not_connected" in msg:
            return "", "未连接飞书"
        return "", msg[:300]
    except Exception as exc:
        return "", str(exc)[:300]


@router.post("/generations")
async def create_generation(
    request: Request,
    data: GenerationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    run = await db.get(AgentRun, data.run_id)
    if run is None or str(run.owner_user_id) != str(current_user.id):
        raise ApiError(status_code=403, code="RUN_NOT_OWNED", message="无权访问该运行")
    if run.status != "succeeded":
        raise ApiError(status_code=400, code="RUN_NOT_COMPLETED", message="运行尚未成功完成")
    session = await db.get(AgentSession, data.session_id)
    if session is None or str(session.owner_user_id) != str(current_user.id):
        raise ApiError(status_code=403, code="SESSION_NOT_OWNED", message="无权访问该会话")
    existing = await db.scalar(
        select(GenerationLog).where(GenerationLog.run_id == data.run_id)
    )
    if existing is not None:
        raise ApiError(status_code=409, code="ALREADY_RECORDED", message="该运行已记录")

    file_id, folder_id = await _find_plan_file(db, data.run_id)
    folder_name = ""
    if folder_id is not None:
        folder = await db.get(FileFolder, folder_id)
        folder_name = folder.name if folder else ""

    quality_score: int | None = None
    quality_rounds = 0
    review_event = (
        await db.execute(
            select(AgentRunEvent)
            .where(
                AgentRunEvent.run_id == data.run_id,
                AgentRunEvent.event_type == "quality_review_completed",
            )
            .order_by(AgentRunEvent.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if review_event is not None:
        payload = review_event.payload or {}
        score = payload.get("score")
        try:
            quality_score = int(score)
        except (TypeError, ValueError):
            quality_score = None
        quality_rounds = int(payload.get("rounds") or 0)

    log = GenerationLog(
        folder_id=folder_id,
        user_id=current_user.id,
        session_id=data.session_id,
        run_id=data.run_id,
        input_text=run.goal,
        final_md_file_id=file_id,
        final_answer=(run.result or {}).get("final_answer", "") or "",
        status="pending",
        quality_score=quality_score,
        quality_review_rounds=quality_rounds,
    )
    db.add(log)
    await db.flush()

    url, error = "", ""
    if current_user.sync_feishu_enabled:
        url, error = await _sync_feishu(db, current_user, log, folder_name)

    log.status = "succeeded"
    log.feishu_doc_url = url
    log.error = error
    await db.commit()
    return success(request, {"log": _log_view(log, folder_name)})


@router.get("/generations")
async def list_generations(
    request: Request,
    folder_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if folder_id is not None:
        folder = await db.get(FileFolder, folder_id)
        if folder is None or str(folder.owner_user_id) != str(current_user.id):
            raise ApiError(status_code=403, code="FOLDER_NOT_OWNED", message="无权访问该文件夹")
    stmt = select(GenerationLog).where(GenerationLog.user_id == current_user.id)
    if folder_id is not None:
        stmt = stmt.where(GenerationLog.folder_id == folder_id)
    total = (
        await db.execute(
            select(GenerationLog.id).where(
                GenerationLog.user_id == current_user.id,
                *([GenerationLog.folder_id == folder_id] if folder_id is not None else []),
            )
        )
    ).all()
    result = await db.execute(
        stmt.order_by(GenerationLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = list(result.scalars().all())
    folder_ids = {l.folder_id for l in logs if l.folder_id}
    names: dict[uuid.UUID, str] = {}
    if folder_ids:
        folders = await db.execute(select(FileFolder).where(FileFolder.id.in_(folder_ids)))
        names = {f.id: f.name for f in folders.scalars().all()}
    return success(
        request,
        {
            "logs": [_log_view(l, names.get(l.folder_id, "")) for l in logs],
            "total": len(total),
        },
    )


def _sanitize_observation(observation) -> str:
    if observation is None:
        return ""
    if isinstance(observation, str):
        return observation[:500]
    if isinstance(observation, dict):
        parts = []
        for key in ("error", "file_id", "filename", "path", "folder_path", "query", "title", "summary"):
            value = observation.get(key)
            if value is not None:
                parts.append(f"{key}: {value}")
        if parts:
            return "; ".join(parts)[:500]
        return ""  # dict without whitelisted keys: never dump raw content
    return str(observation)[:500]


def _timeline_entry(ev: AgentRunEvent) -> dict | None:
    p = ev.payload or {}
    created_at = ev.created_at.isoformat() if ev.created_at else ""
    base = {"created_at": created_at}
    if ev.event_type == "visible_thought_completed":
        return {**base, "type": "thought", "step_index": p.get("step_index"),
                "content": p.get("text", "")}
    if ev.event_type == "step_completed":
        return {**base, "type": "tool", "step_index": p.get("step_index"),
                "action_type": p.get("action_type", ""),
                "input": p.get("tool_call") or {},
                "observation": _sanitize_observation(p.get("observation")),
                "duration_seconds": p.get("step_duration_seconds")}
    if ev.event_type == "answer_completed":
        return {**base, "type": "answer", "content": p.get("text", "")}
    if ev.event_type == "run_failed":
        return {**base, "type": "terminal", "status": "failed", "error": p.get("error", "")}
    if ev.event_type == "run_succeeded":
        return {**base, "type": "terminal", "status": "succeeded"}
    return None


@router.get("/generations/{log_id}/timeline")
async def generation_timeline(
    request: Request,
    log_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    log = await db.get(GenerationLog, log_id)
    if log is None:
        raise ApiError(status_code=404, code="LOG_NOT_FOUND", message="生成记录不存在")
    if str(log.user_id) != str(current_user.id):
        raise ApiError(status_code=403, code="LOG_NOT_OWNED", message="无权访问该记录")
    result = await db.execute(
        select(AgentRunEvent)
        .where(AgentRunEvent.run_id == log.run_id)
        .order_by(AgentRunEvent.seq.asc())
    )
    steps = [
        entry
        for entry in (_timeline_entry(ev) for ev in result.scalars().all())
        if entry is not None
    ]
    return success(request, {"steps": steps})
