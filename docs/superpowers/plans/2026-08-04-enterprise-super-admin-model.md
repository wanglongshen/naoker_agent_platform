# 企业级超级管理员模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现企业级超管模型：超管角色可分配（仅超管可见可选）、内置初始 admin 账号不可删除/禁用/降权、任何人不能移除自己的超管角色。

**Architecture:** 数据层加 `users.is_builtin` 标记（seed 幂等标记初始 admin）；`user_service` 三个写入口（delete_user / update_status / update_user）加内置保护与自降权检查，错误沿用 `ApiError(400, CODE)` 模式；`get_assignable_roles` 改为按当前用户是否超管动态返回；前端用户表对内置账号禁用"停用/删除"菜单项。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (async) + Alembic；前端 Next.js 16 + AntD 5 + vitest；后端 pytest (asyncio)。

**Spec:** `docs/superpowers/specs/2026-08-04-enterprise-super-admin-model-design.md`

## Global Constraints

- 所有后端命令在 `backend/` 目录执行；前端命令在 `frontend/` 目录执行（用 workdir，不要 `cd` 拼接）
- Python 3.11+（代码使用 `datetime.UTC`）；不加任何新依赖（requirements.txt / package.json 不改）
- **每次 pytest 必须配独立测试库**（并发进程会共用 rbac_test 导致互相破坏）：
  `$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_<本任务代号>"; python -m pytest ...`
  不同任务用不同库名（如 `rbac_test_builtin`、`rbac_test_roles`），同一任务内复用同一库名
- 错误响应包络：`response.json()["code"]` 在**顶层**（不是 `["error"]["code"]`）；删除成功返回 204，状态变更 `PATCH /api/users/{id}/status`，更新 `PUT /api/users/{id}`
- 提交信息遵循仓库风格（`feat: ...` / `fix: ...`），每个任务恰好一个提交，只提交任务列出的文件
- 迁移 head 当前为 `79ec88b72f36`；迁移文件用 `alembic revision` 生成（自动分配 revision id），生成后把内容替换为任务给出的代码，保留自动生成的 `revision` 与 `down_revision` 字段值，确认 `down_revision` 是 `79ec88b72f36`
- 前端代码注意 `frontend/AGENTS.md` 警告（本项目 Next.js 有 breaking changes，但本任务只改普通 TS/JSX 组件与测试，不涉及 Next.js API）；前端测试命令：`npx vitest run <文件>`（在 frontend 目录）
- 不要用 autogenerate 生成迁移（会卷入既有模型/迁移漂移）

---

## File Structure

| 文件 | 责任 |
|---|---|
| `backend/app/models/rbac.py` | User 模型加 `is_builtin` 列（T1） |
| `backend/alembic/versions/<rev>_add_users_is_builtin.py` | 新迁移：加列（T1） |
| `backend/app/db/seed.py` | 初始 admin 创建时置 `is_builtin=True` + 存量幂等标记（T1） |
| `backend/app/core/messages.py` | 新增 4 条错误消息常量（T2） |
| `backend/app/services/user_service.py` | 内置保护 + 自降权检查 + 响应加 `is_builtin`（T2） |
| `backend/app/schemas/user.py` | UserResponse 加 `is_builtin`（T2） |
| `backend/app/services/auth_service.py` | `get_assignable_roles` 加当前用户参数，动态返回（T3） |
| `backend/app/api/auth.py` | `/me` 调用处传 `current_user`（T3） |
| `backend/tests/test_users_api.py` | T1/T2 测试（T1、T2） |
| `backend/tests/test_auth_api.py` | T3 测试（T3） |
| `frontend/src/types/user.ts` | `UserListItem` 加 `is_builtin`（T4） |
| `frontend/src/components/users/user-table.tsx` | 内置账号禁用停用/删除菜单项（T4） |
| `frontend/src/components/users/user-management.test.tsx` | 内置账号禁用测试 + fixture 补字段（T4） |
| `frontend/src/components/users/user-drawer.test.tsx`、`user-dialogs.test.tsx` | fixture 补 `is_builtin` 字段（T4） |

任务依赖：T1 → T2 → T3 可并行（不同文件）→ T4（消费后端 `is_builtin` 字段）→ T5 回归。

---

### Task 1: is_builtin 数据模型 + 迁移 + seed 标记

