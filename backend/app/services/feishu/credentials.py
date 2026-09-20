from __future__ import annotations

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.services.feishu.config_service import FeishuConfigService


async def get_feishu_credentials() -> tuple[str, str]:
    """Return (app_id, app_secret). DB default config wins; .env falls back."""
    try:
        async with async_session_factory() as db:
            config = await FeishuConfigService.get_default(db)
            if config is not None:
                return config.app_id, FeishuConfigService.decrypt_secret(config)
    except Exception:
        pass
    settings = get_settings()
    return settings.feishu_app_id, settings.feishu_app_secret
