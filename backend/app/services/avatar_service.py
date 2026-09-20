from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models.rbac import User

_AVATAR_ROOT = Path("./var/avatars")
_AVATAR_MAX_BYTES = 20 * 1024 * 1024
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
        raise ApiError(400, "AVATAR_TOO_LARGE", "头像文件不能超过 20MB")
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
