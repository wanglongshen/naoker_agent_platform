from __future__ import annotations

import asyncio
import logging
import signal
import sys

from app.db.session import async_session_factory
from app.repositories.task_chain_repository import TaskChainRepository
from app.services.task_chain import TaskChainService

logger = logging.getLogger("task_chain_worker")

POLL_INTERVAL_SECONDS = 3


async def run_cycle() -> bool:
    """领取并执行一条 queued 任务链；返回是否实际执行了任务链。"""
    async with async_session_factory() as db:
        repo = TaskChainRepository(db)
        chain = await repo.claim_next_chain()
        if chain is None:
            return False
        logger.info("task_chain_claimed chain=%s user=%s", chain.id, chain.user_id)
        service = TaskChainService(repo)
        await service.run_chain(chain.id)
    return True


async def main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())

    logger.info("task_chain_worker_started")
    while not stop_event.is_set():
        try:
            ran = await run_cycle()
        except Exception:  # noqa: BLE001
            logger.exception("task_chain_cycle_failed")
            ran = False
        if ran:
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("task_chain_worker_stopped")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