**Files:**
- Modify: `backend/app/models/rbac.py:21`（User 类，is_deleted 之后加字段）
- Create: `backend/alembic/versions/<rev>_add_users_is_builtin.py`
- Modify: `backend/app/db/seed.py:245-261`（admin 创建块）
- Test: `backend/tests/test_users_api.py`（追加 2 个测试）

**Interfaces:**
- Consumes: 无（模型层）
- Produces: `User.is_builtin: Mapped[bool]`（默认 False）；seed 后初始 admin 的 `is_builtin == True` —— T2 的服务层检查依赖此字段

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_users_api.py` 末尾）

```python
async def test_new_user_is_builtin_false_by_default(session) -> None:
    from argon2 import PasswordHasher

    from app.models.rbac import User

    user = User(
        username="plain_builtin_user",
        display_name="Plain",
        password_hash=PasswordHasher().hash("Password123"),
    )
    session.add(user)
    await session.flush()
    assert user.is_builtin is False


async def test_seed_marks_initial_admin_as_builtin(admin_user) -> None:
    assert admin_user.is_builtin is True
```

- [ ] **Step 2: 跑测试确认失败**

Run（backend 目录，专用测试库）:
```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_builtin"; python -m pytest tests/test_users_api.py::test_new_user_is_builtin_false_by_default tests/test_users_api.py::test_seed_marks_initial_admin_as_builtin -q
```
Expected: 2 个测试均失败（`AttributeError: 'User' object has no attribute 'is_builtin'`）

- [ ] **Step 3: 模型加字段**（`backend/app/models/rbac.py`，`is_deleted` 行之后插入）

```python
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
```

- [ ] **Step 4: 跑测试确认模型层通过（seed 测试仍失败）**

Run: 同 Step 2 命令
Expected: `test_new_user_is_builtin_false_by_default` PASS；`test_seed_marks_initial_admin_as_builtin` FAIL（is_builtin 为 False）

- [ ] **Step 5: seed 幂等标记**（`backend/app/db/seed.py:245-261`，整个 admin 块替换为）

```python
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
```

- [ ] **Step 6: 跑测试确认全绿**

Run: 同 Step 2 命令
Expected: 2 个测试均 PASS

- [ ] **Step 7: 生成迁移模板**

Run（backend 目录）:
```powershell
alembic revision -m "add users is_builtin"
```
Expected: 输出 `Generating .../alembic/versions/<rev>_add_users_is_builtin.py ...`，且文件内容 `down_revision = "79ec88b72f36"`（如不是，停下检查 head）

- [ ] **Step 8: 写入迁移内容**（把生成的文件整个替换为，保留自动生成的 `revision` 值）

```python
"""add users is_builtin

Revision ID: <自动生成的 revision 值>
Revises: 79ec88b72f36
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = "<自动生成的 revision 值>"
down_revision = "79ec88b72f36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_builtin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_builtin")
```

- [ ] **Step 9: 迁移应用到开发库并验证**

Run（backend 目录）:
```powershell
alembic upgrade head
```
Expected: `Running upgrade 79ec88b72f36 -> <rev>, add users is_builtin` 无报错。随后验证列存在（PowerShell 内联多行 python 会失败，用临时脚本文件）：
```powershell
$lines = @(
  "import asyncio",
  "from sqlalchemy import text",
  "from app.db.session import async_session_factory",
  "async def main():",
  "    async with async_session_factory() as s:",
  "        rows = (await s.execute(text(\"select column_name from information_schema.columns where table_name='users' and column_name='is_builtin'\"))).scalars().all()",
  "        print('is_builtin column:', rows)",
  "asyncio.run(main())"
)
Set-Content -Path "$env:TEMP\check_is_builtin.py" -Value $lines
python -X utf8 "$env:TEMP\check_is_builtin.py"
```
Expected: `is_builtin column: ['is_builtin']`

- [ ] **Step 10: 回归 test_users_api.py 全文件**

Run:
```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_builtin"; python -m pytest tests/test_users_api.py -q
```
Expected: 全部 PASS（现有测试不受影响）

- [ ] **Step 11: 提交**

```bash
git add backend/app/models/rbac.py backend/alembic/versions/<rev>_add_users_is_builtin.py backend/app/db/seed.py backend/tests/test_users_api.py
git commit -m "feat: add users.is_builtin column and mark initial admin"
```

---

### Task 2: 服务层内置保护与自降权检查

**Files:**
- Modify: `backend/app/core/messages.py`（LAST_SUPER_ADMIN 附近追加常量）
- Modify: `backend/app/services/user_service.py`（delete_user / update_status / update_user + 2 个新检查函数 + `_user_to_response` 加字段）
- Modify: `backend/app/schemas/user.py`（UserResponse 加字段）
- Test: `backend/tests/test_users_api.py`（追加 5 个新测试 + **重写** `test_cannot_disable_last_super_admin`）

**Interfaces:**
- Consumes: `User.is_builtin`（T1）
- Produces: 错误码 `BUILTIN_USER`（400，消息区分删除/禁用/降权）、`SELF_DEMOTION`（400）；用户列表/详情响应新增 `is_builtin` 布尔字段 —— T4 前端消费

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_users_api.py` 末尾；同时把既有测试 `test_cannot_disable_last_super_admin`（第 306-338 行）整体替换为 `test_cannot_disable_last_remaining_super_admin`）

替换既有测试为：

```python
async def test_cannot_disable_last_remaining_super_admin(client, test_engine) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        admin = await s.scalar(
            select(User).where(User.username == settings.initial_admin_username)
        )
        admin_sa = await s.scalar(
            select(UserRole).where(UserRole.user_id == admin.id)
        )
        await s.delete(admin_sa)
        sa_role = await s.scalar(select(Role).where(Role.code == "super_admin"))
        sa2 = User(
            username="sa2_only",
            display_name="Only SA",
            password_hash=ph.hash("Password123"),
        )
        s.add(sa2)
        await s.flush()
        s.add(UserRole(user_id=sa2.id, role_id=sa_role.id))
        mgr = User(
            username="mgr_attempt2",
            display_name="Manager",
            password_hash=ph.hash("Password123"),
        )
        s.add(mgr)
        await s.flush()
        manager_role = await s.scalar(select(Role).where(Role.code == "user_manager"))
        s.add(UserRole(user_id=mgr.id, role_id=manager_role.id))
        await s.commit()
        sa2_id = sa2.id

    await client.post(
        "/api/auth/login",
        json={"username": "mgr_attempt2", "password": "Password123"},
    )

    response = await client.patch(
        f"/api/users/{sa2_id}/status",
        json={"status": "disabled"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "LAST_SUPER_ADMIN"
```

追加新测试：

```python
async def test_cannot_delete_builtin_admin(admin_client, admin_user) -> None:
    response = await admin_client.delete(f"/api/users/{admin_user.id}")
    assert response.status_code == 400
    assert response.json()["code"] == "BUILTIN_USER"


async def test_cannot_disable_builtin_admin(admin_client, admin_user) -> None:
    response = await admin_client.patch(
        f"/api/users/{admin_user.id}/status",
        json={"status": "disabled"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "BUILTIN_USER"


async def test_cannot_remove_super_admin_role_from_builtin_admin(
    admin_client, admin_user, test_engine
) -> None:
    other_role = await _db_scalar(
        test_engine, select(Role).where(Role.code == "user_manager")
    )
    response = await admin_client.put(
        f"/api/users/{admin_user.id}",
        json={
            "display_name": "超级管理员",
            "email": None,
            "phone": None,
            "role_ids": [str(other_role.id)],
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "BUILTIN_USER"


async def test_non_builtin_super_admin_cannot_demote_self(client, test_engine) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        sa2 = User(
            username="sa2_self",
            display_name="SA Self",
            password_hash=ph.hash("Password123"),
        )
        s.add(sa2)
        await s.flush()
        super_admin_role = await s.scalar(
            select(Role).where(Role.code == "super_admin")
        )
        s.add(UserRole(user_id=sa2.id, role_id=super_admin_role.id))
        user_manager_role = await s.scalar(
            select(Role).where(Role.code == "user_manager")
        )
        await s.commit()
        sa2_id = sa2.id
        manager_role_id = user_manager_role.id

    await client.post(
        "/api/auth/login",
        json={"username": "sa2_self", "password": "Password123"},
    )

    response = await client.put(
        f"/api/users/{sa2_id}",
        json={
            "display_name": "SA Self",
            "email": None,
            "phone": None,
            "role_ids": [str(manager_role_id)],
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SELF_DEMOTION"


async def test_non_builtin_super_admin_can_be_deleted(admin_client, test_engine) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        sa2 = User(
            username="sa2_del",
            display_name="SA Del",
            password_hash=ph.hash("Password123"),
        )
        s.add(sa2)
        await s.flush()
        super_admin_role = await s.scalar(
            select(Role).where(Role.code == "super_admin")
        )
        s.add(UserRole(user_id=sa2.id, role_id=super_admin_role.id))
        await s.commit()
        sa2_id = sa2.id

    response = await admin_client.delete(f"/api/users/{sa2_id}")
    assert response.status_code == 204
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_roles"; python -m pytest tests/test_users_api.py -q -k "builtin or self or last_remaining"
```
Expected: 6 个测试全部失败（内置保护未实现，删除/禁用返回 204/200；自降权返回 200；重写后的 last_remaining 测试因 BUILTIN_USER 不存在而失败于代码层面之前——实际表现为删除 admin 的 UserRole 后逻辑未变、禁用 sa2_only 返回 200）

- [ ] **Step 3: Messages 常量**（`backend/app/core/messages.py`，`SUPER_ADMIN_ASSIGN_FORBIDDEN` 行后追加）

```python
    BUILTIN_USER_DELETE = "内置账号不可删除"
    BUILTIN_USER_STATUS = "内置账号不可禁用"
    BUILTIN_USER_DEMOTE = "内置账号不可移除超级管理员角色"
    SELF_DEMOTION = "不能移除自己的超级管理员角色"
```

- [ ] **Step 4: 两个新检查函数**（`backend/app/services/user_service.py`，在 `_check_super_admin_protection` 函数（第 293-322 行）之后追加）

```python
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
```

- [ ] **Step 5: delete_user 加内置检查**（`_check_super_admin_protection(db, user_id)` 调用之前插入）

```python
    if user.is_builtin:
        raise ApiError(
            status_code=400,
            code="BUILTIN_USER",
            message=Messages.BUILTIN_USER_DELETE,
        )

    await _check_super_admin_protection(db, user_id)
```

- [ ] **Step 6: update_status 加内置检查**（`if status == "disabled":` 分支内，`_check_super_admin_protection` 之前插入）

```python
    if status == "disabled":
        if user.is_builtin:
            raise ApiError(
                status_code=400,
                code="BUILTIN_USER",
                message=Messages.BUILTIN_USER_STATUS,
            )
        await _check_super_admin_protection(db, user_id)
```

- [ ] **Step 7: update_user 加两道检查**（角色校验循环之后、`_check_final_super_admin_removal` 调用之前插入）

```python
        await _check_builtin_demote(db, user, requested_role_ids)

        await _check_self_demotion(db, user, current_user, requested_role_ids)

        await _check_final_super_admin_removal(db, user_id, requested_role_ids)
```

- [ ] **Step 8: 响应加 is_builtin 字段**（`_user_to_response`（第 278-290 行）的返回字典，`"is_deleted": user.is_deleted,` 行后加）

```python
        "is_builtin": user.is_builtin,
```

同时 `backend/app/schemas/user.py` 的 `UserResponse`（第 34-44 行）在 `is_deleted: bool` 后加：

```python
    is_builtin: bool
```

- [ ] **Step 9: 跑测试确认全绿**

Run:
```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_roles"; python -m pytest tests/test_users_api.py -q
```
Expected: 全部 PASS（含重写后的 LAST_SUPER_ADMIN 测试与 5 个新测试）

- [ ] **Step 10: 提交**

```bash
git add backend/app/core/messages.py backend/app/services/user_service.py backend/app/schemas/user.py backend/tests/test_users_api.py
git commit -m "feat: protect builtin admin and block super admin self-demotion"
```

---

### Task 3: assignable_roles 按身份动态返回

**Files:**
- Modify: `backend/app/services/auth_service.py:76-85`（`get_assignable_roles`）
- Modify: `backend/app/api/auth.py:55`（调用处传 `current_user`）
- Test: `backend/tests/test_auth_api.py`（追加 2 个测试）

**Interfaces:**
- Consumes: 无（与 T1/T2 无文件冲突，可并行执行）
- Produces: `get_assignable_roles(db, current_user)` 新签名；超管的 `/api/auth/me` 响应 `assignable_roles` 含 `super_admin`，非超管不含

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_auth_api.py` 末尾；顶部如有缺失 import 一并补：`from argon2 import PasswordHasher`、`from sqlalchemy import select`、`from app.models.rbac import Role, UserRole`）

```python
async def test_super_admin_me_lists_super_admin_role_as_assignable(client) -> None:
    await client.post(
        "/api/auth/login",
        json={
            "username": settings.initial_admin_username,
            "password": settings.initial_admin_password,
        },
    )
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    codes = [r["code"] for r in response.json()["data"]["assignable_roles"]]
    assert "super_admin" in codes


async def test_user_manager_me_excludes_super_admin_from_assignable(client, test_engine) -> None:
    from argon2 import PasswordHasher
    from sqlalchemy import select

    from app.models.rbac import Role, User, UserRole

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        mgr = User(
            username="mgr_me",
            display_name="Manager Me",
            password_hash=ph.hash("Password123"),
        )
        s.add(mgr)
        await s.flush()
        manager_role = await s.scalar(select(Role).where(Role.code == "user_manager"))
        s.add(UserRole(user_id=mgr.id, role_id=manager_role.id))
        await s.commit()

    await client.post(
        "/api/auth/login",
        json={"username": "mgr_me", "password": "Password123"},
    )

    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert "user:assign_role" in response.json()["data"]["permissions"]
    codes = [r["code"] for r in response.json()["data"]["assignable_roles"]]
    assert "super_admin" not in codes
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_assign"; python -m pytest tests/test_auth_api.py -q
```
Expected: 新增 2 个测试失败（第一个：super_admin 不在 assignable_roles 中；第二个：断言失败——注意第二个测试在旧代码下 `"super_admin" not in codes` 是 PASS 的，所以它不会红——**这个测试在旧代码下是绿的**，用于防回归；真正驱动修复的是第一个测试）

- [ ] **Step 3: 修改 get_assignable_roles**（`backend/app/services/auth_service.py`，整个函数替换）

```python
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
```

顶部 import 确认：`from app.models.rbac import Role, User, UserRole`（若 `UserRole` 未导入则加入）。

- [ ] **Step 4: 调用处传当前用户**（`backend/app/api/auth.py:55`）

```python
        result["assignable_roles"] = await get_assignable_roles(db, current_user)
```

- [ ] **Step 5: 跑测试确认全绿**

Run: 同 Step 2 命令
Expected: 全部 PASS（含既有测试）

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/auth_service.py backend/app/api/auth.py backend/tests/test_auth_api.py
git commit -m "feat: show super_admin role in assignable roles for super admins"
```

---

### Task 4: 前端禁用内置账号的停用/删除操作

**Files:**
- Modify: `frontend/src/types/user.ts:10`（`UserListItem` 加字段）
- Modify: `frontend/src/components/users/user-table.tsx:69-78`（停用/删除菜单项加 disabled/title）
- Modify: `frontend/src/components/users/user-management.test.tsx`（2 个新测试 + mock 数据补字段）
- Modify: `frontend/src/components/users/user-drawer.test.tsx:22`、`frontend/src/components/users/user-dialogs.test.tsx:28`（baseUser fixture 补字段）

**Interfaces:**
- Consumes: 后端用户列表/详情响应的 `is_builtin` 布尔字段（T2）
- Produces: 内置账号的"停用/删除"菜单项渲染为禁用态（`aria-disabled="true"`）

- [ ] **Step 1: 类型加字段**（`frontend/src/types/user.ts`，`status` 行后加）

```ts
  is_builtin: boolean;
```

- [ ] **Step 2: 修复现有测试 fixture**（TS 会立即报错，先把三处 fixture 补上）

`frontend/src/components/users/user-management.test.tsx` 的 `mockUsers` 中每个用户对象（约第 26-40 行的 `baseUser`/`mockUsers.items`）加 `is_builtin: false`；`user-drawer.test.tsx` 的 `baseUser`（约第 22 行）与 `user-dialogs.test.tsx` 的 `baseUser`（约第 28 行）同样加 `is_builtin: false`。

```ts
      status: "active",
      is_builtin: false,
```

- [ ] **Step 3: 跑现有测试确认通过（类型修复后基线）**

Run（frontend 目录）:
```powershell
npx vitest run src/components/users/user-management.test.tsx src/components/users/user-drawer.test.tsx src/components/users/user-dialogs.test.tsx
```
Expected: 全部 PASS

- [ ] **Step 4: 写失败测试**（追加到 `frontend/src/components/users/user-management.test.tsx` 的 describe 块内；确认文件已 import `fireEvent`（来自 `@testing-library/react`），没有则加）

```tsx
  test("disables status toggle for builtin users", async () => {
    mockApi.mockResolvedValue({
      ...mockUsers,
      items: [{ ...mockUsers.items[0], is_builtin: true }],
    });
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");
    fireEvent.click((await screen.findAllByRole("button", { name: "More actions" }))[0]);

    expect(await screen.findByText("停用")).toBeInTheDocument();
    expect(screen.getByText("停用").closest("li")).toHaveAttribute("aria-disabled", "true");
  });

  test("disables delete for builtin users", async () => {
    mockApi.mockResolvedValue({
      ...mockUsers,
      items: [{ ...mockUsers.items[0], is_builtin: true }],
    });
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");
    fireEvent.click((await screen.findAllByRole("button", { name: "More actions" }))[0]);

    expect(await screen.findByText("删除")).toBeInTheDocument();
    expect(screen.getByText("删除").closest("li")).toHaveAttribute("aria-disabled", "true");
  });
```

- [ ] **Step 5: 跑测试确认失败**

Run:
```powershell
npx vitest run src/components/users/user-management.test.tsx
```
Expected: 新增 2 个测试失败（菜单项无 `aria-disabled`，`toHaveAttribute` 断言失败）

- [ ] **Step 6: 菜单项加禁用**（`frontend/src/components/users/user-table.tsx`，第 69-78 行替换为）

```tsx
  if (hasPermission(currentUser, USER_STATUS)) {
    const label = user.status === "active" ? "停用" : "启用";
    items.push({
      key: "toggleStatus",
      label,
      disabled: user.is_builtin,
      title: user.is_builtin ? "内置账号不可禁用" : undefined,
      onClick: () => onToggleStatus(user),
    });
  }
  if (hasPermission(currentUser, USER_RESET_PASSWORD)) {
    items.push({ key: "resetPassword", label: copy.user.resetPassword, onClick: () => onResetPassword(user) });
  }
  if (hasPermission(currentUser, USER_DELETE)) {
    items.push({
      key: "delete",
      label: copy.common.delete,
      danger: true,
      disabled: user.is_builtin,
      title: user.is_builtin ? "内置账号不可删除" : undefined,
      onClick: () => onDelete(user),
    });
  }
```

- [ ] **Step 7: 跑测试确认全绿**

Run: 同 Step 5 命令
Expected: 全部 PASS（含 2 个新测试）

- [ ] **Step 8: 提交**

```bash
git add frontend/src/types/user.ts frontend/src/components/users/user-table.tsx frontend/src/components/users/user-management.test.tsx frontend/src/components/users/user-drawer.test.tsx frontend/src/components/users/user-dialogs.test.tsx
git commit -m "feat: disable delete/disable actions for builtin admin in user table"
```

---

### Task 5: 全量回归

**Files:** 无改动，只跑测试。

- [ ] **Step 1: 后端全量**

Run（backend 目录，专用库）:
```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_final"; python -m pytest -q
```
Expected: 全部 PASS（约 590+ 个测试；若出现与本次改动无关的既有失败，记录下来并在报告中注明，不要"顺手修"）

- [ ] **Step 2: 前端全量**

Run（frontend 目录）:
```powershell
npx vitest run
```
Expected: 全部 PASS

- [ ] **Step 3: 端到端冒烟（可选，本地服务运行中时）**

Run（backend 目录）:
```powershell
$lines = @(
  "import asyncio",
  "from sqlalchemy import select",
  "from app.db.session import async_session_factory",
  "from app.models.rbac import User",
  "async def main():",
  "    async with async_session_factory() as s:",
  "        admin = await s.scalar(select(User).where(User.username == 'admin'))",
  "        print('admin is_builtin:', admin.is_builtin)",
  "asyncio.run(main())"
)
Set-Content -Path "$env:TEMP\check_admin_builtin.py" -Value $lines
python -X utf8 "$env:TEMP\check_admin_builtin.py"
```
Expected: `admin is_builtin: True`（确认开发库已标记）

- [ ] **Step 4: 汇报**

在报告中给出：每个任务的提交 SHA、全量测试结果、与计划不符的偏差及原因（如有）。
