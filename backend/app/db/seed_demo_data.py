"""
Idempotent demo data seed: additional roles and enterprise users.

Usage:
    cd backend
    python -m app.db.seed_demo_data

Safely repeatable: checks each role by code and each user by username
before creating. Does not delete or overwrite existing records.
"""

import asyncio
from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.db.seed import seed_rbac
from app.models.rbac import Permission, Role, RolePermission, User, UserRole

# ── Additional roles beyond the two seeded by seed_rbac ──────────────
DEMO_ROLES = (
    ("role_manager", "角色管理员", "负责角色维护与权限分配", False),
    ("security_auditor", "安全审计员", "只读查看用户与角色信息", False),
)

# ── Permission codes assigned to each demo role ──────────────────────
DEMO_ROLE_PERMISSION_CODES: dict[str, list[str]] = {
    "role_manager": [
        "role:read", "role:create", "role:update", "role:delete",
        "role:status", "role:assign_permission",
    ],
    "security_auditor": [
        "user:read", "role:read",
    ],
}

# ── Demo user catalog (username, display_name, email, phone, status) ──
ACTIVE_USERS = (
    # Technology Department (8)
    ("wang.jian", "王健", "wang.jian@acme.local", "13810000001", "active"),
    ("li.ming", "李明", "li.ming@acme.local", "13810000002", "active"),
    ("zhao.yun", "赵云", "zhao.yun@acme.local", "13810000003", "active"),
    ("xu.ting", "许婷", "xu.ting@acme.local", "13810000004", "active"),
    ("guo.liang", "郭亮", "guo.liang@acme.local", "13810000005", "active"),
    ("jiang.wei", "姜伟", "jiang.wei@acme.local", "13810000006", "active"),
    ("qian.li", "钱丽", "qian.li@acme.local", "13810000007", "active"),
    ("feng.yuan", "冯远", "feng.yuan@acme.local", "13810000008", "active"),
    # Operations Department (6)
    ("chen.wei", "陈伟", "chen.wei@acme.local", "13810000009", "active"),
    ("zheng.rui", "郑瑞", "zheng.rui@acme.local", "13810000010", "active"),
    ("huang.ying", "黄莹", "huang.ying@acme.local", "13810000011", "active"),
    ("ma.qiang", "马强", "ma.qiang@acme.local", "13810000012", "active"),
    ("qi.ping", "齐萍", "qi.ping@acme.local", "13810000013", "active"),
    ("sun.jing", "孙静", "sun.jing@acme.local", "13810000014", "active"),
    # Marketing Department (5)
    ("zhou.yu", "周瑜", "zhou.yu@acme.local", "13810000015", "active"),
    ("wu.ling", "吴玲", "wu.ling@acme.local", "13810000016", "active"),
    ("zheng.hao", "郑浩", "zheng.hao@acme.local", "13810000017", "active"),
    ("liu.fang", "刘芳", "liu.fang@acme.local", "13810000018", "active"),
    ("he.li", "何丽", "he.li@acme.local", "13810000019", "active"),
    # Finance Department (5)
    ("lin.na", "林娜", "lin.na@acme.local", "13810000020", "active"),
    ("xie.yu", "谢宇", "xie.yu@acme.local", "13810000021", "active"),
    ("tang.wei", "唐薇", "tang.wei@acme.local", "13810000022", "active"),
    ("dong.hao", "董浩", "dong.hao@acme.local", "13810000023", "active"),
    ("pan.li", "潘丽", "pan.li@acme.local", "13810000024", "active"),
    # HR Department (4)
    ("sun.nan", "孙楠", "sun.nan@acme.local", "13810000025", "active"),
    ("shi.mei", "石梅", "shi.mei@acme.local", "13810000026", "active"),
    ("kong.xue", "孔雪", "kong.xue@acme.local", "13810000027", "active"),
    ("cui.yong", "崔勇", "cui.yong@acme.local", "13810000028", "active"),
    # Customer Service (4)
    ("chen.xia", "陈霞", "chen.xia@acme.local", "13810000029", "active"),
    ("luo.fei", "罗飞", "luo.fei@acme.local", "13810000030", "active"),
    ("du.rui", "杜瑞", "du.rui@acme.local", "13810000031", "active"),
    ("yan.tao", "严涛", "yan.tao@acme.local", "13810000032", "active"),
)

DISABLED_USERS = (
    ("yao.ming", "姚明", "yao.ming@acme.local", "13810000081", "disabled"),
    ("bai.ling", "白玲", "bai.ling@acme.local", "13810000082", "disabled"),
    ("luo.yang", "罗洋", "luo.yang@acme.local", "13810000083", "disabled"),
    ("di.zhen", "狄真", "di.zhen@acme.local", "13810000084", "disabled"),
)

