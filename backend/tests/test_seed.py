import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.models.rbac import Permission, Role, RolePermission, User, UserRole


@pytest.mark.asyncio
async def test_seed_synchronizes_chinese_system_role_and_permission_labels(session) -> None:
    await seed_rbac(session)
    super_admin = await session.scalar(select(Role).where(Role.code == "super_admin"))
    user_read = await session.scalar(select(Permission).where(Permission.code == "user:read"))

    assert super_admin.name == "超级管理员"
    assert super_admin.description == "拥有系统全部管理权限"
    assert user_read.name == "查看用户"


@pytest.mark.asyncio
async def test_seed_creates_all_roles_and_permissions(session) -> None:
    await seed_rbac(session)
    await seed_rbac(session)
    roles = (await session.scalars(select(Role.code).order_by(Role.code))).all()
    permissions = (await session.scalars(select(Permission.code))).all()
    assert roles == ["regular_user", "role_manager", "super_admin", "user_manager"]
    assert len(permissions) == 18


@pytest.mark.asyncio
async def test_seed_creates_admin_user(session) -> None:
    settings = get_settings()
    await seed_rbac(session)

    admin = await session.scalar(
        select(User).where(User.username == settings.initial_admin_username)
    )
    assert admin is not None
    assert admin.username == settings.initial_admin_username
    assert admin.password_hash.startswith("$argon2")
    assert admin.display_name in ("Administrator", "超级管理员")

    await seed_rbac(session)

    count = await session.scalar(
        select(func.count()).select_from(User).where(
            User.username == settings.initial_admin_username
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_regular_user_role_has_four_file_permissions(session) -> None:
    await seed_rbac(session)
    role = await session.scalar(select(Role).where(Role.code == "regular_user"))
    assert role is not None
    assert role.is_system is True
    perms = (
        await session.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        )
    ).all()
    assert set(perms) == {"file:read", "file:upload", "file:delete", "file:manage_folders"}


@pytest.mark.asyncio
async def test_legacy_roles_soft_deleted_and_users_reassigned(session) -> None:
    await seed_rbac(session)
    legacy = Role(code="operations_specialist", name="运营专员", description="d")
    session.add(legacy)
    await session.flush()
    user = User(username="legacy_user_1", display_name="Legacy", password_hash="x")
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=legacy.id))
    await session.flush()

    await seed_rbac(session)

    legacy_db = await session.scalar(
        select(Role).where(Role.code == "operations_specialist")
    )
    assert legacy_db is not None and legacy_db.is_deleted is True
    regular = await session.scalar(select(Role).where(Role.code == "regular_user"))
    assert regular is not None
    binding = await session.scalar(select(UserRole).where(UserRole.user_id == user.id))
    assert binding is not None and binding.role_id == regular.id


@pytest.mark.asyncio
async def test_legacy_security_auditor_reconciled(session) -> None:
    await seed_rbac(session)
    legacy = Role(code="security_auditor", name="安全审计员", description="d")
    session.add(legacy)
    await session.flush()
    user = User(username="audit_user_1", display_name="Audit", password_hash="x")
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=legacy.id))
    await session.flush()

    await seed_rbac(session)

    legacy_db = await session.scalar(
        select(Role).where(Role.code == "security_auditor")
    )
    assert legacy_db is not None and legacy_db.is_deleted is True
    regular = await session.scalar(select(Role).where(Role.code == "regular_user"))
    binding = await session.scalar(select(UserRole).where(UserRole.user_id == user.id))
    assert binding is not None and binding.role_id == regular.id


@pytest.mark.asyncio
async def test_seed_creates_four_roles(session) -> None:
    await seed_rbac(session)
    roles = (await session.scalars(select(Role.code).order_by(Role.code))).all()
    assert roles == ["regular_user", "role_manager", "super_admin", "user_manager"]


@pytest.mark.asyncio
async def test_seed_role_manager_binds_all_role_permissions(session) -> None:
    await seed_rbac(session)
    role = await session.scalar(select(Role).where(Role.code == "role_manager"))
    assert role is not None
    assert role.is_system is True
    perms = (
        await session.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        )
    ).all()
    assert set(perms) == {
        "role:read", "role:create", "role:update",
        "role:delete", "role:status", "role:assign_permission",
    }


@pytest.mark.asyncio
async def test_seed_sets_system_role_parents(session) -> None:
    await seed_rbac(session)
    regular = await session.scalar(select(Role).where(Role.code == "regular_user"))
    user_manager = await session.scalar(select(Role).where(Role.code == "user_manager"))
    role_manager = await session.scalar(select(Role).where(Role.code == "role_manager"))
    super_admin = await session.scalar(select(Role).where(Role.code == "super_admin"))
    assert user_manager.parent_role_id == regular.id
    assert role_manager.parent_role_id == regular.id
    assert super_admin.parent_role_id is None
    assert regular.parent_role_id is None


def test_user_model_has_avatar_path_column() -> None:
    assert "avatar_path" in User.__table__.columns
