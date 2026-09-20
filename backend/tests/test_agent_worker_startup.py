import pytest

from app.core.config import Settings


def test_worker_rejects_missing_deepseek_key():
    s = Settings.model_construct(
        deepseek_api_key=None,
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-chat",
    )
    from app.workers.agent_worker import validate_agent_worker_settings

    with pytest.raises(Exception, match="DEEPSEEK_API_KEY"):
        validate_agent_worker_settings(s)


def test_worker_rejects_example_deepseek_key():
    s = Settings.model_construct(
        deepseek_api_key="sk-your-deepseek-api-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-chat",
    )
    from app.workers.agent_worker import validate_agent_worker_settings

    with pytest.raises(Exception, match="DEEPSEEK_API_KEY"):
        validate_agent_worker_settings(s)


def test_worker_accepts_valid_deepseek_key():
    s = Settings.model_construct(
        deepseek_api_key="sk-real-key-not-placeholder",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-chat",
    )
    from app.workers.agent_worker import validate_agent_worker_settings

    validate_agent_worker_settings(s)
