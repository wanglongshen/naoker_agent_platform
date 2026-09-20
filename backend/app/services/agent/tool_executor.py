from __future__ import annotations

import ast
import asyncio
import hashlib
import ipaddress
import logging
import operator
import re
import socket
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import uuid

import httpx
from httpx import ConnectError, ReadError, RemoteProtocolError, TimeoutException
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.agent import AgentAttachment
from app.models.file import FileFolder, FileObject
from app.repositories.file_repository import FileRepository
from app.services.agent.file_reader import extract_file_text
from app.services.agent.login_session import assess_login_expired
from app.services.agent.plan_structure import (
    DEFAULT_MODULES,
    build_skeleton,
    extract_blueprint_guides,
    extract_doc_guides,
    has_placeholder_words,
    is_plan_like_content,
    parse_default_structure_from_blueprint,
    parse_structure_from_doc,
    quality_check,
    resolve_structure_doc,
    validate_plan_content_depth,
    validate_plan_structure,
    validate_plan_subitems,
)
from app.services.agent.workflow_policy import workflow_policy
from app.services.feishu.service import FeishuService

logger = logging.getLogger("tool_executor")

settings = get_settings()

FORBIDDEN_UTILITY_HOST_KEYWORDS = {
    "worldtimeapi",
    "openweathermap",
    "ipify",
    "ip-api",
    "quotable",
    "exchangerate",
}
NETWORK_ACTIONS = {"web_search", "http_request", "extract_web_content"}
MAX_WEB_TEXT = 6000
MAX_LINKS = 25
MAX_CALCULATOR_ABS = 10**100


class RetryableToolError(Exception):
    pass


def is_forbidden_utility_url(url: str) -> bool:
    hostname = urlparse(url).hostname or ""
    return any(keyword in hostname for keyword in FORBIDDEN_UTILITY_HOST_KEYWORDS)


def _safe_http_url(url: str) -> str | None:
    clean_url, _fragment = urldefrag(url.strip())
    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    normalized_hostname = parsed.hostname.rstrip(".").lower()
    if normalized_hostname == "localhost" or normalized_hostname.endswith(".localhost"):
        return None
    try:
        address = ipaddress.ip_address(normalized_hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        return None
    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, ""))


async def _request_without_forbidden_redirects(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    body: dict[str, Any] | None,
) -> httpx.Response:
    current_url = url
    for _ in range(5):
        safe_url = _safe_http_url(current_url)
        if safe_url is None:
            raise RetryableToolError("unsafe_network_target")
        if is_forbidden_utility_url(safe_url):
            raise RetryableToolError(f"forbidden_utility_url: {current_url}")
        await _validate_resolved_target(safe_url)
        response = await client.request(
            method=method,
            url=safe_url,
            json=body if method == "POST" else None,
            follow_redirects=False,
        )
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                return response
            current_url = str(response.url.join(location))
            continue
        return response
    raise RetryableToolError(f"redirect_limit_exceeded: {url}")


async def _validate_resolved_target(url: str) -> None:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise RetryableToolError("unsafe_network_target")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            parsed.hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, OSError) as exc:
        raise RetryableToolError("network_target_resolution_failed") from exc
    if not addresses:
        raise RetryableToolError("network_target_resolution_failed")
    try:
        resolved_addresses = [ipaddress.ip_address(item[4][0]) for item in addresses]
    except (IndexError, ValueError, TypeError) as exc:
        raise RetryableToolError("network_target_resolution_failed") from exc
    if any(not address.is_global for address in resolved_addresses):
        if settings.web_tool_allow_non_global_targets:
            logger.warning(
                "web_tool_allow_non_global_targets enabled: allowing non-global resolution host=%s",
                parsed.hostname,
            )
        else:
            raise RetryableToolError("unsafe_network_target")


class _WebContentParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._ignored_depth = 0
        self._in_title = False
        self._link_url: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            self._link_url = _safe_http_url(urljoin(self.base_url, href)) if href else None
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "title":
            self._in_title = False
        if tag == "a":
            title = _normalize_text(" ".join(self._link_text))[:200]
            if self._link_url and len(self.links) < MAX_LINKS:
                self.links.append({"title": title or self._link_url, "url": self._link_url})
            self._link_url = None
            self._link_text = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)
        if self._link_url is not None:
            self._link_text.append(data)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_cookie_string(cookie_str: str, domain: str) -> list[dict]:
    """Convert 'k1=v1; k2=v2' cookie string to Playwright cookie list."""
    cookies = []
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        cookies.append({
            "name": name.strip(),
            "value": value.strip(),
            "domain": domain,
            "path": "/",
        })
    return cookies


def _build_fetch_result(data: dict, url: str) -> dict:
    platform = data.get("platform", "generic")
    text = data.get("text", "")
    return {
        "status_code": data.get("status_code", 0),
        "url": data.get("url", url),
        "title": data.get("title", ""),
        "text": text,
        "platform": platform,
        "source": "playwright",
        "login_expired": assess_login_expired(platform, text),
    }


_structure_cache: dict[str, tuple[str, list[str]]] = {}

_STRUCTURE_RETRY_LIMIT = 3
_structure_retry_counts: dict[tuple[str, str], int] = {}


def _structure_retry_gate(owner: object, path: str, passed: bool) -> bool:
    """结构校验重试闸门：返回 True 表示放行。

    同一 (owner, path) 连续 3 次结构校验失败后放行（纠偏不判死），
    避免模型因表达差异被反复拦截直至 run 超时；放行状态保持到进程重启。
    未放行时校验通过（passed=True）会清除计数。
    """
    key = (str(owner), path)
    if passed:
        n = _structure_retry_counts.get(key, 0)
        if n < _STRUCTURE_RETRY_LIMIT:
            _structure_retry_counts.pop(key, None)
        return False
    n = _structure_retry_counts.get(key, 0) + 1
    _structure_retry_counts[key] = n
    if n >= _STRUCTURE_RETRY_LIMIT:
        logger.warning(
            "plan_structure_retry_exhausted",
            extra={"path": path, "attempts": n},
        )
        return True
    return False


