from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.rbac import Permission, Role, RolePermission, User, UserRole

PERMISSIONS = (
    ("user:read", "查看用户", "user", 10),
    ("user:create", "新建用户", "user", 20),
    ("user:update", "编辑用户", "user", 30),
    ("user:delete", "删除用户", "user", 40),
    ("user:status", "调整用户状态", "user", 50),
    ("user:reset_password", "重置用户密码", "user", 60),
    ("user:assign_role", "分配用户角色", "user", 70),
    ("role:read", "查看角色", "role", 10),
    ("role:create", "新建角色", "role", 20),
    ("role:update", "编辑角色", "role", 30),
    ("role:delete", "删除角色", "role", 40),
    ("role:status", "调整角色状态", "role", 50),
    ("role:assign_permission", "分配角色权限", "role", 60),
    ("file:read", "查看文件", "file", 10),
    ("file:upload", "上传文件", "file", 20),
    ("file:delete", "删除文件", "file", 30),
    ("file:manage_folders", "管理文件夹", "file", 40),
    ("file:admin_view", "全局查看文件", "file", 50),
)

ROLES = (
    ("super_admin", "超级管理员", "拥有系统全部管理权限"),
    ("user_manager", "用户管理员", "负责用户账号、状态、密码和角色分配"),
    ("regular_user", "普通用户", "管理自己的文件与文件夹"),
    ("role_manager", "角色管理员", "管理角色、角色权限与角色层级"),
)

ROLE_PARENTS = {
    "user_manager": "regular_user",
    "role_manager": "regular_user",
}

LEGACY_ROLE_CODES = ("operations_specialist", "read_only_visitor", "security_auditor")


