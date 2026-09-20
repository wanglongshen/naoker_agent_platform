from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.feishu.credentials import get_feishu_credentials

logger = logging.getLogger("feishu_client")

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


class FeishuClient:
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self.timeout = httpx.Timeout(timeout_seconds)

    async def _creds(self) -> tuple[str, str]:
        return await get_feishu_credentials()

    async def _post(self, path: str, json: dict | None = None, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{FEISHU_API_BASE}{path}", json=json, headers=headers)
            if not resp.is_success:
                logger.warning(
                    "feishu_api_error",
                    extra={"path": path, "status": resp.status_code, "body": resp.text[:500]},
                )
            resp.raise_for_status()
            return resp.json()

    async def _get(self, path: str, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{FEISHU_API_BASE}{path}", headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def _patch(self, path: str, json: dict | None = None, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.patch(f"{FEISHU_API_BASE}{path}", json=json, headers=headers)
            resp.raise_for_status()
            return resp.json()

    # ── OAuth ──────────────────────────────────────

    async def exchange_code(self, code: str) -> dict:
        from app.core.config import get_settings

        app_id, app_secret = await self._creds()
        settings = get_settings()
        return await self._post(
            "/authen/v2/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": app_id,
                "client_secret": app_secret,
                "code": code,
                "redirect_uri": settings.feishu_redirect_uri,
            },
        )

    async def refresh_access_token(self, refresh_token: str) -> dict:
        app_id, app_secret = await self._creds()
        return await self._post(
            "/authen/v1/refresh_access_token",
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "app_id": app_id,
                "app_secret": app_secret,
            },
        )

    async def revoke_token(self, access_token: str) -> dict:
        """尽力吊销 user_access_token；失败由调用方吞掉（本地删除不依赖飞书侧成功）。"""
        app_id, app_secret = await self._creds()
        return await self._post(
            "/authen/v1/revoke",
            json={
                "app_id": app_id,
                "app_secret": app_secret,
                "token": access_token,
            },
        )

    # ── Documents ──────────────────────────────────

    def _auth_headers(self, access_token: str) -> dict:
        return {"Authorization": f"Bearer {access_token}"}

    async def read_document(self, doc_token: str, access_token: str) -> dict:
        return await self._get(
            f"/docx/v1/documents/{doc_token}/raw_content",
            headers=self._auth_headers(access_token),
        )

    async def create_document(self, title: str, access_token: str) -> dict:
        return await self._post(
            "/docx/v1/documents",
            json={"title": title},
            headers=self._auth_headers(access_token),
        )

    async def add_blocks(self, doc_id: str, blocks: list[dict], access_token: str) -> dict:
        return await self._post(
            f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            json={"children": blocks},
            headers=self._auth_headers(access_token),
        )

    async def update_block(self, doc_id: str, block_id: str, text: str, access_token: str) -> dict:
        return await self._patch(
            f"/docx/v1/documents/{doc_id}/blocks/{block_id}",
            json={
                "replace_text": {
                    "text": text,
                    "items": [{"text": text}],
                }
            },
            headers=self._auth_headers(access_token),
        )

    async def set_public_permission(self, doc_token: str, access_token: str) -> dict:
        return await self._patch(
            f"/drive/v1/permissions/{doc_token}/public",
            json={
                "link_share_entity": "anyone_readable",
                "external_access_entity": "open",
            },
            headers=self._auth_headers(access_token),
        )