async def _read_full_doc(doc_path: str) -> str:
    """读超管文件库中的规范文档/蓝图全文（不截断）；失败返回空串。"""
    from pathlib import Path
    from app.services.agent.workflow_policy import workflow_policy
    try:
        async with async_session_factory() as session:
            owner_id = await workflow_policy._resolve_super_admin_id(session)
            if owner_id is None:
                return ""
            file_obj = await workflow_policy._resolve_file(session, owner_id, doc_path)
            if file_obj is None or not file_obj.storage_key:
                return ""
            storage_path = Path(file_obj.storage_key)
            if not storage_path.is_file():
                return ""
            return storage_path.read_text(encoding="utf-8")
    except Exception:
        return ""


async def _load_doc_text(doc_path: str) -> str:
    """按文档路径读超管文件库中的规范文档/蓝图全文（不截断）；失败返回空串（静默降级）。"""
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.workflow_docs_enabled:
        return ""
    return await _read_full_doc(doc_path)


async def _resolve_active_structure(goal: str | None) -> list[str]:
    """按 goal 路由规范文档（或蓝图默认段）解析模块清单；失败回退缓存 → DEFAULT_MODULES。"""
    settings = get_settings()
    if not settings.workflow_docs_enabled:
        return DEFAULT_MODULES
    doc_path: str | None = None
    if goal:
        doc_path = resolve_structure_doc(goal)
    if doc_path is None:
        doc_path = settings.workflow_core_doc_path
    cached = _structure_cache.get(doc_path)
    text = await _load_doc_text(doc_path)
    if not text:
        return cached[1] if cached else DEFAULT_MODULES
    try:
        import hashlib
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except Exception:
        fingerprint = ""
    if cached and cached[0] == fingerprint:
        return cached[1]
    if doc_path == settings.workflow_core_doc_path:
        parsed = parse_default_structure_from_blueprint(text)
    else:
        parsed = parse_structure_from_doc(text)
    if parsed is None:
        return cached[1] if cached else DEFAULT_MODULES
    _structure_cache[doc_path] = (fingerprint, parsed)
    return parsed


async def _resolve_active_guides(goal: str | None) -> dict[str, str]:
    """按 goal 路由读规范文档/蓝图原文提取模块描述；失败返回空 dict（降级只查标题）。"""
    settings = get_settings()
    if not settings.workflow_docs_enabled:
        return {}
    doc_path = resolve_structure_doc(goal) if goal else None
    if doc_path is not None:
        doc_text = await _load_doc_text(doc_path)
        if doc_text:
            return extract_doc_guides(doc_text)
    blueprint_text = await _load_doc_text(settings.workflow_core_doc_path)
    if blueprint_text:
        return extract_blueprint_guides(blueprint_text)
    return {}


