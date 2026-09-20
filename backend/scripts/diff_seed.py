"""差分录制前置：把开发库的工作流文档行幂等复制到测试库。

`workflow_policy._load_doc` 以超管用户的 `file_folders` 目录链 + `file_objects.storage_key`
读取文档；测试库（rbac_test）由 `seed_rbac` 建出超管但没有这些文档，导致方案类场景的
规则/门禁注入全部为空（T5 报告环境阻断 #2）。本模块只读取开发库（`DATABASE_URL`），
把 `00_Agent规范与模板` 目录树下的行按主键幂等写入测试库；`storage_key` 为相对路径，
两库共用同一磁盘目录（backend/var/files），因此不复制文件内容、也不修改开发库。

用法（由 langgraph_differential 的 CLI 路径自动调用）::

    python -m scripts.diff_seed        # 手动执行（读 backend/.env 的 DATABASE_URL/TEST_DATABASE_URL）
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.file import FileFolder, FileObject
from app.models.rbac import Role, User, UserRole
from app.services.agent.workflow_policy import workflow_policy

logger = logging.getLogger("diff_seed")

WORKFLOW_ROOT_FOLDER = "00_Agent规范与模板"
# 覆盖四组 route rules 关键词 + 方案类目标（is_plan_goal 正则命中「方案」）
_PROBE_GOAL = "矩阵号 代运营 评分 自评 UGC 种草 KOC 调研 研究 写一份方案"


class DiffSeedError(RuntimeError):
    """seed 前置不满足或执行失败（消息面向操作者，包含可定位信息）。"""


def required_doc_paths() -> list[str]:
    """core 蓝图 + 当前 goal 分类会读取的全部规范文档路径（与生产读取路径一致）。"""
    settings = get_settings()
    paths = [settings.workflow_core_doc_path]
    for path in workflow_policy.required_doc_paths(_PROBE_GOAL, None):
        if path not in paths:
            paths.append(path)
    return paths


async def _super_admin_ids(session: AsyncSession) -> list[UUID]:
    result = await session.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            Role.code == "super_admin",
            Role.is_deleted == False,
            User.is_deleted == False,
        )
    )
    return list(result.scalars().all())


async def _find_source_root(session: AsyncSession) -> FileFolder:
    owners = await _super_admin_ids(session)
    if not owners:
        raise DiffSeedError("开发库中没有 super_admin 用户，无法定位工作流文档")
    roots = list(
        (
            await session.scalars(
                select(FileFolder)
                .where(
                    FileFolder.owner_user_id.in_(owners),
                    FileFolder.name == WORKFLOW_ROOT_FOLDER,
                    FileFolder.parent_folder_id.is_(None),
                    FileFolder.is_deleted == False,
                )
                .order_by(FileFolder.created_at)
            )
        ).all()
    )
    if not roots:
        raise DiffSeedError(f"开发库中找不到超管目录 {WORKFLOW_ROOT_FOLDER!r}")

    best: FileFolder | None = None
    best_count = -1
    for root in roots:
        count = await session.scalar(
            select(func.count())
            .select_from(FileObject)
            .where(
                FileObject.owner_user_id == root.owner_user_id,
                FileObject.is_deleted == False,
            )
        )
        if (count or 0) > best_count:
            best, best_count = root, count or 0
    assert best is not None
    return best


async def _load_tree(
    session: AsyncSession, root: FileFolder
) -> tuple[list[FileFolder], list[FileObject]]:
    all_folders = list(
        (
            await session.scalars(
                select(FileFolder).where(
                    FileFolder.owner_user_id == root.owner_user_id,
                    FileFolder.is_deleted == False,
                )
            )
        ).all()
    )
    by_parent: dict[UUID | None, list[FileFolder]] = {}
    for folder in all_folders:
        by_parent.setdefault(folder.parent_folder_id, []).append(folder)

    tree: list[FileFolder] = []
    queue = [root]
    while queue:
        folder = queue.pop(0)
        tree.append(folder)
        queue.extend(by_parent.get(folder.id, []))
    folder_ids = {folder.id for folder in tree}
    tree.sort(key=lambda item: (item.depth, item.name))

    files = list(
        (
            await session.scalars(
                select(FileObject).where(
                    FileObject.owner_user_id == root.owner_user_id,
                    FileObject.folder_id.in_(folder_ids),
                    FileObject.is_deleted == False,
                )
            )
        ).all()
    )
    return tree, files


async def _copy_tree(
    session: AsyncSession,
    target_owner: UUID,
    folders: list[FileFolder],
    files: list[FileObject],
) -> dict[str, object]:
    inserted_folders = 0
    inserted_files = 0
    skipped: list[str] = []

    for folder in folders:
        result = await session.execute(
            pg_insert(FileFolder)
            .values(
                id=folder.id,
                owner_user_id=target_owner,
                parent_folder_id=folder.parent_folder_id,
                name=folder.name,
                path=folder.path,
                depth=folder.depth,
                child_file_count=folder.child_file_count,
                total_size_bytes=folder.total_size_bytes,
                created_by=target_owner,
                created_at=folder.created_at,
                updated_at=folder.updated_at,
                is_deleted=folder.is_deleted,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        inserted_folders += result.rowcount or 0

    for file_obj in files:
        storage_path = Path(file_obj.storage_key)
        if not storage_path.is_file():
            skipped.append(file_obj.original_filename)
            logger.warning(
                "diff_seed 跳过磁盘缺失文件: %s -> %s",
                file_obj.original_filename,
                file_obj.storage_key,
            )
            continue
        result = await session.execute(
            pg_insert(FileObject)
            .values(
                id=file_obj.id,
                owner_user_id=target_owner,
                folder_id=file_obj.folder_id,
                storage_key=file_obj.storage_key,
                filename=file_obj.filename,
                original_filename=file_obj.original_filename,
                media_type=file_obj.media_type,
                size_bytes=file_obj.size_bytes,
                sha256=file_obj.sha256,
                extracted_text=file_obj.extracted_text,
                preview_status=file_obj.preview_status,
                preview_path=file_obj.preview_path,
                source_attachment_id=None,
                created_by=target_owner,
                created_at=file_obj.created_at,
                updated_at=file_obj.updated_at,
                is_deleted=file_obj.is_deleted,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        inserted_files += result.rowcount or 0

    return {
        "folders_total": len(folders),
        "folders_inserted": inserted_folders,
        "files_total": len(files),
        "files_inserted": inserted_files,
        "skipped_missing_storage": skipped,
    }


async def _verify(session: AsyncSession, target_owner: UUID, paths: list[str]) -> list[str]:
    missing: list[str] = []
    for path in paths:
        file_obj = await workflow_policy._resolve_file(session, target_owner, path)
        if file_obj is None or not file_obj.storage_key:
            missing.append(f"{path}（DB 记录缺失）")
        elif not Path(file_obj.storage_key).is_file():
            missing.append(f"{path}（storage_key 不可读: {file_obj.storage_key}）")
    return missing


async def seed_workflow_docs(
    target_factory: async_sessionmaker[AsyncSession], source_url: str
) -> dict[str, object]:
    """幂等复制工作流文档；失败抛 DiffSeedError。不写开发库。"""
    source_engine = create_async_engine(source_url)
    try:
        source_factory = async_sessionmaker(
            source_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with source_factory() as source:
            root = await _find_source_root(source)
            folders, files = await _load_tree(source, root)
            source_owner = root.owner_user_id
    except DiffSeedError:
        raise
    except Exception as exc:  # noqa: BLE001 - 面向操作者的清晰错误
        raise DiffSeedError(
            f"读取开发库工作流文档失败（{_safe_url(source_url)}）: {exc}"
        ) from exc
    finally:
        await source_engine.dispose()

    async with target_factory() as target:
        owners = await _super_admin_ids(target)
        if not owners:
            raise DiffSeedError("测试库中没有 super_admin 用户（seed_rbac 未执行？）")
        target_owner = owners[0]
        stats = await _copy_tree(target, target_owner, folders, files)
        await target.commit()

    async with target_factory() as target:
        missing = await _verify(target, target_owner, required_doc_paths())
    if missing:
        raise DiffSeedError("工作流文档 seed 后仍不可读: " + "; ".join(missing))

    stats.update(
        {
            "source_owner": str(source_owner),
            "target_owner": str(target_owner),
            "required_docs": required_doc_paths(),
        }
    )
    return stats


def _safe_url(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.hostname or '?'}{parsed.path}"


async def _main() -> None:
    settings = get_settings()
    if not settings.test_database_url or settings.test_database_url == settings.database_url:
        raise SystemExit("TEST_DATABASE_URL 未配置或与 DATABASE_URL 相同，无需 seed")

    import app.models  # noqa: F401  注册全部 ORM 表
    import app.models.points  # noqa: F401
    from app.db.seed import seed_rbac
    from app.models.base import Base

    target_engine = create_async_engine(settings.test_database_url)
    try:
        async with target_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        target_factory = async_sessionmaker(
            target_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with target_factory() as session:
            await seed_rbac(session)
            await session.commit()
        stats = await seed_workflow_docs(target_factory, settings.database_url)
    finally:
        await target_engine.dispose()
    print(json_dumps(stats))


def json_dumps(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_main())
