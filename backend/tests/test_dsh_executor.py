from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from app.services.dsh.executor import DshTaskExecutor


@pytest.fixture
def executor(monkeypatch):
    ex = DshTaskExecutor()

    async def _skip_prepare(home, user_id):
        return None

    monkeypatch.setattr(ex, "_prepare_home", _skip_prepare)
    return ex


def test_spawn_command_uses_headless_profile_and_home(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "dsh_instance_mode", "vendored")
    exe = DshTaskExecutor().spawn_command(tmp_path, "写一句话")
    assert exe[0] == "node"
    assert exe[1].endswith("deepseek-harness/apps/cli/lib/bin.js")
    assert exe[2:4] == ["--profile", "headless"]
    assert exe[-1] == "写一句话"


def test_spawn_command_dev_bin_uses_resolved_js(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings
    from app.services.dsh import instance_config

    monkeypatch.setattr(get_settings(), "dsh_instance_mode", "dev_bin")
    monkeypatch.setattr(instance_config, "resolve_dsh_js", lambda: "X:/npm/dsh/lib/bin.js")
    exe = DshTaskExecutor().spawn_command(tmp_path, "task")
    assert exe == ["node", "X:/npm/dsh/lib/bin.js", "--profile", "headless", "task"]


def test_task_timeout_setting_has_positive_default():
    from app.core.config import get_settings

    assert float(get_settings().dsh_task_timeout_seconds) > 0


def test_install_connector_plugin_uses_given_profile(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings
    from app.services.dsh import instance_config

    monkeypatch.setattr(get_settings(), "dsh_instance_mode", "vendored")
    calls: list[list[str]] = []

    class _Completed:
        returncode = 0
        stdout = ""

    monkeypatch.setattr(instance_config.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or _Completed())

    instance_config.install_connector_plugin(tmp_path, profile="headless")
    assert calls[0][2:6] == ["plugin", "--profile", "headless", "list"]
    assert calls[1][2:6] == ["plugin", "--profile", "headless", "add"]

    instance_config.install_connector_plugin(tmp_path)
    assert calls[2][3:5] == ["--profile", "web"]
    assert calls[3][3:5] == ["--profile", "web"]


@pytest.mark.anyio
async def test_run_returns_final_text_and_exit_code(tmp_path: Path, monkeypatch, executor):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "dsh_instance_mode", "vendored")
    seen: dict = {}

    async def fake_spawn(cmd, *, env, cwd, timeout):
        seen["env"] = env
        seen["cwd"] = cwd
        seen["timeout"] = timeout
        return (0, "这是最终回复\n", "")

    monkeypatch.setattr(executor, "_spawn", fake_spawn)
    result = await executor.run(user_id=uuid.uuid4(), task="写一句话", home_dir=tmp_path)
    assert result.final_text == "这是最终回复"
    assert result.exit_code == 0
    assert result.stdout == "这是最终回复\n"
    assert result.duration_seconds >= 0
    assert seen["env"]["DSH_HOME"] == str(tmp_path)
    assert seen["cwd"] == tmp_path
    assert seen["timeout"] == settings.dsh_task_timeout_seconds


def test_ensure_home_config_writes_given_profile_dir(tmp_path: Path):
    from app.services.dsh.instance_config import ensure_home_config

    skills = tmp_path / "skills-src"
    skills.mkdir()
    ensure_home_config(
        tmp_path,
        platform_base="http://127.0.0.1:8000",
        user_id="u-1",
        platform_token="tok-1",
        trusted_host="localhost:8000",
        skills_src=skills,
        profile="headless",
    )
    patch = (tmp_path / "profiles" / "headless" / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "platformToken: tok-1" in patch
    assert not (tmp_path / "profiles" / "web" / "cordis.patch.yml").exists()


@pytest.mark.anyio
async def test_run_installs_connector_for_headless_profile(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings
    from app.services.dsh import instance_config

    monkeypatch.setattr(get_settings(), "dsh_instance_mode", "vendored")
    installs: list[tuple] = []
    configs: list[dict] = []
    monkeypatch.setattr(
        instance_config,
        "install_connector_plugin",
        lambda home, connector_pkg=None, profile="web": installs.append((home, profile)),
    )
    monkeypatch.setattr(
        instance_config,
        "ensure_home_config",
        lambda home, **kwargs: configs.append({"home": home, **kwargs}),
    )
    executor = DshTaskExecutor()
    user_id = uuid.uuid4()

    async def fake_spawn(cmd, *, env, cwd, timeout):
        return (0, "ok", "")

    monkeypatch.setattr(executor, "_spawn", fake_spawn)
    await executor.run(user_id=user_id, task="x", home_dir=tmp_path)
    assert installs == [(tmp_path, "headless")]
    assert configs[0]["home"] == tmp_path
    assert configs[0]["profile"] == "headless"
    assert configs[0]["user_id"] == str(user_id)
    assert configs[0]["platform_token"]


@pytest.mark.anyio
async def test_run_defaults_home_to_settings_root(tmp_path: Path, monkeypatch, executor):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "dsh_instance_mode", "vendored")
    monkeypatch.setattr(settings, "dsh_home_root", str(tmp_path))
    user_id = uuid.uuid4()
    seen: dict = {}

    async def fake_spawn(cmd, *, env, cwd, timeout):
        seen["env"] = env
        return (0, "ok", "")

    monkeypatch.setattr(executor, "_spawn", fake_spawn)
    await executor.run(user_id=user_id, task="x")
    assert seen["env"]["DSH_HOME"] == str(tmp_path / str(user_id))
    assert (tmp_path / str(user_id)).is_dir()


@pytest.mark.anyio
async def test_run_marks_nonzero_exit_with_stderr(tmp_path: Path, monkeypatch, executor):
    async def fake_spawn(cmd, *, env, cwd, timeout):
        return (1, "", "boom")

    monkeypatch.setattr(executor, "_spawn", fake_spawn)
    result = await executor.run(user_id=uuid.uuid4(), task="x", home_dir=tmp_path)
    assert result.exit_code == 1
    assert "boom" in result.stderr


@pytest.mark.anyio
async def test_run_timeout_returns_124(tmp_path: Path, monkeypatch, executor):
    async def fake_spawn(cmd, *, env, cwd, timeout):
        raise asyncio.TimeoutError

    monkeypatch.setattr(executor, "_spawn", fake_spawn)
    result = await executor.run(
        user_id=uuid.uuid4(), task="x", home_dir=tmp_path, timeout_seconds=1.5
    )
    assert result.exit_code == 124
    assert "timeout" in result.stderr
    assert result.final_text == ""


@pytest.mark.anyio
async def test_spawn_falls_back_to_popen_when_selector_loop(monkeypatch):
    """Windows SelectorEventLoop（uvicorn --reload / worker 策略）下 create_subprocess_exec
    抛 NotImplementedError，必须回退到 subprocess.Popen 且拿到真实输出。"""
    import asyncio as asyncio_module
    import os
    import sys

    from app.services.dsh.executor import DshTaskExecutor

    async def boom(*args, **kwargs):
        raise NotImplementedError

    monkeypatch.setattr(asyncio_module, "create_subprocess_exec", boom)
    executor = DshTaskExecutor()
    code, out, err = await executor._spawn(
        [sys.executable, "-c", "print('fallback-ok')"],
        env=dict(os.environ),
        cwd=Path.cwd(),
        timeout=60,
    )
    assert code == 0
    assert "fallback-ok" in out
