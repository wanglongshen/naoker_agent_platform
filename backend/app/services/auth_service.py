import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.messages import Messages
from app.core.security import verify_password
from app.models.rbac import Permission, Role, RolePermission, User, UserRole


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        raise ApiError(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message=Messages.INVALID_CREDENTIALS,
        )
    if user.status != "active" or user.is_deleted:
        raise ApiError(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message=Messages.ACCOUNT_DISABLED,
        )
    if not verify_password(password, user.password_hash):
        raise ApiError(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message=Messages.INVALID_CREDENTIALS,
        )
    return user


async def get_user_roles(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    result = await db.execute(
        select(Role.id, Role.code, Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            Role.status == "active",
            Role.is_deleted.is_(False),
        )
        .order_by(Role.sort_order, Role.name)
    )
    return [{"id": r.id, "code": r.code, "name": r.name} for r in result.all()]


async def get_user_permissions(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    role_ancestors = (
        select(UserRole.role_id)
        .where(UserRole.user_id == user_id)
        .cte(name="role_ancestors", recursive=True)
    )
    role_ancestors = role_ancestors.union_all(
        select(Role.parent_role_id)
        .where(
            Role.id == role_ancestors.c.role_id,
            Role.parent_role_id.isnot(None),
            Role.status == "active",
            Role.is_deleted.is_(False),
        )
    )
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(role_ancestors, role_ancestors.c.role_id == Role.id)
        .where(Role.status == "active", Role.is_deleted.is_(False), Permission.status == "active")
        .distinct()
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _user_has_super_admin(db: AsyncSession, user: User) -> bool:
    sa_role = await db.scalar(select(Role).where(Role.code == "super_admin"))
    if sa_role is None:
        return False
    exists_sa = await db.scalar(
        select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == sa_role.id,
        )
    )
    return exists_sa is not None


async def get_assignable_roles(db: AsyncSession, current_user: User) -> list[dict]:
    query = select(Role).where(
        Role.status == "active",
        Role.is_deleted.is_(False),
    )
    if not await _user_has_super_admin(db, current_user):
        query = query.where(Role.code != "super_admin")
    result = await db.scalars(query.order_by(Role.sort_order, Role.name))
    roles = result.all()
    return [{"id": str(r.id), "code": r.code, "name": r.name} for r in roles]
