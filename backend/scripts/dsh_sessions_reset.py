"""清理某用户 DSH home 的全部会话，并可播种专业示例对话。

用法（在 backend 目录下运行）：
    python -m scripts.dsh_sessions_reset --user-id <uuid> --dry-run
    python -m scripts.dsh_sessions_reset --user-id <uuid> --clear
    python -m scripts.dsh_sessions_reset --user-id <uuid> --seed

落盘结构（T4 实测）：<home>/sessions/<项目目录>/session-<uuid>/session.jsonl.zstd；
删除项目目录即可让 web 侧栏会话列表消失（session-persistence-jsonl 每次 list 都
直接扫描目录，sqlite 查询索引在 web profile 是内存态）。
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import uuid
from pathlib import Path

from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models.dsh import DshSession
from app.services.dsh.session_sync import iter_sessions

SEED_PROMPTS = [
    "为新品制定一份抖音千川投放策略，包含出价与预算分配",
    "短视频内容选题与脚本框架怎么设计？",
    "直播间转化率提升的关键动作有哪些？",
    "广告投放中哪些表述属于平台规则与广告法风险？",
    "拆解一个生鲜类目的经营案例，提炼可复用打法",
]


def clear_sessions(home: Path) -> int:
    """删除 <home>/sessions 下全部会话，返回删除的会话日志文件数。"""
    sessions_root = home / "sessions"
    if not sessions_root.is_dir():
        return 0
    removed = 0
    for child in sessions_root.iterdir():
        if child.is_dir():
            removed += sum(
                1 for path in child.rglob("session.jsonl*") if path.is_file()
            )
            shutil.rmtree(child, ignore_errors=True)
        else:
            if child.name.startswith("session.jsonl"):
                removed += 1
            child.unlink(missing_ok=True)
    return removed


async def clear_sync_rows(user_id: uuid.UUID) -> int:
    async with async_session_factory() as session:
        result = await session.execute(
            delete(DshSession).where(DshSession.user_id == user_id)
        )
        await session.commit()
        return result.rowcount or 0


async def seed_sessions(
    home: Path, user_id: uuid.UUID, prompts: list[str]
) -> list[str]:
    from app.services.dsh.executor import DshTaskExecutor

    executor = DshTaskExecutor()
    created: list[str] = []
    for prompt in prompts:
        before = {record.id for record in iter_sessions(home)}
        result = await executor.run(
            user_id=user_id, task=prompt, timeout_seconds=900, home_dir=home
        )
        fresh = [r for r in iter_sessions(home) if r.id not in before]
        if not fresh:
            print(f"[播种] 失败（exit={result.exit_code}）：{prompt[:32]}…")
            continue
        record = max(fresh, key=lambda r: r.last_activity_at.timestamp() if r.last_activity_at else 0)
        created.append(record.id)
        title = record.title or prompt[:40]
        print(
            f"[播种] {title} → {record.id}"
            f"（exit={result.exit_code}, {result.duration_seconds}s）"
        )
    return created


def main() -> int:
    from app.core.config import get_settings

    parser = argparse.ArgumentParser(description="清理/播种 DSH 会话")
    parser.add_argument("--user-id", required=True, help="平台用户 UUID")
    parser.add_argument("--home", default=None, help="DSH home（默认按 settings 推导）")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不删除")
    parser.add_argument("--clear", action="store_true", help="删除该用户全部 DSH 会话与同步表记录")
    parser.add_argument("--seed", action="store_true", help="播种专业示例对话")
    args = parser.parse_args()

    user_id = uuid.UUID(args.user_id)
    home = Path(args.home) if args.home else get_settings().dsh_home_root_path / str(user_id)
    if not home.is_dir():
        print(f"[错误] home 不存在：{home}")
        return 1

    records = list(iter_sessions(home))
    print(f"[统计] 会话 {len(records)} 条（home={home}）")
    if args.dry_run:
        for record in records:
            print(f"  - {record.title or '(无标题)'} [{record.id}] turns={record.turn_count}")
        return 0
    if args.clear:
        removed = clear_sessions(home)
        rows = asyncio.run(clear_sync_rows(user_id))
        print(f"[清理] 删除会话日志 {removed} 个、同步表记录 {rows} 条")
    if args.seed:
        created = asyncio.run(seed_sessions(home, user_id, SEED_PROMPTS))
        print(f"[播种] 完成 {len(created)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
