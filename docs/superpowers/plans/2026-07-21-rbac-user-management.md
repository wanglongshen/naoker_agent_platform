# RBAC User Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable phase of a simple RBAC administration system: JWT-cookie login and permission-protected user management with role assignment.

**Architecture:** Next.js App Router renders the login, protected dashboard, user-management, and role-placeholder pages. FastAPI owns authentication, authorization, input validation, business rules, and SQLAlchemy transactions. PostgreSQL stores five RBAC tables; JWTs identify a user only, and every protected API request reloads active account status and permissions from the database.

**Tech Stack:** Next.js + TypeScript, FastAPI, SQLAlchemy 2 async ORM, Pydantic v2, Alembic, PostgreSQL 16, Argon2, python-jose, pytest/httpx, Vitest, React Testing Library.

## Global Constraints

- Use `Next.js App Router` and TypeScript for the frontend.
- Use `FastAPI`, SQLAlchemy async ORM, Pydantic schemas, Alembic, and PostgreSQL for the backend.
- Keep exactly nine first-phase HTTP endpoints: three auth endpoints and six user endpoints.
- Authentication uses a short-lived JWT in an `HttpOnly`, `SameSite=Lax`, `Path=/` cookie; production sets `Secure`.
- JWT claims are exactly `sub`, `username`, `iat`, and `exp`; roles and permissions are read from PostgreSQL on protected requests.
- Password hashes use Argon2. Passwords require at least eight characters with one letter and one digit.
- Backend permission checks are the security boundary; frontend permission checks only control visible UI.
- User deletion is soft deletion. Deleted and disabled users cannot authenticate or access protected APIs.
- Never allow self-deletion/self-disable or an operation that leaves no active `super_admin` account.
- Use five RBAC tables: `users`, `roles`, `permissions`, `user_roles`, and `role_permissions`.
- Error responses use `{ "code": string, "message": string, "details": object | null }`.
- Role assignment stays inside `POST /api/users` and `PUT /api/users/{id}`. `GET /api/auth/me` includes `assignable_roles` only for callers with `user:assign_role`.
- Use ASCII for source files and documentation.

---

## Planned File Structure

| Path | Responsibility |
| --- | --- |
| `.env.example` | Non-secret frontend/backend environment contract for a local PostgreSQL instance |
| `backend/requirements.txt` | FastAPI runtime and test dependencies installed in a Conda environment |
| `backend/pytest.ini` | Pytest configuration |
| `backend/app/core/config.py` | Typed environment settings |
| `backend/app/db/session.py` | Async database engine and session factory |
| `backend/app/models/*.py` | SQLAlchemy user, role, permission, and association models |
| `backend/alembic/versions/0001_rbac_schema.py` | Initial RBAC database migration |
| `backend/app/db/seed.py` | Idempotent roles, permissions, and initial admin seed |
| `backend/app/core/security.py` | Argon2 and JWT primitives |
| `backend/app/core/dependencies.py` | Current-user and permission dependencies |
| `backend/app/schemas/*.py` | Pydantic request/response definitions |
| `backend/app/services/*.py` | Authentication and user-management rules |
| `backend/app/api/*.py` | The nine HTTP endpoint handlers |
| `backend/tests/*.py` | Backend integration tests |
| `frontend/app/**/*.tsx` | Login, dashboard, users, and roles pages |
| `frontend/lib/*.ts` | Credentialed API client and frontend auth helpers |
| `frontend/components/**/*.tsx` | User table and dialogs |
| `frontend/**/*.test.tsx` | Frontend unit tests |
| `README.md` | Setup, seed account, endpoints, and verification instructions |

## Task 1: Bootstrap Repository, Conda Runtime, and Local PostgreSQL Connection

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Create: `backend/app/__init__.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/db/session.py`
- Create: `backend/app/main.py`
- Create: `frontend/` using `create-next-app`

**Interfaces:**
- Produces `Settings` with `database_url`, `jwt_secret`, `jwt_expire_minutes`, `cookie_secure`, `cors_origins`, `initial_admin_username`, and `initial_admin_password`.
- Produces FastAPI `app` at `backend.app.main:app` with `/health` returning `{ "status": "ok" }`.

