# Product RBAC Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the current RBAC demo into an enterprise-style administration console with complete role management, normalized permission assignment, protected system roles, stable API contracts, and a dark-sidebar/light-content UI.

**Architecture:** Preserve the existing FastAPI async SQLAlchemy and normalized five-table RBAC data model. Extend it with role metadata, a role service/API, batch-loaded role DTOs, request correlation middleware, and shared frontend primitives. Stabilize backend contracts before rebuilding user and role views around reusable admin-shell, table, drawer, and permission-tree components.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Vitest, FastAPI, SQLAlchemy 2 async ORM, Pydantic v2, Alembic, PostgreSQL, Argon2, python-jose.

## Global Constraints

- Retain normalized `users`, `roles`, `permissions`, `user_roles`, and `role_permissions` many-to-many RBAC tables.
- Retain JWT authentication in an `HttpOnly`, `SameSite=Lax`, `Path=/` cookie; do not replace it with Header Bearer browser authentication.
- Protected APIs resolve effective permissions from PostgreSQL for every request; frontend permission checks only control visible UI.
- Add `roles.is_system`, `roles.is_deleted`, `roles.sort_order`, `permissions.module`, `permissions.sort_order`, and `permissions.is_system` by Alembic migration.
- `super_admin` may change only name and description. Its code, active state, permissions, and existence are immutable. It has every active system permission.
- Keep at least one active, non-deleted user assigned to `super_admin` at all times.
- Normal role codes are immutable after creation. Disabled/deleted roles cannot be assigned and disabled roles contribute no effective permissions.
- Soft-delete normal roles and remove `user_roles` and `role_permissions` associations transactionally.
- Add `role:read`, `role:create`, `role:update`, `role:delete`, `role:status`, and `role:assign_permission` permissions.
- User-facing DTOs return role `{ id, code, name }` summaries, never raw role UUIDs as display values.
- All non-204 successful responses use `{ data, message, request_id }`; API errors use `{ code, message, details, request_id }`; write the same request ID to `X-Request-ID`.
- Use a dark `#111827` sidebar, light `#f5f7fb` work area, white surfaces, indigo `#4f46e5` primary actions, green active tags, neutral inactive tags, and red destructive actions.
- Do not introduce a heavyweight UI library. Do not use gradients, emoji icons, raw browser controls, UUID display, or scattered inline styles in upgraded UI.
- Preserve existing local configuration behavior: `backend/alembic/env.py` must load `backend/.env` through `get_settings()`. Do not include `.idea/` in commits.

---

## Planned File Structure

| Path | Responsibility |
| --- | --- |
| `backend/alembic/versions/<revision>_product_rbac.py` | Role/permission metadata schema migration |
| `backend/app/models/rbac.py` | Extended normalized RBAC ORM metadata |
| `backend/app/db/seed.py` | Idempotent system role and permission seed synchronization |
| `backend/app/schemas/common.py` | Success envelope, compact role reference, and paginated response DTOs |
| `backend/app/schemas/role.py` | Role create/update/state/detail schemas |
| `backend/app/services/role_service.py` | Role CRUD, system role protection, associations, impact counts |
| `backend/app/services/user_service.py` | Batch role summaries, role validation, user role protections |
| `backend/app/services/auth_service.py` | Current-user typed roles/effective permission resolution |
| `backend/app/api/roles.py` | Role and permission endpoints |
| `backend/app/core/middleware.py` | Request ID and request duration logging middleware |
| `backend/app/main.py` | Middleware, routers, and response/error registration |
| `backend/tests/test_roles_api.py` | Role system integration tests |
| `frontend/src/components/ui/*` | Reusable Button, Input, Select, Drawer, Dialog, Tag, Table states |
| `frontend/src/components/layout/*` | Responsive sidebar, header, page header, dashboard shell |
| `frontend/src/components/users/*` | Product user filter, table, and drawer components |
| `frontend/src/components/roles/*` | Role table, filter, drawer, and grouped permission tree |
| `frontend/src/types/*.ts` | Contract-aligned frontend DTOs |
| `frontend/src/lib/api.ts` | Success-envelope unwrap and request ID error support |
| `frontend/src/app/(dashboard)/roles/page.tsx` | Role management page |
| `README.md` | Local migration, startup, and role-management documentation |

## Task 1: Stabilize Local Migration Configuration and Ignore IDE State

**Files:**
- Modify: `.gitignore`
- Modify: `backend/alembic/env.py`
- Modify: `README.md`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Produces Alembic URL lookup `get_url() -> str` backed by `get_settings().database_url`.
- Produces local startup instruction that distinguishes `alembic current` from `alembic upgrade head`.

- [ ] **Step 1: Write the failing migration-configuration test.**

Create `backend/tests/test_alembic_config.py`:

```python
from app.core.config import get_settings


def test_settings_load_database_url_from_backend_env() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.database_url.startswith("postgresql+asyncpg://")
```

- [ ] **Step 2: Verify the configuration test fails when `backend/.env` is absent.**

Run: `cd backend; Move-Item .env .env.test-backup; python -m pytest tests/test_alembic_config.py -v; Move-Item .env.test-backup .env`

