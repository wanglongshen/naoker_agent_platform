import uuid

from sqlalchemy import func, select, exists, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.messages import Messages
from app.core.security import hash_password, validate_password
from app.models.rbac import Role, User, UserRole
from app.services.avatar_service import avatar_url_for


async def list_users(
    db: AsyncSession,
    keyword: str | None = None,
    status: str | None = None,
    role_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    base_query = select(User).where(User.is_deleted == False)

    if keyword:
        pattern = f"%{keyword}%"
        base_query = base_query.where(
            User.username.ilike(pattern)
            | User.display_name.ilike(pattern)
            | User.email.ilike(pattern)
        )
    if status:
        base_query = base_query.where(User.status == status)
    if role_id:
        base_query = base_query.where(
            exists().where(
                UserRole.user_id == User.id,
                UserRole.role_id == role_id,
            )
        )

    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    query = (
        base_query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    users = result.scalars().all()

    role_rows = await db.execute(
        select(UserRole.user_id, Role.id, Role.code, Role.name)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            UserRole.user_id.in_([user.id for user in users]),
            Role.status == "active",
            Role.is_deleted.is_(False),
        )
        .order_by(Role.sort_order, Role.name)
    )
    roles_by_user: dict[uuid.UUID, list[dict]] = {}
    for row in role_rows.all():
        roles_by_user.setdefault(row.user_id, []).append(
            {"id": row.id, "code": row.code, "name": row.name}
        )

    items = []
    for user in users:
        items.append(_user_to_response(user, roles_by_user.get(user.id, [])))

    return {"items": items, "page": page, "page_size": page_size, "total": total}


async def create_user(db: AsyncSession, data, current_user: User) -> dict:
    try:
        validate_password(data.password)
    except ValueError as e:
        raise ApiError(status_code=400, code="VALIDATION_ERROR", message=str(e)) from e

    existing = await db.scalar(
        select(User).where(User.username == data.username, User.is_deleted == False)
    )
    if existing:
        raise ApiError(
            status_code=409, code="DUPLICATE_VALUE", message=Messages.USERNAME_EXISTS
        )

    if data.email:
        existing_email = await db.scalar(
            select(User).where(User.email == data.email, User.is_deleted == False)
        )
        if existing_email:
            raise ApiError(
                status_code=409, code="DUPLICATE_VALUE", message=Messages.EMAIL_EXISTS
            )

    if data.phone:
        existing_phone = await db.scalar(
            select(User).where(User.phone == data.phone, User.is_deleted == False)
        )
        if existing_phone:
            raise ApiError(
                status_code=409, code="DUPLICATE_VALUE", message=Messages.PHONE_EXISTS
            )

    requested_role_ids = list(dict.fromkeys(data.role_ids or []))

    is_super_admin = await _current_user_is_super_admin(db, current_user)

    for rid in requested_role_ids:
        role = await db.scalar(
            select(Role).where(Role.id == rid, Role.is_deleted.is_(False))
        )
        if role is None:
            raise ApiError(
                status_code=404, code="NOT_FOUND", message=f"角色不存在：{rid}"
            )
        if role.status != "active":
            raise ApiError(
                status_code=400,
                code="INACTIVE_ROLE",
                message=Messages.INACTIVE_ROLE,
            )
        if role.code == "super_admin" and not is_super_admin:
            raise ApiError(
                status_code=403,
                code="PERMISSION_DENIED",
                message=Messages.SUPER_ADMIN_ASSIGN_FORBIDDEN,
            )

    user = User(
        username=data.username,
        display_name=data.display_name,
        password_hash=hash_password(data.password),
        email=data.email,
        phone=data.phone,
        status=data.status,
    )
    db.add(user)
    await db.flush()

    for rid in requested_role_ids:
        db.add(UserRole(user_id=user.id, role_id=rid))

    await db.flush()
    roles = await _get_user_roles_for_user(db, user.id)
    return _user_to_response(user, roles)


async def update_user(db: AsyncSession, user_id: uuid.UUID, data, current_user: User) -> dict:
    user = await db.scalar(
        select(User).where(User.id == user_id, User.is_deleted == False)
    )
    if user is None:
        raise ApiError(status_code=404, code="USER_NOT_FOUND", message=Messages.USER_NOT_FOUND)

    user.display_name = data.display_name
    user.email = data.email
    user.phone = data.phone

    if data.role_ids is not None:
        requested_role_ids = list(dict.fromkeys(data.role_ids))

        is_super_admin = await _current_user_is_super_admin(db, current_user)

        for rid in requested_role_ids:
            role = await db.scalar(
                select(Role).where(Role.id == rid, Role.is_deleted.is_(False))
            )
            if role is None:
                raise ApiError(
                    status_code=404, code="NOT_FOUND", message=f"角色不存在：{rid}"
                )
            if role.status != "active":
                raise ApiError(
                    status_code=400,
                    code="INACTIVE_ROLE",
                    message=Messages.INACTIVE_ROLE,
                )
            if role.code == "super_admin" and not is_super_admin:
                raise ApiError(
                    status_code=403,
                    code="PERMISSION_DENIED",
                    message=Messages.SUPER_ADMIN_ASSIGN_FORBIDDEN,
                )

        await _check_builtin_demote(db, user, requested_role_ids)

        await _check_self_demotion(db, user, current_user, requested_role_ids)

        await _check_final_super_admin_removal(db, user_id, requested_role_ids)

        await db.execute(sa_delete(UserRole).where(UserRole.user_id == user.id))
        for rid in requested_role_ids:
            db.add(UserRole(user_id=user.id, role_id=rid))

    await db.flush()
    roles = await _get_user_roles_for_user(db, user.id)
    return _user_to_response(user, roles)


async def delete_user(db: AsyncSession, user_id: uuid.UUID, current_user_id: uuid.UUID) -> None:
    user = await db.scalar(
        select(User).where(User.id == user_id, User.is_deleted == False)
    )
    if user is None:
        raise ApiError(status_code=404, code="USER_NOT_FOUND", message=Messages.USER_NOT_FOUND)

    if user.is_builtin:
        raise ApiError(
            status_code=400,
            code="BUILTIN_USER",
            message=Messages.BUILTIN_USER_DELETE,
        )

    if user_id == current_user_id:
        raise ApiError(
            status_code=400,
            code="SELF_OPERATION_FORBIDDEN",
            message=Messages.SELF_DELETE_FORBIDDEN,
        )

    await _check_super_admin_protection(db, user_id)

    user.is_deleted = True
    user.status = "disabled"
    await db.flush()


async def update_status(
    db: AsyncSession, user_id: uuid.UUID, status: str, current_user_id: uuid.UUID
) -> dict:
    user = await db.scalar(
        select(User).where(User.id == user_id, User.is_deleted == False)
    )
    if user is None:
        raise ApiError(status_code=404, code="USER_NOT_FOUND", message=Messages.USER_NOT_FOUND)

    if status == "disabled":
        if user.is_builtin:
            raise ApiError(
                status_code=400,
                code="BUILTIN_USER",
                message=Messages.BUILTIN_USER_STATUS,
            )

    if user_id == current_user_id:
        raise ApiError(
            status_code=400,
            code="SELF_OPERATION_FORBIDDEN",
            message=Messages.SELF_STATUS_FORBIDDEN,
        )

    if status == "disabled":
        await _check_super_admin_protection(db, user_id)

    user.status = status
    await db.flush()

    roles = await _get_user_roles_for_user(db, user.id)
    return _user_to_response(user, roles)


async def reset_password(db: AsyncSession, user_id: uuid.UUID, password: str) -> None:
    user = await db.scalar(
        select(User).where(User.id == user_id, User.is_deleted == False)
    )
    if user is None:
        raise ApiError(status_code=404, code="USER_NOT_FOUND", message=Messages.USER_NOT_FOUND)

    try:
        validate_password(password)
    except ValueError as e:
        raise ApiError(status_code=400, code="VALIDATION_ERROR", message=str(e)) from e
    user.password_hash = hash_password(password)
    await db.flush()


async def _get_user_roles_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
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


def _user_to_response(user: User, roles: list[dict]) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "phone": user.phone,
        "status": user.status,
        "is_deleted": user.is_deleted,
        "is_builtin": user.is_builtin,
        "avatar_url": avatar_url_for(user),
        "roles": roles,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


async def _check_super_admin_protection(db: AsyncSession, user_id: uuid.UUID) -> None:
    super_admin_role = await db.scalar(select(Role).where(Role.code == "super_admin"))
    if super_admin_role is None:
        return

    user_has_sa = await db.scalar(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == super_admin_role.id,
        )
    )
    if user_has_sa is None:
        return

    count = await db.scalar(
        select(func.count())
        .select_from(UserRole)
        .join(User, User.id == UserRole.user_id)
        .where(
            UserRole.role_id == super_admin_role.id,
            User.is_deleted == False,
            User.status == "active",
        )
    )
    if count <= 1:
        raise ApiError(
            status_code=400,
            code="LAST_SUPER_ADMIN",
            message=Messages.LAST_SUPER_ADMIN,
        )


