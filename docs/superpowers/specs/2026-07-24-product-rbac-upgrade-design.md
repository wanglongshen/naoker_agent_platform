# Product RBAC Upgrade Design

## 1. Purpose

Upgrade the current simple RBAC system into a product-quality administration console. The target is an enterprise administration experience with a dark navigation sidebar, a light work area, complete role management, grouped permission assignment, and a stable backend contract.

The reference repository at `X:\01_nextjs-fastapi-admin\nextjs-fastapi-admin` is used as an engineering reference, not as a source to copy directly. It currently contains a backend framework only; it does not contain a committed Next.js administration UI. Its useful patterns are module boundaries, user/role domain separation, a shared permission dependency, seed data, common response models, and framework documentation.

## 2. Chosen Approach

Use a product RBAC upgrade, not a visual-only reskin and not a full backend framework rewrite.

- Retain the current async FastAPI, PostgreSQL, and standard five-table many-to-many RBAC model.
- Add complete role CRUD, role state management, and permission assignment.
- Rebuild the administration UI around a cohesive enterprise visual system.
- Improve API DTOs, query efficiency, error handling, and observability without replacing working authentication or authorization primitives.
- Incrementally adopt useful patterns from the reference system without copying its single-role JSON-permission model or Header Bearer authentication.

## 3. Reference Analysis

### 3.1 Patterns to Adopt

The reference backend provides these patterns worth adopting:

- Explicit user and role domain boundaries.
- Thin API handlers and service-owned business rules.
- Central permission dependency (`PermissionChecker`).
- Idempotent initial role and administrator seed data.
- Common page and response concepts.
- Request logging, Request ID, documentation, release, and migration discipline.

### 3.2 Patterns Not to Adopt

Do not regress to these reference implementation choices:

- One user assigned to one role via `role_id`.
- Role permissions stored as a JSON array instead of normalized associations.
- Administrator identity based solely on an integer role ID.
- Header Bearer token authentication for the browser administration UI.
- Automatic `Base.metadata.create_all()` as the production schema migration mechanism.

### 3.3 Current-System Advantages to Preserve

The current system is a better RBAC base because it has:

- Normalized `users`, `roles`, `permissions`, `user_roles`, and `role_permissions` tables.
- Multiple roles per user and multiple permissions per role.
- UUID identifiers.
- HttpOnly JWT cookie authentication.
- Database-backed permission resolution on protected requests.
- Account enable/disable, soft deletion, reset password, and final-super-admin protection.

## 4. Product Scope

This upgrade delivers:

- A redesigned login page.
- A dark-sidebar/light-content administration shell.
- Product-quality user management.
- Complete role list, create, edit, enable/disable, delete, and permission assignment flows.
- Role names instead of UUIDs in user-facing views.
- Role filtering in user management.
- System role protection for `super_admin`.
- Unified API errors and Request ID observability.

This upgrade does not deliver:

- Audit-log user interface or persistent audit tables.
- Menu configuration tables.
- Organization hierarchy, tenant isolation, or data-scope authorization.
- Theme switching, internationalization, dashboards, or charts.

## 5. RBAC Model

Keep the five core tables and relations:

```text
users --< user_roles >-- roles --< role_permissions >-- permissions
```

Add fields through a new Alembic migration:

| Table | Field | Reason |
| --- | --- | --- |
| `roles` | `is_system: bool` | Identifies protected built-in roles. |
| `roles` | `is_deleted: bool` | Supports soft deletion without losing historical relations. |
| `roles` | `sort_order: int` | Stable role list order and future menu ordering. |
| `permissions` | `module: str` | Groups permissions into user, role, and future system sections. |
| `permissions` | `sort_order: int` | Stable permission tree ordering. |
| `permissions` | `is_system: bool` | Protects seeded permissions from removal. |

Existing fields remain valid. User deletion continues to use `users.is_deleted`.

## 6. System Role Rules

`super_admin` is a protected built-in system role.

- Its code is immutable.
- Its active state is immutable; it cannot be disabled.
- It cannot be deleted.
- Its permission set is immutable in the role editor and always includes every active system permission.
- Its name and description are editable.
- Every newly seeded active permission is attached to `super_admin` automatically.
- The system must always retain at least one active, non-deleted user assigned to `super_admin`.
- User deletion, user disablement, and user role replacement must enforce the final-super-admin rule transactionally.

For normal roles:

- Role codes are immutable after creation.
- Code and name are unique among non-deleted roles.
- Disabled roles cannot be assigned to a user.
- Disabled roles do not contribute permissions during authorization.
- Deleting a role soft-deletes it and removes its `user_roles` and `role_permissions` associations in the same transaction.

## 7. Permission Set

Retain user permissions:

```text
user:read
user:create
user:update
user:delete
user:status
user:reset_password
user:assign_role
```

Add role permissions:

