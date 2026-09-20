# 飞书 OAuth 配置管理（超管填写 API Key） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 飞书 OAuth 的 App ID/Secret 从 .env 迁移到系统内：超管在"连接飞书"弹窗填写（企业名称+App ID+Secret，DB 加密存储，支持多份、唯一默认），员工只用默认配置登录各自飞书账号。

**Architecture:** 新表 `feishu_configs`（唯一 `is_default`）+ `FeishuConfigService`（CRUD/加密/默认管理）→ `get_feishu_credentials()`（DB 优先、.env 回退）→ `FeishuClient` 每次调用从 DB 读凭据（配置变更即时生效，无需重启）→ 超管 CRUD API（`require_super_admin` + CSRF）→ 前端连接弹窗双视图（超管：配置表单+登录；员工：仅登录）。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, AES-GCM (cryptography), React + AntD

**Spec:** `docs/superpowers/specs/2026-08-05-feishu-config-management-design.md`

## Global Constraints

- 加密：复用 `app/services/feishu/crypto.py` 的 `encrypt_token/decrypt_token/derive_token_key`，密钥 `derive_token_key(settings.jwt_secret)`——不改 crypto.py
- 唯一默认不变量：`is_default=true` 最多一行；首个创建自动默认；activate 先清后设；删除默认后按 created_at 最早的转移
- 迁移手写（禁止 autogenerate）：revision id 用 `c9d4e5f6a7b8`，down_revision = `8274d2ce84b8`（当前 head——写前用 `alembic heads` 核实）
- FeishuClient 不再读 `get_settings().feishu_app_id/feishu_app_secret`；`oauth.py build_authorize_url` 签名改为 `build_authorize_url(app_id: str, state: str | None = None)`
- 回调 URL 固定 `settings.feishu_redirect_uri`（不迁移）
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；后端测试 workdir `C:\01_agent_loop_pro\backend`；前端 `npx tsc --noEmit` + `npx vitest run src/components/feishu/`（workdir `C:\01_agent_loop_pro\frontend`）
- **git 纪律**：仓库有并行会话的未提交改动——只 `git add` 本任务列出的精确路径，禁止 `git add -A`/`git reset`/rebase；提交前 `git status --short`
- 后端测试可能被并行会话的中间态阻塞（`app/services/agent/loop.py` 等）——遇到 conftest ImportError 时用 `--confcutdir .` 或等待其提交，在报告中说明
- `feishu-connect.test.tsx` 存在（`frontend/src/components/feishu/`）——T5 必须保持其通过（超管视图变更可能需同步更新断言）

---

### Task 1: FeishuConfig 模型 + 手写迁移

**Files:**
- Create: `backend/app/models/feishu_config.py`
- Create: `backend/alembic/versions/c9d4e5f6a7b8_add_feishu_configs.py`

**Interfaces:**
- Consumes: `app/models/base.py` 的 `Base`；`alembic` 版本链
- Produces: `FeishuConfig` ORM 类（字段：`id: uuid.UUID`、`name: str`、`app_id: str`、`app_secret_encrypted: str`、`is_default: bool`、`created_at`、`updated_at`）——T2 依赖

- [ ] **Step 1: 核实 alembic 当前 head**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m alembic heads` (workdir `C:\01_agent_loop_pro\backend`)
Expected: 单行输出（如 `8274d2ce84b8 (head)`）。若 head 不是 `8274d2ce84b8`，把本任务迁移文件的 `down_revision` 改为实际 head 值并在报告注明。

- [ ] **Step 2: 写模型文件**

`backend/app/models/feishu_config.py`（仿 `feishu_token.py` 风格）：

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FeishuConfig(Base):
    __tablename__ = "feishu_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    app_id: Mapped[str] = mapped_column(String(128))
    app_secret_encrypted: Mapped[str] = mapped_column(Text)  # AES-GCM
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
```

- [ ] **Step 3: 写迁移文件**

`backend/alembic/versions/c9d4e5f6a7b8_add_feishu_configs.py`（仿 `8274d2ce84b8_add_user_web_cookies.py` 结构）：

```python
"""add feishu_configs

Revision ID: c9d4e5f6a7b8
Revises: 8274d2ce84b8
Create Date: 2026-08-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = '8274d2ce84b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('feishu_configs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('app_id', sa.String(length=128), nullable=False),
    sa.Column('app_secret_encrypted', sa.Text(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feishu_configs_is_default'), 'feishu_configs', ['is_default'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_feishu_configs_is_default'), table_name='feishu_configs')
    op.drop_table('feishu_configs')
```

