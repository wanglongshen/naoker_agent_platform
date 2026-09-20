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
async def admin_user(test_db):
    from sqlalchemy import select

    async with test_db() as db:
        user = await db.scalar(
            select(User).where(User.username == settings.initial_admin_username)
        )
        assert user is not None
        return user


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
async def csrf_headers(ordinary_client):
    resp = await ordinary_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


@pytest.fixture
async def admin_csrf_headers(admin_client):
    resp = await admin_client.get("/api/auth/csrf")
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    return {"X-CSRF-Token": token}


class TestPointsService:
    @pytest.mark.anyio
    async def test_tokens_to_points_rounds_up(self, monkeypatch):
        from app.services.points import tokens_to_points
        monkeypatch.setattr("app.services.points.settings.points_tokens_per_point", 10000)
        assert tokens_to_points(0) == 0
        assert tokens_to_points(1) == 1
        assert tokens_to_points(9999) == 1
        assert tokens_to_points(10000) == 1
        assert tokens_to_points(10001) == 2

    @pytest.mark.anyio
    async def test_get_or_create_grants_initial(self, test_db, ordinary_user):
        from app.services.points import get_or_create_points
        async with test_db() as db:
            points = await get_or_create_points(db, ordinary_user.id)
            assert points.balance == 1000
            # 再次调用不重复送
            points2 = await get_or_create_points(db, ordinary_user.id)
            assert points2.balance == 1000

    @pytest.mark.anyio
    async def test_deduct_atomic_and_records_transaction(
        self, test_db, ordinary_user, monkeypatch
    ):
        from sqlalchemy import select

        from app.models.points import PointTransaction, UserPoints
        from app.services.points import deduct_for_run, get_or_create_points
        monkeypatch.setattr("app.services.points.settings.points_tokens_per_point", 10000)
        async with test_db() as db:
            await get_or_create_points(db, ordinary_user.id)  # balance 1000
            pts = await deduct_for_run(db, ordinary_user.id, uuid.uuid4(), 25000)  # 3 积点
            assert pts == 3
            row = await db.get(UserPoints, ordinary_user.id)
            assert row.balance == 997
            assert row.total_consumed == 3
            tx = (await db.execute(
                select(PointTransaction).where(PointTransaction.type == "consume")
            )).scalar_one()
            assert tx.amount == -3
            assert tx.tokens == 25000

    @pytest.mark.anyio
    async def test_deduct_insufficient_raises(self, test_db, ordinary_user, monkeypatch):
        from app.services.points import InsufficientPointsError, deduct_for_run, get_or_create_points
        monkeypatch.setattr("app.services.points.settings.points_tokens_per_point", 10000)
        async with test_db() as db:
            await get_or_create_points(db, ordinary_user.id)  # balance 1000
            await deduct_for_run(db, ordinary_user.id, uuid.uuid4(), 999 * 10000)  # 扣 999 → 余 1
            with pytest.raises(InsufficientPointsError):
                await deduct_for_run(db, ordinary_user.id, uuid.uuid4(), 2 * 10000)  # 需 2 > 余 1

    @pytest.mark.anyio
    async def test_redeem_code_flow(self, test_db, ordinary_user, admin_user):
        from app.models.points import RedeemCode, UserPoints
        from app.services.points import redeem_code
        async with test_db() as db:
            db.add(RedeemCode(code="ABCD-EFGH-IJKL", points=500, created_by=admin_user.id))
            await db.commit()
        async with test_db() as db:
            result = await redeem_code(db, ordinary_user.id, "ABCD-EFGH-IJKL")
            assert result["points"] == 500
            row = await db.get(UserPoints, ordinary_user.id)
            assert row.balance == 1500  # 1000 初始 + 500
        async with test_db() as db:
            from app.services.points import RedeemCodeError
            with pytest.raises(RedeemCodeError):
                await redeem_code(db, ordinary_user.id, "ABCD-EFGH-IJKL")  # 重复
            with pytest.raises(RedeemCodeError):
                await redeem_code(db, ordinary_user.id, "NOPE-NOPE-NOPE")  # 无效


