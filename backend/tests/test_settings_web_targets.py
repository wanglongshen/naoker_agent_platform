from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def required_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://rbac:rbac@localhost:5432/rbac")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "ChangeMe-Strong1")


def test_web_tool_allow_non_global_targets_defaults_off():
    from app.core.config import Settings

    assert Settings(_env_file=None).web_tool_allow_non_global_targets is False


def test_web_tool_allow_non_global_targets_readable_from_env(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("WEB_TOOL_ALLOW_NON_GLOBAL_TARGETS", "true")
    assert Settings(_env_file=None).web_tool_allow_non_global_targets is True
