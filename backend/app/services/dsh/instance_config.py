"""DSH 每用户实例配置注入：profile patch 行 + skills 拷贝。

patch 文件按 DSH 真实语法写入（见 dsh-platform/NOTES.md 第 2 项）：用户层
`profiles/web/cordis.patch.yml` 以 id 定向覆盖 connector 的 config，
语义为「整段替换」——每次调用重写完整 config 三键（platformBase/userId/
platformToken），因此重复调用天然刷新 platform_token 值且不产生重复行。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("dsh.instance_config")

CONNECTOR_ID = "naoker-platform-connector"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_dsh_js_cache: str | None = None


def resolve_dsh_js() -> str | None:
    """dev_bin 模式下把 `dsh` 命令解析成真实 node 入口（npm 全局 shim 不是 exe）。

    若 PATH 上存在 npm 全局 @deepseek-ai/dsh，返回其 lib/bin.js 绝对路径；
    解析失败返回 None（调用方回退为直接跑 `dsh`，失败即报）。
    """
    global _dsh_js_cache
    if _dsh_js_cache:
        return _dsh_js_cache
    import shutil

    for name in ("dsh", "dsh.cmd", "dsh.ps1"):
        hit = shutil.which(name)
        if not hit:
            continue
        js = (Path(hit).resolve().parent / "node_modules/@deepseek-ai/dsh/lib/bin.js")
        if js.exists():
            _dsh_js_cache = str(js)
            return _dsh_js_cache
    return None


def install_connector_plugin(
    dsh_home: Path, connector_pkg: Path | None = None, profile: str = "web"
) -> None:
    """一次性把 connector 插件包 install 进该实例的指定 profile（幂等）。

    ``dsh plugin --profile <profile> add <pkg>`` 注册插件到该 profile；
    已安装（``dsh plugin --profile <profile> list`` 含包名）则跳过。失败不抛异常——
    插件缺失只影响工具可用性，不阻塞实例启动（日志记录）。默认 web（实例管理路径），
    任务链 headless 子任务执行前传 ``profile="headless"``（headless 模板不带该插件）。
    """
    from app.core.config import get_settings

    settings = get_settings()
    if settings.dsh_instance_mode == "vendored":
        exe = ["node", str((_REPO_ROOT / "deepseek-harness/apps/cli/lib/bin.js").as_posix())]
    else:
        js = resolve_dsh_js()
        exe = ["node", js] if js else ["dsh"]
    pkg = connector_pkg or (_REPO_ROOT / "dsh-platform/packages/server-connector")
    marker = re.compile(r"@?naoker[-\w/]*platform-connector")
    list_cmd = exe + ["plugin", "--profile", profile, "list"]
    env = dict(os.environ)
    env["DSH_HOME"] = str(dsh_home)
    try:
        out = subprocess.run(
            list_cmd, capture_output=True, text=True, timeout=60,
            env=env, encoding="utf-8", errors="replace",
        )
        if marker.search(out.stdout):
            return
    except Exception:  # noqa: BLE001
        logger.exception("connector plugin check failed home=%s", dsh_home)
    try:
        subprocess.run(
            exe + ["plugin", "--profile", profile, "add", str(pkg)],
            capture_output=True, text=True, timeout=180,
            env=env, encoding="utf-8", errors="replace",
        )
        logger.info("connector plugin installed into home=%s", dsh_home)
    except Exception:  # noqa: BLE001
        logger.exception("connector plugin install failed home=%s", dsh_home)


def _render_row(platform_base: str, user_id: str, platform_token: str) -> str:
    return (
        f"- id: {CONNECTOR_ID}\n"
        "  config:\n"
        f"    platformBase: {platform_base}\n"
        f"    userId: {user_id}\n"
        f"    platformToken: {platform_token}"
    )


def _row_block(lines: list[str]) -> tuple[int, int] | None:
    for i, line in enumerate(lines):
        if line.strip() == f"- id: {CONNECTOR_ID}":
            end = i + 1
            while end < len(lines) and (lines[end] == "" or lines[end][0].isspace()):
                end += 1
            return i, end
    return None


def ensure_home_config(
    home_dir: Path,
    *,
    platform_base: str,
    user_id: str,
    platform_token: str,
    trusted_host: str,
    skills_src: Path,
    profile: str = "web",
) -> None:
    """为单个 DSH 实例写入平台注入并拷贝技能目录（幂等，返回 None）。

    - ``<home>/profiles/<profile>/cordis.patch.yml``：存在 ``id: naoker-platform-connector``
      行则整段替换该行（config 三键一次写齐，platform_token 随之刷新），
      否则追加新行；目录不存在时先行创建。默认 web（实例管理路径），
      任务链 headless 子任务传 ``profile="headless"``（headless 模板不含 connector）。
    - ``<home>/skills/``：递归拷贝 ``skills_src`` 树（dirs_exist_ok，幂等）。
    - ``trusted_host`` 为接口占位：spawn 层已通过 ``--trusted-host`` CLI 传参
      （NOTES 第 5 项），此处不落盘。
    """
    patch_dir = home_dir / "profiles" / profile
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch_file = patch_dir / "cordis.patch.yml"
    new_row = _render_row(platform_base, user_id, platform_token)

    if patch_file.exists():
        lines = patch_file.read_text(encoding="utf-8").splitlines()
        found = _row_block(lines)
        if found is None:
            lines = [line for line in lines if line.strip() != "[]"]
            new_text = ("\n".join(lines).rstrip("\n") + "\n" + new_row).strip("\n") + "\n"
        else:
            start, end = found
            new_text = (
                "\n".join(lines[:start] + new_row.splitlines() + lines[end:]).strip("\n")
                + "\n"
            )
    else:
        new_text = new_row + "\n"
    patch_file.write_text(new_text, encoding="utf-8")

    shutil.copytree(skills_src, home_dir / "skills", dirs_exist_ok=True)
