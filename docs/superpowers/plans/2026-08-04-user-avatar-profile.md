# 用户头像与个人资料页实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户可设置自己的头像并维护个人资料（姓名/邮箱/手机号/密码），管理员可代改头像，导航与用户列表展示真实头像。

**Architecture:** 头像独立存储于 `backend/var/avatars/<user_id>.<ext>`（魔术字节嗅探校验，≤2MB，白名单 png/jpg/jpeg/gif/webp），`User.avatar_path` 存相对路径；上传/清除走 API（本人 `/me` + 管理员 `user:update`），读取走鉴权端点 `GET /api/avatars/{user_id}`；新增 `PUT /api/users/me/profile` 与 `POST /api/users/me/password`；所有用户响应经 `_user_to_response` 与 `/api/auth/me` 统一补 `avatar_url`。前端新增 `/settings/profile` 资料页（头像+基本信息+改密码），导航头像与用户管理表格/抽屉展示真实头像。

**Tech Stack:** FastAPI + SQLAlchemy async + alembic；Next.js 16 + React 19 + AntD 6 + vitest；pytest

## Global Constraints

- 后端 Python 环境：conda 环境 `01-rbac`（X:\python\anaconda\envs\01-rbac\python.exe），不要用全局 Python
- 每个 pytest 任务前必须设置独立测试库环境变量（各任务指定），否则与其他会话并发测试互相破坏
- git 纪律：提交前 `git status --short` 核对暂存区只含本任务列出的文件；`git add <精确路径>`，**绝对禁止 `git add -A`**（工作区有并发进程的 var 存储文件与 .cortexkit/ 等）
- alembic head 可能被并发进程推进：生成迁移模板后检查 `down_revision` 是否为生成时刻的实际 head（`alembic heads` 确认），不是则停下报告
- 头像白名单 mime 及扩展名映射：`image/png → .png`、`image/jpeg → .jpg`、`image/gif → .gif`、`image/webp → .webp`
- 头像大小上限 2MB；魔术字节嗅探读前 4096 字节，命中才接受
- `avatar_path` 只存 `<user_id><ext>` 形式，读取时 `Path.resolve()` 校验前缀在 `var/avatars/` 根内
- 错误码与消息走 `ApiError(status_code, code, message)` + `app.core.messages` 既有模式，中文消息
- 前端测试约束（重要）：本仓库 jsdom 的 `getComputedStyle` 单次调用可达 1000ms（AntD cssinjs 巨型样式表），对完整页面（含 antd 表格行按钮的大 DOM）执行 byRole 查询会 7-10s 超时。**新测试禁止对完整页面做 byRole/getAllByRole 查询**；用 `document.querySelectorAll("button")` + `textContent` 匹配，或 `within()` 小容器（如对话框 footer）内查询
- 前端 `CurrentUser` / `UserListItem` 新字段 `avatar_url` 声明为**可选**（`avatar_url?: string | null`），避免海量 mock 修改
- 新密码校验复用 `validate_password`（≥8 位、含字母和数字），旧密码错误 → `401 INVALID_PASSWORD`

---

### Task 1: User.avatar_path 模型字段 + alembic 迁移

**Files:**
- Modify: `backend/app/models/rbac.py`（User 类，is_builtin 字段后）
- Create: `backend/alembic/versions/<rev>_add_users_avatar_path.py`
- Test: `backend/tests/test_seed.py`

**Interfaces:**
- Consumes: 无
- Produces: `User.avatar_path: str | None`（Task 2 依赖）

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_seed.py` 末尾）

```python
def test_user_model_has_avatar_path_column() -> None:
    assert "avatar_path" in User.__table__.columns
```

文件头已导入 `from app.models.rbac import User`（若没有则补）。

- [ ] **Step 2: 跑测试确认失败**

Run（工作目录 `backend`，先设测试库环境变量）:
```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_t1"; python -X utf8 -m pytest tests/test_seed.py::test_user_model_has_avatar_path_column -q
```
Expected: FAIL（列不存在）

- [ ] **Step 3: 模型加字段**（`backend/app/models/rbac.py` User 类，`is_builtin` 行之后）

```python
    avatar_path: Mapped[str | None] = mapped_column(String(512))
```

- [ ] **Step 4: 迁移**（工作目录 `backend`）

```
alembic revision -m "add users avatar_path"
```
检查生成的 `down_revision` 是否等于 `alembic heads` 的当前 head（写文件时可能已被并发进程推进，以实际为准；多 head 则停下报告 BLOCKED）。在生成的迁移文件中写入：

```python
"""add users avatar_path

Revision ID: <保留生成值>
Revises: <保留生成值>
Create Date: <保留生成值>
"""
from alembic import op
import sqlalchemy as sa