- [ ] **Step 4: 应用迁移**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m alembic upgrade head` (workdir `C:\01_agent_loop_pro\backend`)
Expected: `Running upgrade ... -> c9d4e5f6a7b8` 无错误。注意：**共享开发库**（rbac）——并行会话可能正在跑迁移，若报表已存在（`relation "feishu_configs" already exists`）说明已有他人应用，改用 `alembic stamp c9d4e5f6a7b8` 并注明。

- [ ] **Step 5: 验证模型可导入**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -c "import sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); from app.models.feishu_config import FeishuConfig; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/feishu_config.py backend/alembic/versions/c9d4e5f6a7b8_add_feishu_configs.py
git commit -m "feat: add FeishuConfig model and migration"
```
Workdir `C:\01_agent_loop_pro`（先 `git status --short` 核实暂存内容仅这两文件）。

---

### Task 2: FeishuConfigService（CRUD + 加密 + 默认管理）

**Files:**
- Create: `backend/app/services/feishu/config_service.py`
- Test: `backend/tests/test_feishu_config_service.py`

**Interfaces:**
- Consumes: `FeishuConfig`（T1）、`crypto.encrypt_token/decrypt_token/derive_token_key`、`get_settings().jwt_secret`
- Produces:
  - `FeishuConfigService.get_default(db) -> FeishuConfig | None`
  - `FeishuConfigService.list_all(db) -> list[FeishuConfig]`
  - `FeishuConfigService.create(db, name, app_id, app_secret) -> FeishuConfig`（首个自动 default）
  - `FeishuConfigService.update(db, config_id, name=None, app_id=None, app_secret=None) -> FeishuConfig | None`（None=不存在）
  - `FeishuConfigService.delete(db, config_id) -> bool`（默认被删→created_at 最早者接任 default）
  - `FeishuConfigService.activate(db, config_id) -> bool`
  - `FeishuConfigService.decrypt_secret(config) -> str`（staticmethod）
- 密钥 helper（模块级，T3 复用）：`_config_key() -> bytes` = `derive_token_key(get_settings().jwt_secret)`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_feishu_config_service.py`（用真实 test_db fixture——conftest 已提供；若 test_db 需要 async 上下文见现有用法）：

```python
import uuid

import pytest

from sqlalchemy import func, select

from app.models.feishu_config import FeishuConfig
from app.services.feishu.config_service import FeishuConfigService


async def _count(db) -> int:
    return (
        await db.execute(select(func.count()).select_from(FeishuConfig))
    ).scalar_one()


class TestFeishuConfigService:
    @pytest.mark.anyio
    async def test_create_first_becomes_default(self, test_db):
        cfg = await FeishuConfigService.create(test_db, "公司A", "cli_test_a", "secret-a")
        assert cfg.is_default is True
        assert cfg.name == "公司A"
        assert await _count(test_db) == 1

    @pytest.mark.anyio
    async def test_create_second_does_not_override_default(self, test_db):
        await FeishuConfigService.create(test_db, "公司A", "cli_a", "s1")
        cfg2 = await FeishuConfigService.create(test_db, "公司B", "cli_b", "s2")
        assert cfg2.is_default is False
        default = await FeishuConfigService.get_default(test_db)
        assert default.app_id == "cli_a"

    @pytest.mark.anyio
    async def test_activate_makes_single_default(self, test_db):
        cfg1 = await FeishuConfigService.create(test_db, "公司A", "cli_a", "s1")
        cfg2 = await FeishuConfigService.create(test_db, "公司B", "cli_b", "s2")
        ok = await FeishuConfigService.activate(test_db, cfg2.id)
        assert ok is True
        defaults = [c for c in await FeishuConfigService.list_all(test_db) if c.is_default]
        assert len(defaults) == 1
        assert defaults[0].id == cfg2.id

    @pytest.mark.anyio
    async def test_delete_default_transfers_to_next(self, test_db):
        cfg1 = await FeishuConfigService.create(test_db, "公司A", "cli_a", "s1")
        cfg2 = await FeishuConfigService.create(test_db, "公司B", "cli_b", "s2")
        await FeishuConfigService.activate(test_db, cfg2.id)
        await FeishuConfigService.delete(test_db, cfg2.id)
        default = await FeishuConfigService.get_default(test_db)
        assert default is not None and default.id == cfg1.id

    @pytest.mark.anyio
    async def test_secret_roundtrip(self, test_db):
        cfg = await FeishuConfigService.create(test_db, "公司A", "cli_a", "super-secret-42")
        assert FeishuConfigService.decrypt_secret(cfg) == "super-secret-42"

    @pytest.mark.anyio
    async def test_update_partial(self, test_db):
        cfg = await FeishuConfigService.create(test_db, "公司A", "cli_a", "s1")
        updated = await FeishuConfigService.update(test_db, cfg.id, name="公司A改")
        assert updated.name == "公司A改"
        assert updated.app_id == "cli_a"
