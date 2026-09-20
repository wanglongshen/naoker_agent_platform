import asyncio

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.rbac import User
from app.core.security import hash_password
from app.core.config import get_settings


async def fix_admin_password():
    settings = get_settings()
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.username == settings.initial_admin_username)
        )
        admin = result.scalar_one_or_none()
        if admin is None:
            print(f"Admin user '{settings.initial_admin_username}' not found.")
            return
        admin.password_hash = hash_password(settings.initial_admin_password)
        await session.commit()
        print(f"Password for admin user '{admin.username}' updated successfully.")


if __name__ == "__main__":
    asyncio.run(fix_admin_password())
