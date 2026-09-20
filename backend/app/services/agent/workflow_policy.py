from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.file import FileFolder, FileObject
from app.models.rbac import Role, User, UserRole
from app.services.agent.workflow_rules import (
    ParsedRules,
    classify_task_type,
    workflow_rules_cache,
)

logger = logging.getLogger("workflow_policy")

_DOC_CONTENT_LIMIT = 12000  # 路由规范文档上限

_PLAN_CLASS_TYPES = {
    "完整方案需求",
    "完整 UGC 种草方案",
    "小红书种草方案",
    "矩阵号代运营方案",
    "修改/扩写需求",
}

_PLAN_REQUIRED_DOC_PATHS = (
    "00_Agent规范与模板/脑壳儿_案例库索引.md",
    "00_Agent规范与模板/脑壳儿_方案输出模板.md",
    "00_Agent规范与模板/脑壳儿_方案评分规范.md",
    "00_Agent规范与模板/脑壳儿_中国市场调研资料源规范.md",
)

_PLAN_GOAL_PATTERN = re.compile(r"方案|策划|创意建议")


def is_plan_goal(goal: str, rules: ParsedRules | None) -> bool:
    """Recognize deliverable-plan requests even if blueprint parsing is incomplete."""
    task_type = classify_task_type(goal, rules.task_types) if rules else None
    return bool(
        (task_type is not None and task_type.type_name in _PLAN_CLASS_TYPES)
        or _PLAN_GOAL_PATTERN.search(goal or "")
    )


