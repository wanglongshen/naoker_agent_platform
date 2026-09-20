import uuid

from sqlalchemy import func, select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.messages import Messages
from app.models.rbac import Permission, Role, RolePermission, User, UserRole


def _role_to_summary(role: Role, permission_count: int, parent_code: str | None = None, parent_name: str | None = None) -> dict:
    return {
        "id": role.id,
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "status": role.status,
        "is_system": role.is_system,
        "permission_count": permission_count,
        "parent_role_id": str(role.parent_role_id) if role.parent_role_id else None,
        "parent_role_code": parent_code,
        "parent_role_name": parent_name,
    }


def _permission_to_summary(p: Permission) -> dict:
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "module": p.module,
        "description": p.description,
    }


async def list_roles(
    db: AsyncSession,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    perm_count_subq = (
        select(func.count(RolePermission.permission_id))
        .where(RolePermission.role_id == Role.id)
        .correlate(Role)
        .scalar_subquery()
    )

    query = select(Role, perm_count_subq.label("permission_count")).where(
        Role.is_deleted == False
    )

    if keyword:
        pattern = f"%{keyword}%"
        query = query.where(
            Role.code.ilike(pattern) | Role.name.ilike(pattern)
        )
    if status:
        query = query.where(Role.status == status)

    count_sub = query.subquery()
    count_query = select(func.count()).select_from(count_sub)
    total = (await db.execute(count_query)).scalar_one()

    query = (
        query.order_by(Role.sort_order, Role.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)

    items = []
    rows = result.all()
    parent_ids = {r.parent_role_id for r, _ in rows if r.parent_role_id is not None}
    parent_map: dict[uuid.UUID, Role] = {}
    if parent_ids:
        parent_rows = (
            await db.scalars(select(Role).where(Role.id.in_(parent_ids)))
        ).all()
        parent_map = {p.id: p for p in parent_rows}
    for role, perm_count in rows:
        parent = parent_map.get(role.parent_role_id) if role.parent_role_id else None
        items.append(_role_to_summary(role, perm_count or 0, parent.code if parent else None, parent.name if parent else None))

    return {"items": items, "page": page, "page_size": page_size, "total": total}


async def get_role_detail(db: AsyncSession, role_id: uuid.UUID) -> dict:
    role = await db.scalar(
        select(Role).where(Role.id == role_id, Role.is_deleted == False)
    )
    if role is None:
        raise ApiError(status_code=404, code="ROLE_NOT_FOUND", message=Messages.ROLE_NOT_FOUND)

    parent_role = await db.get(Role, role.parent_role_id) if role.parent_role_id else None

    perm_count = await db.scalar(
        select(func.count()).select_from(RolePermission).where(
            RolePermission.role_id == role_id
        )
    )

    user_count = await db.scalar(
        select(func.count())
        .select_from(UserRole)
        .join(User, User.id == UserRole.user_id)
        .where(
            UserRole.role_id == role_id,
            User.is_deleted == False,
            User.status == "active",
        )
    )

    perm_result = await db.execute(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.sort_order)
    )
    permissions = [_permission_to_summary(p) for p in perm_result.scalars().all()]

    return {
        "id": role.id,
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "status": role.status,
        "is_system": role.is_system,
        "permission_count": perm_count or 0,
        "permissions": permissions,
        "assigned_user_count": user_count or 0,
        "parent_role_id": str(role.parent_role_id) if role.parent_role_id else None,
        "parent_role_code": parent_role.code if parent_role else None,
        "parent_role_name": parent_role.name if parent_role else None,
    }


async def create_role(db: AsyncSession, data) -> dict:
    existing_code = await db.scalar(
        select(Role).where(Role.code == data.code, Role.is_deleted == False)
    )
    if existing_code:
        raise ApiError(
            status_code=409, code="DUPLICATE_VALUE", message=Messages.ROLE_CODE_EXISTS
        )

    existing_name = await db.scalar(
        select(Role).where(Role.name == data.name, Role.is_deleted == False)
    )
    if existing_name:
        raise ApiError(
            status_code=409, code="DUPLICATE_VALUE", message=Messages.ROLE_NAME_EXISTS
        )

    permissions = await _validate_permissions(db, data.permission_ids)

    parent_role = None
    if data.parent_role_id is not None:
        parent_role = await db.get(Role, data.parent_role_id)
        if parent_role is None or parent_role.is_deleted or parent_role.status != "active":
            raise ApiError(status_code=400, code="ROLE_PARENT_NOT_FOUND", message=Messages.ROLE_PARENT_NOT_FOUND)
    role = Role(
        code=data.code,
        name=data.name,
        description=data.description,
        status="active",
        parent_role_id=parent_role.id if parent_role else None,
    )
    db.add(role)
    await db.flush()

    for perm in permissions:
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    await db.flush()
    return await get_role_detail(db, role.id)


async def update_role(db: AsyncSession, role_id: uuid.UUID, data) -> dict:
    role = await db.scalar(
        select(Role).where(Role.id == role_id, Role.is_deleted == False)
    )
    if role is None:
        raise ApiError(status_code=404, code="ROLE_NOT_FOUND", message=Messages.ROLE_NOT_FOUND)

    if role.is_system and data.permission_ids is not None:
        raise ApiError(
            status_code=400,
            code="SYSTEM_ROLE_IMMUTABLE",
            message=Messages.SYSTEM_ROLE_PERMISSION_IMMUTABLE,
        )

    if data.name != role.name:
        existing_name = await db.scalar(
            select(Role).where(
                Role.name == data.name,
                Role.is_deleted == False,
                Role.id != role_id,
            )
        )
        if existing_name:
            raise ApiError(
                status_code=409,
                code="DUPLICATE_VALUE",
                message=Messages.ROLE_NAME_EXISTS,
            )

    if data.parent_role_id is not None:
        parent_role = await db.get(Role, data.parent_role_id)
        if parent_role is None or parent_role.is_deleted or parent_role.status != "active":
            raise ApiError(status_code=400, code="ROLE_PARENT_NOT_FOUND", message=Messages.ROLE_PARENT_NOT_FOUND)
        if data.parent_role_id == role.id or await _role_is_descendant(db, data.parent_role_id, role.id):
            raise ApiError(status_code=400, code="ROLE_PARENT_CYCLE", message=Messages.ROLE_PARENT_CYCLE)
        role.parent_role_id = data.parent_role_id

    role.name = data.name
    role.description = data.description

    if data.permission_ids is not None:
        permissions = await _validate_permissions(db, data.permission_ids)
        await db.execute(
            sa_delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        for perm in permissions:
            db.add(RolePermission(role_id=role_id, permission_id=perm.id))

    await db.flush()
    return await get_role_detail(db, role_id)


async def update_role_status(
    db: AsyncSession, role_id: uuid.UUID, status: str
) -> dict:
    role = await db.scalar(
        select(Role).where(Role.id == role_id, Role.is_deleted == False)
    )
    if role is None:
        raise ApiError(status_code=404, code="ROLE_NOT_FOUND", message=Messages.ROLE_NOT_FOUND)

    if role.is_system:
        raise ApiError(
            status_code=400,
            code="SYSTEM_ROLE_IMMUTABLE",
            message=Messages.SYSTEM_ROLE_STATUS_IMMUTABLE,
        )

    role.status = status
    await db.flush()
    return await get_role_detail(db, role_id)


async def delete_role(db: AsyncSession, role_id: uuid.UUID) -> None:
    role = await db.scalar(
        select(Role).where(Role.id == role_id, Role.is_deleted == False)
    )
    if role is None:
        raise ApiError(status_code=404, code="ROLE_NOT_FOUND", message=Messages.ROLE_NOT_FOUND)

    if role.is_system:
        raise ApiError(
            status_code=400,
            code="SYSTEM_ROLE_IMMUTABLE",
            message=Messages.SYSTEM_ROLE_DELETE_IMMUTABLE,
        )

    child_count = await db.scalar(
        select(func.count())
        .select_from(Role)
        .where(Role.parent_role_id == role_id, Role.is_deleted == False)
    )
    if child_count:
        raise ApiError(status_code=400, code="ROLE_HAS_CHILDREN", message=Messages.ROLE_HAS_CHILDREN)

    await db.execute(sa_delete(UserRole).where(UserRole.role_id == role_id))
    await db.execute(sa_delete(RolePermission).where(RolePermission.role_id == role_id))
    role.is_deleted = True
    role.status = "disabled"
    await db.flush()


async def list_permissions(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Permission)
        .where(Permission.status == "active")
        .order_by(Permission.sort_order)
    )
    return [_permission_to_summary(p) for p in result.scalars().all()]


async def _validate_permissions(
    db: AsyncSession, permission_ids: list[uuid.UUID]
) -> list[Permission]:
    permissions = []
    for pid in permission_ids:
        perm = await db.scalar(select(Permission).where(Permission.id == pid))
        if perm is None:
            raise ApiError(
                status_code=404,
                code="PERMISSION_NOT_FOUND",
                message=f"权限不存在：{pid}",
            )
        if perm.status != "active":
            raise ApiError(
                status_code=400,
                code="INACTIVE_PERMISSION",
                message=Messages.INACTIVE_PERMISSION,
            )
        permissions.append(perm)
    return permissions


async def _role_is_descendant(db: AsyncSession, ancestor_id: uuid.UUID, descendant_id: uuid.UUID) -> bool:
    """True if `descendant_id` appears among `ancestor_id`'s descendants (excluding itself)."""
    current = ancestor_id
    for _ in range(100):
        role = await db.get(Role, current)
        if role is None or role.parent_role_id is None:
            return False
        if role.parent_role_id == descendant_id:
            return True
        current = role.parent_role_id
    return True