Expected: FAIL with a Pydantic validation error for `database_url`, proving this test exercises `.env` loading.

- [ ] **Step 3: Keep Alembic on the same settings path as FastAPI.**

Ensure `backend/alembic/env.py` contains:

```python
from app.core.config import get_settings


def get_url() -> str:
    return get_settings().database_url
```

Remove `os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))`. This prevents Alembic from receiving `None` when the shell environment lacks `DATABASE_URL` while `backend/.env` is valid.

Append these `.gitignore` entries:

```gitignore
.idea/
backend/.env.test-backup
```

Add this README troubleshooting block:

```text
If Alembic reports a revision is current but application tables are missing,
run `alembic current -v` and inspect the actual database before changing
`alembic_version`. Never delete migration metadata from a non-empty database.
```

- [ ] **Step 4: Verify local configuration and current migration state.**

Run: `cd backend; python -m pytest tests/test_alembic_config.py tests/test_health.py -v; alembic current -v`

Expected: both tests PASS and Alembic prints the PostgreSQL URL with password masked plus the current revision.

- [ ] **Step 5: Commit the local setup stabilization.**

```powershell
git add .gitignore backend/alembic/env.py backend/tests/test_alembic_config.py README.md
git commit -m "fix: align alembic with application settings"
```

## Task 2: Add Role and Permission Metadata Migration

**Files:**
- Modify: `backend/app/models/rbac.py`
- Create: `backend/alembic/versions/<revision>_product_rbac_metadata.py`
- Modify: `backend/app/db/seed.py`
- Test: `backend/tests/test_rbac_metadata.py`

**Interfaces:**
- Produces ORM fields `Role.is_system`, `Role.is_deleted`, `Role.sort_order`, `Permission.module`, `Permission.sort_order`, `Permission.is_system`.
- Produces active/deleted role filtering compatible with all later services.

- [ ] **Step 1: Write failing metadata and seed synchronization tests.**

Create `backend/tests/test_rbac_metadata.py`:

```python
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
```

- [ ] **Step 2: Verify the metadata test fails.**

Run: `cd backend; python -m pytest tests/test_rbac_metadata.py -v`

Expected: FAIL because `Role` has no `is_system` field.

- [ ] **Step 3: Extend models and create the migration.**

Add these mapped columns to `Role`:

```python
is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
```

Add these mapped columns to `Permission`:

```python
module: Mapped[str] = mapped_column(String(64), default="system", server_default="system")
sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
is_system: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
```

Create a migration that:

```python
op.add_column("roles", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")))
op.add_column("roles", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")))
op.add_column("roles", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
op.create_index("ix_roles_is_deleted", "roles", ["is_deleted"])
op.add_column("permissions", sa.Column("module", sa.String(length=64), nullable=False, server_default="system"))
op.add_column("permissions", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
op.add_column("permissions", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("true")))
```

Backfill `super_admin.is_system = true`, set existing roles as non-deleted, and backfill permission module with SQL `CASE` prefixes (`user:%` -> `user`, `role:%` -> `role`, otherwise `system`). Downgrade removes the index and six added columns only.

- [ ] **Step 4: Extend idempotent seed data.**

Replace the permission source with module-aware definitions:

```python
PERMISSIONS = (
    ("user:read", "Read users", "user", 10),
    ("user:create", "Create user", "user", 20),
    ("user:update", "Update user", "user", 30),
    ("user:delete", "Delete user", "user", 40),
    ("user:status", "Change user status", "user", 50),
    ("user:reset_password", "Reset user password", "user", 60),
    ("user:assign_role", "Assign user roles", "user", 70),
    ("role:read", "Read roles", "role", 10),
    ("role:create", "Create role", "role", 20),
    ("role:update", "Update role", "role", 30),
    ("role:delete", "Delete role", "role", 40),
    ("role:status", "Change role status", "role", 50),
    ("role:assign_permission", "Assign role permissions", "role", 60),
)
```

Set `super_admin` to `is_system=True`, `status="active"`, and attach every `Permission` where `status == "active"`. Keep `user_manager` limited to `user:*` permissions.

- [ ] **Step 5: Run focused metadata verification.**

Run: `cd backend; python -m pytest tests/test_seed.py tests/test_rbac_metadata.py -v`

Expected: PASS; the active permission assignment set equals the `super_admin` association set.

- [ ] **Step 6: Apply the migration to the local database.**

Run: `cd backend; alembic upgrade head`

Expected: Alembic prints the new revision upgrade exactly once. `alembic current -v` reports that revision as head.

- [ ] **Step 7: Commit metadata support.**

```powershell
git add backend/app/models/rbac.py backend/app/db/seed.py backend/alembic/versions backend/tests/test_rbac_metadata.py
git commit -m "feat: add role and permission metadata"
```

## Task 3: Add Common API Envelopes and Request ID Middleware

**Files:**
- Create: `backend/app/schemas/common.py`
- Create: `backend/app/core/middleware.py`
- Modify: `backend/app/core/errors.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_request_id.py`

**Interfaces:**
- Produces `SuccessResponse[T]` with `data`, `message`, `request_id`.
- Produces `RequestIdMiddleware` and request state property `request.state.request_id`.
- Produces header `X-Request-ID` on every response.

