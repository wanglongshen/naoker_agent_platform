from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_user_and_me_contracts_return_role_summary_objects(admin_client) -> None:
    me = await admin_client.get("/api/auth/me")
    assert me.status_code == 200
    assert {"id", "code", "name"} <= set(me.json()["data"]["roles"][0])

    users = await admin_client.get("/api/users")
    assert users.status_code == 200
    assert "request_id" in users.json()
    assert users.headers["X-Request-ID"] == users.json()["request_id"]


async def test_roles_list_contract_envelope(admin_client) -> None:
    resp = await admin_client.get("/api/roles")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "message" in body
    assert "request_id" in body
    assert "X-Request-ID" in resp.headers
    assert body["request_id"] == resp.headers["X-Request-ID"]
    assert body["message"] == "OK"

    data = body["data"]
    assert "items" in data
    assert "page" in data
    assert "page_size" in data
    assert "total" in data
    assert len(data["items"]) > 0

    role = data["items"][0]
    assert {"id", "code", "name", "description", "status", "is_system", "permission_count"} <= set(role)


async def test_role_detail_contract_envelope(admin_client) -> None:
    roles = await admin_client.get("/api/roles")
    role_id = roles.json()["data"]["items"][0]["id"]

    resp = await admin_client.get(f"/api/roles/{role_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"] == resp.headers["X-Request-ID"]

    detail = body["data"]
    assert "permissions" in detail
    assert "assigned_user_count" in detail
    assert isinstance(detail["permissions"], list)


async def test_permissions_list_contract(admin_client) -> None:
    resp = await admin_client.get("/api/permissions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"] == resp.headers["X-Request-ID"]

    permissions = body["data"]
    assert isinstance(permissions, list)
    assert len(permissions) > 0

    perm = permissions[0]
    assert {"id", "code", "name", "module", "description"} <= set(perm)


async def test_user_list_role_references_contract(admin_client) -> None:
    resp = await admin_client.get("/api/users")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["items"]) > 0

    user = data["items"][0]
    assert "roles" in user
    for role in user["roles"]:
        assert {"id", "code", "name"} <= set(role)


async def test_error_response_includes_request_id(admin_client) -> None:
    resp = await admin_client.get("/api/roles/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    body = resp.json()
    assert "request_id" in body
    assert "X-Request-ID" in resp.headers
    assert body["request_id"] == resp.headers["X-Request-ID"]
    assert "code" in body
    assert "message" in body


async def test_unauthenticated_error_has_request_id() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/auth/me")
        assert resp.status_code == 401
        body = resp.json()
        assert "request_id" in body
        assert "X-Request-ID" in resp.headers
        assert body["request_id"] == resp.headers["X-Request-ID"]


async def test_health_endpoint_envelope() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "message" in body
        assert "request_id" in body
        assert body["data"]["status"] == "ok"
        assert "X-Request-ID" in resp.headers
        assert body["request_id"] == resp.headers["X-Request-ID"]


async def test_create_role_201_has_envelope(admin_client) -> None:
    perms = await admin_client.get("/api/permissions")
    perm_id = perms.json()["data"][0]["id"]

    resp = await admin_client.post(
        "/api/roles",
        json={
            "code": "contract_test_role",
            "name": "Contract Test Role",
            "description": "Created by contract test",
            "permission_ids": [perm_id],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "data" in body
    assert "request_id" in body
    assert body["request_id"] == resp.headers["X-Request-ID"]
    assert body["data"]["code"] == "contract_test_role"


async def test_me_returns_assignable_roles_for_admin(admin_client) -> None:
    resp = await admin_client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert "assignable_roles" in body["data"]


async def test_login_envelope(test_db) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/auth/login",
            json={"username": "admin", "password": "ChangeMe-Strong1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "message" in body
        assert "request_id" in body
        assert "X-Request-ID" in resp.headers
        assert body["request_id"] == resp.headers["X-Request-ID"]


async def test_login_error_envelope(test_db) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/auth/login",
            json={"username": "nonexistent_user", "password": "wrong"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert "request_id" in body
        assert body["request_id"] == resp.headers["X-Request-ID"]


async def test_contract_keeps_english_error_code_with_chinese_message(admin_client) -> None:
    response = await admin_client.put(
        "/api/users/00000000-0000-0000-0000-000000000000",
        json={"display_name": "test", "email": None, "phone": None},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "USER_NOT_FOUND"
    assert body["message"] == "用户不存在"
    assert body["request_id"]
