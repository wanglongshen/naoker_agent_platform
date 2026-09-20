from __future__ import annotations

import secrets
from urllib.parse import urlencode

from app.core.config import get_settings

FEISHU_AUTHORIZE_BASE = "https://open.feishu.cn/open-apis/authen/v1/authorize"


def build_authorize_url(app_id: str, state: str | None = None) -> str:
    settings = get_settings()
    params = {
        "app_id": app_id,
        "redirect_uri": settings.feishu_redirect_uri,
        "scope": "docx:document:readonly docx:document",
        "state": state or secrets.token_urlsafe(32),
    }
    return f"{FEISHU_AUTHORIZE_BASE}?{urlencode(params)}"
