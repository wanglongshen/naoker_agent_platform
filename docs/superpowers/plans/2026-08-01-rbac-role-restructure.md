# RBAC 角色体系重构 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 角色集调整为 5 个（新增普通用户，删除运营专员/只读访客），超管删除他人文件权限收紧为仅限自己。

**Architecture:** `seed.py` 增加 `regular_user` 角色（4 个文件权限）+ 幂等 reconciliation（旧角色用户重指、旧角色软删）；`seed_demo_data.py` 移除旧角色并重映射演示用户；`files.py` 删除端点改用 owner-only 校验；前端文件管理页按属主隐藏删除按钮。

**Tech Stack:** Python (FastAPI/SQLAlchemy), TypeScript/React

## Global Constraints

- 角色 code：`regular_user`（新增）、`operations_specialist`/`read_only_visitor`（移除）
- 普通用户权限：`file:read`, `file:upload`, `file:delete`, `file:manage_folders`
- reconciliation 必须幂等（可重复执行）
- 超管仍可全局查看（download/preview/admin 列表/AI 工具调用）— 仅删除收紧
- 演示用户（seed_demo_data）中的旧角色全部替换为 `regular_user`

---

### Task 1: seed.py — regular_user 角色 + 旧角色 reconciliation

**Files:**
- Modify: `backend/app/db/seed.py`
- Test: `backend/tests/test_seed.py`

**Interfaces:**
- Consumes: `seed_rbac(session)` 现有结构
- Produces: `regular_user` 角色（is_system=True）+ 4 文件权限绑定；`operations_specialist`/`read_only_visitor` 软删；持有旧角色的用户重指 `regular_user`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_seed.py`:

```python
class TestRegularUserRole:
    async def test_regular_user_role_has_four_file_permissions(self, test_db):
        from sqlalchemy import select
        from app.models.rbac import Role, RolePermission, Permission

        async with test_db() as s:
            await seed_rbac(s)
            role = await s.scalar(select(Role).where(Role.code == "regular_user"))
            assert role is not None
            assert role.is_system is True
            perms = (await s.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            )).all()
            assert set(perms) == {"file:read", "file:upload", "file:delete", "file:manage_folders"}

    async def test_legacy_roles_soft_deleted_and_users_reassigned(self, test_db):
        from sqlalchemy import select, delete
        from app.models.rbac import Role, User, UserRole, RolePermission

        async with test_db() as s:
            await seed_rbac(s)
            # Create a legacy scenario: user with operations_specialist role
            legacy = Role(code="operations_specialist", name="运营专员", description="d")
            s.add(legacy)
            await s.flush()
            user = User(username="legacy_user_1", display_name="Legacy", password_hash="x")
            s.add(user)
            await s.flush()
            s.add(UserRole(user_id=user.id, role_id=legacy.id))
            await s.commit()

            # Re-run seed (reconciliation)
            await seed_rbac(s)

            legacy_db = await s.scalar(select(Role).where(Role.code == "operations_specialist"))
            assert legacy_db is not None and legacy_db.is_deleted is True
            regular = await s.scalar(select(Role).where(Role.code == "regular_user"))
            assert regular is not None
            binding = await s.scalar(select(UserRole).where(UserRole.user_id == user.id))
            assert binding is not None and binding.role_id == regular.id
```

Note: match the file's existing fixture patterns (`test_db` fixture, how `seed_rbac` is imported/called). If the file uses a different fixture name, adapt.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_seed.py -v
```

Expected: New tests FAIL (`regular_user` not found).

- [ ] **Step 3: Implement**

In `backend/app/db/seed.py`:

Add constants at module level (after `ROLES`):

```python
LEGACY_ROLE_CODES = ("operations_specialist", "read_only_visitor")
```

Change `ROLES` (line 29-32) to add regular_user:

```python
ROLES = (
    ("super_admin", "超级管理员", "拥有系统全部管理权限"),
    ("user_manager", "用户管理员", "负责用户账号、状态、密码和角色分配"),
    ("regular_user", "普通用户", "管理自己的文件与文件夹"),
)
```

In `seed_rbac`, after the `user_manager` file_permissions block (after line 127), add:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_seed.py -v
```

Expected: All pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/seed.py backend/tests/test_seed.py
git commit -m "feat: add regular_user role and reconcile legacy roles in seed"
```

---

### Task 2: seed_demo_data.py — remove legacy roles, remap demo users

**Files:**
- Modify: `backend/app/db/seed_demo_data.py`
- Test: `backend/tests/test_demo_seed.py`

**Interfaces:**
- Consumes: `EXTRA_ROLES` tuple + `USER_ROLE_MAP` dict
- Produces: no `operations_specialist`/`read_only_visitor` roles; all occurrences in `USER_ROLE_MAP` replaced with `regular_user`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_demo_seed.py`:

```python
class TestDemoRolesUpdated:
    async def test_demo_data_no_longer_creates_legacy_roles(self, test_db):
        from sqlalchemy import select
        from app.models.rbac import Role
        from app.db.seed_demo_data import seed_demo_data

        async with test_db() as s:
            await seed_demo_data(s)
            legacy = (await s.scalars(
                select(Role).where(Role.code.in_(["operations_specialist", "read_only_visitor"]))
            )).all()
            assert all(r.is_deleted for r in legacy) or len(legacy) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_demo_seed.py -v