- [ ] **Step 1: Write failing Request ID tests.**

Create `backend/tests/test_request_id.py`:

```python
async def test_health_returns_generated_request_id(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


async def test_error_returns_forwarded_request_id(client) -> None:
    response = await client.get("/api/users", headers={"X-Request-ID": "manual-request"})
    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "manual-request"
    assert response.json()["request_id"] == "manual-request"
```

- [ ] **Step 2: Verify the tests fail.**

Run: `cd backend; python -m pytest tests/test_request_id.py -v`

Expected: FAIL with missing `X-Request-ID` header and missing error field.

- [ ] **Step 3: Implement middleware and error integration.**

Implement middleware behavior:

```python
request_id = request.headers.get("X-Request-ID") or str(uuid4())
request.state.request_id = request_id
started_at = perf_counter()
response = await call_next(request)
response.headers["X-Request-ID"] = request_id
logger.info("request_complete", extra={"request_id": request_id, "method": request.method, "path": request.url.path, "status": response.status_code, "elapsed_ms": round((perf_counter() - started_at) * 1000, 2)})
return response
```

Update the `ApiError` handler to obtain `request.state.request_id`, include it in the JSON error body, and preserve `details=None` as JSON `null`.

Create:

```python
class SuccessResponse(BaseModel, Generic[T]):
    data: T
    message: str = "OK"
    request_id: str
```

Add `RequestIdMiddleware` before CORS middleware registration in `main.py`.

- [ ] **Step 4: Wrap every non-204 successful response.**

Add a small `success(request: Request, data: T, message: str = "OK") -> dict` helper in `schemas/common.py`. Convert health, login, me, user list, create, update, status, and password reset handlers to use it. Keep `DELETE /api/users/{id}` as `204` with only `X-Request-ID` header.

- [ ] **Step 5: Run API contract regression tests.**

Run: `cd backend; python -m pytest tests/test_auth_api.py tests/test_users_api.py tests/test_request_id.py -v`

Expected: PASS after updating all assertions to access `response.json()["data"]` for successful bodies.

- [ ] **Step 6: Commit envelopes and middleware.**

```powershell
git add backend/app/schemas/common.py backend/app/core/middleware.py backend/app/core/errors.py backend/app/main.py backend/app/api backend/tests/test_request_id.py backend/tests/test_auth_api.py backend/tests/test_users_api.py
git commit -m "feat: add request ids and api response envelopes"
```

## Task 4: Implement Role Service and Role/Permission APIs

**Files:**
- Create: `backend/app/schemas/role.py`
- Create: `backend/app/services/role_service.py`
- Create: `backend/app/api/roles.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/core/dependencies.py`
- Test: `backend/tests/test_roles_api.py`

**Interfaces:**
- Produces `GET /api/roles`, `GET /api/roles/{id}`, `POST /api/roles`, `PUT /api/roles/{id}`, `PATCH /api/roles/{id}/status`, `DELETE /api/roles/{id}`, and `GET /api/permissions`.
- Produces `RoleSummary`, `RoleDetail`, `PermissionSummary`, `RoleCreate`, `RoleUpdate`, `RoleStatusUpdate`.

- [ ] **Step 1: Write failing role API tests.**

Create `backend/tests/test_roles_api.py`:

```python
async def test_admin_creates_role_with_permissions(admin_client, permissions) -> None:
    response = await admin_client.post(
        "/api/roles",
        json={
            "code": "role_manager",
            "name": "Role Manager",
            "description": "Manages ordinary roles",
            "permission_ids": [str(permissions["role:read"].id)],
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["code"] == "role_manager"
    assert response.json()["data"]["permissions"][0]["code"] == "role:read"


async def test_super_admin_permissions_and_status_are_immutable(admin_client, super_admin_role) -> None:
    response = await admin_client.put(
        f"/api/roles/{super_admin_role.id}",
        json={"name": "Renamed", "description": "Allowed", "permission_ids": []},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SYSTEM_ROLE_IMMUTABLE"


async def test_deleting_normal_role_removes_user_associations(admin_client, ordinary_role_with_user) -> None:
    response = await admin_client.delete(f"/api/roles/{ordinary_role_with_user.role.id}")
    assert response.status_code == 204
    assert await ordinary_role_with_user.user_has_no_role_association()
```

- [ ] **Step 2: Verify role tests fail.**

Run: `cd backend; python -m pytest tests/test_roles_api.py -v`

Expected: FAIL with `404` because `/api/roles` is not registered.

- [ ] **Step 3: Define role schemas.**

Define these exact response shapes:

```python
class PermissionSummary(BaseModel):
    id: UUID
    code: str
    name: str
    module: str
    description: str | None

class RoleSummary(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    status: Literal["active", "disabled"]
    is_system: bool
    permission_count: int

class RoleDetail(RoleSummary):
    permissions: list[PermissionSummary]
    assigned_user_count: int
```

`RoleCreate` requires code, name, description optional, and `permission_ids` default empty. `RoleUpdate` has name, description, and optional `permission_ids`; it deliberately has no code or status. `RoleStatusUpdate` accepts active or disabled. `RoleSummary` is used only by role-management endpoints; user and authentication endpoints use the compact `RoleReference` defined in Task 5.

