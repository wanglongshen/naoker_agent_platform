import uuid

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user, get_owned_agent_attachment, get_owned_agent_session
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.agent import AgentAttachment, AgentRunAttachment
from app.models.rbac import User
from app.repositories.agent_repository import AgentRepository
from app.schemas.agent import AgentAttachmentListResponse, AgentAttachmentResponse
from app.schemas.common import success
from app.services.agent.attachments import AttachmentService
from app.services.agent.storage import PrivateObjectStorage, build_attachment_key

router = APIRouter(tags=["Agent Attachments"])

_storage = PrivateObjectStorage()


def _attachment_service(db: AsyncSession):
    return AttachmentService(storage=_storage)


@router.post("/sessions/{session_id}/attachments", status_code=201)
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    session=Depends(get_owned_agent_session),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()

    existing_count = await db.scalar(
        select(func.count()).select_from(AgentAttachment).where(
            AgentAttachment.session_id == session.id,
        )
    )
    if existing_count >= settings.agent_attachment_max_count:
        raise ApiError(
            status_code=422,
            code="ATTACHMENT_LIMIT",
            message=f"会话附件数量已达上限 ({settings.agent_attachment_max_count})",
        )

    svc = _attachment_service(db)
    try:
        attachment = await svc.upload(current_user.id, session, file, db)
    except ValueError as e:
        raise ApiError(
            status_code=422,
            code="ATTACHMENT_REJECTED",
            message=str(e),
        )

    return success(
        request,
        AgentAttachmentResponse.model_validate(attachment).model_dump(mode="json"),
    )


@router.get("/sessions/{session_id}/attachments")
async def list_attachments(
    request: Request,
    session=Depends(get_owned_agent_session),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentAttachment)
        .where(
            AgentAttachment.session_id == session.id,
            AgentAttachment.owner_user_id == current_user.id,
        )
        .order_by(AgentAttachment.created_at.desc())
    )
    attachments = result.scalars().all()
    return success(
        request,
        AgentAttachmentListResponse(
            items=[AgentAttachmentResponse.model_validate(a) for a in attachments],
            page=1,
            page_size=len(attachments),
            total=len(attachments),
        ).model_dump(mode="json"),
    )


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(
    request: Request,
    attachment=Depends(get_owned_agent_attachment),
):
    storage_key = attachment.storage_key

    async def stream():
        async for chunk in _storage.open(storage_key):
            yield chunk

    return StreamingResponse(
        stream(),
        media_type=attachment.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{attachment.filename}"',
            "Content-Length": str(attachment.size_bytes),
        },
    )


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    request: Request,
    attachment=Depends(get_owned_agent_attachment),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    active_ref = await db.scalar(
        select(func.count()).select_from(AgentRunAttachment).where(
            AgentRunAttachment.attachment_id == attachment.id,
        )
    )
    if active_ref > 0:
        raise ApiError(
            status_code=409,
            code="ATTACHMENT_IN_USE",
            message="附件被运行引用，无法删除",
        )

    svc = _attachment_service(db)
    await svc.delete_if_unreferenced(attachment, db)
    return success(request, {"id": str(attachment.id), "deleted": True})