```

（`test_db` fixture 返回 AsyncSession——conftest 中 `test_db(test_engine)` 已建表并 yield session；测试内 `create` 用 flush 不 commit，`get_default`/`list_all` 同 session 可见，无需 commit。若 conftest 的 `test_db` 是其他形态（如每测试回滚），按既有 `test_feishu_service.py` 用法保持一致。）

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_feishu_config_service.py -v --no-header`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.services.feishu.config_service'`）

- [ ] **Step 3: 实现 config_service.py**

`backend/app/services/feishu/config_service.py`：

```python
from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.feishu_config import FeishuConfig
from app.services.feishu.crypto import decrypt_token, derive_token_key, encrypt_token


def _config_key() -> bytes:
    return derive_token_key(get_settings().jwt_secret)


class FeishuConfigService:
    @staticmethod
    def decrypt_secret(config: FeishuConfig) -> str:
        return decrypt_token(config.app_secret_encrypted, _config_key())

    @staticmethod
    async def get_default(db: AsyncSession) -> FeishuConfig | None:
        stmt = (
            select(FeishuConfig)
            .where(FeishuConfig.is_default.is_(True))
            .order_by(FeishuConfig.created_at)
        )
        config = await db.scalar(stmt)
        if config is not None:
            return config
        return await db.scalar(
            select(FeishuConfig).order_by(FeishuConfig.created_at).limit(1)
        )

    @staticmethod
    async def list_all(db: AsyncSession) -> list[FeishuConfig]:
        result = await db.execute(
            select(FeishuConfig).order_by(FeishuConfig.created_at)
        )
        return list(result.scalars().all())

    @staticmethod
    async def create(
        db: AsyncSession, name: str, app_id: str, app_secret: str
    ) -> FeishuConfig:
        existing = await db.scalar(select(FeishuConfig).limit(1))
        config = FeishuConfig(
            name=name,
            app_id=app_id,
            app_secret_encrypted=encrypt_token(app_secret, _config_key()),
            is_default=existing is None,
        )
        db.add(config)
        await db.flush()
        return config

    @staticmethod
    async def update(
        db: AsyncSession,
        config_id: uuid.UUID,
        name: str | None = None,
        app_id: str | None = None,
        app_secret: str | None = None,
    ) -> FeishuConfig | None:
        config = await db.get(FeishuConfig, config_id)
        if config is None:
            return None
        if name is not None:
            config.name = name
        if app_id is not None:
            config.app_id = app_id
        if app_secret is not None:
            config.app_secret_encrypted = encrypt_token(app_secret, _config_key())
        await db.flush()
        return config

    @staticmethod
    async def delete(db: AsyncSession, config_id: uuid.UUID) -> bool:
        config = await db.get(FeishuConfig, config_id)
        if config is None:
            return False
        was_default = config.is_default
        await db.delete(config)
        await db.flush()
        if was_default:
            next_config = await db.scalar(
                select(FeishuConfig).order_by(FeishuConfig.created_at).limit(1)
            )
            if next_config is not None:
                next_config.is_default = True
                await db.flush()
        return True

    @staticmethod
    async def activate(db: AsyncSession, config_id: uuid.UUID) -> bool:
        config = await db.get(FeishuConfig, config_id)
        if config is None:
            return False
        await db.execute(
            update(FeishuConfig).values(is_default=False)
        )
        config.is_default = True
        await db.flush()
        return True
```

（`create`/`update`/`delete`/`activate` 用 `flush` 不 commit——由 API 层统一 commit，与项目现有 repo 模式一致。）

- [ ] **Step 4: 运行确认通过**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_feishu_config_service.py -q --no-header`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/feishu/config_service.py backend/tests/test_feishu_config_service.py
git commit -m "feat: FeishuConfigService with encrypted secrets and default management"
```

---

### Task 3: credentials 加载 + FeishuClient/oauth 参数化