revision = "<保留生成值>"
down_revision = "<保留生成值>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_path", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_path")
```

- [ ] **Step 5: 应用迁移到开发库并验证**

```
alembic upgrade head
```
Expected: 成功升级（当前 head 变成新迁移）

- [ ] **Step 6: 跑测试确认通过**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_t1"; python -X utf8 -m pytest tests/test_seed.py -q
```
Expected: 全部 PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/models/rbac.py backend/alembic/versions/<rev>_add_users_avatar_path.py backend/tests/test_seed.py
git commit -m "feat: add users.avatar_path column"
```

---

### Task 2: 头像服务层与 API（上传/清除/读取）

**Files:**
- Create: `backend/app/services/avatar_service.py`
- Create: `backend/app/api/avatars.py`
- Modify: `backend/app/main.py`（注册 router）
- Test: `backend/tests/test_avatars_api.py`

**Interfaces:**
- Consumes: `User.avatar_path`（Task 1）
- Produces: `avatar_service.avatar_url_for(user) -> str | None`、`avatar_service.upload_avatar(db, user, file) -> dict`、`avatar_service.clear_avatar(db, user) -> dict`、`avatar_service.read_avatar(user) -> tuple[bytes, str] | None`（Task 4 依赖 `avatar_url_for`）

- [ ] **Step 1: 写失败测试**（创建 `backend/tests/test_avatars_api.py`）

```python
import io

import pytest

from app.core.security import hash_password


def _png_bytes() -> bytes:
    # 最小合法 PNG（1x1 像素）
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049"
        "454e44ae426082"
    )


async def _make_user(session, username: str) -> object:
    from app.models.rbac import User

    user = User(
        username=username,
        display_name=username,
        password_hash=hash_password("Password123"),
        status="active",
    )
    session.add(user)
    await session.flush()
    return user


async def test_upload_own_avatar_success(admin_client, session) -> None:
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["avatar_url"] is not None
    assert body["avatar_url"].startswith("/api/avatars/")


async def test_upload_rejects_non_image(admin_client) -> None:
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.txt", io.BytesIO(b"hello world"), "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "AVATAR_INVALID_TYPE"


async def test_upload_rejects_spoofed_content_type(admin_client) -> None:
    # Content-Type 声明 png 但内容是文本
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(b"not an image"), "image/png")},
    )
    assert resp.status_code == 400


async def test_upload_rejects_oversize(admin_client) -> None:
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024)), "image/png")},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "AVATAR_TOO_LARGE"


async def test_upload_requires_auth(client) -> None:
    resp = await client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 401


async def test_clear_own_avatar(admin_client) -> None:
    resp = await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 200
    resp = await admin_client.delete("/api/avatars/me")
    assert resp.status_code == 200
    assert resp.json()["data"]["avatar_url"] is None


