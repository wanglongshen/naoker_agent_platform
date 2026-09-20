from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def required_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://rbac:rbac@localhost:5432/rbac")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "ChangeMe-Strong1")


def test_langgraph_flag_default_true():
    from app.core.config import Settings
    s = Settings(_env_file=None)
    assert s.langgraph_enabled is True


def test_langgraph_flag_env_false_rolls_back(monkeypatch):
    from app.core.config import Settings
    monkeypatch.setenv("LANGGRAPH_ENABLED", "false")
    s = Settings(_env_file=None)
    assert s.langgraph_enabled is False


def test_langgraph_flag_readable_from_env(monkeypatch):
    from app.core.config import Settings
    monkeypatch.setenv("LANGGRAPH_ENABLED", "true")
    s = Settings(_env_file=None)
    assert s.langgraph_enabled is True