- [ ] **Step 4: Implement role service rules.**

Implement:

```python
async def list_roles(db: AsyncSession, keyword: str | None, status: str | None, page: int, page_size: int) -> PageResult
async def get_role_detail(db: AsyncSession, role_id: UUID) -> RoleDetail
async def create_role(db: AsyncSession, data: RoleCreate) -> RoleDetail
async def update_role(db: AsyncSession, role_id: UUID, data: RoleUpdate) -> RoleDetail
async def update_role_status(db: AsyncSession, role_id: UUID, status: str) -> RoleDetail
async def delete_role(db: AsyncSession, role_id: UUID) -> None
async def list_permissions(db: AsyncSession) -> list[PermissionSummary]
```

Rules:

- All role queries exclude `is_deleted=True`.
- `super_admin` update rejects a supplied `permission_ids`; accepts only name and description.
- `super_admin` status changes and deletion raise `ApiError(400, "SYSTEM_ROLE_IMMUTABLE", ...)`.
- Normal role code/name conflicts raise `409 DUPLICATE_VALUE`.
- Permission IDs must all refer to active system permissions; otherwise return `404 PERMISSION_NOT_FOUND` or `400 INACTIVE_PERMISSION`.
- Role deletion runs `delete(UserRole).where(UserRole.role_id == role_id)`, `delete(RolePermission).where(...)`, sets `is_deleted=True`, and sets `status="disabled"` in one transaction.
- Permission counts and assigned user counts use aggregate SQL queries, not Python row counting.

- [ ] **Step 5: Implement permissions and role routes.**

Route guards:

```python
@router.get("")
async def list_roles(..., _: User = require_permissions("role:read")):

@router.post("", status_code=201)
async def create_role(..., current_user: User = Depends(get_current_user)):
    require both "role:create" and "role:assign_permission" when data.permission_ids is non-empty

@router.put("/{role_id}")
async def update_role(..., current_user: User = Depends(get_current_user)):
    require "role:update" and require "role:assign_permission" when data.permission_ids is not None
```

Use the standard `success(request, data, message)` envelope for all non-204 responses.

- [ ] **Step 6: Run role and authorization verification.**

Run: `cd backend; python -m pytest tests/test_roles_api.py tests/test_auth_api.py tests/test_users_api.py -v`

Expected: PASS; verify ordinary roles stop contributing permissions immediately after disablement or deletion using a second authenticated request.

- [ ] **Step 7: Commit the role backend.**

```powershell
git add backend/app/schemas/role.py backend/app/services/role_service.py backend/app/api/roles.py backend/app/main.py backend/app/core/dependencies.py backend/tests/test_roles_api.py
git commit -m "feat: add protected role management api"
```

## Task 5: Upgrade Auth and User DTOs with Batch Role Summaries

**Files:**
- Modify: `backend/app/schemas/auth.py`
- Modify: `backend/app/schemas/user.py`
- Modify: `backend/app/services/auth_service.py`
- Modify: `backend/app/services/user_service.py`
- Modify: `backend/app/api/auth.py`
- Modify: `backend/app/api/users.py`
- Test: `backend/tests/test_auth_api.py`
- Test: `backend/tests/test_users_api.py`

**Interfaces:**
- Produces `RoleReference` roles in `/api/auth/me`, user list, and user detail payloads.
- Produces one batch role query per user page.

- [ ] **Step 1: Write failing DTO contract tests.**

Add to `backend/tests/test_auth_api.py`:

```python
async def test_me_returns_role_summaries_and_menu_permissions(admin_client) -> None:
    response = await admin_client.get("/api/auth/me")
    body = response.json()["data"]
    assert body["roles"][0].keys() >= {"id", "code", "name"}
    assert body["menu_permissions"] == body["permissions"]
```

Add to `backend/tests/test_users_api.py`:

```python
async def test_user_list_returns_role_summaries_not_role_ids(admin_client, user_with_role) -> None:
    response = await admin_client.get("/api/users")
    item = next(item for item in response.json()["data"]["items"] if item["id"] == str(user_with_role.id))
    assert item["roles"] == [{"id": str(user_with_role.role.id), "code": user_with_role.role.code, "name": user_with_role.role.name}]
    assert "role_ids" not in item
```

- [ ] **Step 2: Verify DTO tests fail.**

Run: `cd backend; python -m pytest tests/test_auth_api.py tests/test_users_api.py -v`

Expected: FAIL because current payloads expose role IDs/string codes rather than role summary objects.

- [ ] **Step 3: Define and reuse role summary schemas.**

Add this compact shared DTO to `schemas/common.py` without replacing the richer `RoleSummary` from `schemas/role.py`:

```python
class RoleReference(BaseModel):
    id: UUID
    code: str
    name: str
```

Update `CurrentUserResponse` and `UserResponse` so their role field is `roles: list[RoleReference]`. Add `menu_permissions: list[str]` to `CurrentUserResponse`. Keep `assignable_roles: list[RoleReference] | None` conditional on `user:assign_role`.

- [ ] **Step 4: Replace N+1 user role resolution.**

