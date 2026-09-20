import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.services.feishu.oauth import build_authorize_url


class TestAuthorizeUrl:
    def test_builds_feishu_authorize_url(self, monkeypatch):
        from app.core.config import get_settings
        monkeypatch.setattr(get_settings(), "feishu_redirect_uri", "http://localhost:3000/cb")
        url = build_authorize_url("cli_test123", "state-xyz")
        assert "open.feishu.cn" in url
        assert "cli_test123" in url
        assert "state-xyz" in url
        assert "redirect_uri" in url


class TestOauthCallback:
    """回调必须重定向回前端页面，不能直接返回 JSON（否则浏览器空白页）。"""

    async def test_callback_redirects_to_frontend_on_success(
        self, admin_client, monkeypatch
    ):
        from app.services.feishu.client import FeishuClient

        monkeypatch.setattr(
            FeishuClient,
            "exchange_code",
            AsyncMock(
                return_value={
                    "data": {
                        "access_token": "at-token",
                        "refresh_token": "rt-token",
                        "expires_in": 7200,
                        "open_id": "ou_123",
                    }
                }
            ),
        )
        resp = await admin_client.get(
            "/api/feishu/oauth/callback?code=test-code&state=test-state",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        location = resp.headers.get("location", "")
        assert "/agent" in location
        assert "feishu=connected" in location

    async def test_callback_redirects_with_error_on_exchange_failure(
        self, admin_client, monkeypatch
    ):
        from app.services.feishu.client import FeishuClient

        monkeypatch.setattr(
            FeishuClient,
            "exchange_code",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        resp = await admin_client.get(
            "/api/feishu/oauth/callback?code=bad&state=test-state",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        location = resp.headers.get("location", "")
        assert "/agent" in location
        assert "feishu=error" in location
