import pytest

from app.services.feishu.config_service import FeishuConfigService
from app.services.feishu.credentials import get_feishu_credentials


class TestGetFeishuCredentials:
    @pytest.mark.anyio
    async def test_returns_db_default_when_configured(self, test_db, monkeypatch):
        from app.services.feishu import credentials as creds_module

        monkeypatch.setattr(creds_module, "async_session_factory", test_db)
        async with test_db() as db:
            await FeishuConfigService.create(db, "公司A", "cli_db", "secret-db")
            await db.commit()

        app_id, secret = await get_feishu_credentials()
        assert app_id == "cli_db"
        assert secret == "secret-db"

    @pytest.mark.anyio
    async def test_falls_back_to_env_when_no_db_config(self, test_db, monkeypatch):
        from app.core.config import get_settings
        from app.services.feishu import credentials as creds_module

        monkeypatch.setattr(creds_module, "async_session_factory", test_db)
        monkeypatch.setattr(get_settings(), "feishu_app_id", "cli_env")
        monkeypatch.setattr(get_settings(), "feishu_app_secret", "secret-env")
        app_id, secret = await get_feishu_credentials()
        assert app_id == "cli_env"
        assert secret == "secret-env"
