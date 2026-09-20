import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_status_route_requires_auth():
    client = TestClient(app)
    r = client.get("/api/agent/login-sessions/abc/status")
    assert r.status_code in (401, 403)


def test_frame_route_requires_auth():
    client = TestClient(app)
    r = client.get("/api/agent/login-sessions/abc/frame")
    assert r.status_code in (401, 403)


def test_start_route_requires_auth():
    client = TestClient(app)
    r = client.post("/api/agent/login-sessions", json={"platform": "douyin"})
    assert r.status_code in (401, 403)


def test_refresh_route_requires_auth():
    client = TestClient(app)
    r = client.post("/api/agent/login-sessions/abc/refresh")
    assert r.status_code in (401, 403)


def test_delete_route_requires_auth():
    client = TestClient(app)
    r = client.delete("/api/agent/login-sessions/abc")
    assert r.status_code in (401, 403)
