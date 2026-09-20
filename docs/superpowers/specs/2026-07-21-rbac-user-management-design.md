# Simple RBAC System Design

## 1. Goal and Scope

Build a small, extensible administration system using Next.js, FastAPI, and PostgreSQL. The system uses classic RBAC: users receive roles, roles receive permissions, and permissions govern API access and frontend action visibility.

The product surface contains three pages:

- Login page
- User management page
- Role management page

The first implementation phase delivers the complete login and user-management path. The role-management page exists as a route and basic shell only; its CRUD and permission-assignment behavior is intentionally deferred.

User management includes:

- Paginated user search with keyword, status, and role filters
- User creation and editing
- Role assignment during user creation and editing
- Enable or disable accounts
- Password reset
- Soft deletion

The first phase has exactly nine HTTP endpoints: three authentication endpoints and six user-management endpoints.

## 2. Technology Decisions

| Area | Decision |
| --- | --- |
| Frontend | Next.js with App Router and TypeScript |
| Backend | FastAPI, SQLAlchemy ORM, and Pydantic schemas |
| Database | PostgreSQL |
| Database migrations | Alembic |
| Authentication | Short-lived JWT in an HttpOnly cookie |
| Password hashing | Argon2 |
| Authorization | Backend API permission enforcement; frontend action-level visibility |
| Test tools | pytest/httpx for backend; Vitest/React Testing Library for frontend; Playwright optional later |

## 3. Architecture and Request Flow

The frontend is responsible for pages, forms, user feedback, and non-security UI permission checks. FastAPI is the security boundary: every protected request resolves the JWT subject, validates that the account remains enabled, loads the current permission set, and rejects missing permissions. PostgreSQL stores users, roles, permissions, and associations.

1. The user submits credentials on `/login`.
2. `POST /api/auth/login` validates credentials and active account status.
3. On success, FastAPI creates a JWT and sets it in an HttpOnly, `SameSite=Lax`, `Path=/` cookie. Production deployments add `Secure`.
4. The frontend requests `GET /api/auth/me` on protected page entry to obtain the current user, roles, and permission codes.
5. The frontend hides inaccessible menus and actions based on returned codes.
6. Protected FastAPI endpoints independently validate JWT, current status, and endpoint permissions. A hidden frontend button is never a security control.
7. Logout clears the cookie. A missing, expired, or invalid token returns `401`; the frontend redirects to `/login`.

The JWT contains only `sub` (user UUID), `username`, `iat`, and `exp`. It does not contain roles or permissions. The backend reads current database state per protected request so disabling an account or changing a role is immediately effective.

## 4. RBAC Data Model

Use five core tables.

| Table | Purpose | Principal fields and constraints |
| --- | --- | --- |
| `users` | Login accounts | UUID primary key; unique `username`; `display_name`; password hash; optional unique email and phone; `status`; `is_deleted`; timestamps |
| `roles` | Named role definitions | UUID primary key; unique `code`; unique name; description; status; timestamps |
| `permissions` | Stable action permissions | UUID primary key; unique `code`; name; module; description |
| `user_roles` | User-to-role mapping | `user_id`, `role_id`; composite primary key or unique constraint; both foreign keys |
| `role_permissions` | Role-to-permission mapping | `role_id`, `permission_id`; composite primary key or unique constraint; both foreign keys |

All IDs are application-generated UUIDs, avoiding a PostgreSQL UUID extension requirement. Foreign keys protect referential integrity. Soft deletion is used for users (`is_deleted = true`) so records are retained; normal queries exclude deleted accounts.

Security and integrity rules:

- A disabled or deleted account cannot authenticate or access protected APIs.
- Usernames are unique among all stored records and are not reused after soft deletion in phase one.
- The operator cannot delete or disable their own account.
- The system cannot delete, disable, or remove the final active `super_admin` account's super-administrator role.
- Passwords never leave the backend as plaintext or hash values.

## 5. Seed Data and Permissions

The initial seed creates a first super administrator, two active roles, and the permissions below. Credentials are supplied through environment configuration or a documented safe development default; production startup must require an explicit value.

| Role code | Name | Purpose |
| --- | --- | --- |
| `super_admin` | Super Administrator | Has every permission and initializes the system |
| `user_manager` | User Manager | Has all first-phase user-management permissions |

| Permission code | Meaning |
| --- | --- |
| `user:read` | View and search users |
| `user:create` | Create a user |
| `user:update` | Edit base user data |
| `user:delete` | Soft-delete a user |
| `user:status` | Enable or disable a user |
| `user:reset_password` | Reset a user's password |
| `user:assign_role` | Assign or replace a user's roles |
| `role:read` | View role data and enter the role page |

`super_admin` has all permissions. `user_manager` has every `user:*` permission listed above. Changes to roles inside the user create or update request require `user:assign_role` in addition to the primary create or update permission.

## 6. API Contract

All APIs are prefixed with `/api`. The nine first-phase endpoints are:

