from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.dsh import DshInstance
from app.services.dsh.session_sync import sync_user_sessions

logger = logging.getLogger("dsh_sync_worker")

POLL_INTERVAL_SECONDS = 60


async def sync_cycle() -> int:
    """对 state=running 的每个实例 home 执行一次会话同步，返回写入条数。"""
    settings = get_settings()
    home_root = settings.dsh_home_root_path
    synced = 0
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(DshInstance).where(DshInstance.state == "running")
            )
        ).scalars()
        for instance in rows.all():
            home = home_root / str(instance.user_id)
            if not home.is_dir():
                continue
            synced += await sync_user_sessions(db, instance.user_id, home)
        await db.commit()
    return synced


async def main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())

    logger.info("dsh_sync_worker_started")
    while not stop_event.is_set():
        try:
            synced = await sync_cycle()
            logger.info("dsh_sync_cycle_done synced=%s", synced)
        except Exception:  # noqa: BLE001
            logger.exception("dsh_sync_cycle_failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("dsh_sync_worker_stopped")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
