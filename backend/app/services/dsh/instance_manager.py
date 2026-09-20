from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.dsh import DshInstance

logger = logging.getLogger("dsh.instances")

_STATE_STARTING = "starting"
_STATE_RUNNING = "running"
_STATE_STOPPED = "stopped"
_STATE_ERROR = "error"


class _PopenProcess:
    """subprocess.Popen 适配器：Selector 事件循环（Windows + uvicorn --reload）下
    的替代实现——该循环不支持 asyncio.create_subprocess_exec（NotImplementedError）。"""

    def __init__(self, popen: subprocess.Popen):
        self._p = popen
        self.pid = popen.pid

    async def wait(self):
        return await asyncio.to_thread(self._p.wait)

    def terminate(self):
        self._p.terminate()

    def kill(self):
        self._p.kill()


class DshInstanceManager:
    """每用户 DSH 实例生命周期管理（启动/复用/空闲回收/停止）。"""

    def __init__(
        self,
        settings: Settings | None = None,
        process_factory: Callable[..., Awaitable[Any]] | None = None,
        probe: Callable[..., bool] | None = None,
        probe_timeout: float | None = None,
        probe_interval: float = 0.5,
        stop_grace: float | None = None,
    ):
        self.settings = settings or get_settings()
        self.repo_root = Path(__file__).resolve().parents[4]
        self.process_factory = process_factory or self._default_process_factory
        self.probe = probe or self._default_probe
        self.probe_timeout = probe_timeout or float(self.settings.dsh_health_timeout_seconds)
        self.probe_interval = probe_interval
        self.stop_grace = stop_grace or float(self.settings.dsh_stop_grace_seconds)
        self._running: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._sweep_lock = asyncio.Lock()

    # ---------- resolution helpers ----------

    def resolve_port(self, user_id: str) -> int:
        digest = hashlib.md5(user_id.encode("utf-8")).hexdigest()
        span = self.settings.dsh_port_max - self.settings.dsh_port_min + 1
        return self.settings.dsh_port_min + (int(digest, 16) % span)

    def spawn_command(self, user_id: str, home: str, port: int, trusted_host: str) -> list[str]:
        base = ["--profile", "web", "--host", "127.0.0.1", "--port", str(port),
                "--no-open", "--trusted-host", trusted_host]
        if self.settings.dsh_instance_mode == "vendored":
            return ["node",
                    str((self.repo_root / "deepseek-harness/apps/cli/lib/bin.js").as_posix()),
                    *base]
        from app.services.dsh.instance_config import resolve_dsh_js

        js = resolve_dsh_js()
        if js:
            return ["node", js, *base]
        return ["dsh", *base]

    def spawn_env(self, home: str) -> dict[str, str]:
        env = dict(os.environ)
        env["DSH_HOME"] = str(home)
        env.setdefault("DEEPSEEK_API_KEY", self.settings.deepseek_api_key or "")
        return env

    # ---------- lifecycle ----------

    def _lock_for(self, user_id: str) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    async def _default_process_factory(self, cmd: list[str], env: dict[str, str], cwd: str,
                                       log_path: str | None = None):
        loop = asyncio.get_running_loop()
        use_popen = sys.platform == "win32" and not isinstance(loop, asyncio.ProactorEventLoop)
        if use_popen:
            sink = open(log_path, "ab") if log_path else subprocess.DEVNULL
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            popen = await asyncio.to_thread(
                subprocess.Popen, cmd, env=env, cwd=cwd,
                stdout=sink, stderr=sink, creationflags=flags,
            )
            return _PopenProcess(popen)
        if log_path:
            sink = open(log_path, "ab")
            return await asyncio.create_subprocess_exec(
                *cmd, env=env, cwd=cwd, stdout=sink, stderr=sink)
        return await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            cwd=cwd,
            stdout=None,
            stderr=None,
        )

    async def _default_probe(self, port: int) -> bool:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=1.0)
        except (OSError, asyncio.TimeoutError):
            return False
        writer.close()
        return True

    async def _health_wait(self, port: int) -> bool:
        deadline = asyncio.get_running_loop().time() + self.probe_timeout
        while asyncio.get_running_loop().time() < deadline:
            result = self.probe(port)
            if inspect.isawaitable(result):
                result = await result
            if result:
                return True
            await asyncio.sleep(self.probe_interval)
        return False

    async def get(self, user_id: str, db: AsyncSession) -> DshInstance | None:
        return (
            await db.execute(
                select(DshInstance).where(DshInstance.user_id == user_id)
            )
        ).scalar_one_or_none()

    async def _tcp_ok(self, port: int) -> bool:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=1.0)
        except (OSError, asyncio.TimeoutError):
            return False
        writer.close()
        return True

    async def check_alive(self, user_id: str, db: AsyncSession) -> DshInstance | None:
        """活性校正：DB 标记 running 但进程已死时，把状态修正为 stopped。

        进程独立于 API 存活/死亡，DB 状态是快照而非事实——所有对外读路径
        （状态查询/反代）都必须先过这里，避免把死实例当运行中。
        """
        row = await self.get(user_id, db)
        if row is None or row.state != _STATE_RUNNING:
            return row
        if await self._tcp_ok(row.port):
            return row
        logger.info("dsh instance died user=%s port=%s", user_id, row.port)
        row.state = _STATE_STOPPED
        row.pid = None
        row.error_hint = "process_exited"
        await db.commit()
        await db.refresh(row)
        return row

    async def ensure_running(self, user_id: str, db: AsyncSession) -> DshInstance:
        uid_key = str(user_id)
        async with self._lock_for(uid_key):
            existing = await self.get(user_id, db)
            if existing and existing.state == _STATE_RUNNING:
                return existing

            home_dir = self.settings.dsh_home_root_path / uid_key
            home_dir.mkdir(parents=True, exist_ok=True)
            port = self.resolve_port(uid_key)
            trusted = self.settings.dsh_trusted_hosts

            # 收养已存在的同端口进程（API 重启后进程仍活着的场景），避免重复 spawn
            if await self._tcp_ok(port):
                if existing is None:
                    existing = DshInstance(user_id=user_id, port=port, state=_STATE_RUNNING)
                    db.add(existing)
                else:
                    existing.state = _STATE_RUNNING
                    existing.port = port
                    existing.error_hint = None
                await db.commit()
                await db.refresh(existing)
                logger.info("adopt existing dsh process user=%s port=%s", uid_key, port)
                return existing

            cmd = self.spawn_command(uid_key, str(home_dir), port, trusted)
            env = self.spawn_env(str(home_dir))

            if existing is None:
                existing = DshInstance(
                    user_id=user_id,
                    port=port,
                    state=_STATE_STARTING,
                )
                db.add(existing)
            else:
                existing.state = _STATE_STARTING
                existing.port = port
                existing.error_hint = None
            await db.commit()
            await db.refresh(existing)

            logger.info("spawn dsh user=%s mode=%s port=%s", uid_key,
                        self.settings.dsh_instance_mode, port)
            try:
                from app.services.dsh.instance_config import (
                    ensure_home_config,
                    install_connector_plugin,
                )
                from app.core.security import mint_platform_token

                ensure_home_config(
                    home_dir=home_dir,
                    platform_base=self.settings.dsh_platform_base,
                    user_id=uid_key,
                    platform_token=mint_platform_token(
                        uid_key, int(self.settings.dsh_platform_token_ttl_seconds)),
                    trusted_host=trusted,
                    skills_src=self.repo_root / "dsh-platform/skills-template",
                )
                install_connector_plugin(
                    dsh_home=home_dir,
                    connector_pkg=self.repo_root / "dsh-platform/packages/server-connector",
                )
            except Exception:  # noqa: BLE001
                logger.exception("instance config injection failed user=%s", uid_key)
            try:
                proc = await self.process_factory(
                    cmd=cmd, env=env, cwd=str(self.repo_root),
                    log_path=str(home_dir / "dsh-web.log"))
            except Exception as exc:  # noqa: BLE001
                logger.error("spawn failed user=%s: %s", uid_key, exc)
                existing.state = _STATE_ERROR
                existing.error_hint = f"spawn_failed: {type(exc).__name__}"
                await db.commit()
                return existing

            self._running[uid_key] = proc
            if await self._health_wait(port):
                existing.state = _STATE_RUNNING
                existing.pid = int(getattr(proc, "pid", 0) or 0)
                existing.last_active_at = datetime.now(UTC)
                await db.commit()
                await db.refresh(existing)
            else:
                try:
                    proc.terminate()
                except (AttributeError, OSError, ProcessLookupError):
                    pass
                existing.state = _STATE_ERROR
                existing.error_hint = "health_timeout"
                await db.commit()
            return existing

    async def refresh_injection(
        self, user_id: uuid.UUID, db: AsyncSession | None = None
    ) -> None:
        """刷新该用户的平台注入（token 会过期，任务链每次执行前调用）。

        ``ensure_home_config`` 对 connector 行是整段替换语义，重签 token 后
        重写 patch 行即可，无需重启实例。
        """
        from app.core.security import mint_platform_token
        from app.services.dsh.instance_config import ensure_home_config

        settings = self.settings
        home = settings.dsh_home_root_path / str(user_id)
        home.mkdir(parents=True, exist_ok=True)
        ensure_home_config(
            home_dir=home,
            platform_base=settings.dsh_platform_base,
            user_id=str(user_id),
            platform_token=mint_platform_token(
                str(user_id), int(settings.dsh_platform_token_ttl_seconds)
            ),
            trusted_host=settings.dsh_trusted_hosts,
            skills_src=self.repo_root / "dsh-platform/skills-template",
        )

    async def stop(self, user_id: str, db: AsyncSession, force: bool = False) -> DshInstance | None:
        uid_key = str(user_id)
        async with self._lock_for(uid_key):
            existing = await self.get(user_id, db)
            if existing is None:
                return None
            proc = self._running.pop(uid_key, None)
            if proc is not None:
                try:
                    proc.terminate()
                except (AttributeError, OSError, ProcessLookupError):
                    pass
                if force:
                    try:
                        proc.kill()
                    except (AttributeError, OSError, ProcessLookupError):
                        pass
                else:
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=self.stop_grace)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except (AttributeError, OSError, ProcessLookupError):
                            pass
            existing.state = _STATE_STOPPED
            existing.pid = None
            await db.commit()
            await db.refresh(existing)
            return existing

    async def sweep_idle(self, db: AsyncSession) -> int:
        stopped = 0
        async with self._sweep_lock:
            cutoff = datetime.now(UTC) - timedelta(seconds=self.settings.dsh_idle_seconds)
            rows = (
                await db.execute(
                    select(DshInstance).where(
                        DshInstance.state == _STATE_RUNNING,
                        DshInstance.last_active_at < cutoff,
                    )
                )
            ).scalars().all()
            for row in rows:
                await self.stop(row.user_id, db)
                stopped += 1
        return stopped

    async def touch(self, user_id: str, db: AsyncSession) -> None:
        row = await self.get(user_id, db)
        if row is None:
            return
        row.last_active_at = datetime.now(UTC)
        await db.commit()
