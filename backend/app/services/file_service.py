import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import AsyncIterator

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.file import FileObject
from app.repositories.file_repository import FileRepository
from app.schemas.file import FileObjectResponse

settings = get_settings()

_DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/svg+xml",
    "image/webp",
}

_TEXT_MIME_TYPES = {
    "text/plain",
    "text/csv",
    "text/markdown",
    "text/html",
    "application/json",
    "application/xml",
    "text/xml",
}

_VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/webm",
}

_AUDIO_MIME_TYPES = {
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
}

_ARCHIVE_MIME_TYPES = {
    "application/zip",
    "application/x-rar-compressed",
    "application/x-7z-compressed",
    "application/gzip",
    "application/x-tar",
}

_ALLOWED_MIME_TYPES = (
    _DOCUMENT_MIME_TYPES | _IMAGE_MIME_TYPES | _TEXT_MIME_TYPES
    | _VIDEO_MIME_TYPES | _AUDIO_MIME_TYPES | _ARCHIVE_MIME_TYPES
    | {"application/octet-stream"}
)

_SIZE_LIMITS: dict[str, int] = {}
_SIZE_LIMITS.update({mt: 10 * 1024 * 1024 for mt in _DOCUMENT_MIME_TYPES})
_SIZE_LIMITS.update({mt: 10 * 1024 * 1024 for mt in _TEXT_MIME_TYPES})
_SIZE_LIMITS.update({mt: 5 * 1024 * 1024 for mt in _IMAGE_MIME_TYPES})
_SIZE_LIMITS.update({mt: 50 * 1024 * 1024 for mt in _VIDEO_MIME_TYPES})
_SIZE_LIMITS.update({mt: 20 * 1024 * 1024 for mt in _AUDIO_MIME_TYPES})
_SIZE_LIMITS.update({mt: 20 * 1024 * 1024 for mt in _ARCHIVE_MIME_TYPES})
_SIZE_LIMITS["application/octet-stream"] = 10 * 1024 * 1024

_EXTRACTED_TEXT_MAX_BYTES = 100 * 1024

_FILES_ROOT = Path("./var/files")

_AGENT_STORAGE_ROOT = Path(settings.agent_storage_root)

_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF8", "image/gif"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x1f\x8b\x08", "application/gzip"),
    (b"RIFF", "audio/wav"),
    (b"<!DOCTYPE html", "text/html"),
    (b"<html", "text/html"),
    (b"{", "application/json"),
]


def _detect_mime_type(content: bytes) -> str | None:
    for signature, mime in _MAGIC_SIGNATURES:
        if content.startswith(signature):
            return mime
    return None


def _resolve_storage_path(user_id: uuid.UUID, file_uuid: uuid.UUID) -> Path:
    return _FILES_ROOT / str(user_id) / file_uuid.hex


def _resolve_storage_key(storage_key: str) -> Path:
    """Resolve a stored storage_key: agent-relative keys live under agent_storage_root."""
    if storage_key.startswith("attachments/"):
        return _AGENT_STORAGE_ROOT / storage_key
    return Path(storage_key)


def _validate_filename(filename: str) -> str:
    name = filename.replace("\\", "/")
    name = Path(name).name
    name = name.strip()
    if not name:
        raise ValueError("Empty filename")
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError("Invalid filename")
    return name


def _validate_mime_type(content_type: str) -> str:
    media_type = content_type.split(";")[0].strip().lower()
    if media_type not in _ALLOWED_MIME_TYPES:
        raise ValueError(f"MIME type not allowed: {media_type}")
    return media_type


def _get_size_limit(media_type: str) -> int:
    for group in (_DOCUMENT_MIME_TYPES, _IMAGE_MIME_TYPES, _TEXT_MIME_TYPES):
        if media_type in group:
            return _SIZE_LIMITS.get(media_type, 10 * 1024 * 1024)
    return 10 * 1024 * 1024


def _is_text_mime(media_type: str) -> bool:
    return media_type in _TEXT_MIME_TYPES


def _extract_text(media_type: str, content: bytes) -> str | None:
    if _is_text_mime(media_type):
        try:
            text = content.decode("utf-8", errors="replace")
            return text[:_EXTRACTED_TEXT_MAX_BYTES]
        except Exception:
            return None
    return None


