from app.core.config import get_settings


def test_settings_load_database_url_from_backend_env() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url.startswith("postgresql+asyncpg://")
