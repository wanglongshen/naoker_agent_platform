from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def required_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://rbac:rbac@localhost:5432/rbac")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "ChangeMe-Strong1")


def test_dsh_settings_defaults():
    from app.core.config import Settings

    s = Settings(_env_file=None)
    assert s.dsh_home_root == "var/dsh"
    assert s.dsh_port_min == 3100
    assert s.dsh_port_max == 3399
    assert s.dsh_idle_seconds == 600
    assert s.dsh_stop_grace_seconds == 30
    assert s.dsh_health_timeout_seconds == 30
    assert s.dsh_instance_mode == "dev_bin"
    assert s.dsh_platform_token_ttl_seconds == 300
    assert s.dsh_trusted_hosts == "localhost:8010"
    assert s.dsh_skills_dir == "skills"


def test_dsh_settings_readable_from_env(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("DSH_INSTANCE_MODE", "vendored")
    monkeypatch.setenv("DSH_PORT_MIN", "3300")
    s = Settings(_env_file=None)
    assert s.dsh_instance_mode == "vendored"
    assert s.dsh_port_min == 3300


def test_dsh_instance_mode_rejects_invalid_value():
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(_env_file=None, dsh_instance_mode="bogus")


def test_dsh_home_root_path_is_absolute_and_anchored_at_backend():
    from app.core.config import Settings

    s = Settings(_env_file=None)
    path = s.dsh_home_root_path
    assert path.is_absolute()
    assert str(path).replace("\\", "/").endswith("/backend/var/dsh")


def test_dsh_home_root_path_respects_absolute_override(tmp_path):
    from app.core.config import Settings

    s = Settings(_env_file=None, dsh_home_root=str(tmp_path))
    assert s.dsh_home_root_path == tmp_path