```

Expected: FAIL (demo creates active legacy roles).

- [ ] **Step 3: Implement**

In `backend/app/db/seed_demo_data.py`:

Remove these two entries from `EXTRA_ROLES` (lines 25-26):

```python
    ("operations_specialist", "运营专员", "负责用户查询、新建和资料维护", False),
    ("read_only_visitor", "只读访客", "仅可查看用户信息", False),
```

Remove the corresponding permission maps (the dict entries keyed by those codes, around lines 38-41).

In `USER_ROLE_MAP`, replace EVERY occurrence of `"operations_specialist"` and `"read_only_visitor"` with `"regular_user"` (lines 102-139). Keep users that already have other roles (e.g., `"huang.ying": ["role_manager", "operations_specialist"]` → `["role_manager", "regular_user"]`).

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_demo_seed.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/seed_demo_data.py backend/tests/test_demo_seed.py
git commit -m "feat: remove legacy roles from demo data, remap to regular_user"
```

---

### Task 3: files.py — delete owner-only (remove super-admin bypass)

**Files:**
- Modify: `backend/app/api/files.py`
- Test: `backend/tests/test_agent_authorization.py`（或现有文件 API 测试，以实际文件为准）

**Interfaces:**
- Consumes: `_check_file_access`（保留，用于查看）、`_check_file_owner`（用于删除）
- Produces: 单删/批量删除仅允许属主；超管查看（download/preview/admin list）不变

- [ ] **Step 1: Write the failing test**

Add to the appropriate existing file-API test file (read `backend/tests/test_agent_authorization.py` first to match fixtures; if it has no file-delete coverage, add to the file API test file):

```python
class TestSuperAdminCannotDeleteOthersFiles:
    async def test_super_admin_delete_other_user_file_forbidden(self, test_db, client, ...):
        # Create two users (owner + super_admin), a file owned by owner.
        # Login as super_admin, DELETE /api/files/{file_id}
        # Expected: 403
        ...
```

Adapt to the existing auth/API test patterns in the file (login helper, file upload helper). The assertion MUST be: super_admin deleting another user's file returns 403.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_authorization.py -v
```

Expected: FAIL (currently 200 — super admin bypass).

- [ ] **Step 3: Implement**

In `backend/app/api/files.py`:

Find the single-file delete endpoint (around line 440, uses `_check_file_access`). Change it to owner-only:

```python
    file_obj = await _check_file_owner(await repo.get_file(file_id), current_user)
```

Find the batch delete endpoint (uses a per-file loop with owner-or-super-admin logic). Change the per-file check to owner-only — locate the condition (likely `file_obj.owner_user_id == current_user.id or await _is_super_admin(...)`) and remove the super-admin branch, keeping the per-file failure behavior ("无权删除").

DO NOT change `_check_file_access` itself — download (line 280) and preview (line 312) keep the super-admin view bypass.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_authorization.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full file/agent suites**

```bash
cd C:\01_agent_loop_pro\backend && python -m pytest tests/test_agent_authorization.py tests/test_agent_api.py -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/files.py backend/tests/test_agent_authorization.py
git commit -m "fix: file delete owner-only, super admin keeps view-only access"
```

---

### Task 4: 前端 — 文件管理页按属主隐藏删除按钮

**Files:**
- Modify: `frontend/src/` 下文件管理/管理页组件（先用 grep 定位删除按钮）
- Test: 对应前端测试文件

**Interfaces:**
- Consumes: 文件列表项（含 `owner_user_id`）、当前用户（`currentUser`）
- Produces: 超管在管理页查看他人文件时，删除按钮隐藏（仅查看）

- [ ] **Step 1: Locate the delete button**

```bash
cd C:\01_agent_loop_pro\frontend && grep -rn "delete" src/components/files src/app/\(dashboard\)/files --include="*.tsx" -l
```

Identify the files-admin page/component where the super admin can see ALL users' files (gated by `FILE_ADMIN_VIEW`/`isSuperAdmin`), and where the delete action is rendered.

- [ ] **Step 2: Write the failing test**

In the file-management page test, add a case: super admin viewing ANOTHER user's file → delete button NOT rendered; super admin viewing OWN file → delete button rendered. Follow the existing test patterns in that file.

- [ ] **Step 3: Implement**

In the delete action render site, gate by ownership:

```tsx
const canDelete = file.owner_user_id === currentUser.id;
```

Render the delete button only when `canDelete` is true. (If the component already receives `currentUser` — verify; if not, pass it through.)

- [ ] **Step 4: Run the frontend tests**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/files -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add <modified frontend files>
git commit -m "fix: hide delete for others' files in admin file view"
```