**Files:**
- Create: `backend/app/services/feishu/credentials.py`
- Modify: `backend/app/services/feishu/client.py`
- Modify: `backend/app/services/feishu/oauth.py`
- Test: `backend/tests/test_feishu_credentials.py`
- Modify: `backend/tests/test_feishu_oauth.py`

**Interfaces:**
- Consumes: `FeishuConfigService.get_default`（T2）、`async_session_factory`（`app.db.session`）、`get_settings()`
- Produces:
  - `async get_feishu_credentials() -> tuple[str, str]`（(app_id, app_secret)；DB 默认配置优先，.env 回退）
  - `FeishuClient` 无参构造不再读 settings 凭据；内部 `async _creds() -> tuple[str, str]`；`exchange_code`/`refresh_access_token`/`revoke_token` 开头加载凭据
  - `build_authorize_url(app_id: str, state: str | None = None) -> str`（T4 依赖）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_feishu_credentials.py`：

```python
import pytest

from app.services.feishu.credentials import get_feishu_credentials
from app.services.feishu.config_service import FeishuConfigService


class TestGetFeishuCredentials:
    @pytest.mark.anyio
    async def test_returns_db_default_when_configured(self, test_db):
        from app.db.session import async_session_factory

        async with async_session_factory() as db:
            await FeishuConfigService.create(db, "公司A", "cli_db", "secret-db")
            await db.commit()

        app_id, secret = await get_feishu_credentials()
        assert app_id == "cli_db"
        assert secret == "secret-db"

    @pytest.mark.anyio
    async def test_falls_back_to_env_when_no_db_config(self, test_db, monkeypatch):
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "feishu_app_id", "cli_env")
        monkeypatch.setattr(get_settings(), "feishu_app_secret", "secret-env")
        app_id, secret = await get_feishu_credentials()
        assert app_id == "cli_env"
        assert secret == "secret-env"
```

（`get_feishu_credentials` 内部用 `async_session_factory()` 独立会话——测试不传 db；先跑确认失败：`ModuleNotFoundError`。）

- [ ] **Step 2: 更新 test_feishu_oauth.py（TDD：先改测试）**

`backend/tests/test_feishu_oauth.py` 的 `TestAuthorizeUrl.test_builds_feishu_authorize_url` 改为：

```python
    def test_builds_feishu_authorize_url(self, monkeypatch):
        from app.core.config import get_settings
        monkeypatch.setattr(get_settings(), "feishu_redirect_uri", "http://localhost:3000/cb")
        url = build_authorize_url("cli_test123", "state-xyz")
        assert "open.feishu.cn" in url
        assert "cli_test123" in url
        assert "state-xyz" in url
        assert "redirect_uri" in url
```

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_feishu_oauth.py -q --no-header`
Expected: FAIL（`build_authorize_url() missing 1 required positional argument`）

- [ ] **Step 3: 实现 credentials.py**

`backend/app/services/feishu/credentials.py`：

```python
from __future__ import annotations

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.services.feishu.config_service import FeishuConfigService


async def get_feishu_credentials() -> tuple[str, str]:
    """Return (app_id, app_secret). DB default config wins; .env falls back."""
    try:
        async with async_session_factory() as db:
            config = await FeishuConfigService.get_default(db)
            if config is not None:
                return config.app_id, FeishuConfigService.decrypt_secret(config)
    except Exception:
        pass
    settings = get_settings()
    return settings.feishu_app_id, settings.feishu_app_secret
```

（`except Exception: pass` 兜底：DB 不可用时降级 .env，不阻断登录流程。）

- [ ] **Step 4: 改造 FeishuClient**

`backend/app/services/feishu/client.py`：
- `__init__` 改为：

```python
    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self.timeout = httpx.Timeout(timeout_seconds)
```

（删除 `self.settings = get_settings()`；文件头部 `from app.core.config import get_settings` 改为 `from app.services.feishu.credentials import get_feishu_credentials`）

- 加私有方法（放在 `__init__` 后）：

```python
    async def _creds(self) -> tuple[str, str]:
        return await get_feishu_credentials()
```

- `exchange_code` 开头加 `app_id, app_secret = await self._creds()`，body 改为 `"client_id": app_id, "client_secret": app_secret`
- `refresh_access_token` 开头加 `app_id, app_secret = await self._creds()`，body 的 `"app_id": app_id, "app_secret": app_secret`
- `revoke_token` 开头加 `app_id, app_secret = await self._creds()`，body 的 `"app_id": app_id, "app_secret": app_secret`
- `redirect_uri` 仍从 `get_settings().feishu_redirect_uri` 取（`exchange_code` 内 `from app.core.config import get_settings` 局部 import 或方法内读取）：