Replace `_get_user_role_ids` calls in the list loop with one query:

```python
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
```

Group rows by `user_id` and pass `list[RoleReference]` into `_user_to_response`. Use an `EXISTS` condition for the role filter.

- [ ] **Step 5: Tighten user role assignment validation.**

For create/update role IDs:

```python
requested_role_ids = list(dict.fromkeys(data.role_ids or []))
```

Change `create_user` and `update_user` signatures to accept `current_user: User`. Require every requested role to be active and `is_deleted=False`. If a non-super-admin caller assigns `super_admin`, return `403 PERMISSION_DENIED`. Before removing a target user's final `super_admin` relation, call the existing final-super-admin protection. Pass `current_user` from the API handlers after permission checks.

- [ ] **Step 6: Run DTO and list regression tests.**

Run: `cd backend; python -m pytest tests/test_auth_api.py tests/test_users_api.py tests/test_rbac_end_to_end.py -v`

Expected: PASS; user list role summaries display names, and role mutations alter authorization on the next request.

- [ ] **Step 7: Commit contract and performance upgrade.**

```powershell
git add backend/app/schemas backend/app/services/auth_service.py backend/app/services/user_service.py backend/app/api/auth.py backend/app/api/users.py backend/tests/test_auth_api.py backend/tests/test_users_api.py
git commit -m "feat: return typed role summaries in user contracts"
```

## Task 6: Build Shared Frontend Admin Primitives and Responsive Shell

**Files:**
- Create: `frontend/src/components/ui/button.tsx`
- Create: `frontend/src/components/ui/input.tsx`
- Create: `frontend/src/components/ui/select.tsx`
- Create: `frontend/src/components/ui/drawer.tsx`
- Create: `frontend/src/components/ui/status-tag.tsx`
- Create: `frontend/src/components/ui/empty-state.tsx`
- Create: `frontend/src/components/ui/skeleton.tsx`
- Create: `frontend/src/components/layout/app-sidebar.tsx`
- Create: `frontend/src/components/layout/app-header.tsx`
- Create: `frontend/src/components/layout/page-header.tsx`
- Create: `frontend/src/components/layout/dashboard-shell.tsx`
- Modify: `frontend/src/app/globals.css`
- Modify: `frontend/src/app/(dashboard)/layout.tsx`
- Test: `frontend/src/components/layout/dashboard-shell.test.tsx`

**Interfaces:**
- Produces `DashboardShell({ currentUser, children })` with menu filtering driven by `currentUser.menu_permissions`.
- Produces `Drawer({ open, title, children, onClose, footer })`.
- Produces no inline layout styles in dashboard routes.

- [ ] **Step 1: Write failing shell tests.**

Create `frontend/src/components/layout/dashboard-shell.test.tsx`:

```tsx
test("shows only menu entries allowed by menu permissions", () => {
  render(<DashboardShell currentUser={{ ...user, menu_permissions: ["user:read"] }}>body</DashboardShell>);
  expect(screen.getByRole("link", { name: "User Management" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Role Management" })).not.toBeInTheDocument();
});

test("opens the mobile navigation drawer", async () => {
  render(<DashboardShell currentUser={{ ...user, menu_permissions: ["user:read"] }}>body</DashboardShell>);
  await userEvent.click(screen.getByRole("button", { name: "Open navigation" }));
  expect(screen.getByRole("navigation")).toBeVisible();
});
```

- [ ] **Step 2: Verify shell tests fail.**

Run: `cd frontend; npm test -- --run src/components/layout/dashboard-shell.test.tsx`

Expected: FAIL with module-not-found errors for `DashboardShell`.

- [ ] **Step 3: Implement primitives and CSS token layer.**

Define CSS variables in `globals.css`:

```css
:root {
  --sidebar: #111827;
  --workspace: #f5f7fb;
  --surface: #ffffff;
  --primary: #4f46e5;
  --danger: #dc2626;
  --border: #e5e7eb;
  --text: #1f2937;
  --muted: #64748b;
}
```

Implement component variants using `className` composition rather than inline `style`. `Button` supports `primary`, `secondary`, `danger`, and `ghost`; `StatusTag` supports active and disabled; `Drawer` uses `role="dialog"`, Escape close, overlay close, and focusable close button.

- [ ] **Step 4: Implement responsive shell.**

`DashboardShell` renders a 240px desktop deep-blue-gray sidebar, active nav state, header breadcrumb/current user menu, and a collapsed mobile drawer. Use menu permission checks for User Management (`user:read`) and Role Management (`role:read`). Replace the current inline-styled dashboard layout with this shell.

- [ ] **Step 5: Run primitive and shell tests.**

Run: `cd frontend; npm test -- --run src/components/layout/dashboard-shell.test.tsx; npm run build`

Expected: tests PASS and Next.js build succeeds.

- [ ] **Step 6: Commit shared frontend foundation.**

```powershell
git add frontend/src/components/ui frontend/src/components/layout frontend/src/app/globals.css frontend/src/app/(dashboard)/layout.tsx
git commit -m "feat: add responsive enterprise admin shell"
```