- [ ] **Step 1: Initialize the repository and write the failing health test.**

```powershell
git init
New-Item -ItemType Directory -Force -Path "backend/tests"
```

Create `backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Verify the test fails because the application module does not exist.**

Run: `cd backend; uv run pytest tests/test_health.py -v`

Expected: test collection fails with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Add local runtime configuration and the smallest FastAPI application.**

Create `backend/requirements.txt`:

```text
alembic>=1.14,<2
argon2-cffi>=23.1,<24
asyncpg>=0.30,<1
email-validator>=2.2,<3
fastapi>=0.115,<1
httpx>=0.28,<1
pydantic-settings>=2.7,<3
pytest>=8.3,<9
pytest-asyncio>=0.25,<1
python-jose[cryptography]>=3.3,<4
sqlalchemy>=2.0,<3
uvicorn[standard]>=0.34,<1
```

Create `backend/pytest.ini`:

```ini
[pytest]
pythonpath = .
testpaths = tests
asyncio_mode = auto
```

Create `backend/app/core/config.py`:

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    jwt_secret: str
    jwt_expire_minutes: int = 30
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:3000"
    initial_admin_username: str = "admin"
    initial_admin_password: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Create `backend/app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI(title="Simple RBAC API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

Create `.env.example`:

```dotenv
POSTGRES_DB=rbac
POSTGRES_USER=rbac
POSTGRES_PASSWORD=rbac_local_password
DATABASE_URL=postgresql+asyncpg://rbac:rbac_local_password@localhost:5432/rbac
JWT_SECRET=replace-with-a-long-random-development-secret
JWT_EXPIRE_MINUTES=30
COOKIE_SECURE=false
CORS_ORIGINS=http://localhost:3000
INITIAL_ADMIN_USERNAME=admin
INITIAL_ADMIN_PASSWORD=ChangeMe-Strong1
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Create `.gitignore`:

```gitignore
.env
.superpowers/
__pycache__/
.pytest_cache/
.venv/
backend/.venv/
frontend/node_modules/
frontend/.next/
```

- [ ] **Step 4: Create the Next.js application without replacing the backend files.**

Run: `npx create-next-app@latest frontend --ts --eslint --app --src-dir --use-npm --import-alias "@/*" --no-tailwind --yes`

Expected: command completes and creates `frontend/package.json`.

- [ ] **Step 5: Run health verification.**

In PyCharm, create or select a Conda environment with Python 3.12 or newer, then run: `cd backend; Copy-Item ../.env.example .env; python -m pip install -r requirements.txt; python -m pytest tests/test_health.py -v`

Expected: `1 passed`.

- [ ] **Step 6: Commit the bootstrap.**

```powershell
git add .gitignore .env.example backend frontend
git commit -m "chore: bootstrap rbac applications"
```

## Task 2: Create RBAC Persistence Models, Migration, and Seed Data

**Files:**
- Create: `backend/app/models/base.py`
- Create: `backend/app/models/rbac.py`
- Create: `backend/app/models/__init__.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_rbac_schema.py`
- Create: `backend/app/db/seed.py`
- Create: `backend/tests/test_seed.py`

**Interfaces:**
- Produces ORM classes `User`, `Role`, `Permission`, `UserRole`, and `RolePermission`.
- Produces `seed_rbac(session: AsyncSession) -> None`, safe to run repeatedly.
- Seeds `super_admin`, `user_manager`, and all eight permission codes.

- [ ] **Step 1: Write the failing seed test.**

Create `backend/tests/test_seed.py`:

```python
import pytest
from sqlalchemy import select

from app.db.seed import seed_rbac
from app.models.rbac import Permission, Role


@pytest.mark.asyncio
async def test_seed_creates_two_roles_and_eight_permissions(session) -> None:
    await seed_rbac(session)
    await seed_rbac(session)
    roles = (await session.scalars(select(Role.code).order_by(Role.code))).all()
    permissions = (await session.scalars(select(Permission.code))).all()
    assert roles == ["super_admin", "user_manager"]
    assert len(permissions) == 8
```

- [ ] **Step 2: Verify it fails because the models and seed function are absent.**

Run: `cd backend; python -m pytest tests/test_seed.py -v`

Expected: collection fails with `ModuleNotFoundError` for `app.db.seed`.

- [ ] **Step 3: Implement the models and seed function.**

In `backend/app/models/rbac.py`, define UUID-keyed SQLAlchemy declarative models with these required columns:

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
```

Define `Permission`, `UserRole`, and `RolePermission` similarly, with `ForeignKey("users.id")`, `ForeignKey("roles.id")`, and `ForeignKey("permissions.id")`; association tables use a composite primary key. Add `created_at` and `updated_at` UTC timestamp columns to `User` and `Role`.

Create `backend/app/db/seed.py` with this exact permission source:

```python
PERMISSIONS = (
    ("user:read", "Read users", "user"),
    ("user:create", "Create user", "user"),
    ("user:update", "Update user", "user"),
    ("user:delete", "Delete user", "user"),
    ("user:status", "Change user status", "user"),
    ("user:reset_password", "Reset user password", "user"),
    ("user:assign_role", "Assign user roles", "user"),
    ("role:read", "Read roles", "role"),
)
```

`seed_rbac` must query by code before inserting, assign every permission to `super_admin`, assign the seven `user:*` permissions to `user_manager`, and flush without committing. It must create the initial active `admin` user with the configured Argon2 hash and the `super_admin` mapping only if that username does not already exist.

- [ ] **Step 4: Create and run the initial Alembic migration.**

Run: `cd backend; alembic revision --autogenerate -m "rbac schema"; alembic upgrade head`

Expected: five tables, association constraints, and unique indexes exist in PostgreSQL.

- [ ] **Step 5: Add an async session test fixture and run the seed test.**

Create `backend/tests/conftest.py` with an isolated test database URL from `TEST_DATABASE_URL`, an `AsyncSession` fixture named `session`, and per-test transaction rollback. Run: `cd backend; python -m pytest tests/test_seed.py -v`

Expected: `1 passed`; rerunning the test does not create duplicate roles or permissions.

- [ ] **Step 6: Commit persistence and seed data.**

```powershell
git add backend
git commit -m "feat: add rbac schema and seed data"
```

## Task 3: Implement Security Primitives and Authorization Dependencies

**Files:**
- Create: `backend/app/core/security.py`
- Create: `backend/app/core/errors.py`
- Create: `backend/app/core/dependencies.py`
- Create: `backend/tests/test_security.py`

**Interfaces:**
- Produces `hash_password(password: str) -> str`, `verify_password(password: str, password_hash: str) -> bool`, and `validate_password(password: str) -> None`.
- Produces `create_access_token(user: User) -> str` and `decode_access_token(token: str) -> TokenPayload`.
- Produces FastAPI dependencies `get_current_user` and `require_permissions(*codes: str)`.

- [ ] **Step 1: Write failing password and JWT tests.**

Create `backend/tests/test_security.py`:

```python
import pytest
from app.core.security import create_access_token, hash_password, validate_password, verify_password


def test_password_hash_verifies_only_original_password() -> None:
    password_hash = hash_password("Password123")
    assert verify_password("Password123", password_hash) is True
    assert verify_password("Password124", password_hash) is False


def test_password_requires_letter_digit_and_eight_characters() -> None:
    with pytest.raises(ValueError, match="at least 8"):
        validate_password("abc123")
    with pytest.raises(ValueError, match="letter and digit"):
        validate_password("abcdefgh")
```

- [ ] **Step 2: Verify the tests fail.**

Run: `cd backend; python -m pytest tests/test_security.py -v`

Expected: collection fails because `app.core.security` is missing.

- [ ] **Step 3: Implement security and dependency behavior.**

Implement password policy using:

```python
def validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
        raise ValueError("Password must contain a letter and digit")
```

Create JWT claims with `sub=str(user.id)`, `username=user.username`, UTC `iat`, and UTC `exp`. `get_current_user` must read only cookie `access_token`, reject decode errors as `401 AUTHENTICATION_REQUIRED`, load a non-deleted active user, and attach its distinct permission codes. `require_permissions` must return `403 PERMISSION_DENIED` when any requested code is absent.

Create `backend/app/core/errors.py` with an `ApiError` exception and a handler that returns:

```python
{"code": error.code, "message": error.message, "details": error.details}
```

- [ ] **Step 4: Run the security tests.**

Run: `cd backend; python -m pytest tests/test_security.py -v`

Expected: `2 passed`.

- [ ] **Step 5: Commit security primitives.**

```powershell
git add backend/app/core backend/tests/test_security.py
git commit -m "feat: add jwt and permission dependencies"
```

## Task 4: Add Authentication Schemas, Services, and Three Endpoints

**Files:**
- Create: `backend/app/schemas/auth.py`
- Create: `backend/app/services/auth_service.py`
- Create: `backend/app/api/auth.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_auth_api.py`

**Interfaces:**
- Produces `POST /api/auth/login`, `POST /api/auth/logout`, and `GET /api/auth/me`.
- `GET /api/auth/me` returns `{ id, username, display_name, roles, permissions, assignable_roles? }`.

- [ ] **Step 1: Write failing endpoint tests.**

Create `backend/tests/test_auth_api.py`:

```python
async def test_login_sets_httponly_cookie_and_me_returns_permissions(client) -> None:
    response = await client.post("/api/auth/login", json={"username": "admin", "password": "ChangeMe-Strong1"})
    assert response.status_code == 200
    assert "access_token" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert "user:assign_role" in me.json()["permissions"]
    assert len(me.json()["assignable_roles"]) == 2


async def test_disabled_user_cannot_login(client, disabled_user) -> None:
    response = await client.post("/api/auth/login", json={"username": disabled_user.username, "password": "Password123"})
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
```

- [ ] **Step 2: Verify the endpoint tests fail.**

Run: `cd backend; python -m pytest tests/test_auth_api.py -v`

Expected: `404` for `/api/auth/login`.

- [ ] **Step 3: Implement authentication.**

`LoginRequest` has `username: str` and `password: str`. Login always returns `401` with code `INVALID_CREDENTIALS` and message `Invalid username or password` for missing users, wrong passwords, disabled users, and deleted users. On success, set cookie name `access_token`, `httponly=True`, `samesite="lax"`, `secure=settings.cookie_secure`, and `max_age=settings.jwt_expire_minutes * 60`.

`GET /api/auth/me` returns active `roles` and distinct `permissions`. Add `assignable_roles` as `{id, code, name}` only if `user:assign_role` is present; otherwise omit it. `POST /api/auth/logout` deletes the `access_token` cookie and returns `204`.

Register the router under `/api/auth`, add the `ApiError` handler, and configure `CORSMiddleware` with the comma-separated configured origins, `allow_credentials=True`, and explicit methods/headers.

- [ ] **Step 4: Run auth endpoint tests.**

Run: `cd backend; python -m pytest tests/test_auth_api.py -v`

Expected: all login, logout, and me tests pass.

- [ ] **Step 5: Commit authentication APIs.**

```powershell
git add backend/app backend/tests/test_auth_api.py
git commit -m "feat: add cookie based authentication api"
```

## Task 5: Implement User-Management Service and Six Endpoint Handlers

**Files:**
- Create: `backend/app/schemas/user.py`
- Create: `backend/app/services/user_service.py`
- Create: `backend/app/api/users.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_users_api.py`

**Interfaces:**
- Produces `GET /api/users`, `POST /api/users`, `PUT /api/users/{id}`, `DELETE /api/users/{id}`, `PATCH /api/users/{id}/status`, and `POST /api/users/{id}/reset-password`.
- Produces user list response `{ items: UserResponse[], page: int, page_size: int, total: int }`.

- [ ] **Step 1: Write failing user API tests.**

Create `backend/tests/test_users_api.py` with these core tests:

```python
async def test_user_manager_can_create_and_list_users(authenticated_user_manager_client) -> None:
    created = await authenticated_user_manager_client.post(
        "/api/users",
        json={"username": "alice", "display_name": "Alice", "password": "Password123", "role_ids": []},
    )
    assert created.status_code == 201
    listed = await authenticated_user_manager_client.get("/api/users?keyword=alice&page=1&page_size=20")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["username"] == "alice"


async def test_user_without_permission_gets_403(no_permission_client) -> None:
    response = await no_permission_client.get("/api/users")
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_cannot_disable_or_delete_self(admin_client, admin_user) -> None:
    disable = await admin_client.patch(f"/api/users/{admin_user.id}/status", json={"status": "disabled"})
    delete = await admin_client.delete(f"/api/users/{admin_user.id}")
    assert disable.status_code == 400
    assert delete.status_code == 400
```

- [ ] **Step 2: Verify the tests fail.**

Run: `cd backend; python -m pytest tests/test_users_api.py -v`

Expected: `404` responses because the user router is absent.

- [ ] **Step 3: Define schemas and implement service rules.**

Use these request shapes:

```python
class UserCreate(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    password: str
    email: EmailStr | None = None
    phone: str | None = None
    status: Literal["active", "disabled"] = "active"
    role_ids: list[UUID] = []

class UserUpdate(BaseModel):
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    email: EmailStr | None = None
    phone: str | None = None
    role_ids: list[UUID] | None = None

class UserStatusUpdate(BaseModel):
    status: Literal["active", "disabled"]

class PasswordReset(BaseModel):
    password: str
```

Implement these explicit service rules:

- `GET` excludes `is_deleted=True`, filters keyword against username/display name/email, filters by status and role ID, sorts newest first, and enforces `page >= 1`, `1 <= page_size <= 100`.
- Create validates password before hashing, rejects duplicate username/email/phone with `409 DUPLICATE_VALUE`, validates every supplied role is active, and replaces relationships in one transaction.
- Update does not update username or status. A non-`None` `role_ids` replaces the role mapping atomically. The router requires both `user:update` and `user:assign_role` when role IDs are supplied.
- Delete sets `is_deleted=True` and `status="disabled"`; it never physically deletes a row.
- Status update rejects self-disable and validates the last-active-super-admin rule.
- Delete rejects self-delete and validates the same super-admin rule.
- Password reset validates then hashes the supplied password.
- A missing or deleted target is `404 USER_NOT_FOUND`.

- [ ] **Step 4: Add tests for each mutation and business rule.**

Add tests for duplicate username (`409`), update role assignment without `user:assign_role` (`403`), reset password then login with the new password (`200`), soft-deleted login (`401`), and preventing removal of the sole active super-admin role (`400`).

- [ ] **Step 5: Run the complete user endpoint test module.**

Run: `cd backend; python -m pytest tests/test_users_api.py -v`

Expected: all list, create, update, deletion, status, password reset, authorization, and protected-account cases pass.

- [ ] **Step 6: Commit user-management APIs.**

```powershell
git add backend/app backend/tests/test_users_api.py
git commit -m "feat: add protected user management api"
```

## Task 6: Build the Shared Frontend API Client and Authentication Guard

**Files:**
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/auth.ts`
- Create: `frontend/src/lib/permissions.ts`
- Create: `frontend/src/types/auth.ts`
- Create: `frontend/src/components/auth/protected-page.tsx`
- Create: `frontend/src/lib/api.test.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/test/setup.ts`
- Modify: `frontend/package.json`

**Interfaces:**
- Produces `api<T>(path: string, init?: RequestInit): Promise<T>` that always sends credentials.
- Produces `CurrentUser` with `permissions: string[]` and optional `assignable_roles: AssignableRole[]`.
- Produces `hasPermission(user: CurrentUser, permission: string): boolean`.

- [ ] **Step 1: Write a failing API client test.**

Create `frontend/src/lib/api.test.ts`:

```ts
import { api } from "@/lib/api";

test("api sends cookies and turns error envelope into ApiError", async () => {
  global.fetch = vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ code: "PERMISSION_DENIED", message: "Permission denied", details: null }),
    { status: 403, headers: { "Content-Type": "application/json" } },
  ));
  await expect(api("/api/users")).rejects.toMatchObject({ status: 403, code: "PERMISSION_DENIED" });
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/users"), expect.objectContaining({ credentials: "include" }));
});
```

- [ ] **Step 2: Verify the test fails.**

Run: `cd frontend; npm test -- api.test.ts`

Expected: test command or module resolution fails until Vitest and the API module are configured.

- [ ] **Step 3: Configure Vitest and implement the shared client.**

Install: `cd frontend; npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom`

Create `frontend/vitest.config.ts`:

```ts
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"] },
});
```

Create `frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Add this script to `frontend/package.json`:

```json
"test": "vitest"
```

Implement `api` with `credentials: "include"`, JSON headers when a body exists, `cache: "no-store"`, base URL `process.env.NEXT_PUBLIC_API_BASE_URL`, and an `ApiError` containing `status`, `code`, `message`, and `details`. Export exact permission constants, including `USER_READ`, `USER_CREATE`, `USER_UPDATE`, `USER_DELETE`, `USER_STATUS`, `USER_RESET_PASSWORD`, and `USER_ASSIGN_ROLE`.

- [ ] **Step 4: Implement `ProtectedPage`.**

`ProtectedPage` is a client component that fetches `/api/auth/me` once on mount. It renders a loading state, redirects to `/login` on `401`, renders `No permission` when the required page permission is absent, and passes `CurrentUser` to children.

- [ ] **Step 5: Run frontend unit tests.**

Run: `cd frontend; npm test -- --run`

Expected: API client tests pass.

- [ ] **Step 6: Commit shared frontend infrastructure.**

```powershell
git add frontend
git commit -m "feat: add frontend api and auth helpers"
```

## Task 7: Implement Login and Protected Dashboard Shell

**Files:**
- Create: `frontend/src/app/(auth)/login/page.tsx`
- Create: `frontend/src/app/(dashboard)/layout.tsx`
- Create: `frontend/src/app/(dashboard)/users/page.tsx`
- Create: `frontend/src/app/(dashboard)/roles/page.tsx`
- Create: `frontend/src/components/auth/login-form.tsx`
- Create: `frontend/src/components/auth/login-form.test.tsx`