class ToolExecutor:
    _last_platform_search_at: dict[str, float] = {}
    _last_detail_at: dict[str, float] = {}

    async def _skeleton_with_blueprint(self, goal: str | None, modules: list[str]) -> str:
        """按 goal 路由读对应规范文档/蓝图原文，用其模块描述构建骨架；读不到则回退静态指引。"""
        doc_path = resolve_structure_doc(goal) if goal else None
        guides: dict[str, str] = {}
        if doc_path is not None:
            doc_text = await _load_doc_text(doc_path)
            if doc_text:
                guides = extract_doc_guides(doc_text)
        if not guides:
            blueprint_text = await _load_doc_text(
                get_settings().workflow_core_doc_path
            ) if getattr(get_settings(), "workflow_core_doc_path", None) else ""
            if blueprint_text:
                guides = extract_blueprint_guides(blueprint_text)
        return build_skeleton(modules, guides=guides)

    async def _project_context(
        self, session, owner_user_id: uuid.UUID | None, project_folder_id: uuid.UUID | None
    ) -> tuple[list[uuid.UUID] | None, str | None]:
        """返回 (subtree_ids | None, project_name | None)。未绑定返回 (None, None)。

        project_folder_id 非 None 时在给定 session 内解析项目根（校验归属与未删除），
        并返回其完整子树 id 列表与项目名；根无效返回 ([], None)。
        """
        if project_folder_id is None:
            return None, None
        repo = FileRepository(session)
        root = await session.get(FileFolder, project_folder_id)
        if root is None or root.is_deleted or root.owner_user_id != owner_user_id:
            return [], None
        subtree = await repo.get_folder_subtree_ids(project_folder_id)
        return subtree, root.name

    async def execute(self, action: dict[str, Any], web_enabled: bool = True,
                      owner_user_id: uuid.UUID | None = None,
                      is_super_admin: bool = False,
                      goal: str | None = None,
                      project_folder_id: uuid.UUID | None = None) -> dict[str, Any]:
        action_type = action.get("type")
        payload = action.get("input", {})
        if action_type in NETWORK_ACTIONS and not web_enabled:
            raise ValueError(f"networking_disabled: {action_type}")
        if action_type == "web_search":
            return await self._web_search(payload)
        if action_type in {"http_request", "extract_web_content"}:
            return await self._http_request(payload)
        if action_type == "calculator":
            return self._calculator(payload)
        if action_type == "read_file":
            return await self._read_file(payload, owner_user_id, is_super_admin, project_folder_id=project_folder_id)
        if action_type == "list_files":
            return await self._list_files(payload, owner_user_id, is_super_admin, project_folder_id=project_folder_id)
        if action_type == "write_file":
            return await self._write_file(payload, owner_user_id, goal, project_folder_id=project_folder_id)
        if action_type == "edit_file":
            return await self._edit_file(payload, owner_user_id, project_folder_id=project_folder_id)
        if action_type == "fetch_web_content":
            return await self._fetch_web_content(payload, owner_user_id)
        if action_type == "fetch_platform_search":
            return await self._fetch_platform_search(payload, owner_user_id)
        if action_type in {"feishu_read_doc", "feishu_create_doc", "feishu_edit_doc", "feishu_share_doc"}:
            return await self._feishu_action(action_type, payload, owner_user_id)
        if action_type == "finish":
            return {"final_answer": payload.get("answer", "done")}
        raise ValueError(f"Unsupported action type: {action_type}")

    async def _read_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None, is_super_admin: bool,
        project_folder_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        file_id = payload.get("file_id")
        path = payload.get("path")
        attachment_id = payload.get("attachment_id")

        if file_id:
            async with async_session_factory() as session:
                repo = FileRepository(session)
                file_obj = await repo.get_file(uuid.UUID(file_id))
                if file_obj is None:
                    return {"error": f"file_not_found: {file_id}"}
                if not is_super_admin:
                    if owner_user_id is None:
                        return {"error": f"file_not_found: {file_id}"}
                    try:
                        owner_uuid = uuid.UUID(str(owner_user_id))
                    except ValueError:
                        owner_uuid = None
                    if owner_uuid is not None and str(file_obj.owner_user_id) != str(owner_uuid):
                        return {"error": f"file_not_found: {file_id}"}
                subtree_ids, project_name = await self._project_context(
                    session, owner_user_id, project_folder_id
                )
                if subtree_ids is not None and (
                    file_obj.folder_id is None or file_obj.folder_id not in subtree_ids
                ):
                    return {"error": f"未找到文件，当前会话项目「{project_name}」内没有匹配文件", "hint": "文件不存在，可用 list_files 查看当前项目内的可用文件"}
                return self._format_file_result(file_obj)

        if path:
            # keep existing exact → folder → fuzzy resolution unchanged
            async with async_session_factory() as session:
                repo = FileRepository(session)
                subtree_ids, project_name = await self._project_context(session, owner_user_id, project_folder_id)

                folder_name: str | None = None
                filename = path
                if "/" in path:
                    parts = path.rsplit("/", 1)
                    folder_name = parts[0].strip() or None
                    filename = parts[1].strip()

                if subtree_ids is not None:
                    if not subtree_ids:
                        return {"error": "project_folder_invalid", "hint": "当前会话项目不存在或无权访问"}
                    file_obj = None
                    if folder_name:
                        folder = await repo.find_folder_by_name(owner_user_id, folder_name)
                        if folder is not None and folder.id in subtree_ids:
                            matches = await repo.search_by_folder_and_filename(folder.id, filename)
                            if len(matches) == 1:
                                file_obj = matches[0]
                            elif len(matches) > 1:
                                names = ", ".join(f.original_filename for f in matches[:5])
                                return {"error": f"multiple_files_match_in_folder: {folder_name}: {names}", "hint": "多个同名文件，请使用文件 ID 或更精确的路径定位"}
                    else:
                        file_obj = await repo.get_by_folder_ids(subtree_ids, filename)
                        if file_obj is None:
                            matches = await repo.search_by_folder_ids(subtree_ids, filename)
                            if len(matches) == 1:
                                file_obj = matches[0]
                            elif len(matches) > 1:
                                names = ", ".join(f.original_filename for f in matches[:5])
                                return {"error": f"multiple_files_match: {names}", "hint": "多个同名文件，请使用文件 ID 或带文件夹的路径定位"}
                    if file_obj is None:
                        return {"error": f"未找到文件，当前会话项目「{project_name}」内没有匹配文件", "hint": "文件不存在，可用 list_files 查看当前项目内的可用文件"}
                    return self._format_file_result(file_obj, requested_path=path)

                if is_super_admin:
                    file_obj = await repo.get_by_filename(path)
                else:
                    if owner_user_id is None:
                        raise ValueError("owner_user_id_required")
                    file_obj = await repo.get_by_owner_and_filename(owner_user_id, path)

                if file_obj is None and folder_name:
                    folder = await repo.find_folder_by_name(owner_user_id, folder_name)
                    if folder is not None:
                        matches = await repo.search_by_folder_and_filename(folder.id, filename)
                        if len(matches) == 1:
                            file_obj = matches[0]
                        elif len(matches) > 1:
                            names = ", ".join(f.original_filename for f in matches[:5])
                            return {"error": f"multiple_files_match_in_folder: {folder_name}: {names}", "hint": "多个同名文件，请使用文件 ID 或更精确的路径定位"}

                if file_obj is None:
                    if is_super_admin:
                        matches = await repo.search_by_filename(filename)
                    else:
                        matches = await repo.search_by_owner_and_filename(owner_user_id, filename)
                    if len(matches) == 1:
                        file_obj = matches[0]
                    elif len(matches) > 1:
                        names = ", ".join(f.original_filename for f in matches[:5])
                        return {"error": f"multiple_files_match: {names}", "hint": "多个同名文件，请使用文件 ID 或带文件夹的路径定位"}

                if file_obj is None:
                    hint = f" (folder: {folder_name})" if folder_name else ""
                    return {"error": f"file_not_found: {path}{hint}", "hint": "文件不存在，可用 list_files 查看我的文件中的可用文件"}
                return self._format_file_result(file_obj, requested_path=path)

        if attachment_id:
            if owner_user_id is None:
                raise ValueError("owner_user_id_required")
            async with async_session_factory() as session:
                owner_filter = AgentAttachment.owner_user_id == str(owner_user_id)
                try:
                    owner_filter = AgentAttachment.owner_user_id == uuid.UUID(str(owner_user_id))
                except ValueError:
                    pass
                result = await session.execute(
                    select(AgentAttachment).where(
                        AgentAttachment.id == uuid.UUID(attachment_id),
                        owner_filter,
                    )
                )
                attachment = result.scalar_one_or_none()
                if attachment is None:
                    return {"error": f"attachment_not_found: {attachment_id}"}
                text = attachment.extracted_text or ""
                if not text and attachment.storage_key:
                    from app.services.agent.storage import PrivateObjectStorage
                    storage = PrivateObjectStorage()
                    chunks: list[bytes] = []
                    async for chunk in storage.open(attachment.storage_key):
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    extracted = extract_file_text(attachment.media_type or "application/octet-stream", raw)
                    text = extracted["text"]
                if not text:
                    text = "(binary file, no text extracted)"
                return {
                    "filename": attachment.original_filename,
                    "media_type": attachment.media_type,
                    "content": text[:50000],
                }

        return {"error": "file_id_or_path_or_attachment_required", "hint": "read_file 必须提供 file_id、path 或 attachment_id 之一"}

    async def _list_files(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None, is_super_admin: bool,
        project_folder_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        keyword = payload.get("keyword")
        folder = payload.get("folder")
        # Folder inventory and version scans need to see more than the first
        # screen of files. The planner schema still keeps ordinary calls small.
        limit = min(max(int(payload.get("limit", 10)), 1), 1000)

        async with async_session_factory() as session:
            repo = FileRepository(session)
            subtree_ids, _project_name = await self._project_context(session, owner_user_id, project_folder_id)
            files = []
            if subtree_ids is not None and not subtree_ids:
                files = []
            elif folder:
                folder_obj = await repo.find_folder_by_name(owner_user_id, folder)
                if folder_obj is not None and (subtree_ids is None or folder_obj.id in subtree_ids):
                    files = await repo.search_by_folder_and_filename(folder_obj.id, keyword or "")
            elif keyword:
                if subtree_ids is not None:
                    files = await repo.search_by_folder_ids(subtree_ids, keyword)
                elif is_super_admin:
                    page = await repo.list_files(keyword=keyword, page_size=limit)
                    files = page.items
                else:
                    if owner_user_id is None:
                        raise ValueError("owner_user_id_required")
                    page = await repo.list_files(owner_id=owner_user_id, keyword=keyword, page_size=limit)
                    files = page.items
            else:
                if subtree_ids is not None:
                    files = await repo.search_by_folder_ids(subtree_ids, "")
                else:
                    page = await repo.list_files(owner_id=owner_user_id, page_size=limit)
                    files = page.items

        files = files[:limit]

        folder_paths: dict[str, str] = {}
        folder_ids = [f.folder_id for f in files if isinstance(getattr(f, "folder_id", None), uuid.UUID)]
        if folder_ids:
            async with async_session_factory() as session:
                result = await session.execute(select(FileFolder).where(FileFolder.id.in_(folder_ids)))
                for folder_obj in result.scalars().all():
                    folder_paths[str(folder_obj.id)] = folder_obj.path or "/"

        folders: list[dict[str, str]] = []
        async with async_session_factory() as session:
            repo = FileRepository(session)
            folder_rows = await repo.get_folder_tree(owner_user_id) if owner_user_id else []
            if subtree_ids is not None:
                subtree_set = set(subtree_ids)
                folder_rows = [f for f in folder_rows if f.id in subtree_set]
            seen: set[str] = set()
            for folder_obj in folder_rows:
                key = str(folder_obj.id)
                if key in seen:
                    continue
                seen.add(key)
                folders.append({
                    "folder_id": key,
                    "folder_path": folder_obj.path or "/",
                    "name": folder_obj.name,
                })

        return {
            "files": [
                {
                    "file_id": str(f.id),
                    "filename": f.original_filename,
                    "folder_path": folder_paths.get(str(f.folder_id), "/") if isinstance(getattr(f, "folder_id", None), uuid.UUID) else "/",
                    "size_bytes": f.size_bytes,
                    "updated_at": f.updated_at.isoformat() if f.updated_at else None,
                }
                for f in files
            ],
            "folders": folders,
            "total": len(files),
        }

    async def _write_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None,
        goal: str | None = None,
        project_folder_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        if owner_user_id is None:
            raise ValueError("owner_user_id_required")

        path = payload["path"]
        content = payload["content"]
        overwrite = bool(payload.get("overwrite", False))

        if not path.lower().endswith(".md"):
            raise ValueError("only_md_files_supported")

        if is_plan_like_content(content):
            modules = await _resolve_active_structure(goal)
            gate_open = False
            missing_modules = validate_plan_structure(content, modules=modules)
            if missing_modules and not gate_open:
                if _structure_retry_gate(owner_user_id, path, passed=False):
                    gate_open = True
                else:
                    skeleton = await self._skeleton_with_blueprint(goal, modules)
                    return {
                        "error": "plan_structure_incomplete",
                        "missing_modules": missing_modules,
                        "skeleton": skeleton,
                        "hint": (
                            "请保留你已写的内容，仅按 skeleton 中的模块结构补全缺失模块后重新 write_file，不要重写全文。"
                        "若一次输出放不下全部模块内容：先写入包含全部章节标题与要点的骨架文件（通过校验），"
                        "再用 edit_file 逐章填充详细内容。"
                        "文件内容已在文件中的部分不要重复输出，只补充缺失章节。"
                        ),
                    }
            missing_subitems = validate_plan_subitems(content, modules, await _resolve_active_guides(goal))
            if missing_subitems and not gate_open:
                if _structure_retry_gate(owner_user_id, path, passed=False):
                    gate_open = True
                else:
                    skeleton = await self._skeleton_with_blueprint(goal, modules)
                    flat = {m: "、".join(s) for m, s in missing_subitems.items()}
                    return {
                        "error": "plan_subitems_incomplete",
                        "missing_subitems": flat,
                        "skeleton": skeleton,
                        "hint": (
                            "以下模块缺少蓝图要求的关键子项：" +
                            "；".join(f"{m}（缺：{s}）" for m, s in flat.items()) +
                            "。请按蓝图的模块描述补全这些内容后重新 write_file，不要重写全文。"
                        ),
                    }
            shallow_modules = validate_plan_content_depth(content, modules)
            if shallow_modules and not gate_open:
                if _structure_retry_gate(owner_user_id, path, passed=False):
                    gate_open = True
                else:
                    return {
                        "error": "plan_content_shallow",
                        "shallow_modules": shallow_modules,
                        "hint": (
                            "以下模块只有章节标题、没有实质内容：" +
                            "、".join(shallow_modules) +
                            "。请为每个模块写出完整的正文内容（不要只写标题或留空），"
                            "然后重新 write_file。"
                        ),
                    }
            placeholder_hits = has_placeholder_words(content)
            if placeholder_hits and not gate_open:
                if _structure_retry_gate(owner_user_id, path, passed=False):
                    gate_open = True
                else:
                    return {
                        "error": "plan_has_placeholders",
                        "placeholder_words": placeholder_hits,
                        "hint": (
                            "内容包含未完成标记词：" + "、".join(placeholder_hits) +
                            "。请移除这些词，把内容写成完整的正式交付版本（客户版不得出现待补充/待确认等字样），"
                            "然后重新 write_file。"
                        ),
                    }
            qfails = quality_check(
                content, modules, min_chars=settings.quality_module_min_chars
            )
            if qfails and not gate_open:
                if _structure_retry_gate(owner_user_id, path, passed=False):
                    gate_open = True
                else:
                    return {
                        "error": "quality_check_failed",
                        "hint": "内容质检未通过：\n- " + "\n- ".join(qfails),
                    }

        from pathlib import Path as FilePath
        from datetime import datetime, UTC
        import hashlib

        _structure_retry_gate(owner_user_id, path, passed=True)

        filename = path.split("/")[-1]
        folder_parts = [p for p in path.split("/")[:-1] if p]

        async with async_session_factory() as session:
            subtree_ids, _project_name = await self._project_context(session, owner_user_id, project_folder_id)
            if subtree_ids is not None and not subtree_ids:
                return {"error": "目标文件夹不属于当前项目"}

            folder_uuid: uuid.UUID | None = None
            if folder_parts:
                parent_id: uuid.UUID | None = None
                current_path = ""
                for part in folder_parts:
                    current_path = f"{current_path}/{part}" if current_path else f"/{part}"
                    result = await session.execute(
                        select(FileFolder).where(
                            FileFolder.owner_user_id == owner_user_id,
                            FileFolder.name == part,
                            FileFolder.parent_folder_id == parent_id,
                            FileFolder.is_deleted == False,
                        )
                    )
                    folder = result.scalar_one_or_none()
                    if folder is None:
                        if subtree_ids is not None:
                            return {"error": "目标文件夹不属于当前项目"}
                        folder = FileFolder(
                            owner_user_id=owner_user_id,
                            parent_folder_id=parent_id,
                            name=part,
                            path=current_path,
                            depth=current_path.count("/"),
                            created_by=owner_user_id,
                        )
                        session.add(folder)
                        await session.flush()
                    elif subtree_ids is not None and folder.id not in subtree_ids:
                        return {"error": "目标文件夹不属于当前项目"}
                    parent_id = folder.id
                folder_uuid = parent_id
            elif subtree_ids is not None:
                folder_uuid = project_folder_id

            # Existing file check (exact folder + filename)
            existing_result = await session.execute(
                select(FileObject).where(
                    FileObject.owner_user_id == owner_user_id,
                    FileObject.folder_id == folder_uuid,
                    FileObject.original_filename == filename,
                    FileObject.is_deleted == False,
                )
            )
            existing = existing_result.scalar_one_or_none()

            content_bytes = content.encode("utf-8")
            digest = hashlib.sha256(content_bytes).hexdigest()

            if existing is not None:
                if not overwrite:
                    raise ValueError(f"file_already_exists: {path}")
                storage_path = FilePath(existing.storage_key) if existing.storage_key else None
                if storage_path is None or not storage_path.parent.exists():
                    storage_path = FilePath("./var/files") / str(owner_user_id) / str(existing.id)
                    storage_path.parent.mkdir(parents=True, exist_ok=True)
                storage_path.write_bytes(content_bytes)
                existing.size_bytes = len(content_bytes)
                existing.sha256 = digest
                existing.extracted_text = content
                existing.preview_status = "ready"
                now = datetime.now(UTC)
                existing.created_at = now
                existing.updated_at = now
                session.add(existing)
                await session.commit()
                return {
                    "file_id": str(existing.id),
                    "filename": existing.original_filename,
                    "path": "/" + path.strip("/"),
                    "folder_path": "/" + path.rsplit("/", 1)[0].strip("/") if "/" in path else "/",
                    "bytes": len(content_bytes),
                    "size_bytes": len(content_bytes),
                    "sha256": digest,
                    "source": "my_files",
                    "action": "updated",
                }

            file_uuid = uuid.uuid4()
            storage_root = FilePath("./var/files")
            storage_dir = storage_root / str(owner_user_id)
            storage_dir.mkdir(parents=True, exist_ok=True)
            storage_path = storage_dir / str(file_uuid)
            storage_path.write_bytes(content_bytes)

            file_obj = FileObject(
                id=file_uuid,
                owner_user_id=owner_user_id,
                folder_id=folder_uuid,
                storage_key=storage_path.as_posix(),
                filename=filename,
                original_filename=filename,
                media_type="text/markdown",
                size_bytes=len(content_bytes),
                sha256=digest,
                extracted_text=content,
                preview_status="ready",
                created_by=owner_user_id,
            )
            session.add(file_obj)

            if folder_uuid is not None:
                folder = await session.get(FileFolder, folder_uuid)
                if folder is not None:
                    folder.child_file_count = (folder.child_file_count or 0) + 1
                    folder.total_size_bytes = (folder.total_size_bytes or 0) + len(content_bytes)
                    session.add(folder)

            await session.commit()
            return {
                "file_id": str(file_uuid),
                "filename": filename,
                "path": "/" + path.strip("/"),
                "folder_path": "/" + path.rsplit("/", 1)[0].strip("/") if "/" in path else "/",
                "bytes": len(content_bytes),
                "size_bytes": len(content_bytes),
                "sha256": digest,
                "source": "my_files",
                "action": "created",
            }

    async def _edit_file(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None,
        project_folder_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        if owner_user_id is None:
            raise ValueError("owner_user_id_required")

        file_id = payload.get("file_id")
        path = payload.get("path")
        old_str = payload["old_str"]
        new_str = payload["new_str"]

        from pathlib import Path as FilePath
        from datetime import datetime, UTC
        import hashlib

        async with async_session_factory() as session:
            repo = FileRepository(session)
            file_obj = None

            if file_id:
                file_obj = await repo.get_file(uuid.UUID(file_id))
                if file_obj is None:
                    raise ValueError(f"file_not_found: {file_id}")
                if not (file_obj.owner_user_id == owner_user_id):
                    raise ValueError(f"file_not_found: {file_id}")
                subtree_ids, project_name = await self._project_context(
                    session, owner_user_id, project_folder_id
                )
                if subtree_ids is not None and (
                    file_obj.folder_id is None or file_obj.folder_id not in subtree_ids
                ):
                    raise ValueError(f"未找到文件，当前会话项目「{project_name}」内没有匹配文件")
            elif path:
                folder_name: str | None = None
                filename = path
                if "/" in path:
                    parts = path.rsplit("/", 1)
                    folder_name = parts[0].strip() or None
                    filename = parts[1].strip()

                subtree_ids, project_name = await self._project_context(session, owner_user_id, project_folder_id)
                if subtree_ids is not None:
                    if not subtree_ids:
                        raise ValueError("project_folder_invalid")
                    if folder_name:
                        folder = await repo.find_folder_by_name(owner_user_id, folder_name)
                        if folder is not None and folder.id in subtree_ids:
                            matches = await repo.search_by_folder_and_filename(folder.id, filename)
                            if len(matches) == 1:
                                file_obj = matches[0]
                    else:
                        file_obj = await repo.get_by_folder_ids(subtree_ids, filename)
                        if file_obj is None:
                            matches = await repo.search_by_folder_ids(subtree_ids, filename)
                            if len(matches) == 1:
                                file_obj = matches[0]
                    if file_obj is None:
                        raise ValueError(f"未找到文件，当前会话项目「{project_name}」内没有匹配文件")
                else:
                    file_obj = await repo.get_by_owner_and_filename(owner_user_id, path)
                    if file_obj is None and folder_name:
                        folder = await repo.find_folder_by_name(owner_user_id, folder_name)
                        if folder is not None:
                            matches = await repo.search_by_folder_and_filename(folder.id, filename)
                            if len(matches) == 1:
                                file_obj = matches[0]
                    if file_obj is None:
                        matches = await repo.search_by_owner_and_filename(owner_user_id, filename)
                        if len(matches) == 1:
                            file_obj = matches[0]
                    if file_obj is None:
                        raise ValueError(f"file_not_found: {path}")
            else:
                raise ValueError("file_id_or_path_required")

            storage_path = FilePath(file_obj.storage_key) if file_obj.storage_key else None
            if not storage_path or not storage_path.is_file():
                raise ValueError(f"file_data_not_found: {file_obj.original_filename}")
            current_content = storage_path.read_text(encoding="utf-8")

            count = current_content.count(old_str)
            if count == 0:
                raise ValueError("old_str not found")
            if count > 1:
                raise ValueError(f"old_str found multiple times: {count}")

            new_content = current_content.replace(old_str, new_str, 1)
            storage_path.write_text(new_content, encoding="utf-8")
            content_bytes = new_content.encode("utf-8")
            file_obj.size_bytes = len(content_bytes)
            file_obj.sha256 = hashlib.sha256(content_bytes).hexdigest()
            file_obj.extracted_text = new_content
            file_obj.preview_status = "ready"
            file_obj.updated_at = datetime.now(UTC)
            session.add(file_obj)
            await session.commit()
            return {
                "file_id": str(file_obj.id),
                "filename": file_obj.original_filename,
                "path": "/" + str(path or file_obj.original_filename).strip("/"),
                "bytes": len(content_bytes),
                "size_bytes": len(content_bytes),
                "sha256": file_obj.sha256,
                "source": "my_files",
                "action": "updated",
            }

    @staticmethod
    def _format_file_result(file_obj, requested_path: str | None = None) -> dict[str, Any]:
        from pathlib import Path

        content_bytes = b""
        storage_path = Path(file_obj.storage_key) if file_obj.storage_key else None
        if storage_path and storage_path.is_file():
            size = storage_path.stat().st_size
            if size > 10 * 1024 * 1024:
                result = {"text": f"(file too large: {size} bytes)", "truncated": False}
            else:
                content_bytes = storage_path.read_bytes()
                result_text = extract_file_text(file_obj.media_type or "application/octet-stream", content_bytes)
                result = {"text": result_text["text"], "truncated": result_text["truncated"]}
        else:
            result = {"text": "", "truncated": False}

        digest = hashlib.sha256(content_bytes).hexdigest() if content_bytes else getattr(file_obj, "sha256", None)
        return {
            "file_id": str(file_obj.id),
            "filename": file_obj.original_filename,
            "path": "/" + str(requested_path or file_obj.original_filename).strip("/"),
            "media_type": file_obj.media_type,
            "bytes": len(content_bytes) if content_bytes else int(getattr(file_obj, "size_bytes", 0) or 0),
            "size_bytes": len(content_bytes) if content_bytes else int(getattr(file_obj, "size_bytes", 0) or 0),
            "sha256": digest,
            "source": "my_files",
            "content": result["text"],
            "truncated": result["truncated"],
        }

    async def _web_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not settings.tavily_api_key:
            raise ValueError("tavily_api_key_not_configured")
        max_results = min(max(int(payload.get("max_results", 5)), 1), 10)
        timeout = httpx.Timeout(settings.http_timeout_seconds)
        tavily_url = f"{settings.tavily_base_url.rstrip('/')}/search"
        try:
            await _validate_resolved_target(tavily_url)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    tavily_url,
                    json={
                        "query": payload["query"],
                        "max_results": max_results,
                    },
                    headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
                )
                response.raise_for_status()
        except (TimeoutException, ConnectError, ReadError, RemoteProtocolError, httpx.RequestError) as exc:
            raise RetryableToolError("tavily_request_failed") from exc
        except httpx.HTTPStatusError as exc:
            raise RetryableToolError(f"tavily_status_code: {exc.response.status_code}") from exc

        results = []
        for item in response.json().get("results", [])[:max_results]:
            safe_url = _safe_http_url(str(item.get("url", "")))
            if not safe_url:
                continue
            results.append(
                {
                    "title": _normalize_text(str(item.get("title", "")))[:300],
                    "url": safe_url,
                    "content": _normalize_text(str(item.get("content", "")))[:1000],
                }
            )
        return {"results": results}

    async def _http_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        method = payload.get("method", "GET")
        if method != "GET":
            raise ValueError("http_method_not_allowed")
        url = _safe_http_url(str(payload["url"]))
        if url is None:
            raise ValueError("unsafe_network_target")
        if is_forbidden_utility_url(url):
            raise RetryableToolError(f"forbidden_utility_url: {url}")
        timeout = httpx.Timeout(settings.http_timeout_seconds)
        headers = {
            "User-Agent": "AgentLoopMVP/0.1 (+https://localhost)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers) as client:
                response = await _request_without_forbidden_redirects(client, method, url, None)
        except TimeoutException as exc:
            raise RetryableToolError(f"http_timeout: {url}") from exc
        except ConnectError as exc:
            raise RetryableToolError(f"http_connect_error: {url}") from exc
        except ReadError as exc:
            raise RetryableToolError(f"http_read_error: {url}") from exc
        except RemoteProtocolError as exc:
            raise RetryableToolError(f"http_protocol_error: {url}") from exc
        except httpx.RequestError as exc:
            raise RetryableToolError(f"http_request_error: {url}") from exc
        if response.status_code in {403, 408, 425, 429, 500, 502, 503, 504}:
            raise RetryableToolError(f"retryable_status_code: {response.status_code}")

        final_url = str(response.url)
        parser = _WebContentParser(final_url)
        parser.feed(response.text[:100_000])
        return {
            "status_code": response.status_code,
            "url": final_url,
            "title": _normalize_text(" ".join(parser.title_parts))[:300],
            "text": _normalize_text(" ".join(parser.text_parts))[:MAX_WEB_TEXT],
            "links": parser.links,
        }

    async def _fetch_web_content(self, payload: dict[str, Any], owner_user_id: uuid.UUID | None) -> dict[str, Any]:
        url = _safe_http_url(str(payload.get("url", "")))
        if url is None:
            raise ValueError("unsafe_network_target")
        if is_forbidden_utility_url(url):
            raise RetryableToolError(f"forbidden_utility_url: {url}")

        cookies = payload.get("cookies")
        if cookies is None and owner_user_id is not None:
            from urllib.parse import urlparse
            from app.services.agent.web_cookie_store import get_user_cookie_string

            domain = urlparse(url).hostname or ""
            if domain:
                cookie_str = await get_user_cookie_string(owner_user_id, domain)
                if cookie_str:
                    cookies = _parse_cookie_string(cookie_str, domain)

        timeout = httpx.Timeout(settings.web_renderer_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{settings.web_renderer_url.rstrip('/')}/render",
                    json={"url": url, "cookies": cookies if isinstance(cookies, list) else None},
                )
                response.raise_for_status()
                data = response.json()
        except (TimeoutException, ConnectError, httpx.RequestError) as exc:
            raise RetryableToolError("web_renderer_unavailable") from exc
        except httpx.HTTPStatusError as exc:
            raise RetryableToolError(f"web_renderer_status: {exc.response.status_code}") from exc

        if data.get("error"):
            raise RetryableToolError(f"web_render_error: {data['error'][:200]}")
        return _build_fetch_result(data, url)

    async def _fetch_platform_search(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None
    ) -> dict[str, Any]:
        platform = str(payload.get("platform", ""))
        keyword = str(payload.get("keyword", ""))
        max_results = int(payload.get("max_results", 30))
        if platform not in ("xiaohongshu", "douyin"):
            raise ValueError("unsupported_platform")
        domain = "www.douyin.com" if platform == "douyin" else "www.xiaohongshu.com"

        # 同平台连续搜索至少间隔 3 秒，降低平台风控/验证码触发概率
        now = time.monotonic()
        last = ToolExecutor._last_platform_search_at.get(platform, 0.0)
        wait = 3.0 - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        ToolExecutor._last_platform_search_at[platform] = time.monotonic()

        cookies = None
        if owner_user_id is not None:
            from app.services.agent.web_cookie_store import get_user_cookie_string

            cookie_str = await get_user_cookie_string(owner_user_id, domain)
            if cookie_str:
                cookies = _parse_cookie_string(cookie_str, domain)

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.web_renderer_search_timeout_seconds)
            ) as client:
                response = await client.post(
                    f"{settings.web_renderer_url.rstrip('/')}/search",
                    json={
                        "platform": platform,
                        "keyword": keyword,
                        "max_results": max_results,
                        "cookies": cookies if isinstance(cookies, list) else None,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except (TimeoutException, ConnectError, httpx.RequestError) as exc:
            raise RetryableToolError("web_renderer_unavailable") from exc
        except httpx.HTTPStatusError as exc:
            raise RetryableToolError(f"web_renderer_status: {exc.response.status_code}") from exc

        if data.get("error"):
            raise RetryableToolError(f"web_render_error: {data['error'][:200]}")
        samples = data.get("samples") or []
        cleaned = [
            s
            for s in samples
            if s.get("title") and s.get("url") and s.get("url") != "https://www.douyin.com" and s.get("url") != "https://www.xiaohongshu.com"
        ]
        detail_failed = 0
        stored_count = 0
        platform_total = len(samples)
        if owner_user_id is not None and cleaned:
            sem = asyncio.Semaphore(3)

            async def fetch_detail(sample: dict) -> dict:
                nonlocal detail_failed
                async with sem:
                    now = time.monotonic()
                    last = ToolExecutor._last_detail_at.get(platform, 0.0)
                    wait = 1.0 - (now - last)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    ToolExecutor._last_detail_at[platform] = time.monotonic()
                    try:
                        async with httpx.AsyncClient(
                            timeout=httpx.Timeout(8.0)
                        ) as client:
                            resp = await client.post(
                                f"{settings.web_renderer_url.rstrip('/')}/detail",
                                json={
                                    "platform": platform,
                                    "url": sample["url"],
                                    "cookies": cookies if isinstance(cookies, list) else None,
                                },
                            )
                            resp.raise_for_status()
                            detail = resp.json()
                    except Exception:
                        detail_failed += 1
                        return sample
                    if detail.get("error") or detail.get("login_required"):
                        detail_failed += 1
                        return sample
                    merged = {**sample}
                    for k in (
                        "title",
                        "content",
                        "published_at",
                        "like_count",
                        "collect_count",
                        "comment_count",
                        "topic_tags",
                        "author",
                    ):
                        if detail.get(k) is not None:
                            merged[k] = detail[k]
                    if detail.get("image_urls"):
                        merged["image_urls"] = detail["image_urls"]
                    elif merged.get("cover_image"):
                        merged["image_urls"] = [merged["cover_image"]]
                    return merged

            cleaned = await asyncio.gather(*(fetch_detail(s) for s in cleaned))
            try:
                from app.db.session import async_session_factory
                from app.repositories.platform_note_repository import (
                    count_platform,
                    upsert,
                )

                async with async_session_factory() as session:
                    for sample in cleaned:
                        ok = await upsert(
                            session, owner_user_id, platform, keyword, sample
                        )
                        if ok:
                            stored_count += 1
                    await session.commit()
                    platform_total = await count_platform(
                        session, owner_user_id, platform
                    )
            except Exception:
                logger.warning("platform_note_persist_failed", exc_info=True)
        visible = cleaned[:20]
        note_parts = [f"该平台累计 {platform_total}/40（保底）/150（期望）条（由系统统计）"]
        if platform_total < 150 and platform_total >= 40:
            note_parts.append(f"已达标 40，距 150 期望还差 {150 - platform_total} 条，继续搜索可补充")
        if detail_failed:
            note_parts.append(f"{detail_failed} 条详情抓取失败（可能需登录或受风控）")
        if data.get("login_required"):
            note_parts.append("平台登录态不足，部分内容可能无法获取；可提示用户登录")
        return {
            "platform": platform,
            "keyword": keyword,
            "sample_count": len(samples),
            "samples": visible,
            "total_available": len(cleaned),
            "stored_count": stored_count,
            "detail_failed": detail_failed,
            "platform_total": platform_total,
            "login_required": bool(data.get("login_required")),
            "note": "；".join(note_parts),
        }

    async def _feishu_action(
        self, action_type: str, payload: dict[str, Any], owner_user_id: uuid.UUID | None
    ) -> dict[str, Any]:
        if owner_user_id is None:
            raise ValueError("owner_user_id_required")

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
                await service.edit_document(
                    owner_user_id, payload["doc_token"], payload["block_id"], payload["new_content"]
                )
                return {"updated": True, "source": "feishu"}
            if action_type == "feishu_share_doc":
                await service.set_permission(
                    owner_user_id, payload["doc_token"], payload["permission"]
                )
                return {"shared": True, "source": "feishu"}
        except ValueError:
            raise
        raise ValueError(f"Unsupported action type: {action_type}")

    def _calculator(self, payload: dict[str, Any]) -> dict[str, Any]:
        expression = payload.get("expression", "")
        if not isinstance(expression, str) or not expression.strip() or len(expression) > 200:
            raise ValueError("calculator_invalid_expression")
        expression = expression.replace("^", "**")
        try:
            tree = ast.parse(expression, mode="eval")
            result = self._calculate_node(tree.body, [0])
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("calculator_"):
                raise
            raise ValueError("calculator_invalid_expression") from exc
        return {"result": result}

    def _calculate_node(self, node: ast.AST, operations: list[int]) -> int | float:
        operations[0] += 1
        if operations[0] > 50:
            raise ValueError("calculator_too_complex")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("calculator_unsupported_expression")
            result = node.value
        elif isinstance(node, ast.UnaryOp) and type(node.op) in {ast.UAdd, ast.USub}:
            operand = self._calculate_node(node.operand, operations)
            result = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and type(node.op) in {
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow
        }:
            left = self._calculate_node(node.left, operations)
            right = self._calculate_node(node.right, operations)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("calculator_exponent_too_large")
            functions = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.FloorDiv: operator.floordiv,
                ast.Mod: operator.mod,
                ast.Pow: operator.pow,
            }
            result = functions[type(node.op)](left, right)
        else:
            raise ValueError("calculator_unsupported_expression")
        if not isinstance(result, (int, float)) or abs(result) > MAX_CALCULATOR_ABS:
            raise ValueError("calculator_result_out_of_bounds")
        return result
