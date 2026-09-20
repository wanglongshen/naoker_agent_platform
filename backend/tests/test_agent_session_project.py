import uuid

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.main import app
from app.models.rbac import User

TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture
async def admin_user(test_db):
    settings = get_settings()
    async with test_db() as s:
        user = await s.scalar(
            select(User).where(User.username == settings.initial_admin_username)
        )
        assert user is not None
        return user


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
        transport=transport,
        base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        response = await ac.post(
            "/api/auth/login",
            json={"username": ordinary_user.username, "password": "Password123"},
        )
        assert response.status_code == 200
        yield ac


@pytest.fixture
async def csrf_headers(ordinary_client):
    resp = await ordinary_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


class TestSessionProject:
    @pytest.mark.anyio
    async def test_create_session_with_project(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            folder = FileFolder(owner_user_id=ordinary_user.id, name="项目A", depth=0)
            db.add(folder)
            await db.commit()
            folder_id = folder.id

        resp = await ordinary_client.post(
            "/api/agent/sessions",
            json={"title": "测试", "project_folder_id": str(folder_id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["project_folder_id"] == str(folder_id)

    @pytest.mark.anyio
    async def test_create_session_rejects_non_top_level_folder(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            root = FileFolder(owner_user_id=ordinary_user.id, name="根", depth=0)
            db.add(root)
            await db.flush()
            child = FileFolder(
                owner_user_id=ordinary_user.id,
                name="子",
                depth=1,
                parent_folder_id=root.id,
            )
            db.add(child)
            await db.commit()
            child_id = child.id

        resp = await ordinary_client.post(
            "/api/agent/sessions",
            json={"title": "测试", "project_folder_id": str(child_id)},
            headers=csrf_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_create_session_rejects_others_folder(
        self, test_db, ordinary_client, ordinary_user, admin_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            folder = FileFolder(owner_user_id=admin_user.id, name="别人的文件夹", depth=0)
            db.add(folder)
            await db.commit()
            folder_id = folder.id

        resp = await ordinary_client.post(
            "/api/agent/sessions",
            json={"title": "测试", "project_folder_id": str(folder_id)},
            headers=csrf_headers,
        )
        assert resp.status_code in (400, 403)

    @pytest.mark.anyio
    async def test_switch_project_and_unbind(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            a = FileFolder(owner_user_id=ordinary_user.id, name="项目A", depth=0)
            b = FileFolder(owner_user_id=ordinary_user.id, name="项目B", depth=0)
            db.add_all([a, b])
            await db.commit()
            a_id, b_id = a.id, b.id

        resp = await ordinary_client.post(
            "/api/agent/sessions", json={"title": "测试"}, headers=csrf_headers
        )
        session_id = resp.json()["data"]["id"]

        switch = await ordinary_client.put(
            f"/api/agent/sessions/{session_id}/project",
            json={"project_folder_id": str(a_id)},
            headers=csrf_headers,
        )
        assert switch.status_code == 200, switch.text
        assert switch.json()["data"]["project_folder_id"] == str(a_id)
        assert switch.json()["data"]["project_name"] == "项目A"

        unbind = await ordinary_client.put(
            f"/api/agent/sessions/{session_id}/project",
            json={"project_folder_id": None},
            headers=csrf_headers,
        )
        assert unbind.status_code == 200
        assert unbind.json()["data"]["project_folder_id"] is None

    @pytest.mark.anyio
    async def test_run_creation_snapshots_project(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.file import FileFolder

        async with test_db() as db:
            a = FileFolder(owner_user_id=ordinary_user.id, name="项目A", depth=0)
            db.add(a)
            await db.commit()
            a_id = a.id

        resp = await ordinary_client.post(
            "/api/agent/sessions",
            json={"title": "测试", "project_folder_id": str(a_id)},
            headers=csrf_headers,
        )
        session_id = resp.json()["data"]["id"]

        run_resp = await ordinary_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "写方案", "network_enabled": True},
            headers=csrf_headers,
        )
        assert run_resp.status_code == 201, run_resp.text
        from app.models.agent import AgentRun

        async with test_db() as db:
            run = await db.get(AgentRun, uuid.UUID(run_resp.json()["data"]["id"]))
            assert str(run.project_folder_id) == str(a_id)
