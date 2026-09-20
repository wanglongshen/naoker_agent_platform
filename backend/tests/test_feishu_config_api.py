import uuid

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.main import app
from app.models.rbac import User

settings = get_settings()
TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture
async def admin_client(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={
                "username": settings.initial_admin_username,
                "password": settings.initial_admin_password,
            },
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def ordinary_user(test_db):
    async with test_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"ordinary_{uuid.uuid4().hex[:8]}",
            display_name="Ordinary User",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


@pytest.fixture
async def ordinary_client(test_db, ordinary_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={"username": ordinary_user.username, "password": "Password123"},
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def csrf_headers(admin_client):
    resp = await admin_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


class TestFeishuConfigApi:
    @pytest.mark.anyio
    async def test_non_admin_forbidden(self, ordinary_client, admin_client):
        resp = await ordinary_client.get("/api/feishu/configs")
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_admin_create_and_list(self, admin_client, csrf_headers):
        resp = await admin_client.post(
            "/api/feishu/configs",
            json={"name": "公司A", "app_id": "cli_api_a", "app_secret": "secret-api"},
            headers=csrf_headers,
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["name"] == "公司A"
        assert body["is_default"] is True

        lst = await admin_client.get("/api/feishu/configs")
        assert lst.status_code == 200
        items = lst.json()["data"]["configs"]
        assert len(items) == 1
        assert items[0]["app_id_mask"] == "cli_ap"  # 前 6 位

    @pytest.mark.anyio
    async def test_admin_activate_and_delete(self, admin_client, csrf_headers):
        r1 = await admin_client.post(
            "/api/feishu/configs",
            json={"name": "公司A", "app_id": "cli_a", "app_secret": "s1"},
            headers=csrf_headers,
        )
        r2 = await admin_client.post(
            "/api/feishu/configs",
            json={"name": "公司B", "app_id": "cli_b", "app_secret": "s2"},
            headers=csrf_headers,
        )
        id2 = r2.json()["data"]["id"]
        act = await admin_client.post(f"/api/feishu/configs/{id2}/activate", headers=csrf_headers)
        assert act.status_code == 200
        status = await admin_client.get("/api/feishu/configs/status")
        assert status.json()["data"]["app_id"] == "cli_b"

        d = await admin_client.delete(f"/api/feishu/configs/{id2}", headers=csrf_headers)
        assert d.status_code == 200
        status2 = await admin_client.get("/api/feishu/configs/status")
        assert status2.json()["data"]["app_id"] == "cli_a"

    @pytest.mark.anyio
    async def test_oauth_start_uses_db_config(self, admin_client, csrf_headers, test_engine, monkeypatch):
        from app.core.config import get_settings
        from app.services.feishu import credentials as credentials_module

        factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(credentials_module, "async_session_factory", factory)
        monkeypatch.setattr(get_settings(), "feishu_app_id", "")
        resp = await admin_client.post(
            "/api/feishu/configs",
            json={"name": "公司A", "app_id": "cli_oauth", "app_secret": "s1"},
            headers=csrf_headers,
        )
        assert resp.status_code == 200
        start = await admin_client.get("/api/feishu/oauth/start")
        assert start.status_code == 200
        url = start.json()["data"]["authorize_url"]
        assert "cli_oauth" in url