```text
role:read
role:create
role:update
role:delete
role:status
role:assign_permission
```

Permissions are grouped by `permissions.module`:

| Module | Permissions |
| --- | --- |
| `user` | All `user:*` permissions. |
| `role` | All `role:*` permissions. |
| `system` | Reserved for later audit, menu, and configuration permissions. |

`user_manager` retains user management permissions and does not receive role management permissions by default.

## 8. API Contract

Authentication endpoints remain:

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

`GET /api/auth/me` returns current user profile, typed role summaries, effective permission codes, menu permission codes, and `assignable_roles` only when the caller has `user:assign_role`.

```json
{
  "data": {
    "id": "uuid",
    "username": "admin",
    "display_name": "System Administrator",
    "roles": [{ "id": "uuid", "code": "super_admin", "name": "Super Administrator" }],
    "permissions": ["user:read", "role:read"],
    "menu_permissions": ["user:read", "role:read"],
    "assignable_roles": []
  },
  "message": "OK",
  "request_id": "request-id"
}
```

User endpoints become:

```text
GET    /api/users
GET    /api/users/{id}
POST   /api/users
PUT    /api/users/{id}
PATCH  /api/users/{id}/status
POST   /api/users/{id}/reset-password
DELETE /api/users/{id}
```

User list/detail DTOs return role summaries, never raw role UUIDs as display data:

```json
{
  "id": "uuid",
  "username": "lisa",
  "display_name": "Lisa Chen",
  "email": "lisa@example.com",
  "phone": "13800000000",
  "status": "active",
  "roles": [{ "id": "uuid", "code": "user_manager", "name": "User Manager" }],
  "created_at": "2026-07-24T10:00:00+00:00"
}
```

Add role and permission endpoints:

```text
GET    /api/roles
GET    /api/roles/{id}
POST   /api/roles
PUT    /api/roles/{id}
PATCH  /api/roles/{id}/status
DELETE /api/roles/{id}
GET    /api/permissions
```

Role create/update input uses:

```json
{
  "code": "content_manager",
  "name": "Content Manager",
  "description": "Manages content and can read users.",
  "permission_ids": ["uuid-1", "uuid-2"]
}
```

Required authorization:

| Operation | Required permission |
| --- | --- |
| View role list/detail/permission dictionary | `role:read` |
| Create role | `role:create` |
| Update ordinary role name/description | `role:update` |
| Assign ordinary role permissions | `role:assign_permission` |
| Change ordinary role state | `role:status` |
| Delete ordinary role | `role:delete` |

Creating a role with permissions requires both `role:create` and `role:assign_permission`. Editing `super_admin` only accepts name and description; attempts to change code, state, or permissions return `400`.

## 9. Error and Observability Contract

Successful non-204 responses use:

```json
{
  "data": {},
  "message": "OK",
  "request_id": "request-id"
}
```

Failures use:

```json
{
  "code": "PERMISSION_DENIED",
  "message": "Missing permission: role:update",
  "details": null,
  "request_id": "request-id"
}
```

Request middleware must:

- Generate or forward `X-Request-ID`.
- Include it in response headers and JSON error/success bodies.
- Log request method, route, status, elapsed time, authenticated user ID when available, and request ID.

The existing HTTP semantics remain: `200`, `201`, `204`, `400`, `401`, `403`, `404`, `409`, `422`, and `500` retain their normal meaning.

## 10. Query and Service Design

The user list must replace its current per-user role lookup with one page-level role query.

1. Query the requested user page.
2. Query all role summaries for those user IDs with one join through `user_roles`.
3. Group role DTOs by user ID in memory.
4. Return active, non-deleted role summaries only.

Role filtering uses an `EXISTS` subquery to avoid duplicate users.

Backend boundaries:

```text
api/          HTTP parsing, dependencies, status codes
services/     transactions and RBAC business rules
schemas/      Pydantic input/output DTOs
models/       SQLAlchemy persistence relations
core/         security, dependencies, middleware, logs, errors
db/           sessions and seed logic
```

The upgrade is incremental. It does not replace the current async SQLAlchemy architecture with the reference repository's synchronous repository framework.

## 11. Visual System

The UI adopts an enterprise dark-sidebar/light-content system.

| Token | Direction |
| --- | --- |
| Sidebar | Deep blue-gray `#111827` with subdued text and an active indicator. |
| Work area | Light gray-blue `#f5f7fb`. |
| Surfaces | White cards, restrained borders, limited shadows. |
| Primary action | Indigo `#4f46e5`. |
| Success | Green status tags. |
| Inactive | Neutral gray status tags. |
| Danger | Red deletion actions only. |
| Spacing | Compact, information-dense administrative layout. |
| Corners | 10px cards, 6px controls. |

Avoid gradients, emoji icons, UUID display, oversized whitespace, overly rounded cards, and raw browser controls.

## 12. Frontend Architecture

