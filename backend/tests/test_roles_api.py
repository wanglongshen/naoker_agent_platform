from collections import namedtuple

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.base import Base
from app.models.rbac import Permission, Role, RolePermission, User, UserRole

settings = get_settings()

RoleWithUser = namedtuple("RoleWithUser", ["role", "check_no_association"])


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
async def permissions_dict(test_engine):
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        perms = (await s.execute(select(Permission))).scalars().all()
        return {p.code: p for p in perms}


@pytest.fixture
async def super_admin_role(test_engine):
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        return await s.scalar(select(Role).where(Role.code == "super_admin"))


@pytest.fixture
async def ordinary_role_with_user(client, admin_client, test_engine):
    perm_result = await client.get("/api/permissions")
    role_read_id = None
    for p in perm_result.json()["data"]:
        if p["code"] == "role:read":
            role_read_id = p["id"]
            break

    create_resp = await admin_client.post(
        "/api/roles",
        json={
            "code": "test_deletable",
            "name": "Test Deletable",
            "description": "A role that can be deleted",
            "permission_ids": [role_read_id] if role_read_id else [],
        },
    )
    assert create_resp.status_code == 201
    role_data = create_resp.json()["data"]

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        user = User(
            username="role_test_user",
            display_name="Role Test User",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.flush()

        role = await s.scalar(select(Role).where(Role.id == role_data["id"]))
        s.add(UserRole(user_id=user.id, role_id=role.id))
        await s.commit()

        role_id = role.id
        user_id = user.id

    async def check_no_association():
        async with async_session_factory() as s:
            result = await s.execute(
                select(UserRole).where(
                    UserRole.user_id == user_id,
                    UserRole.role_id == role_id,
                )
            )
            return result.scalar() is None

    class FixtureResult:
        def __init__(self, role_obj, check_fn):
            self.role = role_obj
            self.user_has_no_role_association = check_fn

    async with async_session_factory() as s:
        role_obj = await s.scalar(select(Role).where(Role.id == role_data["id"]))

    return FixtureResult(role_obj, check_no_association)


@pytest.fixture
async def csrf_headers(admin_client):
    resp = await admin_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


# ── Core tests from the task brief ──────────────────────────────────

async def test_admin_creates_role_with_permissions(admin_client, permissions_dict) -> None:
    response = await admin_client.post(
        "/api/roles",
        json={
            "code": "content_editor",
            "name": "Content Editor",
            "description": "Manages content roles",
            "permission_ids": [str(permissions_dict["role:read"].id)],
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["code"] == "content_editor"
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


# ── Additional tests ────────────────────────────────────────────────

async def test_list_roles_returns_paginated(admin_client) -> None:
    response = await admin_client.get("/api/roles")
    assert response.status_code == 200
    data = response.json()["data"]
    assert "items" in data
    assert "page" in data
    assert "page_size" in data
    assert "total" in data
    assert data["page"] == 1
    assert data["total"] >= 2


async def test_list_roles_keyword_filter(admin_client) -> None:
    response = await admin_client.get("/api/roles?keyword=super")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] >= 1
    for item in data["items"]:
        assert "super" in item["code"].lower() or "super" in item["name"].lower()


async def test_list_roles_status_filter(admin_client) -> None:
    response = await admin_client.get("/api/roles?status=active")
    assert response.status_code == 200
    for item in response.json()["data"]["items"]:
        assert item["status"] == "active"


async def test_get_role_detail(admin_client, super_admin_role) -> None:
    response = await admin_client.get(f"/api/roles/{super_admin_role.id}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["code"] == "super_admin"
    assert data["is_system"] is True
    assert "permissions" in data
    assert "assigned_user_count" in data
    assert len(data["permissions"]) >= 1


async def test_create_role_without_permissions(admin_client) -> None:
    response = await admin_client.post(
        "/api/roles",
        json={
            "code": "basic_role",
            "name": "Basic Role",
            "description": "No permissions",
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["code"] == "basic_role"
    assert response.json()["data"]["permission_count"] == 0


async def test_create_role_duplicate_code_returns_409(admin_client) -> None:
    await admin_client.post(
        "/api/roles",
        json={"code": "dup_role_code", "name": "Duplicate Role Code"},
    )
    response = await admin_client.post(
        "/api/roles",
        json={"code": "dup_role_code", "name": "Another Name"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_VALUE"


async def test_create_role_duplicate_name_returns_409(admin_client) -> None:
    await admin_client.post(
        "/api/roles",
        json={"code": "unique_code_1", "name": "Duplicate Name"},
    )
    response = await admin_client.post(
        "/api/roles",
        json={"code": "unique_code_2", "name": "Duplicate Name"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_VALUE"


async def test_create_role_with_nonexistent_permission_returns_404(admin_client) -> None:
    response = await admin_client.post(
        "/api/roles",
        json={
            "code": "bad_perm",
            "name": "Bad Permission",
            "permission_ids": ["00000000-0000-0000-0000-000000000001"],
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "PERMISSION_NOT_FOUND"


async def test_create_role_with_inactive_permission_returns_400(admin_client, test_engine) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        perm = Permission(code="test:inactive", name="Inactive Permission", status="disabled")
        s.add(perm)
        await s.commit()
        perm_id = str(perm.id)

    response = await admin_client.post(
        "/api/roles",
        json={
            "code": "inactive_perm_role",
            "name": "Inactive Permission Role",
            "permission_ids": [perm_id],
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INACTIVE_PERMISSION"


async def test_update_role_name_and_description(admin_client) -> None:
    create_resp = await admin_client.post(
        "/api/roles",
        json={"code": "update_test", "name": "Original Name", "description": "Original"},
    )
    role_id = create_resp.json()["data"]["id"]

    response = await admin_client.put(
        f"/api/roles/{role_id}",
        json={"name": "Updated Name", "description": "Updated"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated"


async def test_update_role_permissions(admin_client) -> None:
    create_resp = await admin_client.post(
        "/api/roles",
        json={"code": "perm_update", "name": "Permission Update", "permission_ids": []},
    )
    role_id = create_resp.json()["data"]["id"]

    perm_list = await admin_client.get("/api/permissions")
    perm_ids = [p["id"] for p in perm_list.json()["data"][:2]]

    response = await admin_client.put(
        f"/api/roles/{role_id}",
        json={"name": "Permission Update", "permission_ids": perm_ids},
    )
    assert response.status_code == 200
    assert response.json()["data"]["permission_count"] == 2


async def test_update_nonexistent_role_returns_404(admin_client) -> None:
    response = await admin_client.put(
        "/api/roles/00000000-0000-0000-0000-000000000001",
        json={"name": "Ghost", "description": "Nope"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "ROLE_NOT_FOUND"


async def test_update_role_duplicate_name_returns_409(admin_client) -> None:
    await admin_client.post(
        "/api/roles",
        json={"code": "name_dup_1", "name": "Name Conflict"},
    )
    create_resp = await admin_client.post(
        "/api/roles",
        json={"code": "name_dup_2", "name": "Name Conflict 2"},
    )
    role_id = create_resp.json()["data"]["id"]

    response = await admin_client.put(
        f"/api/roles/{role_id}",
        json={"name": "Name Conflict"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_VALUE"


async def test_super_admin_status_cannot_change(admin_client, super_admin_role) -> None:
    response = await admin_client.patch(
        f"/api/roles/{super_admin_role.id}/status",
        json={"status": "disabled"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "SYSTEM_ROLE_IMMUTABLE"


async def test_super_admin_cannot_be_deleted(admin_client, super_admin_role) -> None:
    response = await admin_client.delete(f"/api/roles/{super_admin_role.id}")
    assert response.status_code == 400
    assert response.json()["code"] == "SYSTEM_ROLE_IMMUTABLE"


async def test_update_normal_role_status(admin_client) -> None:
    create_resp = await admin_client.post(
        "/api/roles",
        json={"code": "status_test", "name": "Status Test Role"},
    )
    role_id = create_resp.json()["data"]["id"]

    disable_resp = await admin_client.patch(
        f"/api/roles/{role_id}/status",
        json={"status": "disabled"},
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json()["data"]["status"] == "disabled"

    enable_resp = await admin_client.patch(
        f"/api/roles/{role_id}/status",
        json={"status": "active"},
    )
    assert enable_resp.status_code == 200
    assert enable_resp.json()["data"]["status"] == "active"


async def test_delete_role_soft_deletes(admin_client) -> None:
    create_resp = await admin_client.post(
        "/api/roles",
        json={"code": "delete_me", "name": "Delete Me"},
    )
    role_id = create_resp.json()["data"]["id"]

    response = await admin_client.delete(f"/api/roles/{role_id}")
    assert response.status_code == 204

    list_resp = await admin_client.get("/api/roles")
    codes = [r["code"] for r in list_resp.json()["data"]["items"]]
    assert "delete_me" not in codes


async def test_delete_nonexistent_role_returns_404(admin_client) -> None:
    response = await admin_client.delete(
        "/api/roles/00000000-0000-0000-0000-000000000001"
    )
    assert response.status_code == 404
    assert response.json()["code"] == "ROLE_NOT_FOUND"


async def test_list_permissions(admin_client) -> None:
    response = await admin_client.get("/api/permissions")
    assert response.status_code == 200
    data = response.json()["data"]
    assert isinstance(data, list)
    assert len(data) >= 13
    for perm in data:
        assert "id" in perm
        assert "code" in perm
        assert "name" in perm
        assert "module" in perm


async def test_user_without_permission_gets_403(client, test_engine) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()
        user = User(
            username="no_role_user",
            display_name="No Role",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.commit()

    await client.post(
        "/api/auth/login",
        json={"username": "no_role_user", "password": "Password123"},
    )

    response = await client.get("/api/roles")
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


async def test_create_role_requires_assign_permission_when_permissions_provided(
    client, test_engine
) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()

        create_role = Role(code="creator_only", name="Creator Only", status="active")
        s.add(create_role)
        await s.flush()

        perm = await s.scalar(select(Permission).where(Permission.code == "role:create"))
        s.add(RolePermission(role_id=create_role.id, permission_id=perm.id))
        await s.flush()

        user = User(
            username="creator_user",
            display_name="Creator",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.flush()
        s.add(UserRole(user_id=user.id, role_id=create_role.id))
        await s.commit()

    await client.post(
        "/api/auth/login",
        json={"username": "creator_user", "password": "Password123"},
    )

    perm_result = (await _db_all(test_engine, select(Permission)))[0]

    response = await client.post(
        "/api/roles",
        json={
            "code": "needs_assign",
            "name": "Needs Assign",
            "permission_ids": [str(perm_result.id)],
        },
    )
    assert response.status_code == 403


async def test_update_role_requires_assign_permission_when_permissions_changed(
    client, test_engine
) -> None:
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        ph = PasswordHasher()

        updater_role = Role(code="role_updater", name="Role Updater", status="active")
        s.add(updater_role)
        await s.flush()

        perm = await s.scalar(select(Permission).where(Permission.code == "role:update"))
        s.add(RolePermission(role_id=updater_role.id, permission_id=perm.id))
        await s.flush()

        user = User(
            username="role_updater_user",
            display_name="Role Updater",
            password_hash=ph.hash("Password123"),
        )
        s.add(user)
        await s.flush()
        s.add(UserRole(user_id=user.id, role_id=updater_role.id))

        target_role = Role(code="target_role", name="Target Role", status="active")
        s.add(target_role)
        await s.flush()
        target_id = str(target_role.id)

        await s.commit()

    await client.post(
        "/api/auth/login",
        json={"username": "role_updater_user", "password": "Password123"},
    )

    perm_result = await _db_first(test_engine, select(Permission))

    response = await client.put(
        f"/api/roles/{target_id}",
        json={
            "name": "Target Role",
            "permission_ids": [str(perm_result.id)],
        },
    )
    assert response.status_code == 403


async def test_roles_are_soft_deleted_excluded_from_list(admin_client) -> None:
    create_resp = await admin_client.post(
        "/api/roles",
        json={"code": "soft_del_test", "name": "Soft Delete Test"},
    )
    role_id = create_resp.json()["data"]["id"]

    await admin_client.delete(f"/api/roles/{role_id}")

    detail_resp = await admin_client.get(f"/api/roles/{role_id}")
    assert detail_resp.status_code == 404


async def test_role_detail_includes_assigned_user_count(admin_client, super_admin_role) -> None:
    response = await admin_client.get(f"/api/roles/{super_admin_role.id}")
    assert response.status_code == 200
    assert response.json()["data"]["assigned_user_count"] >= 1


async def test_role_update_with_permission_ids_none_does_not_change_permissions(admin_client) -> None:
    perm_list = await admin_client.get("/api/permissions")
    perm_id = perm_list.json()["data"][0]["id"]

    create_resp = await admin_client.post(
        "/api/roles",
        json={
            "code": "partial_update_test",
            "name": "Partial Update",
            "permission_ids": [perm_id],
        },
    )
    role_id = create_resp.json()["data"]["id"]
    assert create_resp.json()["data"]["permission_count"] == 1

    response = await admin_client.put(
        f"/api/roles/{role_id}",
        json={"name": "Partial Update Renamed"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["permission_count"] == 1


# ── Helpers ──────────────────────────────────────────────────────────

async def test_create_role_with_parent(admin_client, csrf_headers, test_engine) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.models.rbac import Role

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        regular = await s.scalar(select(Role).where(Role.code == "regular_user"))
        regular_id = str(regular.id)

    body = {"code": "audit_viewer", "name": "审计查看员", "parent_role_id": regular_id, "permission_ids": []}
    response = await admin_client.post("/api/roles", json=body, headers=csrf_headers)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["parent_role_id"] == regular_id
    assert data["parent_role_code"] == "regular_user"


async def test_update_role_parent_cycle_rejected(admin_client, csrf_headers, test_engine) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.models.rbac import Role

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        regular = await s.scalar(select(Role).where(Role.code == "regular_user"))
        regular_id = str(regular.id)

    body = {"name": "普通用户", "parent_role_id": regular_id}
    response = await admin_client.put(f"/api/roles/{regular_id}", json=body, headers=csrf_headers)
    assert response.status_code == 400, response.text
    assert "环" in response.json()["message"]


async def test_delete_role_with_children_rejected(admin_client, csrf_headers, test_engine) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.models.rbac import Role

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        regular = await s.scalar(select(Role).where(Role.code == "regular_user"))
        regular_id = str(regular.id)

    parent_resp = await admin_client.post(
        "/api/roles",
        json={
            "code": "delete_guard_parent",
            "name": "删除保护父角色",
            "parent_role_id": regular_id,
            "permission_ids": [],
        },
        headers=csrf_headers,
    )
    assert parent_resp.status_code == 201, parent_resp.text
    parent_id = parent_resp.json()["data"]["id"]

    child_resp = await admin_client.post(
        "/api/roles",
        json={
            "code": "delete_guard_child",
            "name": "删除保护子角色",
            "parent_role_id": parent_id,
            "permission_ids": [],
        },
        headers=csrf_headers,
    )
    assert child_resp.status_code == 201, child_resp.text

    response = await admin_client.delete(f"/api/roles/{parent_id}", headers=csrf_headers)
    assert response.status_code == 400, response.text
    assert "下级" in response.json()["message"]


async def test_list_roles_returns_parent_info(admin_client) -> None:
    response = await admin_client.get("/api/roles?page_size=50")
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    user_manager = next(i for i in items if i["code"] == "user_manager")
    assert user_manager["parent_role_code"] == "regular_user"
    regular = next(i for i in items if i["code"] == "regular_user")
    assert regular["parent_role_id"] is None


# ── Helpers ──────────────────────────────────────────────────────────

async def _db_first(test_engine, stmt):
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        return await s.scalar(stmt)


async def _db_all(test_engine, stmt):
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as s:
        return (await s.execute(stmt)).scalars().all()
