from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file import FileFolder, FileObject
from app.models.rbac import User


@dataclass
class Page:
    items: list[Any]
    page: int
    page_size: int
    total: int


class FileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_folder(
        self, owner_id: uuid.UUID, name: str, parent_id: uuid.UUID | None = None
    ) -> FileFolder:
        if parent_id is not None:
            parent = await self.session.get(FileFolder, parent_id)
            if parent is None or parent.is_deleted:
                raise ValueError("Parent folder not found")
            if parent.owner_user_id != owner_id:
                raise ValueError("Access denied")
            path = parent.path + "/" + name if parent.path else "/" + name
            depth = parent.depth + 1
        else:
            path = "/" + name
            depth = 0

        folder = FileFolder(
            owner_user_id=owner_id,
            parent_folder_id=parent_id,
            name=name,
            path=path,
            depth=depth,
            created_by=owner_id,
        )
        self.session.add(folder)
        await self.session.flush()
        return folder

    async def get_folder_tree(self, owner_id: uuid.UUID) -> list[FileFolder]:
        result = await self.session.execute(
            select(FileFolder)
            .where(
                FileFolder.owner_user_id == owner_id,
                FileFolder.is_deleted == False,
            )
            .order_by(FileFolder.path)
        )
        return list(result.scalars().all())

    async def rename_folder(self, folder_id: uuid.UUID, name: str) -> FileFolder:
        folder = await self.session.get(FileFolder, folder_id)
        if folder is None or folder.is_deleted:
            raise ValueError("Folder not found")

        old_name = folder.name
        old_path = folder.path
        new_path = folder.path[: -len(old_name)] + name if old_path.endswith(old_name) else folder.path.replace(old_name, name)

        folder.name = name
        folder.path = new_path
        folder.updated_at = datetime.now(UTC)
        self.session.add(folder)
        await self.session.flush()

        old_path_prefix = old_path + "/"
        new_path_prefix = new_path + "/"

        await self.session.execute(
            update(FileFolder)
            .where(
                FileFolder.path.startswith(old_path_prefix),
                FileFolder.is_deleted == False,
            )
            .values(
                path=func.replace(FileFolder.path, old_path_prefix, new_path_prefix),
                updated_at=datetime.now(UTC),
            )
        )

        return folder

    async def delete_folder(self, folder_id: uuid.UUID) -> FileFolder:
        folder = await self.session.get(FileFolder, folder_id)
        if folder is None or folder.is_deleted:
            raise ValueError("Folder not found")

        now = datetime.now(UTC)
        folder.is_deleted = True
        folder.updated_at = now
        self.session.add(folder)

        all_descendants = await self.session.execute(
            select(FileFolder).where(
                FileFolder.path.startswith(folder.path + "/"),
                FileFolder.is_deleted == False,
            )
        )
        descendant_ids = [folder.id]
        for child in all_descendants.scalars().all():
            child.is_deleted = True
            child.updated_at = now
            self.session.add(child)
            descendant_ids.append(child.id)

        # Soft-delete all files inside this folder and its descendants
        await self.session.execute(
            update(FileObject)
            .where(
                FileObject.folder_id.in_(descendant_ids),
                FileObject.is_deleted == False,
            )
            .values(is_deleted=True, updated_at=now)
        )

        if folder.parent_folder_id is not None:
            child_count = await self.session.execute(
                select(func.count()).select_from(FileFolder).where(
                    FileFolder.parent_folder_id == folder.parent_folder_id,
                    FileFolder.is_deleted == False,
                )
            )
            remaining = child_count.scalar_one()

            await self.session.execute(
                update(FileFolder)
                .where(FileFolder.id == folder.parent_folder_id)
                .values(child_file_count=remaining, updated_at=now)
            )

        await self.session.flush()
        return folder

    async def add_file(self, folder_id: uuid.UUID | None, file_data: dict) -> FileObject:
        file_obj = FileObject(**file_data)
        self.session.add(file_obj)
        await self.session.flush()

        if folder_id is not None:
            await self.session.execute(
                update(FileFolder)
                .where(FileFolder.id == folder_id)
                .values(
                    child_file_count=FileFolder.child_file_count + 1,
                    total_size_bytes=FileFolder.total_size_bytes + file_data.get("size_bytes", 0),
                    updated_at=datetime.now(UTC),
                )
            )

        return file_obj

    async def list_files(
        self,
        folder_id: uuid.UUID | None = None,
        owner_id: uuid.UUID | None = None,
        keyword: str | None = None,
        media_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page:
        base = select(FileObject).where(FileObject.is_deleted == False)

        if folder_id is not None:
            base = base.where(FileObject.folder_id == folder_id)
        if owner_id is not None:
            base = base.where(FileObject.owner_user_id == owner_id)
        if keyword:
            pattern = f"%{keyword}%"
            base = base.where(FileObject.original_filename.ilike(pattern))
        if media_type:
            base = base.where(FileObject.media_type == media_type)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_q)).scalar_one()

        result = await self.session.execute(
            base.order_by(FileObject.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(result.scalars().all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def get_file(self, file_id: uuid.UUID) -> FileObject | None:
        result = await self.session.execute(
            select(FileObject).where(
                FileObject.id == file_id,
                FileObject.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_owner_and_filename(
        self, owner_id: uuid.UUID, filename: str
    ) -> FileObject | None:
        result = await self.session.execute(
            select(FileObject).where(
                FileObject.owner_user_id == owner_id,
                FileObject.original_filename == filename,
                FileObject.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    async def search_by_owner_and_filename(
        self, owner_id: uuid.UUID, keyword: str
    ) -> list[FileObject]:
        result = await self.session.execute(
            select(FileObject).where(
                FileObject.owner_user_id == owner_id,
                FileObject.original_filename.ilike(f"%{keyword}%"),
                FileObject.is_deleted == False,
            )
        )
        return list(result.scalars().all())

    async def get_by_filename(self, filename: str) -> FileObject | None:
        result = await self.session.execute(
            select(FileObject).where(
                FileObject.original_filename == filename,
                FileObject.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    async def search_by_filename(self, keyword: str) -> list[FileObject]:
        result = await self.session.execute(
            select(FileObject).where(
                FileObject.original_filename.ilike(f"%{keyword}%"),
                FileObject.is_deleted == False,
            )
        )
        return list(result.scalars().all())

    async def find_folder_by_name(
        self, owner_id: uuid.UUID, name: str
    ) -> FileFolder | None:
        result = await self.session.execute(
            select(FileFolder).where(
                FileFolder.owner_user_id == owner_id,
                FileFolder.name.ilike(f"%{name}%"),
                FileFolder.is_deleted == False,
            )
        )
        folders = list(result.scalars().all())
        if len(folders) == 1:
            return folders[0]
        if len(folders) > 1:
            exact = [f for f in folders if f.name == name]
            if len(exact) == 1:
                return exact[0]
        return None

    async def search_by_folder_and_filename(
        self, folder_id: uuid.UUID, keyword: str
    ) -> list[FileObject]:
        result = await self.session.execute(
            select(FileObject).where(
                FileObject.folder_id == folder_id,
                FileObject.original_filename.ilike(f"%{keyword}%"),
                FileObject.is_deleted == False,
            )
        )
        return list(result.scalars().all())

    async def get_folder_subtree_ids(self, folder_id: uuid.UUID) -> list[uuid.UUID]:
        ids: list[uuid.UUID] = [folder_id]
        frontier = [folder_id]
        while frontier:
            result = await self.session.execute(
                select(FileFolder.id).where(
                    FileFolder.parent_folder_id.in_(frontier),
                    FileFolder.is_deleted == False,
                )
            )
            frontier = list(result.scalars().all())
            ids.extend(frontier)
        return ids

    async def search_by_folder_ids(
        self, folder_ids: list[uuid.UUID], keyword: str
    ) -> list[FileObject]:
        if not folder_ids:
            return []
        result = await self.session.execute(
            select(FileObject).where(
                FileObject.folder_id.in_(folder_ids),
                FileObject.original_filename.ilike(f"%{keyword}%"),
                FileObject.is_deleted == False,
            )
        )
        return list(result.scalars().all())

    async def get_by_folder_ids(
        self, folder_ids: list[uuid.UUID], filename: str
    ) -> FileObject | None:
        if not folder_ids:
            return None
        result = await self.session.execute(
            select(FileObject).where(
                FileObject.folder_id.in_(folder_ids),
                FileObject.original_filename == filename,
                FileObject.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    async def move_file(
        self, file_id: uuid.UUID, target_folder_id: uuid.UUID | None
    ) -> FileObject:
        file_obj = await self.session.get(FileObject, file_id)
        if file_obj is None or file_obj.is_deleted:
            raise ValueError("File not found")

        old_folder_id = file_obj.folder_id
        old_size = file_obj.size_bytes

        if old_folder_id is not None:
            await self.session.execute(
                update(FileFolder)
                .where(FileFolder.id == old_folder_id)
                .values(
                    child_file_count=func.greatest(FileFolder.child_file_count - 1, 0),
                    total_size_bytes=func.greatest(FileFolder.total_size_bytes - old_size, 0),
                    updated_at=datetime.now(UTC),
                )
            )

        file_obj.folder_id = target_folder_id
        file_obj.updated_at = datetime.now(UTC)
        self.session.add(file_obj)

        if target_folder_id is not None:
            await self.session.execute(
                update(FileFolder)
                .where(FileFolder.id == target_folder_id)
                .values(
                    child_file_count=FileFolder.child_file_count + 1,
                    total_size_bytes=FileFolder.total_size_bytes + old_size,
                    updated_at=datetime.now(UTC),
                )
            )

        await self.session.flush()
        return file_obj

    async def delete_file(self, file_id: uuid.UUID) -> FileObject:
        file_obj = await self.session.get(FileObject, file_id)
        if file_obj is None or file_obj.is_deleted:
            raise ValueError("File not found")

        file_obj.is_deleted = True
        file_obj.updated_at = datetime.now(UTC)
        self.session.add(file_obj)

        if file_obj.folder_id is not None:
            await self.session.execute(
                update(FileFolder)
                .where(FileFolder.id == file_obj.folder_id)
                .values(
                    child_file_count=func.greatest(FileFolder.child_file_count - 1, 0),
                    total_size_bytes=func.greatest(FileFolder.total_size_bytes - file_obj.size_bytes, 0),
                    updated_at=datetime.now(UTC),
                )
            )

        await self.session.flush()
        return file_obj

    async def delete_files_batch(self, ids: list[uuid.UUID]) -> int:
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(FileObject)
            .where(FileObject.id.in_(ids), FileObject.is_deleted == False)
            .values(is_deleted=True, updated_at=now)
            .returning(FileObject.id, FileObject.folder_id, FileObject.size_bytes)
        )
        updated = result.fetchall()

        folder_adjustments: dict[uuid.UUID, tuple[int, int]] = {}
        for row in updated:
            fid = row.folder_id
            if fid is not None:
                count_delta, size_delta = folder_adjustments.get(fid, (0, 0))
                folder_adjustments[fid] = (count_delta + 1, size_delta + row.size_bytes)

        for folder_id, (count_delta, size_delta) in folder_adjustments.items():
            await self.session.execute(
                update(FileFolder)
                .where(FileFolder.id == folder_id)
                .values(
                    child_file_count=func.greatest(FileFolder.child_file_count - count_delta, 0),
                    total_size_bytes=func.greatest(FileFolder.total_size_bytes - size_delta, 0),
                    updated_at=now,
                )
            )

        await self.session.flush()
        return len(updated)

    async def get_admin_all_files(
        self,
        user_id: uuid.UUID | None = None,
        folder_id: uuid.UUID | None = None,
        keyword: str | None = None,
        media_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page:
        base = select(FileObject).where(FileObject.is_deleted == False)

        if user_id is not None:
            base = base.where(FileObject.owner_user_id == user_id)
        if folder_id is not None:
            base = base.where(FileObject.folder_id == folder_id)
        if keyword:
            pattern = f"%{keyword}%"
            base = base.where(FileObject.original_filename.ilike(pattern))
        if media_type:
            base = base.where(FileObject.media_type == media_type)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_q)).scalar_one()

        result = await self.session.execute(
            base.order_by(FileObject.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(result.scalars().all())
        return Page(items=items, page=page, page_size=page_size, total=total)

    async def get_admin_user_folder_trees(
        self, self_user_id: uuid.UUID
    ) -> list[dict]:
        """All users that have files or folders, each with their folder tree.
        The current user (admin) is always first."""
        from sqlalchemy import exists as sql_exists

        has_content = sql_exists(
            select(FileObject.id).where(
                FileObject.owner_user_id == User.id,
                FileObject.is_deleted == False,
            )
        ) | sql_exists(
            select(FileFolder.id).where(
                FileFolder.owner_user_id == User.id,
                FileFolder.is_deleted == False,
            )
        )
        users = (
            await self.session.execute(
                select(User)
                .where(
                    User.is_deleted == False,
                    has_content | (User.id == self_user_id),
                )
                .order_by(User.id)
            )
        ).scalars().all()
        users = sorted(users, key=lambda u: u.id != self_user_id)
        groups = []
        for u in users:
            groups.append(
                {
                    "user_id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "folders": await self.get_folder_tree(u.id),
                }
            )
        return groups

    async def get_files_by_ids(self, ids: list[uuid.UUID]) -> list[FileObject]:
        result = await self.session.execute(
            select(FileObject).where(FileObject.id.in_(ids))
        )
        return list(result.scalars().all())