**Interfaces:**
- Login posts `{ username, password }` to `/api/auth/login` and navigates to `/users`.
- Dashboard uses `ProtectedPage` and shows User Management only with `user:read`; Role Management only with `role:read`.

- [ ] **Step 1: Write a failing login form test.**

```tsx
test("submits credentials and navigates after login", async () => {
  render(<LoginForm />);
  await userEvent.type(screen.getByLabelText("Username"), "admin");
  await userEvent.type(screen.getByLabelText("Password"), "ChangeMe-Strong1");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(api).toHaveBeenCalledWith("/api/auth/login", expect.objectContaining({ method: "POST" }));
  expect(mockPush).toHaveBeenCalledWith("/users");
});
```

- [ ] **Step 2: Verify the test fails.**

Run: `cd frontend; npm test -- login-form.test.tsx`

Expected: module-not-found failure for `LoginForm`.

- [ ] **Step 3: Implement login and layout.**

The login form requires non-empty username/password, disables submit while pending, posts JSON credentials, and displays the backend error message. The dashboard layout fetches current user through `ProtectedPage`, displays username and logout control, calls `POST /api/auth/logout`, then navigates to `/login`. `/users` requires `user:read`; `/roles` is a role-page placeholder requiring `role:read`.

- [ ] **Step 4: Run login and build verification.**

