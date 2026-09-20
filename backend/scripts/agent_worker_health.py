import asyncio
import sys
from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.agent import AgentRunAttempt
from sqlalchemy import select, func


async def load_counts():
    async with async_session_factory() as session:
        q = (await session.execute(select(func.count()).select_from(AgentRunAttempt).where(AgentRunAttempt.status == "queued"))).scalar_one()
        r = (await session.execute(select(func.count()).select_from(AgentRunAttempt).where(AgentRunAttempt.status == "running"))).scalar_one()
        return {"queued": q, "running": r, "expired": 0}


def main():
    settings = get_settings()
    configured = bool(settings.deepseek_api_key and settings.deepseek_api_key.strip() and settings.deepseek_api_key != "sk-your-deepseek-api-key")
    print(f"worker_configured={str(configured).lower()}")
    counts = asyncio.run(load_counts())
    for k, v in counts.items():
        print(f"{k}={v}")