```python
    async def exchange_code(self, code: str) -> dict:
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
```

（`from app.core.config import get_settings` 保留为局部 import。）

- [ ] **Step 5: 改造 oauth.py**

`backend/app/services/feishu/oauth.py` **整体替换为**：

```python
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
```

（`state` 缺省时自动生成与现行为一致；`app_id` 由调用方传入——不再读 settings 凭据。）

- [ ] **Step 6: 运行确认通过**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_feishu_credentials.py tests/test_feishu_oauth.py tests/test_feishu_service.py -q --no-header`
Expected: 全部通过（test_feishu_service 使用 FeishuService/FeishuClient——确认其测试不依赖 client 的 settings 快照；若 test_feishu_service 通过注入 mock client 则不受影响）

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/feishu/credentials.py backend/app/services/feishu/client.py backend/app/services/feishu/oauth.py backend/tests/test_feishu_credentials.py backend/tests/test_feishu_oauth.py
git commit -m "feat: load feishu credentials from DB config with env fallback"
```

---

### Task 4: 超管配置 CRUD API + oauth/start 改造

**Files:**
- Modify: `backend/app/api/feishu.py`
- Test: `backend/tests/test_feishu_config_api.py`

**Interfaces:**
- Consumes: `FeishuConfigService`（T2）、`get_feishu_credentials` + `build_authorize_url(app_id, state)`（T3）、`require_super_admin`（`app.core.dependencies`）、`require_csrf`（`app.core.csrf`）
- Produces: 端点（前端 T5 依赖）：
  - `GET /api/feishu/configs`（超管）→ `{configs: [{id, name, app_id_mask, is_default}]}`
  - `POST /api/feishu/configs`（超管+CSRF，body `{name, app_id, app_secret}`）→ `{id, name, app_id_mask, is_default}`
  - `PUT /api/feishu/configs/{config_id}`（超管+CSRF，body 可选字段）→ 同上
  - `DELETE /api/feishu/configs/{config_id}`（超管+CSRF）→ `{deleted: true}`
  - `POST /api/feishu/configs/{config_id}/activate`（超管+CSRF）→ `{activated: true}`
  - `GET /api/feishu/configs/status`（登录用户）→ `{configured: bool, app_id: str | None}`
  - `/api/feishu/oauth/start` 改用 `get_feishu_credentials()` + `build_authorize_url(app_id, state)`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_feishu_config_api.py`（用 conftest 的 `test_db`/`admin_client` fixtures——先读 conftest 与现有 API 测试（如 test_feishu_oauth.py 的 client 用法）确认客户端调用方式；`admin_client` 是超管鉴权客户端，`client`/`auth_client` 是普通用户）：

```python
import uuid

import pytest


class TestFeishuConfigApi:
    @pytest.mark.anyio
    async def test_non_admin_forbidden(self, client, admin_client):
        # 用普通用户客户端访问 /api/feishu/configs 应 403
        resp = await client.get("/api/feishu/configs")
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_admin_create_and_list(self, admin_client):
        resp = await admin_client.post(
            "/api/feishu/configs",
            json={"name": "公司A", "app_id": "cli_api_a", "app_secret": "secret-api"},
        )
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["name"] == "公司A"
        assert body["is_default"] is True

        lst = await admin_client.get("/api/feishu/configs")
        assert lst.status_code == 200
        items = lst.json()["data"]["configs"]
        assert len(items) == 1
        assert items[0]["app_id_mask"] == "cli_api"  # 前 6 位

    @pytest.mark.anyio
    async def test_admin_activate_and_delete(self, admin_client):
        r1 = await admin_client.post(
            "/api/feishu/configs", json={"name": "公司A", "app_id": "cli_a", "app_secret": "s1"}
        )
        r2 = await admin_client.post(
            "/api/feishu/configs", json={"name": "公司B", "app_id": "cli_b", "app_secret": "s2"}
        )
        id2 = r2.json()["data"]["id"]
        act = await admin_client.post(f"/api/feishu/configs/{id2}/activate")
        assert act.status_code == 200
        status = await admin_client.get("/api/feishu/configs/status")
        assert status.json()["data"]["app_id"] == "cli_b"

        d = await admin_client.delete(f"/api/feishu/configs/{id2}")
        assert d.status_code == 200
        status2 = await admin_client.get("/api/feishu/configs/status")
        assert status2.json()["data"]["app_id"] == "cli_a"

    @pytest.mark.anyio
    async def test_oauth_start_uses_db_config(self, admin_client, monkeypatch):
        from app.core.config import get_settings
        monkeypatch.setattr(get_settings(), "feishu_app_id", "")
        resp = await admin_client.post(
            "/api/feishu/configs", json={"name": "公司A", "app_id": "cli_oauth", "app_secret": "s1"}
        )
        assert resp.status_code == 200
        start = await admin_client.get("/api/feishu/oauth/start")
        assert start.status_code == 200
        url = start.json()["data"]["authorize_url"]
        assert "cli_oauth" in url