Run: `cd frontend; npm test -- --run; npm run build`

Expected: tests pass and Next.js production build completes.

- [ ] **Step 5: Commit login and dashboard shell.**

```powershell
git add frontend
git commit -m "feat: add login and protected dashboard"
```

## Task 8: Implement User List, Filters, and Permission-Aware Action Controls

**Files:**
- Create: `frontend/src/types/user.ts`
- Create: `frontend/src/components/users/user-table.tsx`
- Create: `frontend/src/components/users/user-filters.tsx`
- Create: `frontend/src/components/users/user-management.tsx`
- Modify: `frontend/src/app/(dashboard)/users/page.tsx`
- Create: `frontend/src/components/users/user-management.test.tsx`

**Interfaces:**
- Consumes `CurrentUser`, `UserListResponse`, and `api`.
- Produces a list view with `keyword`, `status`, `role_id`, `page`, and `page_size` request parameters.

- [ ] **Step 1: Write the failing list and permission visibility test.**

```tsx
test("loads users and hides actions without their permissions", async () => {
  render(<UserManagement currentUser={{ permissions: ["user:read"], roles: [], id: "1", username: "reader", display_name: "Reader" }} />);
  expect(await screen.findByText("alice")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Create user" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Delete alice" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Verify the test fails.**

Run: `cd frontend; npm test -- user-management.test.tsx`

Expected: module-not-found failure for `UserManagement`.

- [ ] **Step 3: Implement list behavior.**

Define `UserListItem` as `{ id, username, display_name, email, phone, roles, status, created_at }` and `UserListResponse` as `{ items, page, page_size, total }`. Load `/api/users` on initial render and when submitted filter/page state changes. Render filters for keyword, status, and role only when `currentUser.assignable_roles` exists. Render columns username, display name, contact, roles, status, creation time, and actions. Add loading, empty, and request-error states.

- [ ] **Step 4: Gate each action with its exact permission.**

Render `Create user` only for `user:create`; `Edit` only for `user:update`; `Enable`/`Disable` only for `user:status`; `Reset password` only for `user:reset_password`; and `Delete` only for `user:delete`. Do not use these checks as a substitute for backend checks.

- [ ] **Step 5: Run list tests.**

Run: `cd frontend; npm test -- user-management.test.tsx`

Expected: tests verify data rendering, filter request construction, pagination, empty state, and action visibility.

- [ ] **Step 6: Commit user-list UI.**

```powershell
git add frontend
git commit -m "feat: add permission aware user list"
```

## Task 9: Implement User Create/Edit, Role Assignment, Status, Reset, and Delete Dialogs

**Files:**
- Create: `frontend/src/components/users/user-form-dialog.tsx`
- Create: `frontend/src/components/users/password-reset-dialog.tsx`
- Create: `frontend/src/components/users/confirm-dialog.tsx`
- Modify: `frontend/src/components/users/user-management.tsx`
- Create: `frontend/src/components/users/user-dialogs.test.tsx`

**Interfaces:**
- `UserFormDialog` submits `POST /api/users` for creation and `PUT /api/users/{id}` for edits.
- `PasswordResetDialog` submits `POST /api/users/{id}/reset-password`.
- `ConfirmDialog` is reused for delete and status change.

- [ ] **Step 1: Write failing mutation tests.**

```tsx
test("creates a user with roles and refreshes the list", async () => {
  render(<UserManagement currentUser={adminWithAssignableRoles} />);
  await userEvent.click(await screen.findByRole("button", { name: "Create user" }));
  await userEvent.type(screen.getByLabelText("Username"), "bob");
  await userEvent.type(screen.getByLabelText("Initial password"), "Password123");
  await userEvent.selectOptions(screen.getByLabelText("Roles"), "role-user-manager");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(api).toHaveBeenCalledWith("/api/users", expect.objectContaining({ method: "POST" }));
});
```

- [ ] **Step 2: Verify the tests fail.**

Run: `cd frontend; npm test -- user-dialogs.test.tsx`

Expected: tests fail because dialogs are absent.

- [ ] **Step 3: Implement forms and confirmations.**

The create form includes username, display name, email, phone, initial password, status, and multi-select roles. The edit form excludes username, password, and status. Both validate the same password rule client-side on create, but retain backend validation as authoritative. Only render role selection if `user:assign_role` and `assignable_roles` are both available. Submit role IDs only when role selection is allowed.

Status confirmation sends `{ "status": "active" | "disabled" }` to the status endpoint. Password reset requires a new password and confirmation match before sending `{ "password": "..." }`. Delete confirmation calls the delete endpoint. After every successful mutation, close the dialog, announce success, and reload the current list; map `400`, `403`, `404`, `409`, and `422` API errors to visible feedback.

- [ ] **Step 4: Run dialog and full frontend verification.**

Run: `cd frontend; npm test -- --run; npm run build`

Expected: all frontend tests and production build pass.

- [ ] **Step 5: Commit user mutations UI.**

```powershell
git add frontend
git commit -m "feat: add user management dialogs"
```

## Task 10: Integrate Seed Startup, Documentation, and End-to-End Verification

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_rbac_end_to_end.py`
- Create: `README.md`

