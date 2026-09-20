import asyncio, sys, json
sys.path.insert(0, ".")
from app.db.session import async_session_factory
from sqlalchemy import func, select
from app.models.agent import AgentSession
from app.models.rbac import User
from app.api.agent_audit import list_audit_sessions
from fastapi import Request
from unittest.mock import AsyncMock

async def test():
    async with async_session_factory() as s:
        # Test the query directly
        stmt = select(
            AgentSession, func.coalesce(User.display_name, "").label("owner_display_name")
        ).join(User, AgentSession.owner_user_id == User.id, isouter=True
        ).order_by(AgentSession.updated_at.desc()).limit(3)
        
        result = await s.execute(stmt)
        rows = result.all()
        print(f"Rows: {len(rows)}")
        for session, dn in rows:
            print(f"  title={session.title}, display_name={dn!r}")

asyncio.run(test())