## Task 7: Align Frontend API Client and Types with Enveloped Backend Contracts

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/types/auth.ts`
- Modify: `frontend/src/types/user.ts`
- Create: `frontend/src/types/role.ts`
- Modify: `frontend/src/lib/permissions.ts`
- Test: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces `api<T>() -> Promise<T>` that unwraps `{ data, message, request_id }`.
- Produces `ApiError` with optional `requestId`.
- Produces `RoleReference { id, code, name }`, `PermissionSummary`, `RoleDetail`, and typed `CurrentUser.menu_permissions`.

- [ ] **Step 1: Write failing envelope tests.**

Add to `frontend/src/lib/api.test.ts`:

```ts
test("unwraps a successful api envelope", async () => {
  global.fetch = vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ data: { username: "admin" }, message: "OK", request_id: "request-1" }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  ));
  await expect(api<{ username: string }>("/api/auth/me")).resolves.toEqual({ username: "admin" });
});

test("keeps request id on api errors", async () => {
  global.fetch = vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ code: "PERMISSION_DENIED", message: "Denied", details: null, request_id: "request-2" }),
    { status: 403, headers: { "Content-Type": "application/json" } },
  ));
  await expect(api("/api/roles")).rejects.toMatchObject({ requestId: "request-2" });
});
```

- [ ] **Step 2: Verify tests fail.**

Run: `cd frontend; npm test -- --run src/lib/api.test.ts`

Expected: FAIL because the current client returns the envelope instead of `data` and has no `requestId` field.

- [ ] **Step 3: Implement envelope support and DTOs.**

Add:

```ts
interface ApiEnvelope<T> {
  data: T;
  message: string;
  request_id: string;
}
```

For successful non-204 responses, parse `ApiEnvelope<T>` and return `body.data`. Add `requestId?: string` to `ApiError`; set it from `body.request_id` or `response.headers.get("X-Request-ID")`.

Define frontend types matching backend schemas exactly:

```ts
export interface RoleReference { id: string; code: string; name: string; }
export interface PermissionSummary { id: string; code: string; name: string; module: string; description: string | null; }
export interface UserListItem { id: string; username: string; display_name: string; email: string | null; phone: string | null; status: "active" | "disabled"; roles: RoleReference[]; created_at: string | null; }
export interface CurrentUser { id: string; username: string; display_name: string; roles: RoleReference[]; permissions: string[]; menu_permissions: string[]; assignable_roles?: RoleReference[]; }
```

- [ ] **Step 4: Update all existing auth/user type consumers.**

Replace `role_ids` usages with `roles`. Replace implicit `roles?: string[]` assumptions with `RoleReference[]`. Update mocked responses in current frontend tests to use envelopes and role references.

- [ ] **Step 5: Run frontend contract regression.**

Run: `cd frontend; npm test -- --run; npm run build`

Expected: all current tests PASS against the envelope and typed-role contract.

- [ ] **Step 6: Commit contract alignment.**

```powershell
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts frontend/src/types frontend/src/lib/permissions.ts frontend/src/components frontend/src/app
git commit -m "feat: align frontend with typed api envelopes"
```

## Task 8: Productize the Login and User Management Experience

**Files:**
- Modify: `frontend/src/app/(auth)/login/page.tsx`
- Modify: `frontend/src/components/auth/login-form.tsx`
- Modify: `frontend/src/components/users/user-filters.tsx`
- Modify: `frontend/src/components/users/user-table.tsx`
- Create: `frontend/src/components/users/user-drawer.tsx`
- Modify: `frontend/src/components/users/user-management.tsx`
- Modify: `frontend/src/components/users/password-reset-dialog.tsx`
- Test: `frontend/src/components/auth/login-form.test.tsx`
- Test: `frontend/src/components/users/user-management.test.tsx`
- Test: `frontend/src/components/users/user-drawer.test.tsx`

**Interfaces:**
- Uses `RoleReference` tags in user lists and `Drawer` for create/edit user workflows.
- Displays at most two role tags plus `+N` with the full role names in `title`.

- [ ] **Step 1: Write failing role-tag and drawer tests.**

Create `frontend/src/components/users/user-drawer.test.tsx`:

```tsx
test("renders role names rather than role identifiers", async () => {
  render(<UserTable users={[{ ...user, roles: [{ id: "r1", code: "user_manager", name: "User Manager" }] }]} currentUser={admin} {...handlers} />);
  expect(screen.getByText("User Manager")).toBeVisible();
  expect(screen.queryByText("r1")).not.toBeInTheDocument();
});

