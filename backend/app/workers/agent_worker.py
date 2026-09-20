from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys

from app.core.config import Settings, get_settings
from app.services.agent.worker import AgentWorker

logger = logging.getLogger("agent_worker")


class ProviderConfigurationError(Exception):
    pass


def validate_agent_worker_settings(settings: Settings) -> None:
    if not settings.deepseek_api_key:
        raise ProviderConfigurationError("DEEPSEEK_API_KEY is required")
    key = settings.deepseek_api_key.strip()
    if not key or key == "sk-your-deepseek-api-key":
        raise ProviderConfigurationError("DEEPSEEK_API_KEY is still the example value")


async def main() -> None:
    settings = get_settings()
    validate_agent_worker_settings(settings)
    from app.services.agent.loop import init_redis_bridge, shutdown_redis_bridge
    await init_redis_bridge(subscribe=False)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    logger.info(
        "agent_worker_started",
        extra={
            "worker_id": worker_id,
            "model": settings.deepseek_model,
        },
    )
    try:
        worker = AgentWorker(worker_id=worker_id, concurrency=settings.worker_concurrency)
        await worker.run()
    finally:
        await shutdown_redis_bridge()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
