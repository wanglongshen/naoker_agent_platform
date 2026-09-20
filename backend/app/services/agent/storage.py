import asyncio
import hashlib
import os
from pathlib import Path
from typing import AsyncIterator
from uuid import UUID

from app.core.config import get_settings

_ALLOWED_MIME_TYPES = {
    "text/plain",
    "text/csv",
    "text/markdown",
    "text/html",
    "application/pdf",
    "application/json",
}

_TEXT_MIME_TYPES = {
    "text/plain",
    "text/csv",
    "text/markdown",
    "text/html",
    "application/json",
}

_EXECUTABLE_MAGIC = {
    b"MZ",
    b"\x7fELF",
    b"\xca\xfe\xba\xbe",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
}

_ARCHIVE_MAGIC = {
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x1f\x8b\x08",
    b"\x1f\x9d\x90",
    b"BZh",
    b"\x75\x73\x74\x61\x72",
    b"Rar!\x1a\x07",
    b"\xfd7zXZ\x00",
}

settings = get_settings()


def build_attachment_key(attachment_id: UUID) -> str:
    return f"attachments/{attachment_id.hex}"


def _sniff_magic_bytes(head: bytes) -> str | None:
    for magic in _EXECUTABLE_MAGIC:
        if head.startswith(magic):
            raise ValueError("Executable files are not allowed")
    for magic in _ARCHIVE_MAGIC:
        if head.startswith(magic):
            raise ValueError("Archive files are not allowed")
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    stripped = head.lstrip()
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        return "application/json"
    if stripped.startswith(b"<!DOCTYPE") or stripped.startswith(b"<html") or stripped.startswith(b"<HTML"):
        return "text/html"
    return None


def validate_and_normalize_mime(content_type: str, head: bytes) -> str:
    candidate = content_type.split(";")[0].strip().lower()
    sniffed = _sniff_magic_bytes(head)
    if sniffed:
        candidate = sniffed
    if candidate not in _ALLOWED_MIME_TYPES:
        raise ValueError(f"MIME type not allowed: {candidate}")
    return candidate


def normalize_display_filename(filename: str) -> str:
    name = filename.replace("\\", "/")
    name = Path(name).name
    name = name.strip()
    if not name:
        name = "untitled"
    return name


def is_text_mime(media_type: str) -> bool:
    return media_type in _TEXT_MIME_TYPES


class PrivateObjectStorage:
    def __init__(self, root: str | None = None) -> None:
        if root is None:
            root = settings.agent_storage_root
        self._root = Path(root).resolve()

    @property
    def root_path(self) -> Path:
        return self._root

    def _resolve_key(self, key: str) -> Path:
        normalized = key.replace("\\", "/")
        target = (self._root / normalized).resolve()
        if not str(target).startswith(str(self._root)):
            raise ValueError("Invalid storage key")
        return target

    async def put(self, key: str, content_stream: AsyncIterator[bytes]) -> int:
        target = self._resolve_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        sha256 = hashlib.sha256()
        total = 0

        def _write_sync():
            nonlocal total
            with open(target, "wb") as f:
                return f, sha256

        loop = asyncio.get_running_loop()

        with open(target, "wb") as f:
            async for chunk in content_stream:
                f.write(chunk)
                sha256.update(chunk)
                total += len(chunk)

        return total

    async def open(self, key: str) -> AsyncIterator[bytes]:
        target = self._resolve_key(key)
        if not target.is_file():
            raise FileNotFoundError(key)

        chunk_size = 64 * 1024

        def _read_file():
            with open(target, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

        for chunk in _read_file():
            yield chunk

    async def compute_sha256(self, key: str) -> str:
        sha256 = hashlib.sha256()
        async for chunk in self.open(key):
            sha256.update(chunk)
        return sha256.hexdigest()

    async def delete(self, key: str) -> None:
        target = self._resolve_key(key)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