```

（CSRF：admin_client 是否自动带 CSRF header——读 conftest admin_client 实现，POST 若被 403 CSRF 拦截需在测试里加 `headers={"X-CSRF-Token": ...}` 或 client 已内置——确认现有 POST 测试（如 role 管理）怎么做的，保持一致。）

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_feishu_config_api.py -q --no-header`
Expected: FAIL（404 路由不存在）

- [ ] **Step 3: 实现 API**

`backend/app/api/feishu.py` 新增：

```python
from pydantic import BaseModel, Field

class FeishuConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    app_id: str = Field(min_length=1, max_length=128)
    app_secret: str = Field(min_length=1, max_length=256)


class FeishuConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    app_id: str | None = Field(default=None, min_length=1, max_length=128)
    app_secret: str | None = Field(default=None, min_length=1, max_length=256)
```

路由（放在现有 `/oauth/start` 之前，避免路径冲突）：

```python
def _config_view(config) -> dict:
    return {
        "id": str(config.id),
        "name": config.name,
        "app_id_mask": config.app_id[:6],
        "is_default": config.is_default,
    }


@router.get("/configs/status")
async def feishu_config_status(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    config = await FeishuConfigService.get_default(db)
    if config is None:
        return success(request, {"configured": False, "app_id": None})
    return success(request, {"configured": True, "app_id": config.app_id})


@router.get("/configs")
async def feishu_config_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
):
    configs = await FeishuConfigService.list_all(db)
    return success(request, {"configs": [_config_view(c) for c in configs]})


@router.post("/configs")
async def feishu_config_create(
    request: Request,
    data: FeishuConfigCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
):
    config = await FeishuConfigService.create(db, data.name, data.app_id, data.app_secret)
    await db.commit()
    return success(request, _config_view(config))


@router.put("/configs/{config_id}")
async def feishu_config_update(
    request: Request,
    config_id: uuid.UUID,
    data: FeishuConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
):
    config = await FeishuConfigService.update(
        db, config_id, data.name, data.app_id, data.app_secret
    )
    if config is None:
        raise ApiError(status_code=404, code="CONFIG_NOT_FOUND", message="飞书配置不存在")
    await db.commit()
    return success(request, _config_view(config))


@router.delete("/configs/{config_id}")
async def feishu_config_delete(
    request: Request,
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
):
    ok = await FeishuConfigService.delete(db, config_id)
    if not ok:
        raise ApiError(status_code=404, code="CONFIG_NOT_FOUND", message="飞书配置不存在")
    await db.commit()
    return success(request, {"deleted": True})


@router.post("/configs/{config_id}/activate")
async def feishu_config_activate(
    request: Request,
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
):
    ok = await FeishuConfigService.activate(db, config_id)
    if not ok:
        raise ApiError(status_code=404, code="CONFIG_NOT_FOUND", message="飞书配置不存在")
    await db.commit()
    return success(request, {"activated": True})
```

import 补充：`import uuid`、`from pydantic import BaseModel, Field`、`from app.core.dependencies import require_super_admin`、`from app.core.csrf import require_csrf`、`from app.services.feishu.config_service import FeishuConfigService`、`from app.services.feishu.credentials import get_feishu_credentials`。

`/oauth/start` 改为：

```python
@router.get("/oauth/start")
async def feishu_oauth_start(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    app_id, _ = await get_feishu_credentials()
    if not app_id:
        raise ApiError(status_code=503, code="FEISHU_NOT_CONFIGURED", message="飞书应用未配置")
    state = secrets.token_urlsafe(32)
    url = build_authorize_url(app_id, state)
    return success(request, {"authorize_url": url, "state": state})
```

（删除 `get_settings().feishu_app_id` 检查——改为 credentials。）

