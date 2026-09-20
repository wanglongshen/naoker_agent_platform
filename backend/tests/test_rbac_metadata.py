from sqlalchemy import select

from app.db.seed import seed_rbac
from app.models.rbac import Permission, Role, RolePermission


async def test_seed_marks_super_admin_as_system_and_assigns_all_active_permissions(session):
    await seed_rbac(session)
    super_admin = await session.scalar(select(Role).where(Role.code == "super_admin"))
    permissions = (await session.scalars(select(Permission).where(Permission.status == "active"))).all()
    assignments = (await session.scalars(
        select(RolePermission.permission_id).where(RolePermission.role_id == super_admin.id)
    )).all()

    assert super_admin.is_system is True
    assert super_admin.is_deleted is False
    assert {permission.id for permission in permissions} == set(assignments)
