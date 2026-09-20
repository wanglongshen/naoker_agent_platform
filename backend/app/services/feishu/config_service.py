from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.feishu_config import FeishuConfig
from app.services.feishu.crypto import decrypt_token, derive_token_key, encrypt_token


def _config_key() -> bytes:
    return derive_token_key(get_settings().jwt_secret)


class FeishuConfigService:
    @staticmethod
    def decrypt_secret(config: FeishuConfig) -> str:
        return decrypt_token(config.app_secret_encrypted, _config_key())

    @staticmethod
    async def get_default(db: AsyncSession) -> FeishuConfig | None:
        stmt = (
            select(FeishuConfig)
            .where(FeishuConfig.is_default.is_(True))
            .order_by(FeishuConfig.created_at)
        )
        config = await db.scalar(stmt)
        if config is not None:
            return config
        return await db.scalar(
            select(FeishuConfig).order_by(FeishuConfig.created_at).limit(1)
        )

    @staticmethod
    async def list_all(db: AsyncSession) -> list[FeishuConfig]:
        result = await db.execute(
            select(FeishuConfig).order_by(FeishuConfig.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def create(
        db: AsyncSession, name: str, app_id: str, app_secret: str
    ) -> FeishuConfig:
        existing = await db.scalar(select(FeishuConfig).limit(1))
        config = FeishuConfig(
            name=name,
            app_id=app_id,
            app_secret_encrypted=encrypt_token(app_secret, _config_key()),
            is_default=existing is None,
        )
        db.add(config)
        await db.flush()
        return config

    @staticmethod
    async def update(
        db: AsyncSession,
        config_id: uuid.UUID,
        name: str | None = None,
        app_id: str | None = None,
        app_secret: str | None = None,
    ) -> FeishuConfig | None:
        config = await db.get(FeishuConfig, config_id)
        if config is None:
            return None
        if name is not None:
            config.name = name
        if app_id is not None:
            config.app_id = app_id
        if app_secret is not None:
            config.app_secret_encrypted = encrypt_token(app_secret, _config_key())
        await db.flush()
        return config

    @staticmethod
    async def delete(db: AsyncSession, config_id: uuid.UUID) -> bool:
        config = await db.get(FeishuConfig, config_id)
        if config is None:
            return False
        was_default = config.is_default
        await db.delete(config)
        await db.flush()
        if was_default:
            next_config = await db.scalar(
                select(FeishuConfig).order_by(FeishuConfig.created_at).limit(1)
            )
            if next_config is not None:
                next_config.is_default = True
                await db.flush()
        return True

    @staticmethod
    async def activate(db: AsyncSession, config_id: uuid.UUID) -> bool:
        config = await db.get(FeishuConfig, config_id)
        if config is None:
            return False
        await db.execute(
            update(FeishuConfig).values(is_default=False)
        )
        config.is_default = True
        await db.flush()
        return True
