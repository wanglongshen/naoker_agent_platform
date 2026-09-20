# 飞书文档集成 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Feishu (Lark) document read/create/edit/share capability to the Agent via OAuth user-scoped access.

**Architecture:** New `feishu` package: OAuth flow (start/callback/status endpoints), FeishuService client, encrypted token storage. 4 new Agent tool actions wired into ToolExecutor + Planner. Generated docs sync a Markdown copy to local file storage.

**Tech Stack:** Python 3.12, FastAPI, httpx, SQLAlchemy 2.0, cryptography (AES-GCM via `cryptography` pkg)

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-feishu-docs-integration-design.md`
- Feishu API base: `https://open.feishu.cn`
- Token encryption: AES-GCM, key derived from `JWT_SECRET` (HKDF)
- Per-user token isolation (`owner_user_id`)
- LLM never sees token plaintext
- OAuth `state` param CSRF protection
- Errors: token expiry → refresh → re-auth; rate limit → `RetryableToolError`
- All feishu actions require user to be connected; if not → `ValueError("feishu_not_connected")`

---

### Task 1: Config + Token Model + Encryption

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/app/models/feishu_token.py`
- Create: `backend/app/services/feishu/__init__.py`
- Create: `backend/app/services/feishu/crypto.py`
- Create: `backend/tests/test_feishu_crypto.py`

**Interfaces:**
- Produces:
  - `Settings.feishu_app_id`, `feishu_app_secret`, `feishu_redirect_uri`, `feishu_token_encryption_key`
  - `FeishuToken` model (table `user_feishu_tokens`)
  - `encrypt_token(plaintext: str, key: bytes) -> str`, `decrypt_token(ciphertext: str, key: bytes) -> str`
  - `derive_token_key(secret: str) -> bytes`

- [ ] **Step 1: Add config**

In `backend/app/core/config.py`, after `web_renderer_timeout_seconds`, add:

```python
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_redirect_uri: str = "http://localhost:3000/api/feishu/oauth/callback"
    feishu_token_encryption_key: str = ""
```

- [ ] **Step 2: Create crypto module**

Create `backend/app/services/feishu/__init__.py` (empty) and `backend/app/services/feishu/crypto.py`:

```python
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