async def _check_builtin_demote(
    db: AsyncSession, user: User, requested_role_ids: list[uuid.UUID]
) -> None:
    if not user.is_builtin:
        return
    super_admin_role = await db.scalar(select(Role).where(Role.code == "super_admin"))
    if super_admin_role is None:
        return
    if super_admin_role.id in requested_role_ids:
        return
    user_has_sa = await db.scalar(
        select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == super_admin_role.id,
        )
    )
    if user_has_sa is None:
        return
    raise ApiError(
        status_code=400,
        code="BUILTIN_USER",
        message=Messages.BUILTIN_USER_DEMOTE,
    )


async def _check_self_demotion(
    db: AsyncSession,
    user: User,
    current_user: User,
    requested_role_ids: list[uuid.UUID],
) -> None:
    if user.id != current_user.id:
        return
    super_admin_role = await db.scalar(select(Role).where(Role.code == "super_admin"))
    if super_admin_role is None:
        return
    if super_admin_role.id in requested_role_ids:
        return
    user_has_sa = await db.scalar(
        select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == super_admin_role.id,
        )
    )
    if user_has_sa is None:
        return
    raise ApiError(
        status_code=400,
        code="SELF_DEMOTION",
        message=Messages.SELF_DEMOTION,
    )


async def _current_user_is_super_admin(db: AsyncSession, current_user: User) -> bool:
    sa_role = await db.scalar(select(Role).where(Role.code == "super_admin"))
    if sa_role is None:
        return False
    exists_sa = await db.scalar(
        select(UserRole).where(
            UserRole.user_id == current_user.id,
            UserRole.role_id == sa_role.id,
        )
    )
    return exists_sa is not None


async def _check_final_super_admin_removal(
    db: AsyncSession, user_id: uuid.UUID, new_role_ids: list[uuid.UUID]
) -> None:
    super_admin_role = await db.scalar(select(Role).where(Role.code == "super_admin"))
    if super_admin_role is None:
        return

    user_has_sa = await db.scalar(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == super_admin_role.id,
        )
    )
    if user_has_sa is None:
        return

    if super_admin_role.id in new_role_ids:
        return

    await _check_super_admin_protection(db, user_id)
