"""connector 平台 token 续签 + 平台侧身份加固。

不连真实 DB/网络：`refresh_injection` 用 monkeypatch 拦截 `ensure_home_config`；
依赖校验只走 subject mismatch 分支（在访问 DB 之前抛错）。
"""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.anyio
async def test_refresh_injection_rewrites_patch_with_fresh_token(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.core.security import decode_platform_token
    from app.services.dsh import instance_config

    settings = get_settings()
    monkeypatch.setattr(settings, "dsh_home_root", str(tmp_path))
    monkeypatch.setattr(settings, "dsh_platform_base", "http://localhost:8000")
    calls = {}

    def fake_ensure_home_config(home_dir, **kwargs):
        calls["home"] = home_dir
        calls.update(kwargs)

    monkeypatch.setattr(instance_config, "ensure_home_config", fake_ensure_home_config)
    from app.services.dsh.instance_manager import DshInstanceManager

    manager = DshInstanceManager()
    user_id = uuid.uuid4()
    await manager.refresh_injection(user_id, db=None)

    assert calls["home"] == tmp_path / str(user_id)
    assert calls["platform_token"]
    assert calls["user_id"] == str(user_id)
    assert calls["platform_base"] == "http://localhost:8000"
    assert decode_platform_token(calls["platform_token"]) == str(user_id)


@pytest.mark.anyio
async def test_platform_token_subject_mismatch_is_rejected():
    from starlette.requests import Request

    from app.core import dependencies
    from app.core.errors import ApiError
    from app.core.security import mint_platform_token

    owner = uuid.uuid4()
    token = mint_platform_token(str(owner), 300)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/dsh/sessions",
            "headers": [
                (b"x-platform-token", token.encode()),
                (b"x-dsh-platform-user", str(uuid.uuid4()).encode()),
            ],
        }
    )

    with pytest.raises(ApiError) as exc:
        await dependencies.get_current_user(request, db=None)

    assert exc.value.status_code == 401


@pytest.mark.anyio
async def test_platform_token_subject_match_passes_check():
    from starlette.requests import Request

    from app.core import dependencies
    from app.core.security import mint_platform_token

    owner = uuid.uuid4()
    token = mint_platform_token(str(owner), 300)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/dsh/sessions",
            "headers": [
                (b"x-platform-token", token.encode()),
                (b"x-dsh-platform-user", str(owner).encode()),
            ],
        }
    )

    class StopDb:
        async def scalar(self, stmt):
            raise RuntimeError("reached-db")

    with pytest.raises(RuntimeError, match="reached-db"):
        await dependencies.get_current_user(request, db=StopDb())