test("shows only two role tags and an overflow count", () => {
  render(<UserTable users={[{ ...user, roles: threeRoles }]} currentUser={admin} {...handlers} />);
  expect(screen.getByText("+1")).toHaveAttribute("title", "Role One, Role Two, Role Three");
});
```

- [ ] **Step 2: Verify tests fail.**

Run: `cd frontend; npm test -- --run src/components/users/user-drawer.test.tsx`

Expected: FAIL because the current table renders `role_ids`.

- [ ] **Step 3: Rebuild login presentation.**

Build a desktop two-column login page: restrained brand narrative panel at >=960px and a compact 400px card. On smaller screens hide the brand panel and center the card. Preserve labels, generic invalid-credential text, loading, disabled inputs, and `/users` navigation after successful login. Do not use gradients.

- [ ] **Step 4: Rebuild the user list and filters.**

Use the shared `PageHeader`, `Button`, `Input`, `Select`, `StatusTag`, `Skeleton`, and `EmptyState` primitives. Implement a white filter surface with keyword/status/role/query/reset controls. Render role names as tags. Maintain mobile horizontal table scroll. Provide skeleton rows during initial and filter loads, a retryable inline error state, and a create-user CTA in the empty state.

- [ ] **Step 5: Replace create/edit modal with user drawer.**

`UserDrawer` provides username (creation only), display name, email, phone, state (creation only), roles when allowed, and initial password (creation only). It must:

- Require an 8+ character password containing a letter and digit.
- Use `assignable_roles` role objects in the multi-select.
- Hide role selection without `user:assign_role`.
- Submit `POST /api/users` or `PUT /api/users/{id}`.
- Present `400`, `403`, `404`, `409`, and `422` errors in the drawer.
- Refresh the current user page and close only on successful mutation.

- [ ] **Step 6: Run user UI verification.**

Run: `cd frontend; npm test -- --run src/components/auth/login-form.test.tsx src/components/users/user-management.test.tsx src/components/users/user-drawer.test.tsx; npm run build`

Expected: PASS and build succeeds.

- [ ] **Step 7: Commit user experience upgrade.**

```powershell
git add frontend/src/app/(auth) frontend/src/components/auth frontend/src/components/users frontend/src/app/globals.css
git commit -m "feat: productize login and user management ui"
```

## Task 9: Build Role Management and Grouped Permission Assignment UI

**Files:**
- Create: `frontend/src/components/roles/role-filters.tsx`
- Create: `frontend/src/components/roles/role-table.tsx`
- Create: `frontend/src/components/roles/permission-tree.tsx`
- Create: `frontend/src/components/roles/role-drawer.tsx`
- Create: `frontend/src/components/roles/role-management.tsx`
- Modify: `frontend/src/app/(dashboard)/roles/page.tsx`
- Create: `frontend/src/components/roles/role-management.test.tsx`
- Create: `frontend/src/components/roles/permission-tree.test.tsx`

**Interfaces:**
- Uses `GET /api/roles`, `GET /api/permissions`, and role mutation APIs through `api<T>()`.
- Produces a permission tree grouped by `PermissionSummary.module`.

- [ ] **Step 1: Write failing permission tree tests.**

Create `frontend/src/components/roles/permission-tree.test.tsx`:

```tsx
test("checks and unchecks every child in a module", async () => {
  render(<PermissionTree permissions={permissions} selectedIds={[]} onChange={onChange} readOnly={false} />);
  await userEvent.click(screen.getByRole("checkbox", { name: "User Management" }));
  expect(onChange).toHaveBeenCalledWith(["p1", "p2"]);
});

test("shows a read-only super admin permission tree", () => {
  render(<PermissionTree permissions={permissions} selectedIds={["p1", "p2"]} onChange={onChange} readOnly />);
  expect(screen.getByRole("checkbox", { name: "User Management" })).toBeDisabled();
});
```

- [ ] **Step 2: Verify permission tree tests fail.**

Run: `cd frontend; npm test -- --run src/components/roles/permission-tree.test.tsx`

Expected: FAIL with module-not-found errors for `PermissionTree`.

- [ ] **Step 3: Implement role list.**

Implement keyword/status filters, `RoleTable`, page controls, skeleton, empty state, and error retry. Table columns are code, name, permission count, state, system marker, and actions. Render system role marker for `is_system=true`. Gate visible actions by exact `role:*` permissions.

- [ ] **Step 4: Implement grouped permission tree.**

Group permissions by module label: `user` -> User Management, `role` -> Role Management, all other modules -> System Management. Implement group checked/unchecked/indeterminate state, child checkboxes, and stable sort by `module`, `sort_order`, and name. Never display raw permission IDs; display name and optional description.

- [ ] **Step 5: Implement role drawer and system role safeguards.**

For normal roles, show editable code only on create, editable name/description, state control, permission tree, and permission-change summary calculated from original/selected IDs. For `super_admin`, disable state and permission inputs, hide delete/status actions in table, and show: `System role: all active permissions are assigned automatically.` The drawer only submits name/description for the system role.

- [ ] **Step 6: Implement destructive role workflows.**

Before deleting a role, request role detail to read `assigned_user_count`, then show: `Deleting this role will remove it from N users.` Confirm invokes `DELETE /api/roles/{id}`. Status control invokes `PATCH /api/roles/{id}/status`. Surface backend `SYSTEM_ROLE_IMMUTABLE`, `DUPLICATE_VALUE`, and authorization errors.

- [ ] **Step 7: Run role UI verification.**

Run: `cd frontend; npm test -- --run src/components/roles/role-management.test.tsx src/components/roles/permission-tree.test.tsx; npm run build`

Expected: PASS and route `/roles` builds.

- [ ] **Step 8: Commit role management UI.**

```powershell
git add frontend/src/components/roles frontend/src/app/(dashboard)/roles/page.tsx frontend/src/app/globals.css
git commit -m "feat: add role management and permission assignment ui"
```

## Task 10: Contract Verification, Responsive QA, and Documentation

**Files:**
- Modify: `backend/tests/test_rbac_end_to_end.py`
- Create: `backend/tests/test_contracts.py`
- Modify: `README.md`
- Modify: `frontend/README.md`

**Interfaces:**
- Produces regression evidence for envelope, role DTO, permission refresh, and protected system role behavior.
- Documents PostgreSQL migration and startup exactly for Conda/PyCharm backend and npm/VS Code frontend usage.

- [ ] **Step 1: Write failing cross-contract regression tests.**

Create `backend/tests/test_contracts.py`:

```python
async def test_user_and_me_contracts_return_role_summary_objects(admin_client) -> None:
    me = await admin_client.get("/api/auth/me")
    assert me.status_code == 200
    assert {"id", "code", "name"} <= set(me.json()["data"]["roles"][0])

    users = await admin_client.get("/api/users")
    assert users.status_code == 200
    assert "request_id" in users.json()
    assert users.headers["X-Request-ID"] == users.json()["request_id"]
