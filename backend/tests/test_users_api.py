import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from types import SimpleNamespace

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.base import Base
from app.models.rbac import Role, User, UserRole

settings = get_settings()

INITIAL_ADMIN_PASSWORD = settings.initial_admin_password


@pytest.fixture
async def client(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as s:
        await seed_rbac(s)
        await s.commit()

    async def override_get_db():
        async with async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def admin_client(client):
    response = await client.post(
        "/api/auth/login",
        json={"username": settings.initial_admin_username, "password": settings.initial_admin_password},
    )
    assert response.status_code == 200
    return client


@pytest.fixture
async def admin_user(test_engine):
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        return await s.scalar(
            select(User).where(User.username == settings.initial_admin_username)
        )


@pytest.fixture
async def authenticated_user_manager_client(client, test_engine):
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        user = User(
            username="manager1",
            display_name="Manager One",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.flush()
        role = await s.scalar(select(Role).where(Role.code == "user_manager"))
        s.add(UserRole(user_id=user.id, role_id=role.id))
        await s.commit()

    await client.post(
        "/api/auth/login",
        json={"username": "manager1", "password": "Password123"},
    )
    return client


@pytest.fixture
async def no_permission_client(client, test_engine):
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        user = User(
            username="nobody",
            display_name="No Permission",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.commit()

    await client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "Password123"},
    )
    return client


@pytest.fixture
async def user_with_role(client, test_engine):
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        role = await s.scalar(select(Role).where(Role.code == "user_manager"))
        user = User(
            username="role_test_user",
            display_name="Role Test",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.flush()
        s.add(UserRole(user_id=user.id, role_id=role.id))
        await s.commit()
    role_ref = SimpleNamespace(id=role.id, code=role.code, name=role.name)
    uw = SimpleNamespace(id=user.id, role=role_ref)
    return uw


# ── Step 1: Core tests from the task brief ───────────────────────────

async def test_user_manager_can_create_and_list_users(authenticated_user_manager_client) -> None:
    created = await authenticated_user_manager_client.post(
        "/api/users",
        json={"username": "alice", "display_name": "Alice", "password": "Password123", "role_ids": []},
    )
    assert created.status_code == 201
    listed = await authenticated_user_manager_client.get("/api/users?keyword=alice&page=1&page_size=20")
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["username"] == "alice"


async def test_user_without_permission_gets_403(no_permission_client) -> None:
    response = await no_permission_client.get("/api/users")
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_cannot_disable_or_delete_self(admin_client, admin_user) -> None:
    disable = await admin_client.patch(
        f"/api/users/{admin_user.id}/status", json={"status": "disabled"}
    )
    delete = await admin_client.delete(f"/api/users/{admin_user.id}")
    assert disable.status_code == 400
    assert delete.status_code == 400


async def test_user_list_returns_role_summaries_not_role_ids(admin_client, user_with_role) -> None:
    response = await admin_client.get("/api/users")
    item = next(item for item in response.json()["data"]["items"] if item["id"] == str(user_with_role.id))
    assert item["roles"] == [{"id": str(user_with_role.role.id), "code": user_with_role.role.code, "name": user_with_role.role.name}]
    assert "role_ids" not in item


# ── Step 4: Additional business-rule tests ───────────────────────────

async def test_duplicate_username_returns_409(admin_client) -> None:
    created = await admin_client.post(
        "/api/users",
        json={"username": "dupe1", "display_name": "Dupe", "password": "Password123", "role_ids": []},
    )
    assert created.status_code == 201
    dupe = await admin_client.post(
        "/api/users",
        json={"username": "dupe1", "display_name": "Dupe Again", "password": "Password123", "role_ids": []},
    )
    assert dupe.status_code == 409
    assert dupe.json()["code"] == "DUPLICATE_VALUE"


async def test_update_role_without_assign_role_permission_returns_403(
    client, test_engine
) -> None:
    from app.models.rbac import Permission, RolePermission

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()

        updater_role = Role(code="updater", name="Updater", status="active")
        s.add(updater_role)
        await s.flush()

        perm = await s.scalar(select(Permission).where(Permission.code == "user:update"))
        s.add(RolePermission(role_id=updater_role.id, permission_id=perm.id))
        await s.flush()

        user = User(
            username="update_me",
            display_name="Update Me",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.flush()
        s.add(UserRole(user_id=user.id, role_id=updater_role.id))

        target = User(
            username="target_user",
            display_name="Target",
            password_hash=ph.hash("Password123"),
        )
        s.add(target)
        await s.flush()
        target_id = str(target.id)

        role_sa = await s.scalar(select(Role).where(Role.code == "super_admin"))

        await s.commit()

    await client.post(
        "/api/auth/login",
        json={"username": "update_me", "password": "Password123"},
    )

    response = await client.put(
        f"/api/users/{target_id}",
        json={
            "display_name": "Updated Name",
            "role_ids": [str(role_sa.id)],
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_reset_password_then_login(client, admin_client, test_engine) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        user = User(
            username="pwuser",
            display_name="PW User",
            password_hash=ph.hash("OldPass1"),
        )
        s.add(user)
        await s.commit()
        target_id = str(user.id)

    reset = await admin_client.post(
        f"/api/users/{target_id}/reset-password",
        json={"password": "NewPass123"},
    )
    assert reset.status_code == 200

    await client.post("/api/auth/logout")
    login = await client.post(
        "/api/auth/login",
        json={"username": "pwuser", "password": "NewPass123"},
    )
    assert login.status_code == 200


async def test_soft_deleted_user_cannot_login(client, admin_client, test_engine) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        user = User(
            username="softdel",
            display_name="Soft Delete",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.commit()
        target_id = str(user.id)

    await admin_client.delete(f"/api/users/{target_id}")

    await client.post("/api/auth/logout")
    login = await client.post(
        "/api/auth/login",
        json={"username": "softdel", "password": "Password123"},
    )
    assert login.status_code == 401


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


async def test_create_user_with_invalid_role_returns_error(admin_client) -> None:
    response = await admin_client.post(
        "/api/users",
        json={
            "username": "badrole",
            "display_name": "Bad Role",
            "password": "Password123",
            "role_ids": ["00000000-0000-0000-0000-000000000001"],
        },
    )
    assert response.status_code == 404


async def test_delete_soft_deletes_and_excludes_from_list(admin_client) -> None:
    created = await admin_client.post(
        "/api/users",
        json={
            "username": "delete_me",
            "display_name": "Delete Me",
            "password": "Password123",
            "role_ids": [],
        },
    )
    assert created.status_code == 201
    user_id = created.json()["data"]["id"]

    deleted = await admin_client.delete(f"/api/users/{user_id}")
    assert deleted.status_code == 204

    users = await admin_client.get("/api/users?keyword=delete_me")
    assert users.json()["data"]["total"] == 0


async def test_create_user_password_validation(admin_client) -> None:
    response = await admin_client.post(
        "/api/users",
        json={"username": "weakpw1", "display_name": "Weak PW", "password": "short", "role_ids": []},
    )
    assert response.status_code == 400


async def test_admin_can_update_user(admin_client) -> None:
    created = await admin_client.post(
        "/api/users",
        json={
            "username": "editme",
            "display_name": "Edit Me",
            "password": "Password123",
            "role_ids": [],
        },
    )
    assert created.status_code == 201
    user_id = created.json()["data"]["id"]

    updated = await admin_client.put(
        f"/api/users/{user_id}",
        json={"display_name": "Edited Name"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["display_name"] == "Edited Name"
    assert updated.json()["data"]["username"] == "editme"


async def test_admin_can_change_user_status(admin_client) -> None:
    created = await admin_client.post(
        "/api/users",
        json={
            "username": "status_test",
            "display_name": "Status Test",
            "password": "Password123",
            "role_ids": [],
        },
    )
    assert created.status_code == 201
    user_id = created.json()["data"]["id"]

    disabled = await admin_client.patch(
        f"/api/users/{user_id}/status",
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["status"] == "disabled"

    reenabled = await admin_client.patch(
        f"/api/users/{user_id}/status",
        json={"status": "active"},
    )
    assert reenabled.status_code == 200
    assert reenabled.json()["data"]["status"] == "active"


async def test_update_nonexistent_user_returns_404(admin_client) -> None:
    response = await admin_client.put(
        "/api/users/00000000-0000-0000-0000-000000000001",
        json={"display_name": "Ghost"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


async def test_delete_nonexistent_user_returns_404(admin_client) -> None:
    response = await admin_client.delete("/api/users/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


async def test_list_users_pagination(admin_client) -> None:
    response = await admin_client.get("/api/users")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "items" in data
    assert "page" in data
    assert "page_size" in data
    assert "total" in data
    assert data["page"] == 1


async def test_filter_users_by_status(admin_client) -> None:
    response = await admin_client.get("/api/users?status=active")
    assert response.status_code == 200
    for item in response.json()["data"]["items"]:
        assert item["status"] == "active"


async def test_filter_users_by_role(admin_client) -> None:
    roles = (await admin_client.get("/api/roles?page_size=50")).json()["data"]
    sa_id = [r for r in roles["items"] if r["code"] == "super_admin"][0]["id"]

    response = await admin_client.get(f"/api/users?role_id={sa_id}")
    assert response.status_code == 200
    assert response.json()["data"]["total"] >= 1
    for item in response.json()["data"]["items"]:
        role_ids_in_item = [r["id"] for r in item["roles"]]
        assert sa_id in role_ids_in_item


async def test_user_cannot_update_their_own_role_without_assign_role_permission(
    client, test_engine
) -> None:
    from app.models.rbac import Permission, RolePermission

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()

        updater_role = Role(code="updater2", name="Updater2", status="active")
        s.add(updater_role)
        await s.flush()

        perm = await s.scalar(select(Permission).where(Permission.code == "user:update"))
        s.add(RolePermission(role_id=updater_role.id, permission_id=perm.id))
        await s.flush()

        user = User(
            username="update_me2",
            display_name="Update Me 2",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.flush()
        s.add(UserRole(user_id=user.id, role_id=updater_role.id))

        target = User(
            username="target_user2",
            display_name="Target 2",
            password_hash=ph.hash("Password123"),
        )
        s.add(target)
        await s.flush()
        target_id = str(target.id)

        role = await s.scalar(select(Role).where(Role.code == "user_manager"))

        await s.commit()

    await client.post(
        "/api/auth/login",
        json={"username": "update_me2", "password": "Password123"},
    )

    response = await client.put(
        f"/api/users/{target_id}",
        json={"display_name": "Test", "role_ids": [str(role.id)]},
    )
    assert response.status_code == 403


async def test_create_user_with_inactive_role_returns_400(admin_client, test_engine) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        inactive_role = Role(code="inactive_role", name="Inactive", status="disabled")
        s.add(inactive_role)
        await s.commit()
        rid = str(inactive_role.id)

    response = await admin_client.post(
        "/api/users",
        json={
            "username": "badrole2",
            "display_name": "Bad Role 2",
            "password": "Password123",
            "role_ids": [rid],
        },
    )
    assert response.status_code == 400


async def test_reset_password_validation(admin_client, test_engine) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        user = User(
            username="rpw_user",
            display_name="RPW User",
            password_hash=ph.hash("OldPass1"),
        )
        s.add(user)
        await s.commit()
        target_id = str(user.id)

    response = await admin_client.post(
        f"/api/users/{target_id}/reset-password",
        json={"password": "short"},
    )
    assert response.status_code == 400


# ── Helpers ──────────────────────────────────────────────────────────

async def _db_scalar(test_engine, stmt):
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        return await s.scalar(stmt)


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


async def test_seed_marks_initial_admin_as_builtin(client, admin_user) -> None:
    assert admin_user.is_builtin is True


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


# ── Own profile & password change ────────────────────────────────────

async def test_update_own_profile(admin_client) -> None:
    resp = await admin_client.put(
        "/api/users/me/profile",
        json={"display_name": "New Name", "email": "newmail@example.com"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["display_name"] == "New Name"
    assert body["email"] == "newmail@example.com"


async def test_update_own_profile_email_conflict(admin_client, session) -> None:
    from app.core.security import hash_password
    from app.models.rbac import User

    other = User(
        username="mailowner",
        display_name="Mail Owner",
        email="taken@example.com",
        password_hash=hash_password("Password123"),
        status="active",
    )
    session.add(other)
    await session.commit()

    resp = await admin_client.put(
        "/api/users/me/profile",
        json={"email": "taken@example.com"},
    )
    assert resp.status_code == 409


async def test_update_own_profile_empty_body(admin_client) -> None:
    resp = await admin_client.put("/api/users/me/profile", json={})
    assert resp.status_code == 400


async def test_change_password_wrong_old(admin_client) -> None:
    resp = await admin_client.post(
        "/api/users/me/password",
        json={"old_password": "WrongPass123", "new_password": "NewPass456"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_PASSWORD"


async def test_change_password_success_and_relogin(admin_client) -> None:
    resp = await admin_client.post(
        "/api/users/me/password",
        json={"old_password": INITIAL_ADMIN_PASSWORD, "new_password": "NewPass456"},
    )
    assert resp.status_code == 200, resp.text
    login = await admin_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "NewPass456"},
    )
    assert login.status_code == 200


async def test_change_password_weak_new(admin_client) -> None:
    resp = await admin_client.post(
        "/api/users/me/password",
        json={"old_password": INITIAL_ADMIN_PASSWORD, "new_password": "weak"},
    )
    assert resp.status_code == 400


async def test_user_list_includes_avatar_url(admin_client) -> None:
    resp = await admin_client.get("/api/users?page_size=10")
    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert "avatar_url" in item
    assert item["avatar_url"] is None or item["avatar_url"].startswith("/api/avatars/")