**Interfaces:**
- Startup runs schema migration outside the application process and runs idempotent `seed_rbac` during FastAPI lifespan.
- README supplies complete local startup and verification instructions.

- [ ] **Step 1: Write the failing end-to-end authorization test.**

Create `backend/tests/test_rbac_end_to_end.py`:

```python
async def test_role_change_takes_effect_on_next_request(admin_client, user_manager, user_manager_client) -> None:
    before = await user_manager_client.get("/api/users")
    assert before.status_code == 200
    response = await admin_client.put(
        f"/api/users/{user_manager.id}",
        json={"display_name": user_manager.display_name, "email": None, "phone": None, "role_ids": []},
    )
    assert response.status_code == 200
    after = await user_manager_client.get("/api/users")
    assert after.status_code == 403
```

- [ ] **Step 2: Verify the end-to-end test fails before its behavior is completed.**

Run: `cd backend; python -m pytest -v`

Expected: the new end-to-end test fails until session fixtures preserve the same JWT cookie across the post-update request or the authorization query is corrected. All earlier test modules remain green.

- [ ] **Step 3: Implement application lifespan seed and write README.**

Use FastAPI lifespan to open an async session, call `seed_rbac`, commit, and close it. Do not run Alembic migrations at application startup; README must explicitly require migrations before starting the API.

