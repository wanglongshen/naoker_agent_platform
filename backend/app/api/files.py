import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user, require_permissions, require_super_admin
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.agent import AgentAttachment
from app.models.file import FileFolder, FileObject
from app.models.rbac import Role, User, UserRole
from app.repositories.file_repository import FileRepository
from app.schemas.common import success
from app.schemas.file import (
    BatchDeleteRequest,
    BatchDeleteResponse,
    FileFolderCreate,
    FileFolderResponse,
    FileFolderUpdate,
    FileMoveRequest,
    FileObjectListResponse,
    FileObjectResponse,
    FileRenameRequest,
    LinkAttachmentRequest,
    UserFolderGroup,
)
from app.services.agent.storage import PrivateObjectStorage
from app.services.file_service import FileService, _resolve_storage_key

router = APIRouter(tags=["File Management"])

_FILE_PERMISSIONS = [
    {"code": "file:read", "name": "文件查看", "description": "查看文件列表与文件内容"},
    {"code": "file:upload", "name": "文件上传", "description": "上传文件到文件库"},
    {"code": "file:delete", "name": "文件删除", "description": "删除自己或其他用户的文件"},
    {"code": "file:manage_folders", "name": "文件夹管理", "description": "创建、重命名、删除文件夹"},
    {"code": "file:admin_view", "name": "全平台文件查看", "description": "查看所有用户的文件"},
]

_file_storage = PrivateObjectStorage(root="./var/files")
_agent_storage = PrivateObjectStorage()

_TEXT_MIME_TYPES = {
    "text/plain",
    "text/csv",
    "text/markdown",
    "text/html",
    "application/json",
}

_EXTRACTED_TEXT_MAX_BYTES = 100 * 1024


def _extract_text(media_type: str, content: bytes) -> str | None:
    if media_type not in _TEXT_MIME_TYPES:
        return None
    try:
        text = content.decode("utf-8", errors="replace")
        return text[:_EXTRACTED_TEXT_MAX_BYTES]
    except Exception:
        return None


async def _is_super_admin(user: User, db: AsyncSession) -> bool:
    stmt = select(exists().where(
        UserRole.user_id == user.id,
        UserRole.role_id == Role.id,
        Role.code == "super_admin",
        Role.status == "active",
        Role.is_deleted.is_(False),
    ))
    return await db.scalar(stmt) or False


def _check_folder_owner(folder: FileFolder | None, current_user: User) -> None:
    if folder is None or folder.is_deleted:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="文件夹不存在")
    if folder.owner_user_id != current_user.id:
        raise ApiError(status_code=403, code="PERMISSION_DENIED", message="无权操作")


async def _check_file_access(file_obj: FileObject | None, current_user: User, db: AsyncSession) -> FileObject:
    if file_obj is None or file_obj.is_deleted:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="文件不存在")
    if file_obj.owner_user_id != current_user.id and not await _is_super_admin(current_user, db):
        raise ApiError(status_code=403, code="PERMISSION_DENIED", message="无权访问")
    return file_obj


async def _check_file_owner(file_obj: FileObject | None, current_user: User) -> FileObject:
    if file_obj is None or file_obj.is_deleted:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="文件不存在")
    if file_obj.owner_user_id != current_user.id:
        raise ApiError(status_code=403, code="PERMISSION_DENIED", message="无权操作")
    return file_obj


# ============================================================
# Folders
# ============================================================