- [ ] **Step 4: 运行确认通过**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_feishu_config_api.py tests/test_feishu_oauth.py tests/test_feishu_disconnect.py -q --no-header`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/feishu.py backend/tests/test_feishu_config_api.py
git commit -m "feat: super admin feishu config CRUD API and DB-backed oauth start"
```

---

### Task 5: 前端连接飞书双视图

**Files:**
- Modify: `frontend/src/components/feishu/feishu-connect.tsx`
- Modify: `frontend/src/components/feishu/feishu-connect.test.tsx`（现有测试同步）
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: 后端端点（T4）契约：`GET /api/feishu/configs`、`POST /api/feishu/configs`、`PUT/DELETE /api/feishu/configs/{id}`、`POST /api/feishu/configs/{id}/activate`、`GET /api/feishu/configs/status`；`/api/auth/me`（roles 判断超管）；`frontend/src/lib/roles.ts` 的 `isSuperAdmin(user)`
- Produces: 无（最终交付）

- [ ] **Step 1: 读现状**

读 `frontend/src/components/feishu/feishu-connect.tsx` 与 `frontend/src/components/feishu/feishu-connect.test.tsx`、`frontend/src/lib/roles.ts`、`frontend/src/lib/api.ts` 的 `api()` 签名（`api<T>(path, opts)`）。确认组件结构（状态检查/连接/断开的现有渲染）。

- [ ] **Step 2: api.ts 加配置函数**

`frontend/src/lib/api.ts` 追加（跟随现有 `api()` 模式）：

```ts
export interface FeishuConfigItem {
  id: string;
  name: string;
  app_id_mask: string;
  is_default: boolean;
}

export async function listFeishuConfigs() {
  return api<{ configs: FeishuConfigItem[] }>("/api/feishu/configs");
}

export async function createFeishuConfig(data: { name: string; app_id: string; app_secret: string }) {
  return api<FeishuConfigItem>("/api/feishu/configs", {
    method: "POST",
    body: JSON.stringify(data),
    csrf: true,
  });
}

export async function updateFeishuConfig(
  id: string,
  data: { name?: string; app_id?: string; app_secret?: string },
) {
  return api<FeishuConfigItem>(`/api/feishu/configs/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
    csrf: true,
  });
}

export async function deleteFeishuConfig(id: string) {
  return api<{ deleted: boolean }>(`/api/feishu/configs/${id}`, {
    method: "DELETE",
    csrf: true,
  });
}

export async function activateFeishuConfig(id: string) {
  return api<{ activated: boolean }>(`/api/feishu/configs/${id}/activate`, {
    method: "POST",
    csrf: true,
  });
}