class WorkflowPolicy:
    def __init__(self) -> None:
        self._cache: dict[str, dict[str, str]] = {}
        self._super_admin_id: UUID | None = None

    async def _resolve_super_admin_id(self, session: AsyncSession) -> UUID | None:
        if self._super_admin_id is not None:
            return self._super_admin_id
        result = await session.execute(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                Role.code == "super_admin",
                Role.is_deleted == False,
                User.is_deleted == False,
            )
            .limit(1)
        )
        self._super_admin_id = result.scalar_one_or_none()
        return self._super_admin_id

    async def _resolve_file(
        self, session: AsyncSession, owner_id: UUID, doc_path: str
    ) -> FileObject | None:
        parts = [p for p in doc_path.split("/") if p]
        if not parts:
            return None
        filename = parts[-1]
        folder_parts = parts[:-1]

        parent_id: UUID | None = None
        for part in folder_parts:
            folder = await session.scalar(
                select(FileFolder).where(
                    FileFolder.owner_user_id == owner_id,
                    FileFolder.name == part,
                    FileFolder.parent_folder_id == parent_id,
                    FileFolder.is_deleted == False,
                )
            )
            if folder is None:
                return None
            parent_id = folder.id

        stmt = select(FileObject).where(
            FileObject.owner_user_id == owner_id,
            FileObject.original_filename == filename,
            FileObject.is_deleted == False,
        )
        if parent_id is not None:
            stmt = stmt.where(FileObject.folder_id == parent_id)
        else:
            stmt = stmt.where(FileObject.folder_id.is_(None))
        return await session.scalar(stmt)

    async def _load_doc(
        self, session: AsyncSession, owner_id: UUID, doc_path: str, limit: int | None = None
    ) -> str:
        if limit is None:
            limit = _DOC_CONTENT_LIMIT
        cached = self._cache.get(doc_path)
        file_obj = await self._resolve_file(session, owner_id, doc_path)
        if file_obj is None:
            logger.warning(
                "workflow_doc_resolve_failed",
                extra={
                    "path": doc_path,
                    "owner": str(owner_id),
                    "cwd": str(Path.cwd()),
                },
            )
            self._cache.pop(doc_path, None)
            return ""

        storage_path = Path(file_obj.storage_key) if file_obj.storage_key else None
        if storage_path is None or not storage_path.is_file():
            logger.warning(
                "workflow_doc_storage_missing",
                extra={
                    "path": doc_path,
                    "storage_key": file_obj.storage_key,
                    "resolved": str(storage_path) if storage_path else None,
                    "cwd": str(Path.cwd()),
                    "exists": storage_path.is_file() if storage_path else False,
                },
            )
            self._cache.pop(doc_path, None)
            return ""

        raw = storage_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if cached is not None and cached.get("sha256") == digest:
            return cached["content"]
        content = raw.decode("utf-8")
        if len(content) > limit:
            content = content[:limit]
            logger.warning("workflow_doc_truncated", extra={"path": doc_path})
        self._cache[doc_path] = {"sha256": digest, "content": content}
        return content

    async def get_doc_receipt(
        self, session: AsyncSession, owner_id: UUID, doc_path: str
    ) -> dict[str, object] | None:
        file_obj = await self._resolve_file(session, owner_id, doc_path)
        if file_obj is None or not file_obj.storage_key:
            return None
        storage_path = Path(file_obj.storage_key)
        if not storage_path.is_file():
            return None
        raw = storage_path.read_bytes()
        return {
            "file_id": str(file_obj.id),
            "path": "/" + doc_path.strip("/"),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "source": "my_files",
        }

    def _parse_route_rules(self, raw: str) -> list[tuple[list[str], str]]:
        rules: list[tuple[list[str], str]] = []
        for group in raw.split("|"):
            group = group.strip()
            if not group or "=>" not in group:
                continue
            keywords_part, _, path_part = group.partition("=>")
            keywords = [k.strip() for k in keywords_part.split(";;") if k.strip()]
            path = path_part.strip()
            if keywords and path:
                rules.append((keywords, path))
        return rules

    def required_doc_paths(self, goal: str, rules: ParsedRules | None) -> list[str]:
        """Return every admin document that must be loaded for this task."""
        paths = list(_PLAN_REQUIRED_DOC_PATHS) if is_plan_goal(goal, rules) else []
        for keywords, path in self._parse_route_rules(get_settings().workflow_route_rules):
            if any(keyword in goal for keyword in keywords) and path not in paths:
                paths.append(path)
        return paths

    async def get_rules(self, session: AsyncSession, goal: str) -> ParsedRules | None:
        """加载核心蓝图原文 → 解析规则集；失败返回 None。"""
        settings = get_settings()
        if not settings.workflow_docs_enabled:
            return None
        owner_id = await self._resolve_super_admin_id(session)
        if owner_id is None:
            return None
        blueprint = await self._load_doc(
            session,
            owner_id,
            settings.workflow_core_doc_path,
            limit=settings.workflow_blueprint_full_limit,
        )
        if not blueprint:
            return None
        return workflow_rules_cache.get(blueprint)

    async def get_instruction(self, session: AsyncSession, goal: str) -> str:
        settings = get_settings()
        if not settings.workflow_docs_enabled:
            return ""
        owner_id = await self._resolve_super_admin_id(session)
        if owner_id is None:
            return ""

        parts: list[str] = []
        rules = await self.get_rules(session, goal)
        plan_class = is_plan_goal(goal, rules)
        if plan_class and rules is not None:
            blueprint = await self._load_doc(
                session,
                owner_id,
                settings.workflow_core_doc_path,
                limit=settings.workflow_blueprint_full_limit,
            )
            if blueprint:
                parts.append(f"【脑壳儿_Agent运行蓝图（完整原文，必须严格遵守）】\n{blueprint}")

        for path in self.required_doc_paths(goal, rules):
            content = await self._load_doc(session, owner_id, path)
            if not content:
                raise RuntimeError(f"workflow_required_doc_unavailable:{path}")
            parts.append(f"【{path.split('/')[-1]}】\n{content}")

        if not parts:
            return ""
        return "【系统工作流约束（必须严格遵守，每次任务都必须执行）】\n" + "\n\n".join(parts)

    def invalidate(self) -> None:
        self._cache.clear()
        self._super_admin_id = None
        workflow_rules_cache.invalidate()


workflow_policy = WorkflowPolicy()
