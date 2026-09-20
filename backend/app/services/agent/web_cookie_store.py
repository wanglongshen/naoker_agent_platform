from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.web_cookie import WebCookie
from app.services.feishu.crypto import decrypt_token, derive_token_key, encrypt_token

logger = logging.getLogger(__name__)


def _key() -> bytes:
    settings = get_settings()
    return derive_token_key(settings.feishu_token_encryption_key or settings.jwt_secret)


async def save_user_cookie(
    owner_user_id: uuid.UUID, domain: str, cookie_string: str
) -> None:
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(WebCookie).where(
                WebCookie.owner_user_id == owner_user_id,
                WebCookie.domain == domain,
            )
        )
        if existing is None:
            existing = WebCookie(
                owner_user_id=owner_user_id,
                domain=domain,
                cookie_string=encrypt_token(cookie_string, _key()),
            )
            session.add(existing)
        else:
            existing.cookie_string = encrypt_token(cookie_string, _key())
            session.add(existing)
        await session.commit()


async def get_user_cookie_string(owner_user_id: uuid.UUID, domain: str) -> str | None:
    async with async_session_factory() as session:
        row = await session.scalar(
            select(WebCookie).where(
                WebCookie.owner_user_id == owner_user_id,
                WebCookie.domain == domain,
            )
        )
        if row is None:
            return None
        try:
            return decrypt_token(row.cookie_string, _key())
        except Exception:
            # 密钥轮换/漂移导致无法解密：清理坏记录（永不可恢复），按未登录处理
            logger.warning(
                "web_cookie_decrypt_failed",
                extra={"owner_user_id": str(owner_user_id), "domain": domain},
            )
            await session.delete(row)
            await session.commit()
            return None


async def list_user_cookies(owner_user_id: uuid.UUID) -> list[dict]:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(WebCookie).where(WebCookie.owner_user_id == owner_user_id)
            )
        ).scalars().all()
        return [
            {"domain": r.domain, "cookie_string": r.cookie_string[:20] + "..."}
            for r in rows
        ]


async def delete_user_cookie(owner_user_id: uuid.UUID, domain: str) -> bool:
    async with async_session_factory() as session:
        row = await session.scalar(
            select(WebCookie).where(
                WebCookie.owner_user_id == owner_user_id,
                WebCookie.domain == domain,
            )
        )
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
