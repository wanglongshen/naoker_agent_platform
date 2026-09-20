from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.feishu_token import FeishuToken
from app.services.feishu.client import FeishuClient
from app.services.feishu.crypto import decrypt_token, derive_token_key, encrypt_token

# Feishu docx block types
BLOCK_HEADING1 = 3
BLOCK_HEADING2 = 4
BLOCK_HEADING3 = 5
BLOCK_PARAGRAPH = 2
BLOCK_BULLET = 12
BLOCK_TABLE = 31
BLOCK_TABLE_CELL = 32


def _text_block(text: str) -> dict:
    return {
        "block_type": BLOCK_PARAGRAPH,
        "text": {"elements": [{"text_run": {"content": text}}]},
    }


def _heading_block(text: str, level: int) -> dict:
    field = f"heading{level}"
    return {
        "block_type": BLOCK_HEADING1 + (level - 1),
        field: {"elements": [{"text_run": {"content": text}}]},
    }


def markdown_to_blocks(markdown: str) -> list[dict]:
    """Convert simple markdown to Feishu docx blocks.

    Supports: headings (#, ##, ###), paragraphs, bullet lists (- ).
    """
    blocks: list[dict] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Heading
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            level = min(max(level, 1), 3)
            text = stripped.lstrip("#").strip()
            blocks.append(_heading_block(text, level))
            i += 1
            continue

        # Bullet
        if stripped.startswith("- ") or stripped.startswith("* "):
            text = stripped[2:].strip()
            blocks.append({
                "block_type": BLOCK_BULLET,
                "bullet": {"elements": [{"text_run": {"content": text}}]},
            })
            i += 1
            continue

        # Paragraph
        blocks.append(_text_block(stripped))
        i += 1

    return blocks


class FeishuService:
    def __init__(self, client: FeishuClient | None = None) -> None:
        self.client = client or FeishuClient()
        self.settings = get_settings()

    def _key(self) -> bytes:
        secret = self.settings.feishu_token_encryption_key or self.settings.jwt_secret
        return derive_token_key(secret)

    async def get_access_token(self, owner_user_id: uuid.UUID) -> str:
        async with async_session_factory() as session:
            token = await session.scalar(
                select(FeishuToken).where(FeishuToken.owner_user_id == owner_user_id)
            )
            if token is None:
                raise ValueError("feishu_not_connected")

            if token.expires_at and token.expires_at > datetime.now(UTC) + timedelta(minutes=5):
                return decrypt_token(token.access_token, self._key())

            # Expired — try refresh
            if token.refresh_token:
                try:
                    data = await self.client.refresh_access_token(
                        decrypt_token(token.refresh_token, self._key())
                    )
                    token.access_token = encrypt_token(data["access_token"], self._key())
                    token.refresh_token = encrypt_token(data["refresh_token"], self._key())
                    token.expires_at = datetime.now(UTC) + timedelta(
                        seconds=data.get("expires_in", 7200)
                    )
                    await session.commit()
                    return data["access_token"]
                except Exception:
                    raise ValueError("feishu_token_expired_reauthorize")

            raise ValueError("feishu_token_expired_reauthorize")

    async def read_document(self, owner_user_id: uuid.UUID, doc_token: str) -> dict:
        token = await self.get_access_token(owner_user_id)
        return await self.client.read_document(doc_token, token)

    async def create_document(
        self, owner_user_id: uuid.UUID, title: str, markdown: str
    ) -> dict:
        token = await self.get_access_token(owner_user_id)
        created = await self.client.create_document(title, token)
        doc_id = created["data"]["document"]["document_id"]
        blocks = markdown_to_blocks(markdown)
        if blocks:
            await self.client.add_blocks(doc_id, blocks, token)
        return {
            "document_id": doc_id,
            "url": f"https://feishu.cn/docx/{doc_id}",
            "title": title,
        }

    async def edit_document(
        self, owner_user_id: uuid.UUID, doc_token: str, block_id: str, new_content: str
    ) -> dict:
        token = await self.get_access_token(owner_user_id)
        return await self.client.update_block(doc_token, block_id, new_content, token)

    async def set_permission(
        self, owner_user_id: uuid.UUID, doc_token: str, permission: str
    ) -> dict:
        token = await self.get_access_token(owner_user_id)
        if permission not in {"anyone_readable", "link_share"}:
            raise ValueError("feishu_invalid_permission")
        return await self.client.set_public_permission(doc_token, token)
