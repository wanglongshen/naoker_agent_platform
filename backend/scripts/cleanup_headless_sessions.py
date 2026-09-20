"""清理 Web home 中由 headless 子任务遗留的历史会话（A6 一次性清理）。

背景：修复前任务链 headless 子任务与 Web 实例共用 `<root>/<uid>` DSH_HOME，
headless 会话因此落在 Web home 的 `sessions/<项目目录>/session-<id>/` 下，并被
`dsh_sync_worker` 同步进 `dsh_sessions`，污染侧栏。修复后 headless 使用
`<root>/<uid>-headless`（A8），本脚本清理存量。

识别口径（dsh-platform/NOTES.md:511）：会话项目目录名由会话 cwd（即 home 绝对
路径）编码而来（`--...var-dsh-<uid>--`），与 Web 实例（cwd=repo root）的项目目录
可精确区分；兼容按 `var-dsh-<uid>` 子串匹配。

用法（在 backend 目录下运行）：
    python -m scripts.cleanup_headless_sessions --dry-run
    python -m scripts.cleanup_headless_sessions
    python -m scripts.cleanup_headless_sessions --user-id <uuid> --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import uuid
from pathlib import Path

from sqlalchemy import delete, func, select

from app.db.session import async_session_factory
from app.models.dsh import DshSession
from app.services.dsh.session_sync import _scan_log

# 演示种子会话（2026-09-18 用 headless 播种的 5 条示例对话）：它们同样落在
# headless 项目目录下，但属于用户要求保留的内容，默认跳过；--include-seeds 可覆盖。
DEMO_SEED_TITLES = {
    "新品抖音千川投放策略",
    "短视频内容选题与脚本框架设计",
    "直播间转化率提升关键动作",
    "广告投放合规风险点",
    "拆解生鲜经营案例提炼打法",
}


def project_key(cwd: str) -> str:
    """DSH `projectKey` 的 Python 移植（session-persistence-jsonl/format.ts:147）。"""
    readable = ""
    separator_run = False
    for ch in cwd:
        code = ord(ch)
        if ch in "/\\:":
            if not separator_run:
                readable += "-"
            separator_run = True
        elif ch != "~" and ch.isascii() and (ch.isalnum() or ch in "._-"):
            readable += ch
            separator_run = False
        else:
            readable += f"~{code:04X}"
            separator_run = False
    slug = readable.lstrip("-") or "root"
    return f"--{slug[:251]}--"


def find_headless_projects(home: Path) -> list[Path]:
    """返回 <home>/sessions 下由 headless（cwd=home）产生的项目目录。"""
    sessions_root = home / "sessions"
    if not sessions_root.is_dir():
        return []
    expected = project_key(str(home))
    legacy_marker = f"var-dsh-{home.name}"
    return [
        child
        for child in sorted(sessions_root.iterdir())
        if child.is_dir() and (child.name == expected or legacy_marker in child.name)
    ]


def iter_project_sessions(project_dir: Path):
    """扫描项目目录下全部会话日志并解析为 DshSessionRecord（解析口径同同步器）。"""
    seen: set[Path] = set()
    for pattern in ("session.jsonl.zstd", "session.jsonl"):
        for path in sorted(project_dir.rglob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            record = _scan_log(raw)
            if record is not None:
                yield record


async def count_rows(user_id: uuid.UUID, session_ids: list[str]) -> int:
    if not session_ids:
        return 0
    async with async_session_factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(DshSession)
            .where(
                DshSession.user_id == user_id,
                DshSession.dsh_session_id.in_(session_ids),
            )
        )
        return int(result.scalar_one())


async def delete_rows(user_id: uuid.UUID, session_ids: list[str]) -> int:
    if not session_ids:
        return 0
    async with async_session_factory() as session:
        result = await session.execute(
            delete(DshSession).where(
                DshSession.user_id == user_id,
                DshSession.dsh_session_id.in_(session_ids),
            )
        )
        await session.commit()
        return result.rowcount or 0


def _is_uuid(name: str) -> bool:
    try:
        uuid.UUID(name)
    except ValueError:
        return False
    return True


def main() -> int:
    from app.core.config import get_settings

    parser = argparse.ArgumentParser(description="清理 Web home 中 headless 遗留会话")
    parser.add_argument("--user-id", default=None, help="只清理指定用户（默认扫描全部）")
    parser.add_argument("--root", default=None, help="DSH home 根目录（默认按 settings 推导）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将删除的内容")
    args = parser.parse_args()

    root = Path(args.root) if args.root else get_settings().dsh_home_root_path
    if not root.is_dir():
        print(f"[错误] home 根目录不存在：{root}")
        return 1

    if args.user_id:
        homes = [root / str(uuid.UUID(args.user_id))]
    else:
        homes = sorted(
            child
            for child in root.iterdir()
            if child.is_dir() and not child.name.endswith("-headless") and _is_uuid(child.name)
        )

    total_projects = total_sessions = total_rows = 0
    for home in homes:
        projects = find_headless_projects(home)
        if not projects:
            continue
        user_id = uuid.UUID(home.name)
        for project in projects:
            records = list(iter_project_sessions(project))
            ids = [record.id for record in records]
            if args.dry_run:
                rows = asyncio.run(count_rows(user_id, ids))
                print(f"[将删除] {project}")
            else:
                rows = asyncio.run(delete_rows(user_id, ids))
                shutil.rmtree(project, ignore_errors=True)
                print(f"[已删除] {project}")
            for record in records:
                print(f"  - {record.title or '(无标题)'} [{record.id}]")
            print(f"  会话 {len(records)} 个，dsh_sessions 记录 {rows} 条")
            total_projects += 1
            total_sessions += len(records)
            total_rows += rows

    prefix = "（dry-run）" if args.dry_run else ""
    print(
        f"[汇总]{prefix}项目目录 {total_projects} 个、会话 {total_sessions} 个、"
        f"dsh_sessions 记录 {total_rows} 条"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
