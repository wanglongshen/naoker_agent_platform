import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import AsyncIterator

from fastapi import UploadFile

from app.core.config import get_settings
from app.models.agent import AgentAttachment, AgentSession
from app.models.file import FileFolder, FileObject
from app.repositories.file_repository import FileRepository
from app.services.agent.storage import (
    PrivateObjectStorage,
    build_attachment_key,
    is_text_mime,
    normalize_display_filename,
    validate_and_normalize_mime,
)

settings = get_settings()

logger = logging.getLogger("attachments")

ATTACHMENT_FOLDER_NAME = "附件"

_EXTRACTED_TEXT_MAX_BYTES = 10 * 1024


class AttachmentService:
    def __init__(
        self,
        storage: PrivateObjectStorage,
    ) -> None:
        self._storage = storage

    async def upload(
        self,
        owner_user_id: uuid.UUID,
        session: AgentSession,
        upload: UploadFile,
        db_session,
    ) -> AgentAttachment:
        if upload.filename is None:
            raise ValueError("Missing filename")

        display_name = normalize_display_filename(upload.filename)
        if ".." in display_name or "/" in display_name or "\\" in display_name:
            raise ValueError("Invalid filename")

        content_type = upload.content_type or "application/octet-stream"

        head = b""
        chunks: list[bytes] = []
        total = 0
        max_bytes = settings.agent_attachment_max_bytes

        while True:
            chunk = await upload.read(65536)
            if not chunk:
                break
            if not head:
                head = chunk[:4096] if len(chunk) >= 8 else chunk
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"File exceeds maximum size of {max_bytes} bytes")
            chunks.append(chunk)

        content = b"".join(chunks)
        if not head:
            head = content[:4096] if content else b""

        media_type = validate_and_normalize_mime(content_type, head)

        attachment_id = uuid.uuid4()
        storage_key = build_attachment_key(attachment_id)
        temp_key = f"temp/{attachment_id.hex}"

        attachment = AgentAttachment(
            id=attachment_id,
            owner_user_id=owner_user_id,
            session_id=session.id,
            storage_key=storage_key,
            filename=display_name,
            original_filename=upload.filename,
            media_type=media_type,
            size_bytes=total,
            sha256="",
            extraction_status="pending_scan",
            expires_at=datetime.now(UTC) + timedelta(days=settings.agent_attachment_retention_days),
        )
        db_session.add(attachment)
        await db_session.flush()

        try:
            async def _chunk_iter() -> AsyncIterator[bytes]:
                yield content

            await self._storage.put(temp_key, _chunk_iter())
        except Exception:
            attachment.extraction_status = "rejected"
            db_session.add(attachment)
            await db_session.flush()
            raise

        try:
            sha256 = await self._storage.compute_sha256(temp_key)
            attachment.sha256 = sha256

            extracted_text: str | None = None
            try:
                extracted_text = await self._extract_text(media_type, content)
            except Exception:
                extracted_text = None

            if extracted_text is not None:
                attachment.extracted_text = extracted_text
                attachment.extraction_status = "ready"
            elif media_type in {"application/pdf"}:
                attachment.extraction_status = "rejected"
            else:
                attachment.extraction_status = "ready"

            db_session.add(attachment)
            await db_session.flush()
        except Exception:
            try:
                await self._storage.delete(temp_key)
            except Exception:
                pass
            raise

        try:
            await self._rename_storage_key(temp_key, storage_key)
        except Exception:
            attachment.extraction_status = "rejected"
            db_session.add(attachment)
            await db_session.flush()
            raise

        try:
            await self._write_attachment_folder_record(
                owner_user_id, attachment, db_session
            )
        except Exception:
            logger.warning("attachment_folder_write_failed", exc_info=True)

        return attachment

    async def _write_attachment_folder_record(
        self, owner_user_id: uuid.UUID, attachment: AgentAttachment, db_session
    ) -> None:
        """双写：在用户"附件"文件夹建 file_objects 记录（storage 复用，不二次写）。"""
        from sqlalchemy import select

        folder = await db_session.scalar(
            select(FileFolder).where(
                FileFolder.owner_user_id == owner_user_id,
                FileFolder.name == ATTACHMENT_FOLDER_NAME,
                FileFolder.parent_folder_id.is_(None),
                FileFolder.is_deleted == False,
            )
        )
        if folder is None:
            folder = await FileRepository(db_session).create_folder(
                owner_user_id, ATTACHMENT_FOLDER_NAME
            )

        existing = await db_session.scalar(
            select(FileObject).where(
                FileObject.storage_key == attachment.storage_key,
                FileObject.is_deleted == False,
            )
        )
        if existing is not None:
            return

        await FileRepository(db_session).add_file(
            folder.id,
            {
                "owner_user_id": owner_user_id,
                "folder_id": folder.id,
                "storage_key": attachment.storage_key,
                "filename": attachment.filename,
                "original_filename": attachment.original_filename,
                "media_type": attachment.media_type,
                "size_bytes": attachment.size_bytes,
                "sha256": attachment.sha256,
                "extracted_text": attachment.extracted_text,
                "preview_status": "ready" if attachment.extraction_status == "ready" else "pending",
            },
        )

    async def _rename_storage_key(self, src_key: str, dst_key: str) -> None:
        import asyncio

        src_path = self._storage._resolve_key(src_key)
        dst_path = self._storage._resolve_key(dst_key)
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        def _rename():
            src_path.rename(dst_path)

        await asyncio.to_thread(_rename)

    async def _extract_text(self, media_type: str, content: bytes) -> str | None:
        if is_text_mime(media_type):
            try:
                text = content.decode("utf-8", errors="replace")
                return text[:_EXTRACTED_TEXT_MAX_BYTES]
            except Exception:
                return None
        if media_type == "application/pdf":
            return None
        return None

    async def read_prompt_context(
        self, attachments: list[AgentAttachment]
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for att in attachments:
            if att.extraction_status != "ready":
                continue
            text = att.extracted_text or ""
            result.append({
                "label": f"[UNTRUSTED USER ATTACHMENT: {att.filename}]",
                "content": text[:_EXTRACTED_TEXT_MAX_BYTES],
            })
        return result

    async def delete_if_unreferenced(self, attachment: AgentAttachment, db_session) -> bool:
        from sqlalchemy import select, func
        from app.models.agent import AgentRunAttachment, AgentRun

        result = await db_session.execute(
            select(func.count()).select_from(AgentRunAttachment).where(
                AgentRunAttachment.attachment_id == attachment.id,
            )
        )
        ref_count = result.scalar_one()

        if ref_count > 0:
            return False

        try:
            await self._storage.delete(attachment.storage_key)
        except Exception:
            pass

        await db_session.delete(attachment)
        await db_session.flush()
        return True