export async function getFeishuConfigStatus() {
  return api<{ configured: boolean; app_id: string | null }>("/api/feishu/configs/status");
}
```

- [ ] **Step 3: feishu-connect.tsx 双视图**

读现有组件后重构：组件内部加载 `/api/auth/me`（用 `frontend/src/lib/auth.ts` 的 `fetchCurrentUser` 或现有状态管理——读文件确认；`isSuperAdmin(user)` 判断超管）。

超管视图新增（放在现有连接区上方）：

```tsx
const [showConfigForm, setShowConfigForm] = useState(false);
const [configs, setConfigs] = useState<FeishuConfigItem[]>([]);
const [cfgName, setCfgName] = useState("");
const [cfgAppId, setCfgAppId] = useState("");
const [cfgSecret, setCfgSecret] = useState("");
const [cfgBusy, setCfgBusy] = useState(false);
const [cfgError, setCfgError] = useState("");
```

加载：`useEffect` 中（组件挂载且超管）`listFeishuConfigs().then((d) => setConfigs(d.configs)).catch(() => {})`。

渲染（超管时，登录区上方）：

```tsx
{isAdmin && (
  <div style={{ marginBottom: 16, border: "1px solid #f0f0f0", borderRadius: 8, padding: 12 }}>
    <div style={{ fontWeight: 600, marginBottom: 8 }}>填写 API Key（企业飞书应用配置）</div>
    {!showConfigForm ? (
      <Button size="small" onClick={() => setShowConfigForm(true)}>添加配置</Button>
    ) : (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Input placeholder="企业名称" value={cfgName} onChange={(e) => setCfgName(e.target.value)} />
        <Input placeholder="App ID" value={cfgAppId} onChange={(e) => setCfgAppId(e.target.value)} />
        <Input.Password placeholder="App Secret" value={cfgSecret} onChange={(e) => setCfgSecret(e.target.value)} />
        {cfgError && <div style={{ color: "#cf1322", fontSize: 12 }}>{cfgError}</div>}
        <div style={{ display: "flex", gap: 8 }}>
          <Button type="primary" size="small" loading={cfgBusy}
            onClick={async () => {
              if (!cfgName.trim() || !cfgAppId.trim() || !cfgSecret.trim()) {
                setCfgError("请填写完整"); return;
              }
              setCfgBusy(true); setCfgError("");
              try {
                await createFeishuConfig({ name: cfgName.trim(), app_id: cfgAppId.trim(), app_secret: cfgSecret.trim() });
                setCfgName(""); setCfgAppId(""); setCfgSecret(""); setShowConfigForm(false);
                const d = await listFeishuConfigs();
                setConfigs(d.configs);
              } catch { setCfgError("保存失败，请重试"); }
              setCfgBusy(false);
            }}>保存</Button>
          <Button size="small" onClick={() => { setShowConfigForm(false); setCfgError(""); }}>取消</Button>
        </div>
      </div>
    )}
    {configs.length > 0 && (
      <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
        {configs.map((c) => (
          <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            <span>{c.name}（{c.app_id_mask}…）</span>
            {c.is_default && <Tag color="green">默认</Tag>}
            <Button size="small" disabled={c.is_default}
              onClick={async () => { await activateFeishuConfig(c.id); const d = await listFeishuConfigs(); setConfigs(d.configs); }}>
              设为默认
            </Button>
            <Button size="small" danger
              onClick={async () => { await deleteFeishuConfig(c.id); const d = await listFeishuConfigs(); setConfigs(d.configs); }}>
              删除
            </Button>
          </div>
        ))}
      </div>
    )}
  </div>
)}
```

员工（非超管）且 `!configured` 时显示提示：`企业尚未配置飞书，请联系管理员`（`configured` 来自现有 status 检查——读现有组件如何取 `connected`，一并扩展）。

保持现有连接/断开流程不变；超管判断用 `isSuperAdmin(user)`（`frontend/src/lib/roles.ts`——确认其导出名与签名）。

- [ ] **Step 4: 前端验证**

Run: `npx tsc --noEmit`（workdir `C:\01_agent_loop_pro\frontend`）——本文件零新增错误（仓库有并行会话的 pre-existing 错误，只保证本文件不出现）
Run: `npx vitest run src/components/feishu/feishu-connect.test.tsx`——现有测试通过（若超管视图变更破坏断言（如新增按钮导致 findByText 冲突），同步更新断言并在报告说明）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feishu/feishu-connect.tsx frontend/src/components/feishu/feishu-connect.test.tsx frontend/src/lib/api.ts
git commit -m "feat: feishu config management UI in connect modal (admin only)"
```

---

### Task 6: E2E 验证与收尾

- [ ] **Step 1: 应用迁移 + 重启 API**

```powershell
& "X:\python\anaconda\envs\01-rbac\python.exe" -m alembic upgrade head   # workdir C:\01_agent_loop_pro\backend
```
API（uvicorn 8000）带 `--reload` 应已自动加载；若未运行 `--reload`，重启 uvicorn（`uvicorn app.main:app --reload`）。用 `GET http://127.0.0.1:8000/docs` 确认存活。

- [ ] **Step 2: 后端全量回归（隔离 DB）**

```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_feishucfg"
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header
```
Expected: 全部通过或仅已知失败（pypdf 缺失 4 个）；并行会话中间态导致的 conftest ImportError 时等待其提交后重跑。

- [ ] **Step 3: 用户实测**

1. 超管登录 → 打开"连接飞书"→ 应看到"填写 API Key"区 + "登录飞书账号"按钮
2. 填企业名称 + App ID + App Secret → 保存 → 列表出现该配置且标记"默认"
3. 点"登录飞书账号" → 跳飞书授权 → 授权成功 → 状态"已连接"
4. 普通员工登录 → 打开"连接飞书"→ **无**配置区，只有登录按钮 → 点登录 → 飞书授权 → 连接成功
5. 超管添加第二份配置 → 列表两条 → "设为默认"切换 → 员工登录仍可用默认配置
6. Agent 测飞书工具：让 agent 读/建飞书文档 → 成功

- [ ] **Step 4: 提交校准修复（如有）**

```bash
git add <精确路径>
git commit -m "fix: feishu config E2E calibration"
```
（仅当有修复；无则跳过。）
