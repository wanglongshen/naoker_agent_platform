from __future__ import annotations

import uuid

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.models.rbac import User

settings = get_settings()

TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture
async def user_a(test_db):
    async with test_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"tc_a_{uuid.uuid4().hex[:8]}",
            display_name="Task Chain User A",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


@pytest.fixture
async def user_b(test_db):
    async with test_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"tc_b_{uuid.uuid4().hex[:8]}",
            display_name="Task Chain User B",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


async def _login(user, password="Password123"):
    transport = ASGITransport(app=app)
    ac = AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    )
    response = await ac.post(
        "/api/auth/login",
        json={"username": user.username, "password": password},
    )
    assert response.status_code == 200
    return ac


@pytest.fixture
async def client_a(test_db, user_a):
    ac = await _login(user_a)
    yield ac
    await ac.aclose()


@pytest.fixture
async def client_b(test_db, user_b):
    ac = await _login(user_b)
    yield ac
    await ac.aclose()


async def _csrf_headers(client) -> dict[str, str]:
    response = await client.get("/api/auth/csrf")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["data"]["token"]}


async def _create_chain(client, goal="写一份方案", payload=None) -> dict:
    headers = await _csrf_headers(client)
    response = await client.post(
        "/api/task-chains",
        json={"goal": goal, "input_payload": payload or {}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_create_list_detail_cancel_flow(test_db, client_a):
    data = await _create_chain(client_a, payload={"brand": "X"})
    assert data["status"] == "queued"
    assert data["goal"] == "写一份方案"
    assert data["input_payload"] == {"brand": "X"}
    assert data["stages"] == []
    chain_id = data["id"]

    listing = await client_a.get("/api/task-chains")
    assert listing.status_code == 200
    page = listing.json()["data"]
    assert page["total"] == 1
    assert page["items"][0]["id"] == chain_id

    detail = await client_a.get(f"/api/task-chains/{chain_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "queued"

    headers = await _csrf_headers(client_a)
    cancel = await client_a.post(
        f"/api/task-chains/{chain_id}/cancel", headers=headers
    )
    assert cancel.status_code == 200
    assert cancel.json()["data"]["status"] == "cancelled"
    assert cancel.json()["data"]["finished_at"] is not None

    again = await client_a.post(
        f"/api/task-chains/{chain_id}/cancel", headers=headers
    )
    assert again.status_code == 409


async def test_detail_includes_stages(test_db, client_a):
    from app.repositories.task_chain_repository import TaskChainRepository

    data = await _create_chain(client_a)
    async with test_db() as s:
        repo = TaskChainRepository(s)
        stage = await repo.add_stage(
            chain_id=uuid.UUID(data["id"]), stage="research_agenda", seq=1
        )
        await repo.update_stage(
            stage.id, status="succeeded", output_payload={"topics": ["a"]}
        )

    detail = await client_a.get(f"/api/task-chains/{data['id']}")
    assert detail.status_code == 200
    stages = detail.json()["data"]["stages"]
    assert len(stages) == 1
    assert stages[0]["stage"] == "research_agenda"
    assert stages[0]["status"] == "succeeded"
    assert stages[0]["output_payload"] == {"topics": ["a"]}


async def test_other_user_gets_404_and_own_list_scoped(
    test_db, client_a, client_b
):
    data = await _create_chain(client_a)
    chain_id = data["id"]

    detail = await client_b.get(f"/api/task-chains/{chain_id}")
    assert detail.status_code == 404

    headers = await _csrf_headers(client_b)
    cancel = await client_b.post(
        f"/api/task-chains/{chain_id}/cancel", headers=headers
    )
    assert cancel.status_code == 404

    listing = await client_b.get("/api/task-chains")
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 0


async def test_create_requires_login(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    ) as ac:
        response = await ac.post(
            "/api/task-chains", json={"goal": "写一份方案", "input_payload": {}}
        )
    assert response.status_code == 401


async def test_create_requires_csrf(test_db, client_a):
    response = await client_a.post(
        "/api/task-chains", json={"goal": "写一份方案", "input_payload": {}}
    )
    assert response.status_code == 403


async def test_create_rejects_empty_goal(test_db, client_a):
    headers = await _csrf_headers(client_a)
    response = await client_a.post(
        "/api/task-chains",
        json={"goal": "   ", "input_payload": {}},
        headers=headers,
    )
    assert response.status_code == 422


async def test_create_rejects_insufficient_points(test_db, client_a, user_a):
    from app.models.points import UserPoints

    async with test_db() as s:
        s.add(UserPoints(user_id=user_a.id, balance=0, total_granted=0, total_consumed=0))
        await s.commit()

    headers = await _csrf_headers(client_a)
    response = await client_a.post(
        "/api/task-chains",
        json={"goal": "写一份方案", "input_payload": {}},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INSUFFICIENT_POINTS"
