import asyncio
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.services.agent.retention import RetentionService
from app.services.agent.storage import PrivateObjectStorage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent_maintenance")

_stop = False


def _handle_signal(signum, frame):
    global _stop
    logger.info("Shutdown signal received")
    _stop = True


async def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    settings = get_settings()
    storage = PrivateObjectStorage(settings.agent_storage_root)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("Agent maintenance started")

    while not _stop:
        now = datetime.now(UTC)

        async with async_session_factory() as session:
            try:
                svc = RetentionService(session=session, storage=storage)
                result = await svc.run_once(now)
                await session.commit()
                logger.info(
                    "Retention completed: attachments=%d events=%d steps=%d attempts=%d runs=%d sessions=%d errors=%d",
                    result.deleted_attachments,
                    result.deleted_events,
                    result.deleted_steps,
                    result.deleted_attempts,
                    result.deleted_runs,
                    result.deleted_sessions,
                    len(result.errors),
                )
            except Exception as exc:
                await session.rollback()
                logger.error("Retention failed: %s", exc)

        await asyncio.sleep(86400)

    logger.info("Agent maintenance stopped")


if __name__ == "__main__":
    asyncio.run(main())