@router.get("/folders")
async def list_folders(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = FileRepository(db)
    folders = await repo.get_folder_tree(current_user.id)
    return success(
        request,
        [FileFolderResponse.model_validate(f).model_dump(mode="json") for f in folders],
    )


@router.get("/folders/admin")
async def list_all_folders(
    request: Request,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = FileRepository(db)
    groups = await repo.get_admin_user_folder_trees(current_user.id)
    return success(
        request,
        [
            UserFolderGroup(
                user_id=g["user_id"],
                username=g["username"],
                display_name=g["display_name"],
                folders=[FileFolderResponse.model_validate(f) for f in g["folders"]],
            ).model_dump(mode="json")
            for g in groups
        ],
    )


@router.post("/folders", status_code=201)
async def create_folder(
    request: Request,
    data: FileFolderCreate,
    current_user: User = require_permissions("file:manage_folders"),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    repo = FileRepository(db)
    try:
        folder = await repo.create_folder(current_user.id, data.name, data.parent_folder_id)
    except ValueError as e:
        raise ApiError(status_code=422, code="INVALID_OPERATION", message=str(e))

    return success(
        request,
        FileFolderResponse.model_validate(folder).model_dump(mode="json"),
    )


@router.put("/folders/{folder_id}")
async def rename_folder(
    folder_id: uuid.UUID,
    request: Request,
    data: FileFolderUpdate,
    current_user: User = require_permissions("file:manage_folders"),
    db: AsyncSession = Depends(get_db),
):
    folder = await db.get(FileFolder, folder_id)
    _check_folder_owner(folder, current_user)

    repo = FileRepository(db)
    try:
        updated = await repo.rename_folder(folder_id, data.name)
    except ValueError as e:
        raise ApiError(status_code=422, code="INVALID_OPERATION", message=str(e))

    return success(
        request,
        FileFolderResponse.model_validate(updated).model_dump(mode="json"),
    )


@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: uuid.UUID,
    request: Request,
    current_user: User = require_permissions("file:manage_folders"),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    folder = await db.get(FileFolder, folder_id)
    _check_folder_owner(folder, current_user)

    repo = FileRepository(db)
    try:
        await repo.delete_folder(folder_id)
    except ValueError as e:
        raise ApiError(status_code=422, code="INVALID_OPERATION", message=str(e))

    return success(request, {"id": str(folder_id), "deleted": True})


# ============================================================
# Files
# ============================================================

@router.get("")
async def list_files(
    request: Request,
    folder_id: uuid.UUID | None = Query(None),
    keyword: str | None = Query(None),
    media_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = FileRepository(db)
    result = await repo.list_files(
        folder_id=folder_id,
        owner_id=current_user.id,
        keyword=keyword,
        media_type=media_type,
        page=page,
        page_size=page_size,
    )
    return success(
        request,
        FileObjectListResponse(
            items=[FileObjectResponse.model_validate(f) for f in result.items],
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        ).model_dump(mode="json"),
    )


@router.get("/admin")
async def list_all_files(
    request: Request,
    user_id: uuid.UUID | None = Query(None),
    folder_id: uuid.UUID | None = Query(None),
    keyword: str | None = Query(None),
    media_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = FileRepository(db)
    result = await repo.get_admin_all_files(
        user_id=user_id,
        folder_id=folder_id,
        keyword=keyword,
        media_type=media_type,
        page=page,
        page_size=page_size,
    )
    return success(
        request,
        FileObjectListResponse(
            items=[FileObjectResponse.model_validate(f) for f in result.items],
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        ).model_dump(mode="json"),
    )


@router.post("/upload", status_code=201)
async def upload_file(
    request: Request,
    file: list[UploadFile] = File(...),
    folder_id: uuid.UUID | None = Form(None),
    current_user: User = require_permissions("file:upload"),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    svc = FileService()
    uploaded = []
    errors = []
    for f in file:
        try:
            file_obj = await svc.upload(current_user.id, folder_id, f, db)
            uploaded.append(FileObjectResponse.model_validate(file_obj).model_dump(mode="json"))
        except ValueError as e:
            errors.append({"filename": f.filename, "error": str(e)})

    return success(
        request,
        {"uploaded": uploaded, "errors": errors, "total": len(uploaded), "failed": len(errors)},
    )


@router.get("/{file_id}/download")
async def download_file(
    file_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    download: bool = False,
):
    repo = FileRepository(db)
    file_obj = await _check_file_access(await repo.get_file(file_id), current_user, db)

    storage_path = _resolve_storage_key(file_obj.storage_key)
    if not storage_path.is_file():
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message=f"File data not found: {file_id}")

    def _read_file():
        with open(storage_path, "rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    from urllib.parse import quote

    safe_filename = file_obj.filename.encode("ascii", errors="ignore").decode("ascii") or "download"
    encoded_filename = quote(file_obj.filename)
    disposition = "attachment" if download else "inline"
    return StreamingResponse(
        _read_file(),
        media_type=file_obj.media_type,
        headers={
            "Content-Disposition": f"{disposition}; filename=\"{safe_filename}\"; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(file_obj.size_bytes),
        },
    )


@router.get("/{file_id}/preview")
async def preview_file(
    file_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = FileRepository(db)
    file_obj = await _check_file_access(await repo.get_file(file_id), current_user, db)

    media_type = file_obj.media_type or ""

    if media_type.startswith("video/") or media_type.startswith("audio/") or media_type.startswith("image/") or media_type == "application/pdf":
        return success(request, {"type": "stream", "url": f"/api/files/{file_id}/download"})
    if media_type.startswith("text/") or media_type == "application/json":
        sp = _resolve_storage_key(file_obj.storage_key)
        try:
            content = sp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = "无法读取文件内容。"
        return success(request, {"type": "text", "content": content})

    _DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    _XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    _PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if media_type in {_DOCX_MIME, _XLSX_MIME, _PPTX_MIME}:
        from app.services.agent.file_reader import extract_file_text
        sp = _resolve_storage_key(file_obj.storage_key)
        try:
            extracted = extract_file_text(media_type, sp.read_bytes())
        except Exception:
            extracted = {"text": "无法读取文档内容。", "truncated": False}
        return success(request, {"type": "text", "content": extracted["text"]})
    return success(request, {"type": "unsupported"})


@router.put("/{file_id}/move")
async def move_file(
    file_id: uuid.UUID,
    request: Request,
    data: FileMoveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    repo = FileRepository(db)
    file_obj = await _check_file_owner(await repo.get_file(file_id), current_user)

    try:
        moved = await repo.move_file(file_id, data.target_folder_id)
    except ValueError as e:
        raise ApiError(status_code=422, code="INVALID_OPERATION", message=str(e))

    return success(
        request,
        FileObjectResponse.model_validate(moved).model_dump(mode="json"),
    )


@router.put("/{file_id}/rename")
async def rename_file(
    file_id: uuid.UUID,
    request: Request,
    data: FileRenameRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    repo = FileRepository(db)
    file_obj = await _check_file_owner(await repo.get_file(file_id), current_user)

    file_obj.filename = data.name
    file_obj.updated_at = datetime.now(UTC)
    db.add(file_obj)
    await db.flush()

    return success(
        request,
        FileObjectResponse.model_validate(file_obj).model_dump(mode="json"),
    )


# ============================================================
# Batch
# ============================================================

@router.delete("/batch")
async def batch_delete_files(
    request: Request,
    data: BatchDeleteRequest,
    current_user: User = require_permissions("file:delete"),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    repo = FileRepository(db)
    files = await repo.get_files_by_ids(data.ids)

    file_map: dict[uuid.UUID, FileObject] = {f.id: f for f in files}
    valid_ids: list[uuid.UUID] = []
    failed: list[dict] = []

    for fid in data.ids:
        f = file_map.get(fid)
        if f is None or f.is_deleted:
            failed.append({"id": str(fid), "reason": "文件不存在"})
        elif f.owner_user_id != current_user.id:
            failed.append({"id": str(fid), "reason": "无权删除"})
        else:
            valid_ids.append(fid)

    deleted: list[uuid.UUID] = []
    storage_keys: list[str] = []
    if valid_ids:
        # Collect storage keys for physical deletion
        for fid in valid_ids:
            f = file_map.get(fid)
            if f and f.storage_key:
                storage_keys.append(f.storage_key)
        await repo.delete_files_batch(valid_ids)
        deleted = valid_ids

    # Delete physical files from disk (best-effort)
    from pathlib import Path
    for key in storage_keys:
        try:
            storage_path = Path(key)
            if storage_path.is_file():
                storage_path.unlink()
        except Exception:
            pass

    return success(
        request,
        BatchDeleteResponse(deleted=deleted, failed=failed).model_dump(mode="json"),
    )


@router.delete("/{file_id}")
async def delete_file(
    file_id: uuid.UUID,
    request: Request,
    current_user: User = require_permissions("file:delete"),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    repo = FileRepository(db)
    file_obj = await _check_file_owner(await repo.get_file(file_id), current_user)

    # Remember storage path before soft delete
    storage_key = file_obj.storage_key

    try:
        await repo.delete_file(file_id)
    except ValueError as e:
        raise ApiError(status_code=422, code="INVALID_OPERATION", message=str(e))

    # Delete physical file from disk (best-effort)
    from pathlib import Path
    try:
        storage_path = Path(storage_key) if storage_key else None
        if storage_path and storage_path.is_file():
            storage_path.unlink()
    except Exception:
        pass

    return success(request, {"id": str(file_id), "deleted": True})


# ============================================================
# Agent Link
# ============================================================

@router.post("/link-attachment", status_code=201)
async def link_attachment(
    request: Request,
    data: LinkAttachmentRequest,
    current_user: User = require_permissions("file:upload"),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    attachment = await db.scalar(
        select(AgentAttachment).where(
            AgentAttachment.id == data.attachment_id,
            AgentAttachment.owner_user_id == current_user.id,
        )
    )
    if attachment is None:
        raise ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="附件不存在或无权访问")

    chunks: list[bytes] = []
    async for chunk in _agent_storage.open(attachment.storage_key):
        chunks.append(chunk)
    content = b"".join(chunks)

    digest = hashlib.sha256(content).hexdigest()

    file_uuid = uuid.uuid4()
    storage_key = f"{current_user.id}/{file_uuid.hex}"

    async def _content_stream():
        yield content

    total = await _file_storage.put(storage_key, _content_stream())

    repo = FileRepository(db)
    extracted_text = _extract_text(attachment.media_type, content)

    file_data = {
        "id": file_uuid,
        "owner_user_id": current_user.id,
        "folder_id": data.folder_id,
        "storage_key": (Path("./var/files") / storage_key).as_posix(),
        "filename": attachment.filename,
        "original_filename": attachment.filename,
        "media_type": attachment.media_type,
        "size_bytes": total if total > 0 else attachment.size_bytes,
        "sha256": digest,
        "extracted_text": extracted_text,
        "preview_status": "ready" if extracted_text is not None else ("pending" if attachment.media_type in _TEXT_MIME_TYPES else "none"),
        "source_attachment_id": attachment.id,
        "created_by": current_user.id,
    }

    file_obj = await repo.add_file(data.folder_id, file_data)

    return success(
        request,
        FileObjectResponse.model_validate(file_obj).model_dump(mode="json"),
    )


# ============================================================
# Permissions
# ============================================================

@router.get("/permissions")
async def list_file_permissions(request: Request):
    return success(request, _FILE_PERMISSIONS)