# ── Role assignments for demo users ──────────────────────────────────
# Users not listed here receive the default role for the seed.
USER_ROLE_MAP: dict[str, list[str]] = {
    "wang.jian": ["super_admin"],
    "li.ming": ["user_manager", "role_manager"],
    "zhao.yun": ["user_manager"],
    "xu.ting": ["security_auditor"],
    "guo.liang": ["regular_user"],
    "jiang.wei": ["regular_user"],
    "qian.li": ["regular_user"],
    "feng.yuan": ["regular_user"],

    "chen.wei": ["role_manager"],
    "zheng.rui": ["user_manager"],
    "huang.ying": ["role_manager", "regular_user"],
    "ma.qiang": ["security_auditor"],
    "qi.ping": ["regular_user"],
    "sun.jing": ["regular_user"],

    "zhou.yu": ["regular_user"],
    "wu.ling": ["regular_user"],
    "zheng.hao": ["regular_user"],
    "liu.fang": ["regular_user"],
    "he.li": ["security_auditor"],

    "lin.na": ["regular_user"],
    "xie.yu": ["regular_user"],
    "tang.wei": ["regular_user"],
    "dong.hao": ["regular_user"],
    "pan.li": ["regular_user"],

    "sun.nan": ["user_manager"],
    "shi.mei": ["regular_user"],
    "kong.xue": ["regular_user"],
    "cui.yong": ["security_auditor"],

    "chen.xia": ["regular_user"],
    "luo.fei": ["regular_user"],
    "du.rui": ["regular_user"],
    "yan.tao": ["regular_user"],

    "yao.ming": ["regular_user"],
    "bai.ling": ["regular_user"],
    "luo.yang": ["regular_user"],
    "di.zhen": ["regular_user"],
}

DEFAULT_PASSWORD = "ChangeMe-Demo1"


async def _upsert_demo_roles(session: AsyncSession) -> dict[str, Role]:
    role_map: dict[str, Role] = {}
    for code, name, description, is_system in DEMO_ROLES:
        existing = await session.scalar(select(Role).where(Role.code == code))
        if existing is None:
            role = Role(code=code, name=name, description=description, is_system=is_system)
            session.add(role)
            await session.flush()
            role_map[code] = role
        else:
            existing.name = name
            existing.description = description
            existing.is_system = is_system
            role_map[code] = existing
    return role_map


async def _assign_demo_permissions(
    session: AsyncSession, role_map: dict[str, Role]
) -> None:
    all_permissions = (await session.scalars(select(Permission))).all()
    perm_by_code: dict[str, Permission] = {p.code: p for p in all_permissions}

    for role_code, perm_codes in DEMO_ROLE_PERMISSION_CODES.items():
        role = role_map[role_code]
        for code in perm_codes:
            perm = perm_by_code.get(code)
            if perm is None:
                continue
            existing = await session.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id,
                )
            )
            if existing is None:
                session.add(RolePermission(role_id=role.id, permission_id=perm.id))


async def _upsert_demo_users(session: AsyncSession) -> dict[str, User]:
    ph = PasswordHasher()
    user_map: dict[str, User] = {}

    for username, display_name, email, phone, status in ACTIVE_USERS + DISABLED_USERS:
        existing = await session.scalar(
            select(User).where(User.username == username)
        )
        if existing is None:
            user = User(
                username=username,
                display_name=display_name,
                password_hash=ph.hash(DEFAULT_PASSWORD),
                email=email,
                phone=phone,
                status=status,
            )
            session.add(user)
            await session.flush()
            user_map[username] = user
        else:
            user_map[username] = existing
    return user_map


async def _assign_demo_user_roles(
    session: AsyncSession,
    user_map: dict[str, User],
    role_map: dict[str, Role],
) -> None:
    for username, role_codes in USER_ROLE_MAP.items():
        user = user_map.get(username)
        if user is None:
            continue
        for rc in role_codes:
            role = role_map.get(rc)
            if role is None:
                continue
            existing = await session.scalar(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.role_id == role.id,
                )
            )
            if existing is None:
                session.add(UserRole(user_id=user.id, role_id=role.id))


async def seed_demo_data(session: AsyncSession | None = None) -> None:
    if session is not None:
        await seed_rbac(session)
        role_map = await _upsert_demo_roles(session)
        await _assign_demo_permissions(session, role_map)
        user_map = await _upsert_demo_users(session)
        await _assign_demo_user_roles(session, user_map, role_map)
        return

    async with async_session_factory() as s:
        await seed_rbac(s)
        role_map = await _upsert_demo_roles(s)
        await _assign_demo_permissions(s, role_map)
        user_map = await _upsert_demo_users(s)
        await _assign_demo_user_roles(s, user_map, role_map)
        await s.commit()


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
    print("演示数据写入完成。")