| # | Endpoint | Access rule | Description |
| --- | --- | --- | --- |
| 1 | `POST /api/auth/login` | Public | Validate credentials and set the JWT cookie |
| 2 | `POST /api/auth/logout` | Authenticated | Clear the authentication cookie |
| 3 | `GET /api/auth/me` | Authenticated | Return current user details, role codes, and permission codes |
| 4 | `GET /api/users` | `user:read` | Paginated list with keyword, status, and role filters |
| 5 | `POST /api/users` | `user:create`; `user:assign_role` when roles supplied | Create user and initial role mappings in one transaction |
| 6 | `PUT /api/users/{id}` | `user:update`; `user:assign_role` when roles change | Update user profile and role mappings atomically; status is changed only through endpoint 8 |
| 7 | `DELETE /api/users/{id}` | `user:delete` | Soft-delete a user subject to protected-account rules |
| 8 | `PATCH /api/users/{id}/status` | `user:status` | Enable or disable a user subject to protected-account rules |
| 9 | `POST /api/users/{id}/reset-password` | `user:reset_password` | Validate and replace the target password hash |

Role assignment remains inside the create and update endpoints to preserve the nine-endpoint constraint. `GET /api/auth/me` returns the current user's profile, role codes, and permission codes. When the caller has `user:assign_role`, it additionally returns the active roles they may assign (`assignable_roles`, with UUID, code, and name). This supplies the user-management role filter and multi-select without a tenth endpoint. Unauthorized callers never receive this collection.

## 7. API Errors and Validation

Error responses use a stable envelope:

```json
{
  "code": "USER_NOT_FOUND",
  "message": "User not found",
  "details": null
}
```

| Condition | HTTP status | Frontend behavior |
| --- | --- | --- |
| Missing, expired, or invalid authentication | `401` | Clear page auth state and redirect to `/login` |
| Valid login but missing required permission | `403` | Show a no-permission message; do not render the action initially |
| Missing or soft-deleted target user | `404` | Notify user and refresh the list |
| Duplicate username, email, or phone | `409` | Show field-level conflict feedback |
| Invalid input or password policy violation | `422` | Display form validation errors |
| Forbidden self-operation or final-super-admin operation | `400` | Display explicit business-rule message |
| Unexpected error | `500` | Show generic failure; log full context server-side |

Passwords must be at least eight characters and contain both letters and digits. Login failures always use the same message, such as "Invalid username or password", so account existence is not disclosed.

## 8. Frontend Pages

### Login (`/login`)

Contains username and password fields, submit loading state, validation feedback, and a generic invalid-credential message. On success, navigates to `/users`.

### User Management (`/users`)

Contains a keyword filter (username, display name, email), status filter, role filter, query/reset actions, paginated user table, and action controls. The table displays username, display name, contact data, assigned roles, status, creation time, and actions. User creation and editing use a dialog that collects profile fields, password on creation, state, and roles. Reset password and deletion require separate confirmation dialogs.

Buttons are rendered only when the current permissions allow them: create, update, status change, password reset, and delete. The role filter and role multi-select are available only when role data is supplied to an authorized user.

### Role Management (`/roles`)

Provides the route, dashboard layout integration, and a basic read-only or placeholder state in phase one. Full role CRUD and permission assignment are phase-two work.

## 9. Repository Layout

```text
01_RBAC/
├─ frontend/
│  ├─ app/
│  │  ├─ (auth)/login/page.tsx
│  │  ├─ (dashboard)/layout.tsx
│  │  ├─ (dashboard)/users/page.tsx
│  │  └─ (dashboard)/roles/page.tsx
│  ├─ components/
│  │  ├─ auth/
│  │  ├─ users/
│  │  └─ ui/
│  ├─ lib/
│  │  ├─ api.ts
│  │  ├─ auth.ts
│  │  └─ permissions.ts
│  └─ types/
├─ backend/
│  ├─ app/
│  │  ├─ api/
│  │  ├─ core/
│  │  ├─ db/
│  │  ├─ models/
│  │  ├─ schemas/
│  │  ├─ services/
│  │  └─ main.py
│  ├─ alembic/
│  └─ tests/
├─ docker-compose.yml
├─ .env.example
├─ README.md
└─ rbac-diagrams.html
```

API modules parse requests and format responses. Services enforce business rules and transactions. Models define SQLAlchemy persistence. Schemas define Pydantic request and response types. Core dependencies centralize current-user resolution and permission checks.

## 10. Testing and Acceptance

Backend tests cover successful and failed login, disabled-user login, expired JWT, unauthenticated access (`401`), permission denial (`403`), all six user endpoints, duplicate data conflicts, password policy, role validation, and protected-account rules. Tests also verify that current permission resolution reflects role changes.

Frontend tests cover login routing and failure handling, protected page redirect, list filters and pagination, permission-driven button visibility, form validation, API error rendering, and state refresh after actions. A later Playwright suite may cover login through each user-management operation.

Manual acceptance uses three identities: super administrator, user manager, and a user with no user-management permissions.

## 11. Delivery Sequence

1. Bootstrap frontend/backend, Docker Compose PostgreSQL, environment templates, migrations, CORS, configuration, and logging.
2. Add tables, models, migrations, and seed data for users, roles, permissions, and associations.
3. Implement authentication, JWT cookie handling, current-user and permission dependencies, login page, dashboard layout, and shared API client.
4. Implement all user-management services and endpoints with tests.
5. Implement the user-management page, forms, permission-aware actions, and frontend tests.
6. Perform integration testing, manual role-based acceptance, and document installation, seed credentials, testing, and API use in README.

## 12. Visual Reference

`rbac-diagrams.html` is a browser-rendered Mermaid reference containing six diagrams: authentication and authorization flow, page map, user operation flow, user-management layout, service/API relationship, and endpoint-permission mapping.