Create or consolidate components around clear responsibilities:

```text
components/
  layout/
    app-sidebar.tsx
    app-header.tsx
    page-header.tsx
    dashboard-shell.tsx
  ui/
    button.tsx
    input.tsx
    select.tsx
    dialog.tsx
    drawer.tsx
    data-table.tsx
    status-tag.tsx
    empty-state.tsx
    skeleton.tsx
  users/
    user-table.tsx
    user-filters.tsx
    user-drawer.tsx
    reset-password-dialog.tsx
  roles/
    role-table.tsx
    role-filters.tsx
    role-drawer.tsx
    permission-tree.tsx
```

Use CSS variables plus modular or structured styles. Eliminate scattered inline styles. Do not introduce a heavy UI library in this phase.

## 13. Pages and Interactions

### Login

- Desktop: quiet brand panel plus a compact login card.
- Mobile: centered login card only.
- Fields have default, focus, disabled, loading, and error states.
- Login failure remains generic: "Invalid username or password".

### Dashboard Shell

- Fixed 240px dark sidebar on desktop and collapsible drawer on narrow screens.
- Menu visibility derives from `menu_permissions`.
- Header shows breadcrumb and current user menu.
- Sidebar contains User Management and Role Management during this release.

### User Management

- Filter card: keyword, status, role, query, and reset.
- Data table: username, display name, contact, role-name tags, status tag, date, and action buttons.
- At most two visible role tags; extra roles display `+N` with full names available on hover/focus.
- Loading uses table skeletons; empty and error states use dedicated components.
- Create/edit uses a right-side drawer, preserving table context.
- Password reset and destructive operations use focused dialogs.

### Role Management

- List: code, name, permission count, state, system-role marker, and actions.
- Create/edit uses a right-side drawer.
- Permission tree groups permissions by module with checked, unchecked, and indeterminate group state.
- Before saving, display a permission change summary.
- `super_admin` permission controls and state controls are read-only; only name and description can be saved.
- Deleting an ordinary role warns how many user bindings will be removed.

## 14. Migration and Seed Plan

One Alembic revision:

1. Add role and permission metadata fields.
2. Mark `super_admin` as `is_system=true`.
3. Mark existing records active/non-deleted and assign default sort orders.
4. Backfill permission modules from `user:*` and `role:*` prefixes.
5. Seed new `role:*` permission records idempotently.
6. Attach every active permission to `super_admin`.
7. Keep migrations reversible without deleting user or role records.

Before any upgrade work, reconcile the local `alembic_version` state with actual tables. Do not delete migration metadata in environments containing real data without an explicit backup and inspection procedure.

## 15. Verification

Backend tests must cover:

- Role CRUD and all role permission guards.
- Role state effects on assignment and effective authorization.
- Role deletion association cleanup.
- Immutable `super_admin` state and permissions.
- Final super-admin user protection.
- Role DTOs in user lists and no N+1 behavior regression.
- `/api/auth/me` typed roles, permissions, and conditional assignable roles.
- Response envelopes and `X-Request-ID`.

Frontend tests must cover:

- Menu filtering from permissions.
- User role tags and role filtering.
- User drawer validation and role assignment visibility.
- Role list, role drawer, permission tree states, system-role safeguards, and delete confirmation.
- Error, empty, loading, and mobile navigation states.

Manual acceptance identities:

| Identity | Expected outcome |
| --- | --- |
| Super administrator | Manages users and ordinary roles; only name/description can change for the system role. |
| User manager | Manages allowed user actions but cannot see or call role management. |
| Role manager | Manages allowed roles but cannot perform user password/reset/delete actions. |
| Unprivileged user | Sees no management menu and receives `403` for protected APIs. |

## 16. Delivery Order

1. Stabilize local configuration: Alembic `.env` loading, migration-state documentation, and ignore IDE workspace files.
2. Add migration, seed upgrades, role service, role APIs, role schemas, Request ID, and tests.
3. Upgrade user DTOs and batch role queries.
4. Build the shared visual foundation and administration shell.
5. Productize user management on the new APIs.
6. Build role management and permission assignment UI.
7. Run API contract, unit, integration, responsive, and manual role-based acceptance checks.

## 17. Risks and Controls

| Risk | Control |
| --- | --- |
| Incorrect local migration state | Inspect actual tables and version metadata before upgrades; do not destroy non-empty databases. |
| RBAC regression | Test system-role immutability, role disablement, deletion, and final-super-admin protection independently. |
| Frontend/backend drift | Treat Pydantic DTOs as contracts and add boundary tests for critical payloads. |
| Role deletion impacts users | Count affected users, show warning, and clean associations transactionally. |
| UI rewrite breaks behavior | Stabilize DTOs before component rewrites and retain component coverage for each workflow. |
| Scope creep | Keep this release to login, user, and role flows; defer audit, menus, organizations, and tenancy. |
