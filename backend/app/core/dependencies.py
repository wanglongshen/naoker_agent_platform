import uuid

from sqlalchemy import select, exists
from fastapi import Depends, Request
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.core.messages import Messages
from app.core.security import decode_access_token, decode_platform_token
from app.db.session import get_db
from app.models.agent import AgentAttachment, AgentRun, AgentSession
from app.models.rbac import Permission, Role, RolePermission, User, UserRole


async def get_current_user(request: Request, db=Depends(get_db)):
    platform_token = request.headers.get("x-platform-token")
    if platform_token:
        sub = decode_platform_token(platform_token)
        if sub is None:
            raise ApiError(
                status_code=401,
                code="AUTHENTICATION_REQUIRED",
                message=Messages.AUTH_EXPIRED,
            )
        header_user = request.headers.get("x-dsh-platform-user")
        if header_user and header_user != sub:
            raise ApiError(
                status_code=401,
                code="AUTHENTICATION_REQUIRED",
                message="platform token subject mismatch",
            )
    else:
        token = request.cookies.get("access_token")
        if not token:
            raise ApiError(
                status_code=401,
                code="AUTHENTICATION_REQUIRED",
                message=Messages.AUTH_EXPIRED,
            )
        try:
            payload = decode_access_token(token)
        except (JWTError, ValueError):
            raise ApiError(
                status_code=401,
                code="AUTHENTICATION_REQUIRED",
                message=Messages.AUTH_EXPIRED,
            )
        sub = payload.sub

    try:
        user = await db.scalar(
            select(User).where(
                User.id == uuid.UUID(sub),
                User.is_deleted == False,
                User.status == "active",
            )
        )
    except ValueError:
        raise ApiError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message=Messages.AUTH_EXPIRED,
        )
    if user is None:
        raise ApiError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message=Messages.ACCOUNT_DISABLED,
        )

    role_ancestors = (
        select(UserRole.role_id)
        .where(UserRole.user_id == user.id)
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
        .where(
            Role.status == "active",
            Role.is_deleted.is_(False),
            Permission.status == "active",
        )
        .distinct()
    )
    result = await db.execute(stmt)
    user._permission_codes = set(result.scalars().all())

    return user


def require_permissions(*codes: str):
    async def dependency(current_user=Depends(get_current_user)):
        user_codes = getattr(current_user, "_permission_codes", set())
        missing = set(codes) - user_codes
        if missing:
            raise ApiError(
                status_code=403,
                code="PERMISSION_DENIED",
                message=Messages.PERMISSION_DENIED,
                details={"missing": sorted(missing)},
            )
        return current_user

    return Depends(dependency)


async def require_super_admin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    stmt = select(
        exists().where(
            UserRole.user_id == current_user.id,
            UserRole.role_id == Role.id,
            Role.code == "super_admin",
            Role.status == "active",
            Role.is_deleted.is_(False),
        )
    )
    result = await db.scalar(stmt)
    if not result:
        raise ApiError(
            status_code=403,
            code="PERMISSION_DENIED",
            message=Messages.PERMISSION_DENIED,
        )
    return current_user


async def get_owned_agent_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentSession:
    session = await db.scalar(
        select(AgentSession).where(
            AgentSession.id == session_id,
            AgentSession.owner_user_id == current_user.id,
        )
    )
    if session is None:
        raise ApiError(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            message="资源不存在",
        )
    return session


async def get_owned_agent_run(
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentRun:
    run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.owner_user_id == current_user.id,
        )
    )
    if run is None:
        raise ApiError(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            message="资源不存在",
        )
    return run


async def get_owned_agent_attachment(
    attachment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentAttachment:
    attachment = await db.scalar(
        select(AgentAttachment).where(
            AgentAttachment.id == attachment_id,
            AgentAttachment.owner_user_id == current_user.id,
        )
    )
    if attachment is None:
        raise ApiError(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            message="资源不存在",
        )
    return attachment
