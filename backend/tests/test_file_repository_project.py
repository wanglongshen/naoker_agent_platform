import uuid
from types import SimpleNamespace

import pytest

from app.models.rbac import User


@pytest.fixture
async def owner_user(test_db):
    async with test_db() as db:
        user = User(
            username="owner_user",
            display_name="Owner User",
            password_hash="test-password-hash",
        )
        db.add(user)
        await db.commit()
        user_id = user.id
    return SimpleNamespace(id=user_id)


class TestFolderSubtree:
    @pytest.mark.anyio
    async def test_subtree_includes_self_and_all_descendants(
        self, test_db, owner_user
    ):
        from app.models.file import FileFolder
        from app.repositories.file_repository import FileRepository

        async with test_db() as db:
            repo = FileRepository(db)
            root = FileFolder(owner_user_id=owner_user.id, name="项目A", depth=0)
            db.add(root)
            await db.flush()
            child = FileFolder(
                owner_user_id=owner_user.id, name="子", depth=1,
                parent_folder_id=root.id,
            )
            db.add(child)
            await db.flush()
            grand = FileFolder(
                owner_user_id=owner_user.id, name="孙", depth=2,
                parent_folder_id=child.id,
            )
            db.add(grand)
            await db.flush()

            ids = await repo.get_folder_subtree_ids(root.id)
            assert set(ids) == {root.id, child.id, grand.id}

    @pytest.mark.anyio
    async def test_subtree_excludes_deleted_and_other_branches(
        self, test_db, owner_user
    ):
        from app.models.file import FileFolder
        from app.repositories.file_repository import FileRepository

        async with test_db() as db:
            repo = FileRepository(db)
            root_a = FileFolder(owner_user_id=owner_user.id, name="A", depth=0)
            root_b = FileFolder(owner_user_id=owner_user.id, name="B", depth=0)
            db.add_all([root_a, root_b])
            await db.flush()
            deleted_child = FileFolder(
                owner_user_id=owner_user.id, name="已删", depth=1,
                parent_folder_id=root_a.id, is_deleted=True,
            )
            db.add(deleted_child)
            await db.flush()

            ids = await repo.get_folder_subtree_ids(root_a.id)
            assert set(ids) == {root_a.id}
            ids_b = await repo.get_folder_subtree_ids(root_b.id)
            assert set(ids_b) == {root_b.id}


class TestFolderScopedFileSearch:
    @pytest.mark.anyio
    async def test_search_by_folder_ids_scopes_to_given_folders(
        self, test_db, owner_user
    ):
        from app.models.file import FileFolder, FileObject
        from app.repositories.file_repository import FileRepository

        async with test_db() as db:
            repo = FileRepository(db)
            root_a = FileFolder(owner_user_id=owner_user.id, name="A", depth=0)
            root_b = FileFolder(owner_user_id=owner_user.id, name="B", depth=0)
            db.add_all([root_a, root_b])
            await db.flush()
            fa = FileObject(
                owner_user_id=owner_user.id, folder_id=root_a.id,
                original_filename="方案.md", filename="x1", storage_key="k1",
                media_type="text/markdown", size_bytes=1024, sha256="a" * 64,
            )
            fb = FileObject(
                owner_user_id=owner_user.id, folder_id=root_b.id,
                original_filename="方案.md", filename="x2", storage_key="k2",
                media_type="text/markdown", size_bytes=2048, sha256="b" * 64,
            )
            db.add_all([fa, fb])
            await db.flush()

            hits = await repo.search_by_folder_ids([root_a.id], "方案")
            assert [f.id for f in hits] == [fa.id]

            exact = await repo.get_by_folder_ids([root_a.id], "方案.md")
            assert exact is not None and exact.id == fa.id
            outside = await repo.get_by_folder_ids([root_a.id], "别的.md")
            assert outside is None

    @pytest.mark.anyio
    async def test_search_excludes_files_without_folder(self, test_db, owner_user):
        from app.models.file import FileObject
        from app.repositories.file_repository import FileRepository

        async with test_db() as db:
            repo = FileRepository(db)
            db.add(FileObject(
                owner_user_id=owner_user.id, folder_id=None,
                original_filename="无项目.md", filename="x3", storage_key="k3",
                media_type="text/markdown", size_bytes=512, sha256="c" * 64,
            ))
            await db.flush()
            hits = await repo.search_by_folder_ids([uuid.uuid4()], "无项目")
            assert hits == []