async def test_get_avatar_returns_image(admin_client, session) -> None:
    from sqlalchemy import select
    from app.models.rbac import User

    await admin_client.post(
        "/api/avatars/me",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    admin = await session.scalar(select(User).where(User.username == "admin"))
    resp = await admin_client.get(f"/api/avatars/{admin.id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")
    assert resp.content.startswith(b"\x89PNG")


async def test_get_avatar_without_avatar_404(admin_client, session) -> None:
    from sqlalchemy import select
    from app.models.rbac import User

    admin = await session.scalar(select(User).where(User.username == "admin"))
    resp = await admin_client.get(f"/api/avatars/{admin.id}")
    assert resp.status_code == 404


async def test_admin_can_set_avatar_for_other_user(admin_client, session) -> None:
    target = await _make_user(session, "avatar_target")
    resp = await admin_client.post(
        f"/api/avatars/{target.id}",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 200, resp.text


async def test_normal_user_cannot_set_avatar_for_other(admin_client, session, client) -> None:
    target = await _make_user(session, "avatar_target2")
    resp = await client.post(
        f"/api/avatars/{target.id}",
        files={"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 403
```

注意：`client` / `admin_client` / `session` fixture 已由 `backend/tests/conftest.py` 提供（`client` 是未登录客户端、`admin_client` 是登录 admin 的客户端、`session` 是测试库 AsyncSession）。若 conftest 里 admin 用户名不是 `"admin"`，以实际为准调整两个读取测试的查询。

- [ ] **Step 2: 跑测试确认失败**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_t2"; python -X utf8 -m pytest tests/test_avatars_api.py -q
```
Expected: 大量 FAIL（模块不存在/路由 404）

- [ ] **Step 3: 实现服务层**（创建 `backend/app/services/avatar_service.py`）

```python
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models.rbac import User

_AVATAR_ROOT = Path("./var/avatars")
_AVATAR_MAX_BYTES = 2 * 1024 * 1024
_AVATAR_HEADER_SIZE = 4096

_AVATAR_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _detect_image_mime(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"GIF8"):
        return "image/gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _ext_to_mime(ext: str) -> str | None:
    for mime, e in _AVATAR_MIME_EXT.items():
        if e == ext:
            return mime
    return None


def _safe_absolute(path: Path) -> Path:
    root = _AVATAR_ROOT.resolve()
    resolved = path.resolve()
    if not str(resolved).startswith(str(root)):
        raise ApiError(500, "AVATAR_PATH_INVALID", "头像路径非法")
    return resolved


def avatar_url_for(user: User) -> str | None:
    if not user.avatar_path:
        return None
    path = _safe_absolute(_AVATAR_ROOT / user.avatar_path)
    mtime = int(path.stat().st_mtime) if path.is_file() else 0
    return f"/api/avatars/{user.id}?v={mtime}"


async def upload_avatar(db: AsyncSession, user: User, file: UploadFile) -> dict:
    content = await file.read(_AVATAR_MAX_BYTES + 1)
    if len(content) > _AVATAR_MAX_BYTES:
        raise ApiError(400, "AVATAR_TOO_LARGE", "头像文件不能超过 2MB")
    mime = _detect_image_mime(content)
    if mime is None or mime not in _AVATAR_MIME_EXT:
        raise ApiError(400, "AVATAR_INVALID_TYPE", "仅支持 PNG/JPG/GIF/WebP 格式的图片")
    ext = _AVATAR_MIME_EXT[mime]
    _AVATAR_ROOT.mkdir(parents=True, exist_ok=True)
    for old_ext in _AVATAR_MIME_EXT.values():
        old = _safe_absolute(_AVATAR_ROOT / f"{user.id}{old_ext}")
        if old.is_file():
            old.unlink()
    target = _safe_absolute(_AVATAR_ROOT / f"{user.id}{ext}")
    try:
        target.write_bytes(content)
    except OSError as exc:
        raise ApiError(500, "AVATAR_WRITE_FAILED", "头像保存失败，请稍后重试") from exc
    user.avatar_path = f"{user.id}{ext}"
    await db.flush()
    return {"avatar_url": avatar_url_for(user)}


async def clear_avatar(db: AsyncSession, user: User) -> dict:
    for ext in _AVATAR_MIME_EXT.values():
        old = _safe_absolute(_AVATAR_ROOT / f"{user.id}{ext}")
        if old.is_file():
            old.unlink()
    user.avatar_path = None
    await db.flush()
    return {"avatar_url": None}


async def read_avatar(user: User) -> tuple[bytes, str] | None:
    if not user.avatar_path:
        return None
    path = _safe_absolute(_AVATAR_ROOT / user.avatar_path)
    if not path.is_file():
        return None
    mime = _ext_to_mime(path.suffix) or "application/octet-stream"
    return path.read_bytes(), mime
```

- [ ] **Step 4: 实现 API 路由**（创建 `backend/app/api/avatars.py`）

```python
import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user, require_permissions
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.rbac import User
from app.schemas.common import success
from app.services import avatar_service

router = APIRouter(tags=["头像管理"])


@router.post("/me")
async def upload_own_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    result = await avatar_service.upload_avatar(db, current_user, file)
    await db.commit()
    return success(request, result)


@router.delete("/me")
async def clear_own_avatar(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    result = await avatar_service.clear_avatar(db, current_user)
    await db.commit()
    return success(request, result)


async def _target_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(
        select(User).where(User.id == user_id, User.is_deleted == False)
    )
    if user is None:
        raise ApiError(404, "USER_NOT_FOUND", "用户不存在")
    return user


@router.post("/{user_id}")
async def upload_avatar_for_user(
    request: Request,
    user_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = require_permissions("user:update"),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    target = await _target_user(db, user_id)
    result = await avatar_service.upload_avatar(db, target, file)
    await db.commit()
    return success(request, result)


@router.delete("/{user_id}")
async def clear_avatar_for_user(
    request: Request,
    user_id: uuid.UUID,
    current_user: User = require_permissions("user:update"),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    target = await _target_user(db, user_id)
    result = await avatar_service.clear_avatar(db, target)
    await db.commit()
    return success(request, result)


@router.get("/{user_id}")
async def get_avatar(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await _target_user(db, user_id)
    data = await avatar_service.read_avatar(target)
    if data is None:
        raise ApiError(404, "AVATAR_NOT_FOUND", "该用户未设置头像")
    content, mime = data
    return Response(
        content=content,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=3600"},
    )
```

- [ ] **Step 5: 注册路由**（`backend/app/main.py`）

import 区（`from app.api.agent import router as agent_router` 附近）加：

```python
from app.api.avatars import router as avatars_router
```

`app.include_router(metrics_router, prefix="/api")` 行后加：

```python
app.include_router(avatars_router, prefix="/api/avatars")
```

- [ ] **Step 6: 跑测试确认通过**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_t2"; python -X utf8 -m pytest tests/test_avatars_api.py -q
```
Expected: 全部 PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/services/avatar_service.py backend/app/api/avatars.py backend/app/main.py backend/tests/test_avatars_api.py
git commit -m "feat: add avatar upload/clear/read APIs"
```

---

### Task 3: 个人资料与修改密码 API

**Files:**
- Modify: `backend/app/schemas/user.py`
- Modify: `backend/app/api/users.py`
- Test: `backend/tests/test_users_api.py`

**Interfaces:**
- Consumes: `validate_password` / `verify_password` / `hash_password`（`app.core.security`）
- Produces: `PUT /api/users/me/profile`、`POST /api/users/me/password`（Task 5 前端依赖）

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_users_api.py` 末尾；先读该文件已有 fixture 与断言风格，沿用）

```python
async def test_update_own_profile(admin_client) -> None:
    resp = await admin_client.put(
        "/api/users/me/profile",
        json={"display_name": "New Name", "email": "newmail@example.com"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["display_name"] == "New Name"
    assert body["email"] == "newmail@example.com"


async def test_update_own_profile_email_conflict(admin_client, session) -> None:
    from app.models.rbac import User

    other = User(
        username="mailowner",
        display_name="Mail Owner",
        email="taken@example.com",
        password_hash=hash_password("Password123"),
        status="active",
    )
    session.add(other)
    await session.flush()

    resp = await admin_client.put(
        "/api/users/me/profile",
        json={"email": "taken@example.com"},
    )
    assert resp.status_code == 409


async def test_update_own_profile_empty_body(admin_client) -> None:
    resp = await admin_client.put("/api/users/me/profile", json={})
    assert resp.status_code == 400


async def test_change_password_wrong_old(admin_client) -> None:
    resp = await admin_client.post(
        "/api/users/me/password",
        json={"old_password": "WrongPass123", "new_password": "NewPass456"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_PASSWORD"


async def test_change_password_success_and_relogin(admin_client) -> None:
    resp = await admin_client.post(
        "/api/users/me/password",
        json={"old_password": "ChangeMe-Strong1", "new_password": "NewPass456"},
    )
    assert resp.status_code == 200, resp.text
    # 用新密码重新登录
    login = await admin_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "NewPass456"},
    )
    assert login.status_code == 200


async def test_change_password_weak_new(admin_client) -> None:
    resp = await admin_client.post(
        "/api/users/me/password",
        json={"old_password": "ChangeMe-Strong1", "new_password": "weak"},
    )
    assert resp.status_code == 400
```

注意：admin 初始密码是 `ChangeMe-Strong1`（conftest 的 INITIAL_ADMIN_PASSWORD 环境变量为 `ChangeMe-Strong1`，如测试库里 admin 密码不同，先读 `backend/tests/conftest.py` 确认后按实际值调整 `test_change_password_success_and_relogin` 的旧密码；改密码测试会把 admin 密码改成 NewPass456，**最后一个执行的弱密码测试用 `ChangeMe-Strong1` 会在改密后失败**——把 `test_change_password_weak_new` 的旧密码也改为 `NewPass456` 即可，或让改密测试最后恢复 `ChangeMe-Strong1`。以 conftest 实际为准，保证测试独立可重复。）

- [ ] **Step 2: 跑测试确认失败**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_t3"; python -X utf8 -m pytest tests/test_users_api.py -k "own_profile or change_password" -q
```
Expected: FAIL（路由不存在 404）

- [ ] **Step 3: schemas**（`backend/app/schemas/user.py` 追加）

```python
class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = None
    phone: str | None = None


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str
```

（`Field`/`BaseModel` 已在文件头部导入；若 `Field` 未导入则补 `from pydantic import BaseModel, Field`）

- [ ] **Step 4: 实现端点**（`backend/app/api/users.py` 追加，import 区补 `select`、`hash_password`、`verify_password`、`validate_password`、`_user_to_response` 相关导入——先读文件确认现有 import 与 `_user_to_response` 的引用方式）

```python
@router.put("/me/profile", summary="更新个人资料")
async def update_own_profile(
    request: Request,
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    if data.display_name is None and data.email is None and data.phone is None:
        raise ApiError(400, "VALIDATION_ERROR", "至少提供一个要更新的字段")
    if data.email is not None:
        existing = await db.scalar(
            select(User).where(
                User.email == data.email,
                User.id != current_user.id,
                User.is_deleted == False,
            )
        )
        if existing is not None:
            raise ApiError(409, "EMAIL_CONFLICT", "该邮箱已被其他用户使用")
    if data.phone is not None:
        existing = await db.scalar(
            select(User).where(
                User.phone == data.phone,
                User.id != current_user.id,
                User.is_deleted == False,
            )
        )
        if existing is not None:
            raise ApiError(409, "PHONE_CONFLICT", "该手机号已被其他用户使用")
    if data.display_name is not None:
        current_user.display_name = data.display_name
    if data.email is not None:
        current_user.email = data.email or None
    if data.phone is not None:
        current_user.phone = data.phone or None
    await db.commit()
    roles = await get_user_roles(db, current_user.id)
    return success(request, _user_to_response(current_user, roles))


@router.post("/me/password", summary="修改个人密码")
async def change_own_password(
    request: Request,
    data: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _csrf=Depends(require_csrf),
):
    if not verify_password(data.old_password, current_user.password_hash):
        raise ApiError(401, "INVALID_PASSWORD", "当前密码不正确")
    try:
        validate_password(data.new_password)
    except ValueError as exc:
        raise ApiError(400, "VALIDATION_ERROR", str(exc)) from exc
    current_user.password_hash = hash_password(data.new_password)
    await db.commit()
    return success(request, {"message": "密码已更新"})
```

注：`get_user_roles` 与 `_user_to_response` 的导入方式以 `users.py` 现有代码为准（若 users.py 已从 `app.services.user_service` 导入则沿用）。路由顺序注意：`/me/profile`、`/me/password` 必须放在 `/{user_id}` 相关路由**之前**或使用静态前缀——FastAPI 按声明顺序匹配，`PUT /me/profile` 与 `PUT /{user_id}` 方法相同，**必须把 `/me/*` 路由声明在 `/{user_id}` 之前**。

- [ ] **Step 5: 跑测试确认通过**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_t3"; python -X utf8 -m pytest tests/test_users_api.py -k "own_profile or change_password" -q
```
Expected: 全部 PASS

- [ ] **Step 6: 全文件回归**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_t3"; python -X utf8 -m pytest tests/test_users_api.py -q
```
Expected: 全部 PASS（若既有测试因 `/me/*` 路由顺序或 email 校验行为受影响，以最小适配修正并记录偏差）

- [ ] **Step 7: 提交**

```bash
git add backend/app/schemas/user.py backend/app/api/users.py backend/tests/test_users_api.py
git commit -m "feat: add own profile update and password change APIs"
```

---

### Task 4: 用户响应统一补 avatar_url

**Files:**
- Modify: `backend/app/services/user_service.py`（`_user_to_response`）
- Modify: `backend/app/api/auth.py`（`/me`）
- Modify: `frontend/src/types/auth.ts`、`frontend/src/types/user.ts`
- Test: `backend/tests/test_users_api.py`、`backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `avatar_service.avatar_url_for(user)`（Task 2）
- Produces: 所有用户响应含 `avatar_url`；前端 `CurrentUser.avatar_url?` / `UserListItem.avatar_url?`（Task 5/6 依赖）

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_users_api.py` 末尾）

```python
async def test_user_list_includes_avatar_url(admin_client) -> None:
    resp = await admin_client.get("/api/users?page_size=10")
    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert "avatar_url" in item
    assert item["avatar_url"] is None or item["avatar_url"].startswith("/api/avatars/")
```

追加到 `backend/tests/test_auth_api.py` 末尾（读该文件已有 /me 测试风格后写）：

```python
async def test_me_includes_avatar_url(admin_client) -> None:
    resp = await admin_client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert "avatar_url" in body
```

- [ ] **Step 2: 跑测试确认失败**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_t4"; python -X utf8 -m pytest tests/test_users_api.py::test_user_list_includes_avatar_url tests/test_auth_api.py::test_me_includes_avatar_url -q
```
Expected: FAIL（字段不存在）

- [ ] **Step 3: 后端实现**

`backend/app/services/user_service.py`：`_user_to_response` 的返回 dict 中 `"is_builtin": user.is_builtin,` 行后加：

```python
        "avatar_url": avatar_url_for(user),
```

文件头 import 区加：`from app.services.avatar_service import avatar_url_for`（注意：avatar_service 不 import user_service，无循环依赖；若 user_service 与 avatar_service 在同一包层级，用 `from app.services.avatar_service import avatar_url_for`）

`backend/app/api/auth.py`：`/me` 的 result dict 中 `"menu_permissions": permissions,` 行后加：

```python
        "avatar_url": avatar_url_for(current_user),
```

import 区加：`from app.services.avatar_service import avatar_url_for`

- [ ] **Step 4: 前端类型**

`frontend/src/types/auth.ts`：`CurrentUser` 接口加：

```typescript
  avatar_url?: string | null;
```

`frontend/src/types/user.ts`：`UserListItem` 接口加：

```typescript
  avatar_url?: string | null;
```

- [ ] **Step 5: 跑测试确认通过**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_t4"; python -X utf8 -m pytest tests/test_users_api.py tests/test_auth_api.py -q
```
Expected: 全部 PASS（`test_me_includes_avatar_url` 断言字段存在即可）

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/user_service.py backend/app/api/auth.py backend/tests/test_users_api.py backend/tests/test_auth_api.py frontend/src/types/auth.ts frontend/src/types/user.ts
git commit -m "feat: include avatar_url in user responses"
```

---

### Task 5: 前端个人资料页

**Files:**
- Create: `frontend/src/app/(dashboard)/settings/profile/page.tsx`
- Create: `frontend/src/components/profile/profile-page.tsx`
- Create: `frontend/src/components/profile/profile-page.test.tsx`

**Interfaces:**
- Consumes: `PUT /api/users/me/profile`、`POST /api/users/me/password`、`POST/DELETE /api/avatars/me`（Task 2/3）
- Produces: `/settings/profile` 路由（Task 6 导航入口指向它）

- [ ] **Step 1: 写失败测试**（创建 `frontend/src/components/profile/profile-page.test.tsx`，模式参考 `frontend/src/components/users/user-dialogs.test.tsx` 的 mock 方式；**禁止页面级 byRole**，用 `findPageButton` 模式）

```tsx
import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: mockApi };
});

import ProfilePage from "@/components/profile/profile-page";
import type { CurrentUser } from "@/types/auth";

const currentUser: CurrentUser = {
  id: "1",
  username: "admin",
  display_name: "Admin",
  roles: [],
  permissions: [],
  menu_permissions: [],
  avatar_url: null,
};

function pageButtons() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
}

function findPageButton(label: RegExp) {
  return pageButtons().find((b) => label.test(b.textContent || ""));
}

describe("ProfilePage", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  test("renders profile info form and password block", async () => {
    render(<ProfilePage currentUser={currentUser} />);
    expect(screen.getByLabelText("姓名")).toBeVisible();
    expect(screen.getByLabelText("邮箱")).toBeVisible();
    expect(screen.getByLabelText("手机号")).toBeVisible();
    expect(screen.getByText("修改密码")).toBeVisible();
  });

  test("saves profile changes", async () => {
    const user = userEvent.setup();
    render(<ProfilePage currentUser={currentUser} />);
    mockApi.mockResolvedValue({ display_name: "New Name" });

    await user.clear(screen.getByLabelText("姓名"));
    await user.type(screen.getByLabelText("姓名"), "New Name");
    await user.click(findPageButton(/保\s*存/)!);

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/users/me/profile",
        expect.objectContaining({ method: "PUT" })
      );
    });
  });

  test("blocks password change when confirmation mismatches", async () => {
    const user = userEvent.setup();
    render(<ProfilePage currentUser={currentUser} />);
    mockApi.mockClear();

    await user.type(screen.getByLabelText("旧密码"), "OldPass123");
    await user.type(screen.getByLabelText("新密码"), "NewPass456");
    await user.type(screen.getByLabelText("确认新密码"), "Different789");
    await user.click(findPageButton(/修改密码/)!);

    expect(mockApi).not.toHaveBeenCalledWith(
      "/api/users/me/password",
      expect.anything()
    );
    expect(await screen.findByText(/不一致/i)).toBeVisible();
  });

  test("uploads avatar via FormData", async () => {
    const user = userEvent.setup();
    render(<ProfilePage currentUser={currentUser} />);
    mockApi.mockResolvedValue({ avatar_url: "/api/avatars/1?v=123" });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array([137, 80, 78, 71])], "a.png", { type: "image/png" });
    Object.defineProperty(input, "files", { value: [file] });
    await user.upload(input, file);

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/avatars/me",
        expect.objectContaining({ method: "POST" })
      );
    });
  });
});
```

注：`user.upload` 需要 input 是 `type="file"`。组件实现用 `<input type="file" accept="image/png,image/jpeg,image/gif,image/webp">`（不用 antd Upload，减少测试复杂度）。

- [ ] **Step 2: 跑测试确认失败**

Run（工作目录 `frontend`）: `npx vitest run src/components/profile/profile-page.test.tsx`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 实现页面组件**（创建 `frontend/src/components/profile/profile-page.tsx`）

```tsx
"use client";