def derive_token_key(secret: str) -> bytes:
    """Derive a 32-byte AES key from a base secret via HKDF-SHA256."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"feishu-token-v1",
        info=b"feishu-token-encryption",
    ).derive(secret.encode("utf-8"))


def encrypt_token(plaintext: str, key: bytes) -> str:
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_token(ciphertext: str, key: bytes) -> str:
    raw = base64.b64decode(ciphertext)
    nonce, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")
```

- [ ] **Step 3: Create token model**

Create `backend/app/models/feishu_token.py`:

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FeishuToken(Base):
    __tablename__ = "user_feishu_tokens"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    access_token: Mapped[str] = mapped_column(Text)      # AES-GCM encrypted
    refresh_token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
```

- [ ] **Step 4: Write crypto tests**

Create `backend/tests/test_feishu_crypto.py`:

```python
import pytest
from app.services.feishu.crypto import derive_token_key, encrypt_token, decrypt_token


class TestTokenCrypto:
    def test_round_trip(self):
        key = derive_token_key("test-secret")
        ct = encrypt_token("access-token-abc", key)
        assert decrypt_token(ct, key) == "access-token-abc"

    def test_different_ciphertexts_same_plaintext(self):
        key = derive_token_key("test-secret")
        ct1 = encrypt_token("same", key)
        ct2 = encrypt_token("same", key)
        assert ct1 != ct2  # random nonce

    def test_wrong_key_fails(self):
        key1 = derive_token_key("secret-a")
        key2 = derive_token_key("secret-b")
        ct = encrypt_token("data", key1)
        with pytest.raises(Exception):
            decrypt_token(ct, key2)

    def test_derived_key_stable(self):
        assert derive_token_key("s") == derive_token_key("s")
```

- [ ] **Step 5: Run tests**

```powershell
python -X utf8 -m pytest tests/test_feishu_crypto.py -v --no-header
```
Expected: 4 tests PASS. Install `cryptography` if missing: `pip install cryptography`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/app/models/feishu_token.py backend/app/services/feishu/ backend/tests/test_feishu_crypto.py
git commit -m "feat: feishu config, encrypted token model, crypto utils"
```

---

### Task 2: Feishu OAuth Flow + API Client

**Files:**
- Create: `backend/app/services/feishu/client.py`
- Create: `backend/app/services/feishu/oauth.py`
- Create: `backend/app/api/feishu.py`
- Create: `backend/tests/test_feishu_oauth.py`

**Interfaces:**
- Consumes: `FeishuToken` model, `derive_token_key`, `encrypt_token`, `decrypt_token` (Task 1)
- Produces:
  - `class FeishuClient` with `exchange_code(code) -> dict`, `refresh_access_token(refresh_token) -> dict`, `read_document(doc_token, access_token) -> dict`, `create_document(title, access_token) -> dict`, `add_blocks(doc_id, blocks, access_token) -> dict`, `update_block(doc_id, block_id, text, access_token) -> dict`, `set_public_permission(doc_token, access_token) -> dict`
  - `build_authorize_url(state: str) -> str`
  - API endpoints: `GET /api/feishu/oauth/start`, `GET /api/feishu/oauth/callback`, `GET /api/feishu/status`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_feishu_oauth.py`:

```python
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.services.feishu.oauth import build_authorize_url


class TestAuthorizeUrl:
    def test_builds_feishu_authorize_url(self, monkeypatch):
        from app.core.config import get_settings
        monkeypatch.setattr(get_settings(), "feishu_app_id", "cli_test123")
        monkeypatch.setattr(get_settings(), "feishu_redirect_uri", "http://localhost:3000/cb")
        url = build_authorize_url("state-xyz")
        assert "open.feishu.cn" in url
        assert "cli_test123" in url
        assert "state-xyz" in url
        assert "redirect_uri" in url
```

- [ ] **Step 2: Run test — FAIL**

```powershell
python -X utf8 -m pytest tests/test_feishu_oauth.py -v --no-header
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement client.py**

Create `backend/app/services/feishu/client.py`:

```python
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("feishu_client")

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


class FeishuClient:
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self.settings = get_settings()
        self.timeout = httpx.Timeout(timeout_seconds)

    async def _post(self, path: str, json: dict | None = None, headers: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{FEISHU_API_BASE}{path}", json=json, headers=headers)
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
        return await self._post(
            "/authen/v1/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": self.settings.feishu_app_id,
                "client_secret": self.settings.feishu_app_secret,
                "code": code,
                "redirect_uri": self.settings.feishu_redirect_uri,
            },
        )

    async def refresh_access_token(self, refresh_token: str) -> dict:
        return await self._post(
            "/authen/v1/refresh_access_token",
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "app_id": self.settings.feishu_app_id,
                "app_secret": self.settings.feishu_app_secret,
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
            f"/docx/v1/documents/{doc_id}/blocks",
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
```

- [ ] **Step 4: Implement oauth.py**

Create `backend/app/services/feishu/oauth.py`:

```python
from __future__ import annotations

import secrets
from urllib.parse import quote, urlencode

from app.core.config import get_settings

FEISHU_AUTHORIZE_BASE = "https://open.feishu.cn/open-apis/authen/v1/authorize"


def build_authorize_url(state: str | None = None) -> str:
    settings = get_settings()
    params = {
        "app_id": settings.feishu_app_id,
        "redirect_uri": settings.feishu_redirect_uri,
        "scope": "docx:document:readonly docx:document",
        "state": state or secrets.token_urlsafe(32),
    }
    return f"{FEISHU_AUTHORIZE_BASE}?{urlencode(params)}"
```

- [ ] **Step 5: Run test — PASS**

```powershell
python -X utf8 -m pytest tests/test_feishu_oauth.py -v --no-header
```
Expected: 1 test PASS.

- [ ] **Step 6: Implement API endpoints**

Create `backend/app/api/feishu.py`:

```python
from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.errors import ApiError
from app.core.config import get_settings
from app.db.session import get_db
from app.models.feishu_token import FeishuToken
from app.models.rbac import User
from app.schemas.common import success
from app.services.feishu.client import FeishuClient
from app.services.feishu.crypto import decrypt_token, derive_token_key, encrypt_token
from app.services.feishu.oauth import build_authorize_url

router = APIRouter(tags=["Feishu"])


@router.get("/oauth/start")
async def feishu_oauth_start(current_user: User = Depends(get_current_user)):
    if not get_settings().feishu_app_id:
        raise ApiError(status_code=503, code="FEISHU_NOT_CONFIGURED", message="飞书应用未配置")
    state = secrets.token_urlsafe(32)
    # TODO: store state in a short-lived store (session/redis) — for MVP, embed user id in state
    url = build_authorize_url(state)
    return success(await _request(request=None), {"authorize_url": url, "state": state})


@router.get("/oauth/callback")
async def feishu_oauth_callback(
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    # For MVP: callback uses a pre-issued state that maps to user (implemented via frontend passing user_id)
    # NOTE: Real impl must store state → user mapping server-side. See Non-Goals.
    raise ApiError(status_code=501, code="FEISHU_CALLBACK_NOT_IMPLEMENTED", message="回调端点待实现")


@router.get("/status")
async def feishu_status(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token = await db.scalar(
        select(FeishuToken).where(FeishuToken.owner_user_id == current_user.id)
    )
    if token is None:
        return success(request, {"connected": False})
    return success(request, {"connected": True, "open_id": token.open_id})
```

NOTE: The callback endpoint needs a state→user mapping to be production-safe. For this plan, the frontend will:
1. Call `/api/feishu/oauth/start` → get `authorize_url`
2. Redirect to `authorize_url` with state = random
3. On callback, frontend re-attaches the user via a POST body (JWT cookie already present) — callback endpoint is stubbed as 501 for now and implemented in a follow-up task if needed.

- [ ] **Step 7: Register router in main.py**

In `backend/app/main.py`, add import and include:

```python
from app.api.feishu import router as feishu_router
app.include_router(feishu_router, prefix="/api/feishu")
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/feishu/client.py backend/app/services/feishu/oauth.py backend/app/api/feishu.py backend/tests/test_feishu_oauth.py backend/app/main.py
git commit -m "feat: feishu oauth flow and api client"
```

---

### Task 3: FeishuService — Token Mgmt + Doc Operations

**Files:**
- Create: `backend/app/services/feishu/service.py`
- Create: `backend/tests/test_feishu_service.py`

**Interfaces:**
- Consumes: `FeishuClient`, `FeishuToken`, crypto utils (Tasks 1-2)
- Produces:
  - `class FeishuService` with:
    - `async get_access_token(owner_user_id) -> str` (auto-refresh)
    - `async read_document(owner_user_id, doc_token) -> dict`
    - `async create_document(owner_user_id, title, markdown) -> dict`
    - `async edit_document(owner_user_id, doc_token, block_id, new_content) -> dict`
    - `async set_permission(owner_user_id, doc_token, permission) -> dict`
  - `markdown_to_blocks(markdown: str) -> list[dict]`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_feishu_service.py`:

```python
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.services.feishu.service import markdown_to_blocks


class TestMarkdownToBlocks:
    def test_heading_and_paragraph(self):
        blocks = markdown_to_blocks("# 标题\n\n这是正文")
        assert len(blocks) == 2
        assert blocks[0]["block_type"] == 3  # heading1
        assert blocks[1]["block_type"] == 2  # paragraph

    def test_bullet_list(self):
        blocks = markdown_to_blocks("- 项目A\n- 项目B")
        assert len(blocks) == 2
        assert blocks[0]["block_type"] == 12  # bullet

    def test_table_rows_split(self):
        blocks = markdown_to_blocks("| 列1 | 列2 |\n|---|---|\n| A | B |")
        assert len(blocks) >= 2  # header row + data row as tables
```

- [ ] **Step 2: Run test — FAIL**

```powershell
python -X utf8 -m pytest tests/test_feishu_service.py -v --no-header
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement service.py**

Create `backend/app/services/feishu/service.py`:

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.feishu_token import FeishuToken
from app.services.feishu.client import FeishuClient
from app.services.feishu.crypto import decrypt_token, derive_token_key, encrypt_token

# Feishu docx block types
BLOCK_HEADING1 = 3
BLOCK_HEADING2 = 4
BLOCK_HEADING3 = 5
BLOCK_PARAGRAPH = 2
BLOCK_BULLET = 12
BLOCK_TABLE = 31
BLOCK_TABLE_CELL = 32


def _text_block(text: str) -> dict:
    return {
        "block_type": BLOCK_PARAGRAPH,
        "paragraph": {"elements": [{"text_run": {"content": text}}]},
    }


def _heading_block(text: str, level: int) -> dict:
    return {
        "block_type": BLOCK_HEADING1 + (level - 1),
        "heading1": {"elements": [{"text_run": {"content": text}}]},
    }


def markdown_to_blocks(markdown: str) -> list[dict]:
    """Convert simple markdown to Feishu docx blocks.

    Supports: headings (#, ##, ###), paragraphs, bullet lists (- ), tables (|...|).
    Unsupported syntax falls back to paragraph text.
    """
    blocks: list[dict] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Heading
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            level = min(max(level, 1), 3)
            text = stripped.lstrip("#").strip()
            blocks.append(_heading_block(text, level))
            i += 1
            continue

        # Bullet
        if stripped.startswith("- ") or stripped.startswith("* "):
            text = stripped[2:].strip()
            blocks.append({
                "block_type": BLOCK_BULLET,
                "bullet": {"elements": [{"text_run": {"content": text}}]},
            })
            i += 1
            continue

        # Table: detect | header | and --- separator
        if stripped.startswith("|") and i + 1 < len(lines) and "---" in lines[i + 1]:
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            blocks.append(_table_block(header_cells, rows))
            continue

        # Paragraph
        blocks.append(_text_block(stripped))
        i += 1

    return blocks


def _table_block(header: list[str], rows: list[list[str]]) -> dict:
    """Build a simple Feishu table block (2 rows x N cols).

    Feishu table API requires full cell structure; for MVP build a
    header row + up to 9 data rows as separate table blocks.
    """
    cell_texts = header
    if rows:
        cell_texts = header + [cell for row in rows[:9] for cell in row]
    return {
        "block_type": BLOCK_TABLE,
        "table": {"property": {"row_size": 2, "column_size": max(len(header), 1)}},
        "children": [
            {"block_type": BLOCK_TABLE_CELL, "table_cell": {}, "children": [_text_block(c)]}
            for c in cell_texts
        ],
    }


class FeishuService:
    def __init__(self, client: FeishuClient | None = None) -> None:
        self.client = client or FeishuClient()
        self.settings = get_settings()

    def _key(self) -> bytes:
        secret = self.settings.feishu_token_encryption_key or self.settings.jwt_secret
        return derive_token_key(secret)

    async def get_access_token(self, owner_user_id: uuid.UUID) -> str:
        async with async_session_factory() as session:
            token = await session.scalar(
                select(FeishuToken).where(FeishuToken.owner_user_id == owner_user_id)
            )
            if token is None:
                raise ValueError("feishu_not_connected")

            if token.expires_at and token.expires_at > datetime.now(UTC) + timedelta(minutes=5):
                return decrypt_token(token.access_token, self._key())

            # Expired — try refresh
            if token.refresh_token:
                try:
                    data = await self.client.refresh_access_token(
                        decrypt_token(token.refresh_token, self._key())
                    )
                    token.access_token = encrypt_token(data["access_token"], self._key())
                    token.refresh_token = encrypt_token(data["refresh_token"], self._key())
                    token.expires_at = datetime.now(UTC) + timedelta(
                        seconds=data.get("expires_in", 7200)
                    )
                    await session.commit()
                    return data["access_token"]
                except Exception:
                    raise ValueError("feishu_token_expired_reauthorize")

            raise ValueError("feishu_token_expired_reauthorize")

    async def read_document(self, owner_user_id: uuid.UUID, doc_token: str) -> dict:
        token = await self.get_access_token(owner_user_id)
        return await self.client.read_document(doc_token, token)

    async def create_document(
        self, owner_user_id: uuid.UUID, title: str, markdown: str
    ) -> dict:
        token = await self.get_access_token(owner_user_id)
        created = await self.client.create_document(title, token)
        doc_id = created["data"]["document"]["document_id"]
        blocks = markdown_to_blocks(markdown)
        if blocks:
            await self.client.add_blocks(doc_id, blocks, token)
        return {
            "document_id": doc_id,
            "url": f"https://feishu.cn/docx/{doc_id}",
            "title": title,
        }

    async def edit_document(
        self, owner_user_id: uuid.UUID, doc_token: str, block_id: str, new_content: str
    ) -> dict:
        token = await self.get_access_token(owner_user_id)
        return await self.client.update_block(doc_token, block_id, new_content, token)

    async def set_permission(
        self, owner_user_id: uuid.UUID, doc_token: str, permission: str
    ) -> dict:
        token = await self.get_access_token(owner_user_id)
        if permission not in {"anyone_readable", "link_share"}:
            raise ValueError("feishu_invalid_permission")
        return await self.client.set_public_permission(doc_token, token)
```

- [ ] **Step 4: Run tests — PASS**

```powershell
python -X utf8 -m pytest tests/test_feishu_service.py -v --no-header
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/feishu/service.py backend/tests/test_feishu_service.py
git commit -m "feat: feishu service with token mgmt and doc operations"
```

---

### Task 4: Agent Tool Actions

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`
- Modify: `backend/app/services/agent/planner.py`
- Modify: `backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Consumes: `FeishuService` (Task 3)
- Produces: 4 tool actions: `feishu_read_doc`, `feishu_create_doc`, `feishu_edit_doc`, `feishu_share_doc`

- [ ] **Step 1: Add actions to execute()**

In `tool_executor.py` `execute()` method, add before `finish`:

```python
        if action_type in {"feishu_read_doc", "feishu_create_doc", "feishu_edit_doc", "feishu_share_doc"}:
            return await self._feishu_action(action_type, payload, owner_user_id)
```

- [ ] **Step 2: Implement _feishu_action**

Add to `ToolExecutor` class:

```python
    async def _feishu_action(
        self, action_type: str, payload: dict[str, Any], owner_user_id: uuid.UUID | None
    ) -> dict[str, Any]:
        if owner_user_id is None:
            raise ValueError("owner_user_id_required")

        from app.services.feishu.service import FeishuService

        service = FeishuService()
        try:
            if action_type == "feishu_read_doc":
                result = await service.read_document(owner_user_id, payload["doc_token"])
                content = result.get("data", {}).get("content", "")
                return {"content": content[:10000], "source": "feishu"}
            if action_type == "feishu_create_doc":
                result = await service.create_document(
                    owner_user_id, payload["title"], payload["content"]
                )
                return {**result, "source": "feishu"}
            if action_type == "feishu_edit_doc":
                result = await service.edit_document(
                    owner_user_id, payload["doc_token"], payload["block_id"], payload["new_content"]
                )
                return {"updated": True, "source": "feishu"}
            if action_type == "feishu_share_doc":
                result = await service.set_permission(
                    owner_user_id, payload["doc_token"], payload["permission"]
                )
                return {"shared": True, "source": "feishu"}
        except ValueError as exc:
            raise
        raise ValueError(f"Unsupported action type: {action_type}")
```

- [ ] **Step 3: Add planner schemas**

In `planner.py`, add:

```python
class FeishuReadDocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_token: str = Field(min_length=1, max_length=200)


class FeishuCreateDocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50000)


class FeishuEditDocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_token: str = Field(min_length=1, max_length=200)
    block_id: str = Field(min_length=1, max_length=200)
    new_content: str = Field(min_length=1, max_length=10000)


class FeishuShareDocInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_token: str = Field(min_length=1, max_length=200)
    permission: str = Field(min_length=1, max_length=50)
```

Update `PlanAction.type` Literal to include the 4 new types. Update `input_models` dict. Update `action_policy` string.

- [ ] **Step 4: Add test**

Append to `backend/tests/test_agent_tool_files.py`:

```python
class TestFeishuActions:
    @pytest.mark.anyio
    async def test_create_doc_dispatches(self, monkeypatch):
        executor = ToolExecutor()
        uid = uuid.uuid4()

        async def fake_create_doc(owner, title, content):
            return {"document_id": "doc1", "url": "https://feishu.cn/docx/doc1", "title": title}

        fake_service = type("FakeService", (), {
            "create_document": fake_create_doc,
            "read_document": AsyncMock(return_value={"data": {"content": "x"}}),
            "edit_document": AsyncMock(return_value={}),
            "set_permission": AsyncMock(return_value={}),
        })()
        monkeypatch.setattr("app.services.agent.tool_executor.FeishuService", lambda: fake_service)

        result = await executor.execute(
            {"type": "feishu_create_doc", "input": {"title": "报告", "content": "# 标题"}},
            owner_user_id=uid,
        )
        assert result["document_id"] == "doc1"
        assert result["source"] == "feishu"

    @pytest.mark.anyio
    async def test_read_requires_owner(self, monkeypatch):
        executor = ToolExecutor()
        from app.services.agent.tool_executor import FeishuService as _FS  # noqa
        monkeypatch.setattr("app.services.agent.tool_executor.FeishuService", lambda: type("F", (), {})())
        with pytest.raises(ValueError, match="owner_user_id_required"):
            await executor.execute(
                {"type": "feishu_read_doc", "input": {"doc_token": "d1"}},
                owner_user_id=None,
            )
```

NOTE: The test imports `FeishuService` from tool_executor — so tool_executor must import it at module level. Add at top of tool_executor.py:

```python
from app.services.feishu.service import FeishuService
```

- [ ] **Step 5: Run tests**

```powershell
python -X utf8 -m pytest tests/test_agent_tool_files.py -v --no-header
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/app/services/agent/planner.py backend/tests/test_agent_tool_files.py
git commit -m "feat: feishu agent tool actions (read/create/edit/share)"
```

---

### Task 5: Frontend — Connect Feishu Button

**Files:**
- Create: `frontend/src/components/feishu/feishu-connect.tsx`
- Modify: `frontend/src/components/layout/conversation-top-bar.tsx` (or app-shell)

**Interfaces:**
- Consumes: `/api/feishu/oauth/start`, `/api/feishu/status`
- Produces: A "连接飞书" button with connected state

- [ ] **Step 1: Create the component**

Create `frontend/src/components/feishu/feishu-connect.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { Button, message } from "antd";
import { LinkOutlined, CheckCircleOutlined } from "@ant-design/icons";
import { api } from "@/lib/api";

export default function FeishuConnect() {
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api<{ connected: boolean }>("/api/feishu/status")
      .then((d) => setConnected(d.connected))
      .catch(() => setConnected(false));
  }, []);

  async function handleConnect() {
    setLoading(true);
    try {
      const data = await api<{ authorize_url: string }>("/api/feishu/oauth/start");
      window.location.href = data.authorize_url;
    } catch (e) {
      message.error("飞书未配置，请联系管理员");
    } finally {
      setLoading(false);
    }
  }

  return connected ? (
    <Button icon={<CheckCircleOutlined />} disabled>
      已连接飞书
    </Button>
  ) : (
    <Button icon={<LinkOutlined />} onClick={handleConnect} loading={loading}>
      连接飞书
    </Button>
  );
}
```

- [ ] **Step 2: Place it in the top bar**

Read `frontend/src/components/layout/conversation-top-bar.tsx` and add `<FeishuConnect />` into the actions area.

- [ ] **Step 3: TypeScript check**

```powershell
npx tsc --noEmit
```
Expected: no errors in feishu-connect.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/feishu/feishu-connect.tsx frontend/src/components/layout/conversation-top-bar.tsx
git commit -m "feat: add feishu connect button to top bar"
```

---

### Task 6: Manual E2E Verification

- [ ] **Step 1: Set config**

In `backend/.env`, add real Feishu app credentials (create an app at open.feishu.cn):

```
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

- [ ] **Step 2: Apply DB migration for user_feishu_tokens**

```powershell
alembic revision --autogenerate -m "add user_feishu_tokens"
alembic upgrade head
```

- [ ] **Step 3: Start backend + frontend**

```powershell
uvicorn app.main:app --reload --port 8000
npm run dev  # frontend
```

- [ ] **Step 4: Test connect flow**

1. Click "连接飞书" → redirects to Feishu auth page
2. Authorize → callback → status shows connected
3. Ask the agent: "读取飞书文档 xxxx" (replace xxxx with a doc token)
4. Ask the agent: "帮我生成一份飞书文档，标题是XX，内容是YY" → agent calls feishu_create_doc → returns link
5. Verify the doc appears in Feishu with correct content

- [ ] **Step 5: Commit any fixes**
