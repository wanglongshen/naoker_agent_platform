import asyncio, sys
sys.path.insert(0, ".")
from app.db.session import async_session_factory
from sqlalchemy import select
from app.models.rbac import User
from app.core.security import verify_password

async def check():
    async with async_session_factory() as s:
        user = (await s.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
        if user is None:
            print("No admin user found!")
            return
        print(f"ID: {user.id}")
        print(f"Status: {user.status}")
        print(f"Deleted: {user.is_deleted}")
        print(f"Hash: {user.password_hash[:30]}...")
        print(f"Verify 'ChangeMe-Strong1': {verify_password('ChangeMe-Strong1', user.password_hash)}")
        print(f"Verify 'admin1234': {verify_password('admin1234', user.password_hash)}")

asyncio.run(check())
