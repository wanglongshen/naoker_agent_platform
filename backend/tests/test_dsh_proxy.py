import asyncio
import json
import uuid

import pytest
from argon2 import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.seed import seed_rbac
from app.db.session import get_db
from app.main import app
from app.models.base import Base
from app.models.dsh import DshInstance
from app.models.rbac import User

settings = get_settings()

TEST_ORIGIN = "http://localhost:3000"


@pytest.fixture
async def api_db(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as s:
        await seed_rbac(s)
        await s.commit()

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    yield session_factory

    app.dependency_overrides.clear()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def admin_client(api_db):
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
async def user_a(api_db):
    async with api_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"dsh_pa_{uuid.uuid4().hex[:8]}",
            display_name="DSH Proxy User A",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


@pytest.fixture
async def user_b(api_db):
    async with api_db() as s:
        ph = PasswordHasher()
        user = User(
            username=f"dsh_pb_{uuid.uuid4().hex[:8]}",
            display_name="DSH Proxy User B",
            password_hash=ph.hash("Password123"),
            status="active",
        )
        s.add(user)
        await s.commit()
        return user


async def _login(user, password="Password123"):
    transport = ASGITransport(app=app)
    ac = AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Origin": TEST_ORIGIN},
    )
    response = await ac.post(
        "/api/auth/login",
        json={"username": user.username, "password": password},
    )
    assert response.status_code == 200
    return ac


@pytest.fixture
async def client_a(api_db, user_a):
    ac = await _login(user_a)
    yield ac
    await ac.aclose()


@pytest.fixture
async def client_b(api_db, user_b):
    ac = await _login(user_b)
    yield ac
    await ac.aclose()


class StubManager:
    """无真实 spawn 的 get_manager 替身：instance 由测试注入，记录 get/touch。"""

    def __init__(self):
        self.instance: DshInstance | None = None
        self.get_calls: list = []
        self.touch_calls: list = []

    async def get(self, user_id, db):
        self.get_calls.append(user_id)
        return self.instance

    async def check_alive(self, user_id, db):
        self.get_calls.append(user_id)
        return self.instance

    async def touch(self, user_id, db):
        self.touch_calls.append(user_id)


@pytest.fixture
def stub_manager(api_db):
    from app.services.dsh import get_manager as real_get_manager

    stub = StubManager()
    app.dependency_overrides[real_get_manager] = lambda: stub
    yield stub
    app.dependency_overrides.pop(real_get_manager, None)


class FakeUpstream:
    """本机假 DSH 上游：HTTP/1.1 200，记录收到的请求，body 含 path/method/host。"""

    def __init__(self):
        self.seen = {"method": [], "path": [], "query": [], "host": []}
        self.servers = []

    async def start(self) -> int:
        server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.servers.append(server)
        return server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        raw = head.decode("iso-8859-1")
        lines = raw.split("\r\n")
        method, uri, _version = lines[0].split(" ")
        path, _, query = uri.partition("?")
        headers = {}
        for line in lines[1:]:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        body = b""
        if "content-length" in headers:
            body = await reader.readexactly(int(headers["content-length"]))
        self.seen["method"].append(method)
        self.seen["path"].append(path)
        self.seen["query"].append(query)
        self.seen["host"].append(headers.get("host"))
        payload = json.dumps(
            {
                "ok": True,
                "path": path,
                "method": method,
                "host": headers.get("host"),
                "body": body.decode("utf-8") if body else None,
            }
        ).encode("utf-8")
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            + b"Content-Length: "
            + str(len(payload)).encode("ascii")
            + b"\r\n"
            b"X-Dsh-Upstream: yes-value\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            + payload
        )
        await writer.drain()
        writer.close()


@pytest.fixture
async def fake_upstream():
    upstream = FakeUpstream()
    yield upstream
    for server in upstream.servers:
        server.close()


def _running_instance(user_id, port):
    return DshInstance(user_id=user_id, port=port, state="running", pid=1)


async def test_proxy_requires_login(api_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/dsh-proxy/u-1/x")
    assert response.status_code == 401


async def test_proxy_non_owner_404(client_a, user_b, stub_manager):
    response = await client_a.get(f"/api/dsh-proxy/{user_b.id}/x")
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert stub_manager.get_calls == []


async def test_proxy_instance_missing_404(client_a, user_a, stub_manager):
    response = await client_a.get(f"/api/dsh-proxy/{user_a.id}/x")
    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_proxy_forwards_to_instance_passthrough(
    client_a, user_a, stub_manager, fake_upstream
):
    port = await fake_upstream.start()
    stub_manager.instance = _running_instance(user_a.id, port)
    response = await client_a.get(f"/api/dsh-proxy/{user_a.id}/x")
    assert response.status_code == 200
    assert response.headers["x-dsh-upstream"] == "yes-value"
    data = response.json()
    assert data == {
        "ok": True,
        "path": "/x",
        "method": "GET",
        "host": "test",
        "body": None,
    }
    assert fake_upstream.seen["path"] == ["/x"]
    assert fake_upstream.seen["host"] == ["test"]


async def test_proxy_preserves_query_string(
    client_a, user_a, stub_manager, fake_upstream
):
    port = await fake_upstream.start()
    stub_manager.instance = _running_instance(user_a.id, port)
    response = await client_a.get(
        f"/api/dsh-proxy/{user_a.id}/api/session?x=1&y=two"
    )
    assert response.status_code == 200
    assert fake_upstream.seen["path"] == ["/api/session"]
    assert fake_upstream.seen["query"] == ["x=1&y=two"]


async def test_proxy_post_forwards_body_and_method(
    client_a, user_a, stub_manager, fake_upstream
):
    port = await fake_upstream.start()
    stub_manager.instance = _running_instance(user_a.id, port)
    response = await client_a.post(
        f"/api/dsh-proxy/{user_a.id}/echo", json={"hello": 1}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["method"] == "POST"
    assert data["path"] == "/echo"
    assert json.loads(data["body"]) == {"hello": 1}
    assert fake_upstream.seen["method"] == ["POST"]


async def test_proxy_touches_activity_after_forward(
    client_a, user_a, stub_manager, fake_upstream
):
    port = await fake_upstream.start()
    stub_manager.instance = _running_instance(user_a.id, port)
    response = await client_a.get(f"/api/dsh-proxy/{user_a.id}/x")
    assert response.status_code == 200
    assert stub_manager.touch_calls == [user_a.id]
