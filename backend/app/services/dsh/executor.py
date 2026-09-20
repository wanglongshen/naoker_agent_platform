"""DSH headless 子任务执行层：任务链的「执行工人」。

决策（2026-09-15）：走 headless CLI 而不是 Python SDK——SDK 需要额外 runtime
二进制（deepseek-harness/python/sdk），CLI 已 vendored 且与实例管理共用 DSH_HOME；
两者产物等价（最终文本），usage 统一从会话 JSONL 读取（services/dsh/usage.py）。

CLI 行为实测（2026-09-15，node 24 + vendored bin.js，DSH_HOME=已存在用户 home）：
`node deepseek-harness/apps/cli/lib/bin.js --profile headless "用一句话介绍你自己"`
→ 6.93s、exit 0、stdout 即最终 assistant 文本（UTF-8，尾随换行）、stderr 为空；
失败时以非 0 退出（上游 `apps/cli/reference/README.md`：completed 才 0）。
headless profile 首次使用自动初始化，但不带 connector 插件（`plugin --profile
headless list` 为空）；且只装插件不写平台配置会让插件树加载失败（platformBase
缺失，实测 exit 1），故执行前对 headless profile 幂等安装 connector 并重写
`profiles/headless/cordis.patch.yml` 平台注入（token 每次执行前刷新）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger("dsh.executor")

_REPO_ROOT = Path(__file__).resolve().parents[4]
_connector_ready: set[str] = set()


@dataclass
class DshTaskResult:
    final_text: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


class DshTaskExecutor:
    def spawn_command(self, home: Path, task: str) -> list[str]:
        settings = get_settings()
        if settings.dsh_instance_mode == "vendored":
            exe = ["node", (_REPO_ROOT / "deepseek-harness/apps/cli/lib/bin.js").as_posix()]
        else:
            from app.services.dsh.instance_config import resolve_dsh_js

            js = resolve_dsh_js()
            exe = ["node", js] if js else ["dsh"]
        return exe + ["--profile", "headless", task]

    def _env(self, home: Path) -> dict[str, str]:
        settings = get_settings()
        env = dict(os.environ)
        env["DSH_HOME"] = str(home)
        if settings.deepseek_api_key:
            env["DEEPSEEK_API_KEY"] = settings.deepseek_api_key
        return env

    async def _prepare_home(self, home: Path, user_id: uuid.UUID) -> None:
        """headless profile 的 connector 安装与平台注入（幂等）。

        插件安装检查较贵（node 启动约 2s），按 home 进程内缓存；平台配置行每次
        执行前重写（token 过期即刷新，语义同 web 实例的 ensure_home_config）。
        """
        from app.core.security import mint_platform_token
        from app.services.dsh.instance_config import (
            ensure_home_config,
            install_connector_plugin,
        )

        settings = get_settings()
        key = str(home)
        if key not in _connector_ready:
            await asyncio.to_thread(install_connector_plugin, home, None, "headless")
            _connector_ready.add(key)
        await asyncio.to_thread(
            ensure_home_config,
            home,
            platform_base=settings.dsh_platform_base,
            user_id=str(user_id),
            platform_token=mint_platform_token(
                str(user_id), int(settings.dsh_platform_token_ttl_seconds)
            ),
            trusted_host=settings.dsh_trusted_hosts,
            skills_src=_REPO_ROOT / "dsh-platform/skills-template",
            profile="headless",
        )

    async def _spawn(self, cmd: list[str], *, env: dict[str, str], cwd: Path, timeout: float):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, env=env, cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except NotImplementedError:
            # Windows 的 SelectorEventLoop（uvicorn --reload / worker 策略）不支持
            # create_subprocess_exec，回退到线程里的 subprocess.Popen（同实例管理器口径）。
            return await self._spawn_popen(cmd, env=env, cwd=cwd, timeout=timeout)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        return (
            int(proc.returncode or 0),
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"),
        )

    async def _spawn_popen(
        self, cmd: list[str], *, env: dict[str, str], cwd: Path, timeout: float
    ) -> tuple[int, str, str]:
        def _run() -> tuple[int, str, str]:
            proc = subprocess.Popen(
                cmd,
                env=env,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise
            return (
                int(proc.returncode or 0),
                out.decode("utf-8", errors="replace"),
                err.decode("utf-8", errors="replace"),
            )

        try:
            return await asyncio.to_thread(_run)
        except subprocess.TimeoutExpired as exc:
            raise asyncio.TimeoutError from exc

    async def run(
        self,
        *,
        user_id: uuid.UUID,
        task: str,
        timeout_seconds: float | None = None,
        home_dir: Path | None = None,
    ) -> DshTaskResult:
        settings = get_settings()
        home = home_dir or (settings.dsh_home_root_path / str(user_id))
        home.mkdir(parents=True, exist_ok=True)
        await self._prepare_home(home, user_id)
        cmd = self.spawn_command(home, task)
        timeout = timeout_seconds or settings.dsh_task_timeout_seconds
        started = time.monotonic()
        try:
            code, out, err = await self._spawn(cmd, env=self._env(home), cwd=home, timeout=timeout)
        except asyncio.TimeoutError:
            code, out, err = 124, "", f"dsh task timeout after {timeout}s"
            logger.warning("dsh task timeout user=%s task=%s", user_id, task[:80])
        return DshTaskResult(
            final_text=out.strip(),
            exit_code=code,
            stdout=out,
            stderr=err,
            duration_seconds=round(time.monotonic() - started, 3),
        )
