import asyncio, sys
sys.path.insert(0, ".")
from app.db.session import async_session_factory
from sqlalchemy import func, select
from app.models.agent import AgentSession
from app.models.rbac import User
from app.schemas.agent import AgentSessionResponse

async def test():
    async with async_session_factory() as s:
        stmt = select(AgentSession, func.coalesce(User.display_name, "").label("owner_display_name")
        ).join(User, AgentSession.owner_user_id == User.id, isouter=True
        ).limit(1)
        result = await s.execute(stmt)
        session, dn = result.one()
        session.owner_display_name = dn
        try:
            validated = AgentSessionResponse.model_validate(session)
            print(f"OK: id={validated.id}, dn={validated.owner_display_name!r}")
        except Exception as e:
            print(f"FAIL: {e}")

asyncio.run(test())