```

- [ ] **Step 2: Verify tests fail before final contract fixes.**

Run: `cd backend; python -m pytest tests/test_contracts.py -v`

Expected: FAIL until every upgraded endpoint uses the documented envelope and role summary DTOs.

- [ ] **Step 3: Add final end-to-end authorization cases.**

Extend `test_rbac_end_to_end.py` with:

```python
async def test_disabled_role_stops_contributing_permission_on_next_request(role_user_client, admin_client, role) -> None:
    before = await role_user_client.get("/api/roles")
    assert before.status_code == 200
    changed = await admin_client.patch(f"/api/roles/{role.id}/status", json={"status": "disabled"})
    assert changed.status_code == 200
    after = await role_user_client.get("/api/roles")
    assert after.status_code == 403
```

- [ ] **Step 4: Run complete backend verification.**

Run: `cd backend; python -m pytest -v`

Expected: zero failures, including role CRUD, `super_admin` immutability, role disablement, role deletion cleanup, envelopes, and existing user/auth behavior.

- [ ] **Step 5: Run complete frontend verification.**

Run: `cd frontend; npm test -- --run; npm run build`

Expected: zero failures and a build containing `/login`, `/users`, and `/roles` routes.

- [ ] **Step 6: Perform responsive and role-based manual acceptance.**

Verify at 1440px and 390px widths:

1. Super admin sees both menus, creates a role, assigns permissions, creates a user with that role, and observes role-name tags in user list.
2. Super admin can edit only name/description of `super_admin`; its state and permission controls are read-only and delete action is absent.
3. User manager cannot see `/roles`; direct role API requests return `403`.
4. A user with a role-management role can manage roles but cannot reset another user's password or delete users.
5. Disabling/deleting an ordinary role removes its effective permission on the user's next protected request.
6. The mobile navigation opens/closes, tables remain usable with horizontal scroll, and drawers fit inside viewport.

- [ ] **Step 7: Update operational documentation.**

README must document:

```powershell
cd X:\01_RBAC\backend
Copy-Item ../.env .env
python -m pip install -r requirements.txt
alembic current -v
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

And in a second terminal:

```powershell
cd X:\01_RBAC\frontend
npm install
npm run dev
```

Document `admin / ChangeMe-Strong1` as development-only seed credentials, `http://localhost:3000`, `http://localhost:8000/docs`, all role APIs, `super_admin` protection, and the warning to inspect migration state rather than delete `alembic_version` in databases containing real data.

- [ ] **Step 8: Commit final verification and documentation.**

```powershell
git add backend/tests README.md frontend/README.md
git commit -m "docs: complete product rbac upgrade verification"
```

## Plan Self-Review

### Spec Coverage

- Five-table normalized RBAC retained, metadata added, migration backfill, seed synchronization, and protected `super_admin`: Tasks 2 and 4.
- Full role CRUD, permissions, state, deletion association cleanup, and effective-permission refresh: Task 4 and Task 10.
- Typed role summaries, conditional assignable roles, no raw UUID display, and N+1 user-role fix: Task 5.
- Success/error envelopes, Request ID header/body, and request logging: Task 3.
- Dark-sidebar/light-content system, responsive shell, reusable primitives, product login, user page, role page, drawers, dialogs, status tags, permission tree: Tasks 6, 8, and 9.
- Local Alembic configuration, IDE ignore, migration safety, tests, responsive manual checks, and documentation: Tasks 1 and 10.

### Consistency Check

- User/auth role references are `RoleReference { id, code, name }`; the same type is defined and consumed in Tasks 5, 7, and 8. Role-management endpoints use richer `RoleSummary`/`RoleDetail` DTOs from Task 4.
- Every successful non-204 route is unwrapped through `api<T>()` in Task 7, while `204` remains `undefined`.
- `super_admin` is immutable in status/permissions/deletion at data, API, and UI levels in Tasks 2, 4, and 9.
- User role assignment and role permission assignment use underscore permission codes consistently: `user:assign_role` and `role:assign_permission`.
- No task asks to replace cookie authentication, the async ORM, or the normalized association tables.
