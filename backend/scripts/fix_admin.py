import asyncio, sys
sys.path.insert(0, ".")
from app.db.session import async_session_factory
from sqlalchemy import select
from app.models.rbac import User
from argon2 import PasswordHasher
from app.core.config import get_settings

async def reset():
    settings = get_settings()
    async with async_session_factory() as s:
        user = (await s.execute(select(User).where(User.username == "admin"))).scalar_one()
        ph = PasswordHasher()
        user.password_hash = ph.hash(settings.initial_admin_password)
        s.add(user)
        await s.commit()
        print(f"Password reset to: {settings.initial_admin_password}")

asyncio.run(reset())