README must include these exact commands:

```powershell
Copy-Item .env.example .env
cd backend
Copy-Item ../.env .env
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Document `http://localhost:3000`, `http://localhost:8000/docs`, initial development credentials `admin` / `ChangeMe-Strong1` only when `.env` keeps its example value, all nine endpoints, and the rule to replace both JWT secret and initial admin password in non-development environments.

- [ ] **Step 4: Execute final verification.**

Run: `cd backend; python -m pytest -v`

Expected: all backend tests pass.

Run: `cd frontend; npm test -- --run; npm run build`

Expected: all frontend tests pass and Next.js build completes.

Run: `cd backend; python -c "from app.core.config import get_settings; print(get_settings().database_url)"`

Expected: the configured local PostgreSQL connection URL is printed without exposing a production secret in committed files.

- [ ] **Step 5: Perform manual acceptance with three seeded/test identities.**

Verify in the browser:

1. Super admin can see all user actions, create a user, assign roles, change status, reset password, and soft-delete another user.
2. User manager can perform only its assigned user-management actions and cannot access the role page without `role:read`.
3. A user with no user-management permissions receives `403` from user APIs and has no user-management menu/action controls.

- [ ] **Step 6: Commit final integration and documentation.**

```powershell
git add backend README.md
git commit -m "docs: add rbac setup and verification guide"
```

## Plan Self-Review

### Spec Coverage

- Next.js, FastAPI, local PostgreSQL, Alembic, JWT cookie, Argon2, CORS, and typed settings: Tasks 1-4.
- Five-table RBAC schema, UUID keys, constraints, and seed roles/permissions/admin: Task 2.
- Three auth endpoints, current permission resolution, and optional assignable role data: Task 4.
- Six user endpoints, role assignment without a tenth endpoint, soft delete, state changes, reset password, duplicate validation, and protected-super-admin rules: Task 5.
- Three pages, protected routing, button-level permission display, list/filter/pagination, and all dialogs: Tasks 6-9.
- Backend/frontend tests, manual three-role acceptance, Conda/PyCharm/VS Code/README documentation: Task 10.

### Consistency Check

- `GET /api/auth/me` is the single frontend source for `permissions` and conditional `assignable_roles` in Tasks 4, 6, 8, and 9.
- Status updates use only `PATCH /api/users/{id}/status`; `PUT /api/users/{id}` deliberately excludes status in Tasks 5 and 9.
- All endpoint counts total nine: three auth endpoints plus six user endpoints.
- Permission codes match the approved design consistently across seeds, backend guards, and frontend constants.