async def seed_rbac(session: AsyncSession) -> None:
    settings = get_settings()

    for code, name, description in ROLES:
        existing = await session.scalar(select(Role).where(Role.code == code))
        if existing is None:
            kwargs = {"code": code, "name": name, "description": description}
            if code in ("super_admin", "user_manager"):
                kwargs["is_system"] = True
                kwargs["status"] = "active"
            session.add(Role(**kwargs))
        else:
            existing.name = name
            existing.description = description
            if code in ("super_admin", "user_manager"):
                existing.is_system = True
                existing.status = "active"

    for code, name, module, sort_order in PERMISSIONS:
        existing = await session.scalar(
            select(Permission).where(Permission.code == code)
        )
        if existing is None:
            session.add(Permission(code=code, name=name, module=module, sort_order=sort_order))
        else:
            existing.name = name
            existing.module = module
            existing.sort_order = sort_order

    await session.flush()

    for child_code, parent_code in ROLE_PARENTS.items():
        child = await session.scalar(
            select(Role).where(Role.code == child_code, Role.is_deleted == False)
        )
        parent = await session.scalar(
            select(Role).where(Role.code == parent_code, Role.is_deleted == False)
        )
        if child is not None and parent is not None:
            child.parent_role_id = parent.id

    super_admin_role = await session.scalar(
        select(Role).where(Role.code == "super_admin")
    )
    user_manager_role = await session.scalar(
        select(Role).where(Role.code == "user_manager")
    )

    all_active_permissions = (await session.scalars(
        select(Permission).where(Permission.status == "active")
    )).all()
    for perm in all_active_permissions:
        existing = await session.scalar(
            select(RolePermission).where(
                RolePermission.role_id == super_admin_role.id,
                RolePermission.permission_id == perm.id,
            )
        )
        if existing is None:
            session.add(
                RolePermission(role_id=super_admin_role.id, permission_id=perm.id)
            )

    user_permissions = (
        await session.scalars(
            select(Permission).where(
                Permission.code.startswith("user:"),
                Permission.status == "active",
            )
        )
    ).all()
    for perm in user_permissions:
        existing = await session.scalar(
            select(RolePermission).where(
                RolePermission.role_id == user_manager_role.id,
                RolePermission.permission_id == perm.id,
            )
        )
        if existing is None:
            session.add(
                RolePermission(role_id=user_manager_role.id, permission_id=perm.id)
            )

    file_permissions = (
        await session.scalars(
            select(Permission).where(
                Permission.code.in_(
                    ["file:read", "file:upload", "file:delete", "file:manage_folders"]
                ),
                Permission.status == "active",
            )
        )
    ).all()
    for perm in file_permissions:
        existing = await session.scalar(
            select(RolePermission).where(
                RolePermission.role_id == user_manager_role.id,
                RolePermission.permission_id == perm.id,
            )
        )
        if existing is None:
            session.add(
                RolePermission(role_id=user_manager_role.id, permission_id=perm.id)
            )

    # role_manager role + its 6 role permissions
    role_manager_role = await session.scalar(
        select(Role).where(Role.code == "role_manager")
    )
    if role_manager_role is None:
        role_manager_role = Role(
            code="role_manager",
            name="角色管理员",
            description="管理角色、角色权限与角色层级",
            is_system=True,
            status="active",
        )
        session.add(role_manager_role)
        await session.flush()
    else:
        role_manager_role.is_system = True
        role_manager_role.status = "active"
    role_permissions = (
        await session.scalars(
            select(Permission).where(
                Permission.code.startswith("role:"),
                Permission.status == "active",
            )
        )
    ).all()
    for perm in role_permissions:
        existing = await session.scalar(
            select(RolePermission).where(
                RolePermission.role_id == role_manager_role.id,
                RolePermission.permission_id == perm.id,
            )
        )
        if existing is None:
            session.add(
                RolePermission(role_id=role_manager_role.id, permission_id=perm.id)
            )

    # regular_user role + its 4 file permissions
    regular_user_role = await session.scalar(
        select(Role).where(Role.code == "regular_user")
    )
    if regular_user_role is None:
        regular_user_role = Role(
            code="regular_user",
            name="普通用户",
            description="管理自己的文件与文件夹",
            is_system=True,
            status="active",
        )
        session.add(regular_user_role)
        await session.flush()
    else:
        regular_user_role.is_system = True
        regular_user_role.status = "active"
    for perm in file_permissions:
        existing = await session.scalar(
            select(RolePermission).where(
                RolePermission.role_id == regular_user_role.id,
                RolePermission.permission_id == perm.id,
            )
        )
        if existing is None:
            session.add(
                RolePermission(role_id=regular_user_role.id, permission_id=perm.id)
            )

    # ── Legacy role reconciliation (idempotent) ──────────────
    legacy_roles = (
        await session.scalars(
            select(Role).where(
                Role.code.in_(LEGACY_ROLE_CODES),
                Role.is_deleted == False,
            )
        )
    ).all()
    if legacy_roles:
        legacy_ids = [role.id for role in legacy_roles]
        legacy_bindings = (
            await session.scalars(select(UserRole).where(UserRole.role_id.in_(legacy_ids)))
        ).all()
        affected_user_ids = {ur.user_id for ur in legacy_bindings}
        for ur in legacy_bindings:
            await session.delete(ur)
        for uid in affected_user_ids:
            existing_binding = await session.scalar(
                select(UserRole).where(
                    UserRole.user_id == uid,
                    UserRole.role_id == regular_user_role.id,
                )
            )
            if existing_binding is None:
                session.add(UserRole(user_id=uid, role_id=regular_user_role.id))
        for role in legacy_roles:
            role.is_deleted = True
            role.status = "inactive"
            session.add(role)

    existing_admin = await session.scalar(
        select(User).where(User.username == settings.initial_admin_username)
    )
    if existing_admin is None:
        ph = PasswordHasher()
        admin = User(
            username=settings.initial_admin_username,
            display_name="超级管理员",
            password_hash=ph.hash(settings.initial_admin_password),
            is_builtin=True,
        )
        session.add(admin)
        await session.flush()
        session.add(
            UserRole(user_id=admin.id, role_id=super_admin_role.id)
        )
        existing_admin = admin
    elif not existing_admin.is_builtin:
        existing_admin.is_builtin = True
        session.add(existing_admin)

    await session.flush()
