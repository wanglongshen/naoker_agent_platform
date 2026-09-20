import uuid

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.main import app
from app.models.rbac import Permission, Role, RolePermission, User, UserRole

settings = get_settings()


@pytest.fixture
async def user_manager(test_db):
    async with test_db() as s:
        ph = PasswordHasher()
        user = User(
            username="manager_e2e",
            display_name="Manager E2E",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.flush()
        role = await s.scalar(select(Role).where(Role.code == "user_manager"))
        s.add(UserRole(user_id=user.id, role_id=role.id))
        await s.commit()
        return user


@pytest.fixture
async def user_manager_client(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/auth/login",
            json={"username": "manager_e2e", "password": "Password123"},
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def custom_role(admin_client):
    perms = await admin_client.get("/api/permissions")
    perm_id = None
    for p in perms.json()["data"]:
        if p["code"] == "role:read":
            perm_id = p["id"]
            break
    assert perm_id is not None

    resp = await admin_client.post(
        "/api/roles",
        json={
            "code": f"e2e_custom_{uuid.uuid4().hex[:8]}",
            "name": f"E2E Custom {uuid.uuid4().hex[:6]}",
            "description": "End-to-end test role",
            "permission_ids": [perm_id],
        },
    )
    assert resp.status_code == 201
    return resp.json()["data"]


@pytest.fixture
async def role_user(custom_role, test_db):
    async with test_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"roleuser_{uuid.uuid4().hex[:8]}",
            display_name="Role User E2E",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.flush()
        s.add(UserRole(user_id=user.id, role_id=uuid.UUID(custom_role["id"])))
        await s.commit()
        return user


@pytest.fixture
async def role_user_client(role_user, test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/auth/login",
            json={"username": role_user.username, "password": "Password123"},
        )
        assert response.status_code == 200
        yield ac


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


async def test_disabled_role_stops_contributing_permission_on_next_request(
    role_user_client, admin_client, custom_role
) -> None:
    before = await role_user_client.get("/api/roles")
    assert before.status_code == 200

    changed = await admin_client.patch(
        f"/api/roles/{custom_role['id']}/status", json={"status": "disabled"}
    )
    assert changed.status_code == 200

    after = await role_user_client.get("/api/roles")
    assert after.status_code == 403


async def test_deleted_role_stops_contributing_permission(
    admin_client, test_db
) -> None:
    perms = await admin_client.get("/api/permissions")
    perm_id = None
    for p in perms.json()["data"]:
        if p["code"] == "role:read":
            perm_id = p["id"]
            break

    resp = await admin_client.post(
        "/api/roles",
        json={
            "code": f"del_test_{uuid.uuid4().hex[:8]}",
            "name": f"Delete Test {uuid.uuid4().hex[:6]}",
            "permission_ids": [perm_id],
        },
    )
    assert resp.status_code == 201
    role = resp.json()["data"]

    async with test_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"deluser_{uuid.uuid4().hex[:8]}",
            display_name="Delete Role User",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.flush()
        s.add(UserRole(user_id=user.id, role_id=uuid.UUID(role["id"])))
        await s.commit()
        username = user.username

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login_resp = await ac.post(
            "/api/auth/login",
            json={"username": username, "password": "Password123"},
        )
        assert login_resp.status_code == 200

        before = await ac.get("/api/roles")
        assert before.status_code == 200

    await admin_client.delete(f"/api/roles/{role['id']}")

    transport2 = ASGITransport(app=app)
    async with AsyncClient(transport=transport2, base_url="http://test") as ac2:
        login_resp2 = await ac2.post(
            "/api/auth/login",
            json={"username": username, "password": "Password123"},
        )
        assert login_resp2.status_code == 200

        after = await ac2.get("/api/roles")
        assert after.status_code == 403
