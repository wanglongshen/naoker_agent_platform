import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.services.agent.web_cookie_store import _key
from app.services.feishu.crypto import decrypt_token, encrypt_token

settings = get_settings()

TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture
async def admin_client(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
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
async def csrf_headers(admin_client):
    resp = await admin_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


@pytest.fixture
async def cookie_store_db(test_db, monkeypatch):
    from app.services.agent import web_cookie_store as wcs

    monkeypatch.setattr(wcs, "async_session_factory", test_db)
    return test_db


class TestWebCookieKey:
    def test_key_derivation_stable(self):
        k1 = _key()
        k2 = _key()
        assert k1 == k2

    def test_encrypt_decrypt_round_trip(self):
        key = _key()
        ct = encrypt_token("sessionid=abc; uid=123", key)
        assert decrypt_token(ct, key) == "sessionid=abc; uid=123"


class TestCookieImport:
    async def test_import_groups_by_platform_and_saves(
        self, admin_client, csrf_headers, cookie_store_db
    ):
        resp = await admin_client.post(
            "/api/agent/cookies/import",
            json={
                "cookies": [
                    {"name": "sessionid", "value": "abc", "domain": ".douyin.com"},
                    {"name": "UIFID", "value": "xyz", "domain": "www.douyin.com"},
                    {"name": "id_token", "value": "tkn", "domain": ".xiaohongshu.com"},
                ]
            },
            headers=csrf_headers,
        )
        assert resp.status_code == 200
        saved = resp.json()["data"]["saved"]
        assert saved == {"douyin": 2, "xiaohongshu": 1}

    async def test_import_rejects_foreign_domain(self, admin_client, csrf_headers):
        resp = await admin_client.post(
            "/api/agent/cookies/import",
            json={
                "cookies": [
                    {"name": "x", "value": "y", "domain": "https://evil.com"}
                ]
            },
            headers=csrf_headers,
        )
        assert resp.status_code == 422

    async def test_import_rejects_invalid_items(self, admin_client, csrf_headers):
        resp = await admin_client.post(
            "/api/agent/cookies/import",
            json={
                "cookies": [
                    {"name": "", "value": "v", "domain": ".douyin.com"},
                    {"name": "ok", "value": "", "domain": ".douyin.com"},
                ]
            },
            headers=csrf_headers,
        )
        assert resp.status_code == 422

    async def test_import_requires_csrf(self, admin_client):
        resp = await admin_client.post(
            "/api/agent/cookies/import",
            json={"cookies": [{"name": "x", "value": "y", "domain": ".douyin.com"}]},
        )
        assert resp.status_code in (401, 403)