class TestPointsApi:
    @pytest.mark.anyio
    async def test_me_returns_balance_and_recent(
        self, test_db, ordinary_client, ordinary_user
    ):
        resp = await ordinary_client.get("/api/points/me")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["balance"] == 1000
        assert isinstance(data["recent"], list)

    @pytest.mark.anyio
    async def test_redeem_api(self, test_db, ordinary_client, ordinary_user, admin_user, csrf_headers):
        from app.models.points import RedeemCode
        async with test_db() as db:
            db.add(RedeemCode(code="WXYZ-1234-5678", points=300, created_by=admin_user.id))
            await db.commit()
        resp = await ordinary_client.post(
            "/api/points/redeem", json={"code": "WXYZ-1234-5678"}, headers=csrf_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["points"] == 300
        bad = await ordinary_client.post(
            "/api/points/redeem", json={"code": "BAD-BAD-BAD"}, headers=csrf_headers
        )
        assert bad.status_code == 400

    @pytest.mark.anyio
    async def test_usage_returns_full_30_days_with_zero_fill(
        self, test_db, ordinary_client, ordinary_user
    ):
        resp = await ordinary_client.get("/api/points/usage")
        assert resp.status_code == 200, resp.text
        days = resp.json()["data"]["days"]
        assert len(days) == 30
        assert all(d["tokens"] == 0 and d["points"] == 0 for d in days)
        dates = [d["date"] for d in days]
        assert dates == sorted(dates)
        from datetime import UTC, datetime, timedelta
        assert dates[-1] == (datetime.now(UTC) - timedelta(seconds=10)).date().isoformat() or dates[-1] == datetime.now(UTC).date().isoformat()

    @pytest.mark.anyio
    async def test_usage_includes_consume_day_tokens(
        self, test_db, ordinary_client, ordinary_user, monkeypatch
    ):
        from datetime import UTC, datetime, timedelta

        from app.models.points import PointTransaction
        from app.services.points import tokens_to_points
        monkeypatch.setattr("app.services.points.settings.points_tokens_per_point", 10000)
        async with test_db() as db:
            db.add(PointTransaction(
                user_id=ordinary_user.id,
                amount=-1,
                type="consume",
                tokens=189,
                created_at=datetime.now(UTC) - timedelta(days=2),
            ))
            await db.commit()
        resp = await ordinary_client.get("/api/points/usage")
        days = resp.json()["data"]["days"]
        assert len(days) == 30
        hit = [d for d in days if d["tokens"] == 189]
        assert len(hit) == 1
        assert hit[0]["points"] == -1
        assert len([d for d in days if d["tokens"] == 0]) == 29

    @pytest.mark.anyio
    async def test_admin_grant_and_codes(
        self, test_db, admin_client, ordinary_user, admin_csrf_headers
    ):
        resp = await admin_client.post(
            "/api/admin/points/grant",
            json={"user_id": str(ordinary_user.id), "points": 200, "description": "补偿"},
            headers=admin_csrf_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["balance"] == 1200
        codes = await admin_client.post(
            "/api/admin/redeem-codes", json={"points": 100, "count": 2}, headers=admin_csrf_headers
        )
        assert codes.status_code == 200
        assert len(codes.json()["data"]["codes"]) == 2
        lst = await admin_client.get("/api/admin/redeem-codes")
        assert lst.status_code == 200
        assert lst.json()["data"]["total"] == 2

    @pytest.mark.anyio
    async def test_admin_endpoints_forbidden_for_employee(
        self, test_db, ordinary_client, csrf_headers
    ):
        resp = await ordinary_client.post(
            "/api/admin/points/grant",
            json={"user_id": str(uuid.uuid4()), "points": 1, "description": ""},
            headers=csrf_headers,
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.anyio
    async def test_run_create_blocked_when_insufficient(
        self, test_db, ordinary_client, ordinary_user, csrf_headers
    ):
        from app.models.points import UserPoints
        async with test_db() as db:
            row = await db.get(UserPoints, ordinary_user.id)
            if row is None:
                row = UserPoints(user_id=ordinary_user.id, balance=0)
                db.add(row)
            else:
                row.balance = 0
            await db.commit()
        # 创建 session + run
        resp = await ordinary_client.post(
            "/api/agent/sessions", json={"title": "测试"}, headers=csrf_headers
        )
        assert resp.status_code == 201, resp.text
        session_id = resp.json()["data"]["id"]
        run_resp = await ordinary_client.post(
            f"/api/agent/sessions/{session_id}/runs",
            json={"goal": "写方案", "network_enabled": True},
            headers=csrf_headers,
        )
        assert run_resp.status_code == 400
        assert run_resp.json()["code"] == "INSUFFICIENT_POINTS"