class FileService:
    async def upload(
        self,
        owner_user_id: uuid.UUID,
        folder_id: uuid.UUID | None,
        upload_file: UploadFile,
        db_session: AsyncSession,
        settings: Settings | None = None,
    ) -> FileObjectResponse:
        if upload_file.filename is None:
            raise ValueError("Missing filename")

        raw_filename = upload_file.filename
        # If filename contains a relative path (folder upload), resolve/create subfolders
        target_folder_id = folder_id
        clean_filename = raw_filename
        if "/" in raw_filename:
            path_parts = raw_filename.split("/")
            clean_filename = path_parts[-1]
            # If any path segment is unsafe (., ..), treat as plain filename — no folder creation
            has_unsafe = any(p in {".", ".."} or not p for p in path_parts[:-1])
            folder_paths = [] if has_unsafe else [p for p in path_parts[:-1] if p]

            if folder_paths:
                repo = FileRepository(db_session)
                current_parent = folder_id
                for part in folder_paths:
                    sub = await repo.find_folder_by_name(owner_user_id, part)
                    if sub is None:
                        sub = await repo.create_folder(owner_user_id, part, current_parent)
                        await db_session.flush()
                    current_parent = sub.id
                target_folder_id = current_parent

        display_name = _validate_filename(clean_filename)

        content_type = upload_file.content_type or "application/octet-stream"
        media_type = content_type.split(";")[0].strip().lower()

        chunks: list[bytes] = []
        total = 0
        sha256 = hashlib.sha256()

        head_bytes = b""
        while True:
            chunk = await upload_file.read(65536)
            if not chunk:
                break
            total += len(chunk)
            sha256.update(chunk)
            chunks.append(chunk)
            if len(head_bytes) < 4096:
                head_bytes = (head_bytes + chunk)[:4096]

        content = b"".join(chunks)

        detected = _detect_mime_type(head_bytes)
        if detected:
            media_type = detected
        elif media_type not in _ALLOWED_MIME_TYPES:
            raise ValueError(f"MIME type not allowed: {content_type}")
        elif media_type == "application/octet-stream":
            raise ValueError(f"MIME type not allowed: {content_type}")

        _validate_mime_type(media_type)
        max_bytes = _get_size_limit(media_type)
        if total > max_bytes:
            raise ValueError(f"File exceeds maximum size of {max_bytes} bytes")
        digest = sha256.hexdigest()

        existing = await db_session.scalar(
            select(FileObject).where(
                FileObject.owner_user_id == owner_user_id,
                FileObject.folder_id == target_folder_id,
                FileObject.original_filename == display_name,
                FileObject.is_deleted == False,
            )
        )
        if existing is not None:
            now = datetime.now(UTC)
            storage_path = Path(existing.storage_key) if existing.storage_key else None
            if storage_path is None or not storage_path.parent.exists():
                storage_path = _resolve_storage_path(owner_user_id, existing.id)
                storage_path.parent.mkdir(parents=True, exist_ok=True)

            def _write_existing_sync():
                with open(storage_path, "wb") as f:
                    f.write(content)

            await asyncio.to_thread(_write_existing_sync)

            extracted_text: str | None = None
            try:
                extracted_text = _extract_text(media_type, content)
            except Exception:
                extracted_text = None
            existing.media_type = media_type
            existing.size_bytes = total
            existing.sha256 = digest
            existing.extracted_text = extracted_text
            existing.preview_status = "ready" if extracted_text is not None else ("pending" if _is_text_mime(media_type) else "none")
            existing.created_at = now
            existing.updated_at = now
            db_session.add(existing)
            await db_session.flush()
            return FileObjectResponse.model_validate(existing)

        file_uuid = uuid.uuid4()
        storage_path = _resolve_storage_path(owner_user_id, file_uuid)
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        def _write_sync():
            with open(storage_path, "wb") as f:
                f.write(content)

        await asyncio.to_thread(_write_sync)

        repo = FileRepository(db_session)

        file_data = {
            "id": file_uuid,
            "owner_user_id": owner_user_id,
            "folder_id": target_folder_id,
            "storage_key": storage_path.as_posix(),
            "filename": display_name,
            "original_filename": clean_filename,
            "media_type": media_type,
            "size_bytes": total,
            "sha256": digest,
            "created_by": owner_user_id,
        }

        extracted_text: str | None = None
        try:
            extracted_text = _extract_text(media_type, content)
        except Exception:
            extracted_text = None

        if extracted_text is not None:
            file_data["extracted_text"] = extracted_text
            file_data["preview_status"] = "ready"
        else:
            file_data["preview_status"] = "pending" if _is_text_mime(media_type) else "none"

        file_obj = await repo.add_file(target_folder_id, file_data)
        return FileObjectResponse.model_validate(file_obj)

    async def download(
        self,
        file_id: uuid.UUID,
        user_id: uuid.UUID,
        db_session: AsyncSession,
    ) -> AsyncIterator[bytes]:
        repo = FileRepository(db_session)
        file_obj = await repo.get_file(file_id)
        if file_obj is None:
            raise FileNotFoundError(f"File not found: {file_id}")
        if file_obj.owner_user_id != user_id:
            raise PermissionError("Access denied")

        storage_path = _resolve_storage_key(file_obj.storage_key)
        if not storage_path.is_file():
            raise FileNotFoundError(f"File data not found: {file_id}")

        chunk_size = 64 * 1024

        def _read_file():
            with open(storage_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

        for chunk in _read_file():
            yield chunk

    async def preview(
        self,
        file_id: uuid.UUID,
        user_id: uuid.UUID,
        db_session: AsyncSession,
    ) -> dict:
        repo = FileRepository(db_session)
        file_obj = await repo.get_file(file_id)
        if file_obj is None:
            raise FileNotFoundError(f"File not found: {file_id}")
        if file_obj.owner_user_id != user_id:
            raise PermissionError("Access denied")

        result = {
            "id": str(file_obj.id),
            "filename": file_obj.filename,
            "media_type": file_obj.media_type,
            "preview_status": file_obj.preview_status,
            "extracted_text": file_obj.extracted_text,
        }

        if file_obj.extracted_text is None and _is_text_mime(file_obj.media_type):
            storage_path = _resolve_storage_key(file_obj.storage_key)
            if storage_path.is_file():
                try:
                    extracted = _extract_text(file_obj.media_type, storage_path.read_bytes())
                    if extracted:
                        result["extracted_text"] = extracted
                        result["preview_status"] = "ready"
                except Exception:
                    pass

        return result
