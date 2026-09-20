import asyncio
from app.core.security import hash_password, verify_password
from app.db.session import async_session_factory
from app.models.rbac import User
from sqlalchemy import select

async def main():
    async with async_session_factory() as s:
        result = await s.execute(select(User).where(User.username == "admin"))
        user = result.scalar_one_or_none()
        if user:
            print(f"User found: {user.username}")
            print(f"ID: {user.id}")
            print(f"Status: {user.status}")
            print(f"Is deleted: {user.is_deleted}")
            print(f"Password hash: {user.password_hash[:50]}...")
            result = verify_password("ChangeMe-Strong1", user.password_hash)
            print(f"verify_password('ChangeMe-Strong1', hash): {result}")

            new_hash = hash_password("ChangeMe-Strong1")
            print(f"\nNew hash for ChangeMe-Strong1: {new_hash[:50]}...")
            print(f"verify_password on new hash: {verify_password('ChangeMe-Strong1', new_hash)}")

            print(f"\nDB hash length: {len(user.password_hash)}")
            print(f"New hash length: {len(new_hash)}")
        else:
            print("User 'admin' not found!")

asyncio.run(main())
