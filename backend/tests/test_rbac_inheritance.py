import uuid

import pytest
from sqlalchemy import select

from app.db.seed import seed_rbac
from app.models.rbac import Permission, Role, RolePermission, User, UserRole
from app.services.auth_service import get_user_permissions


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _create_user(session, username: str, role_code: str) -> uuid.UUID:
    user = User(username=username, display_name=username, password_hash="x")
    session.add(user)
    await session.flush()
    role = await session.scalar(select(Role).where(Role.code == role_code))
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.flush()
    return user.id


async def _role_permission_codes(session, role_code: str) -> set[str]:
    role = await session.scalar(select(Role).where(Role.code == role_code))
    return set(
        (
            await session.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            )
        ).all()
    )


async def test_user_manager_inherits_regular_user_permissions(session) -> None:
    await seed_rbac(session)
    uid = await _create_user(session, "um1", "user_manager")
    await session.flush()

    perms = await get_user_permissions(session, uid)
    inherited = await _role_permission_codes(session, "regular_user")

    assert inherited.issubset(set(perms))


async def test_role_manager_inherits_regular_user_permissions(session) -> None:
    await seed_rbac(session)
    uid = await _create_user(session, "rm1", "role_manager")
    await session.flush()

    perms = set(await get_user_permissions(session, uid))
    inherited = await _role_permission_codes(session, "regular_user")
    own = await _role_permission_codes(session, "role_manager")

    assert inherited.issubset(perms)
    assert own.issubset(perms)
    assert "file:read" in perms
    assert "role:read" in perms


async def test_regular_user_gets_only_own_permissions(session) -> None:
    await seed_rbac(session)
    uid = await _create_user(session, "ru1", "regular_user")
    await session.flush()

    perms = set(await get_user_permissions(session, uid))
    assert perms == {"file:read", "file:upload", "file:delete", "file:manage_folders"}


async def test_multi_level_inheritance_chain(session) -> None:
    await seed_rbac(session)
    base = await session.scalar(select(Role).where(Role.code == "regular_user"))
    mid = Role(code="mid_level", name="中层", description="d", is_system=False, status="active", parent_role_id=base.id)
    session.add(mid)
    await session.flush()
    top = Role(code="top_level", name="顶层", description="d", is_system=False, status="active", parent_role_id=mid.id)
    session.add(top)
    await session.flush()
    user = User(username="chain1", display_name="chain1", password_hash="x")
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=top.id))
    await session.flush()

    perms = set(await get_user_permissions(session, user.id))
    assert {"file:read", "file:upload", "file:delete", "file:manage_folders"}.issubset(perms)


async def test_inheritance_reflects_permission_changes_immediately(session) -> None:
    await seed_rbac(session)
    uid = await _create_user(session, "um2", "user_manager")
    await session.flush()
    before = set(await get_user_permissions(session, uid))

    new_perm = Permission(code="file:test_extra", name="测试权限", module="file", sort_order=99)
    session.add(new_perm)
    await session.flush()
    regular = await session.scalar(select(Role).where(Role.code == "regular_user"))
    session.add(RolePermission(role_id=regular.id, permission_id=new_perm.id))
    await session.flush()

    after = set(await get_user_permissions(session, uid))
    assert "file:test_extra" not in before
    assert "file:test_extra" in after