import { useRef, useState } from "react";
import { Avatar, Button, Form, Input, message, Space, UploadOutlined } from "antd";
import { UserOutlined } from "@ant-design/icons";
import { api } from "@/lib/api";
import PageHeader from "@/components/layout/page-header";
import DataSurface from "@/components/ui/data-surface";
import type { CurrentUser } from "@/types/auth";

interface ProfilePageProps {
  currentUser: CurrentUser;
}

export default function ProfilePage({ currentUser }: ProfilePageProps) {
  const [avatarUrl, setAvatarUrl] = useState<string | null>(
    currentUser.avatar_url ?? null
  );
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    if (file.size > 2 * 1024 * 1024) {
      message.error("头像文件不能超过 2MB");
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    setUploading(true);
    try {
      const data = await api<{ avatar_url: string }>("/api/avatars/me", {
        method: "POST",
        body: formData,
        csrf: true,
      });
      setAvatarUrl(data.avatar_url);
      message.success("头像已更新");
    } catch {
      message.error("头像上传失败");
    } finally {
      setUploading(false);
    }
  }

  async function handleClearAvatar() {
    setUploading(true);
    try {
      const data = await api<{ avatar_url: string | null }>("/api/avatars/me", {
        method: "DELETE",
        csrf: true,
      });
      setAvatarUrl(data.avatar_url);
      message.success("头像已移除");
    } catch {
      message.error("移除头像失败");
    } finally {
      setUploading(false);
    }
  }

  async function handleSaveProfile(values: { display_name: string; email?: string; phone?: string }) {
    setSaving(true);
    try {
      await api("/api/users/me/profile", {
        method: "PUT",
        body: JSON.stringify(values),
        csrf: true,
      });
      message.success("资料已保存");
    } catch {
      message.error("保存失败，请检查输入");
    } finally {
      setSaving(false);
    }
  }

  async function handleChangePassword(values: { old_password: string; new_password: string; confirm: string }) {
    if (values.new_password !== values.confirm) {
      message.error("两次输入的新密码不一致");
      return;
    }
    setSaving(true);
    try {
      await api("/api/users/me/password", {
        method: "POST",
        body: JSON.stringify({ old_password: values.old_password, new_password: values.new_password }),
        csrf: true,
      });
      message.success("密码已更新");
    } catch (err) {
      if (err instanceof Error && err.message) {
        message.error(err.message);
      } else {
        message.error("修改密码失败");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="page-hero">
        <PageHeader title="个人资料" description="管理你的头像、基本信息和密码" />
      </div>
      <div className="content" style={{ maxWidth: 720 }}>
        <DataSurface>
          <div style={{ padding: 24 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 24, marginBottom: 32 }}>
              <Avatar size={72} src={avatarUrl ?? undefined} icon={avatarUrl ? undefined : <UserOutlined />} />
              <Space direction="vertical">
                <Space>
                  <Button size="small" loading={uploading} onClick={() => fileRef.current?.click()}>
                    上传头像
                  </Button>
                  {avatarUrl && (
                    <Button size="small" danger onClick={handleClearAvatar} disabled={uploading}>
                      移除头像
                    </Button>
                  )}
                </Space>
                <span style={{ color: "var(--warm-muted)", fontSize: 12 }}>
                  支持 PNG/JPG/GIF/WebP，不超过 2MB
                </span>
              </Space>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleUpload(file);
                  e.target.value = "";
                }}
              />
            </div>

            <Form
              layout="vertical"
              initialValues={{
                display_name: currentUser.display_name,
                email: currentUser.email ?? undefined,
                phone: currentUser.phone ?? undefined,
              }}
              onFinish={handleSaveProfile}
              style={{ maxWidth: 480 }}
            >
              <Form.Item name="display_name" label="姓名" rules={[{ required: true, message: "请输入姓名" }]}>
                <Input />
              </Form.Item>
              <Form.Item name="email" label="邮箱" rules={[{ type: "email", message: "邮箱格式不正确" }]}>
                <Input />
              </Form.Item>
              <Form.Item name="phone" label="手机号">
                <Input />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
            </Form>

            <div style={{ marginTop: 40, paddingTop: 24, borderTop: "1px solid var(--warm-border)" }}>
              <h3>修改密码</h3>
              <Form
                layout="vertical"
                onFinish={handleChangePassword}
                style={{ maxWidth: 480, marginTop: 16 }}
              >
                <Form.Item name="old_password" label="旧密码" rules={[{ required: true, message: "请输入旧密码" }]}>
                  <Input.Password />
                </Form.Item>
                <Form.Item name="new_password" label="新密码" rules={[{ required: true, message: "请输入新密码" }]}>
                  <Input.Password />
                </Form.Item>
                <Form.Item name="confirm" label="确认新密码" rules={[{ required: true, message: "请确认新密码" }]}>
                  <Input.Password />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={saving}>修改密码</Button>
              </Form>
            </div>
          </div>
        </DataSurface>
      </div>
    </div>
  );
}
```

注意：`CurrentUser` 类型含 `email`/`phone`？先读 `frontend/src/types/auth.ts` 确认字段，若 `CurrentUser` 无 email/phone，则在 Task 4 的 Step 4 一并补上 `email?: string | null; phone?: string | null;`（**Task 4 的 Step 4 必须加这两个字段**，本任务依赖）。

- [ ] **Step 4: 创建路由页面**（创建 `frontend/src/app/(dashboard)/settings/profile/page.tsx`）

```tsx
"use client";

import ProfilePage from "@/components/profile/profile-page";

export default function SettingsProfilePage() {
  return <ProfilePage currentUser={undefined as never} />;
}
```

路由页需要用当前登录用户渲染——改为参考 `frontend/src/app/(dashboard)/users/page.tsx` 的 `ProtectedPage` 模式不行（资料页登录即可）。参考 `(agent)/layout.tsx` 的 `AuthenticatedPage` 模式：

```tsx
"use client";

import AuthenticatedPage from "@/components/auth/authenticated-page";
import ProfilePage from "@/components/profile/profile-page";

export default function SettingsProfilePage() {
  return (
    <AuthenticatedPage>
      {(user) => <ProfilePage currentUser={user} />}
    </AuthenticatedPage>
  );
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `npx vitest run src/components/profile/profile-page.test.tsx`
Expected: 全部 PASS（如有字段/标签不符，以组件实际为准最小适配测试，记录偏差）

- [ ] **Step 6: tsc 与 eslint**

Run: `npx eslint src/components/profile/profile-page.tsx src/components/profile/profile-page.test.tsx src/app/(dashboard)/settings/profile/page.tsx`
Expected: 0 errors（既有 warning 可忽略）

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/profile/profile-page.tsx frontend/src/components/profile/profile-page.test.tsx "frontend/src/app/(dashboard)/settings/profile/page.tsx"
git commit -m "feat: add profile settings page"
```

---

### Task 6: 导航头像与用户管理头像展示

**Files:**
- Modify: `frontend/src/components/layout/app-header.tsx`
- Modify: `frontend/src/components/layout/app-sidebar.tsx`
- Modify: `frontend/src/components/users/user-table.tsx`
- Modify: `frontend/src/components/users/user-drawer.tsx`
- Test: `frontend/src/components/layout/dashboard-shell.test.tsx`（如含 header 断言则适配）、`frontend/src/components/users/user-management.test.tsx`

**Interfaces:**
- Consumes: `CurrentUser.avatar_url?` / `UserListItem.avatar_url?`（Task 4）、头像 API（Task 2）
- Produces: 导航入口 `/settings/profile`（指向 Task 5 页面）

- [ ] **Step 1: 写失败测试**（追加到 `frontend/src/components/users/user-management.test.tsx` 末尾，用既有 `pageButtons`/`findPageButton` helper 风格）

```tsx
  test("renders avatar column with src when avatar_url present", async () => {
    mockApi.mockResolvedValue({
      ...mockUsers,
      items: [{ ...mockUsers.items[0], avatar_url: "/api/avatars/1?v=1" }],
    });
    render(<UserManagement currentUser={adminUser} />);
    await screen.findByText("alice");
    const avatar = document.querySelector(".ant-table-row .ant-avatar img");
    expect(avatar).not.toBeNull();
    expect(avatar?.getAttribute("src")).toBe("/api/avatars/1?v=1");
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/users/user-management.test.tsx -t "renders avatar column"`（若该文件无 `pageButtons` helper，参考 `user-dialogs.test.tsx` 的 helper 定义补上）
Expected: FAIL（无头像列）

- [ ] **Step 3: 用户表格头像列**（`frontend/src/components/users/user-table.tsx`）

在 columns 数组**最前面**加（操作列保持最右侧不动）：

```tsx
    {
      title: "头像",
      key: "avatar",
      width: 64,
      render: (_, user) => (
        <Avatar size={36} src={user.avatar_url ?? undefined} icon={user.avatar_url ? undefined : <UserOutlined />}>
          {!user.avatar_url && user.display_name?.[0]}
        </Avatar>
      ),
    },
```

import 区补：`import { Avatar } from "antd";`、`import { UserOutlined } from "@ant-design/icons";`

- [ ] **Step 4: 编辑抽屉头像区块**（`frontend/src/components/users/user-drawer.tsx`）

在抽屉 `Form` 上方（或抽屉 body 顶部）加头像区（管理员可上传/清除，`user` prop 是当前编辑的用户，`editing` 状态判断 create/edit；create 模式不显示头像区）：

```tsx
      {user && (
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <Avatar size={48} src={user.avatar_url ?? undefined} icon={user.avatar_url ? undefined : <UserOutlined />} />
          <Space>
            <Button size="small" onClick={() => fileRef.current?.click()}>上传头像</Button>
            {user.avatar_url && (
              <Button size="small" danger onClick={handleClearAvatar}>移除头像</Button>
            )}
          </Space>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleDrawerUpload(file);
              e.target.value = "";
            }}
          />
        </div>
      )}
```

组件内补状态与处理函数（`avatarUrl` 本地 state 初始自 `user?.avatar_url`，user 变化时同步——用 `useEffect` 或在抽屉 `open` 时重置；参考抽屉现有表单 initialValues 的处理方式；`handleDrawerUpload` 调 `POST /api/avatars/{user.id}`（FormData + csrf: true），`handleClearAvatar` 调 `DELETE /api/avatars/{user.id}`，成功后更新本地 avatarUrl state 并提示成功；上传后通知父组件刷新列表——父组件已有 `onSuccess` 回调，可复用）。

- [ ] **Step 5: 导航头像替换**

`frontend/src/components/layout/app-header.tsx`：
- `<Avatar icon={<UserOutlined />} className="header-avatar" />` 改为：

```tsx
          <Avatar
            src={user.avatar_url ?? undefined}
            icon={user.avatar_url ? undefined : <UserOutlined />}
            className="header-avatar"
          />
```

- 下拉菜单 items 加"个人资料"项（logout 前）：

```tsx
      {
        key: "profile",
        icon: <UserOutlined />,
        label: "个人资料",
        onClick: () => router.push("/settings/profile"),
      },
```

（`UserOutlined` 已在 import 中）

`frontend/src/components/layout/app-sidebar.tsx`：
- `<Avatar icon={<UserOutlined />} size="small" />` 改为：

```tsx
          <Avatar
            src={user.avatar_url ?? undefined}
            icon={user.avatar_url ? undefined : <UserOutlined />}
            size="small"
          />
```

（`UserOutlined` 若未导入则补 `import { UserOutlined } from "@ant-design/icons";`——先读文件确认）

- [ ] **Step 6: 跑测试确认通过**

Run: `npx vitest run src/components/users/user-management.test.tsx src/components/layout/dashboard-shell.test.tsx`
Expected: 全部 PASS（如 dashboard-shell 测试断言 header 下拉项数量，需按实际最小适配并记录偏差）

- [ ] **Step 7: eslint**

Run: `npx eslint src/components/layout/app-header.tsx src/components/layout/app-sidebar.tsx src/components/users/user-table.tsx src/components/users/user-drawer.tsx src/components/users/user-management.test.tsx`
Expected: 0 errors

- [ ] **Step 8: 提交**

```bash
git add frontend/src/components/layout/app-header.tsx frontend/src/components/layout/app-sidebar.tsx frontend/src/components/users/user-table.tsx frontend/src/components/users/user-drawer.tsx frontend/src/components/users/user-management.test.tsx
git commit -m "feat: show real avatars in nav and user management"
```

---

### Task 7: 全量回归

**Files:** 无代码改动

- [ ] **Step 1: 后端全量**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_final"; python -X utf8 -m pytest -q
```
Expected: 全部 PASS（如出现与本计划无关的既有失败，记录并注明，不顺手修）

- [ ] **Step 2: 前端全量**

Run（`frontend`）: `npx vitest run`
Expected: 除已知的并发进程 SSE 失败（run-stream-reducer / thought-narrative / run-diagnostics / use-run-event-stream 约 11 个）外全部 PASS

- [ ] **Step 3: 汇报**

汇总提交清单与回归结果。
