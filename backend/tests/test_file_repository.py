import uuid

import pytest

from app.models.file import FileFolder, FileObject
from app.repositories.file_repository import FileRepository


@pytest.fixture
async def file_repo(session):
    return FileRepository(session)


@pytest.fixture
async def root_folder(session, seeded_user):
    folder = FileFolder(
        owner_user_id=seeded_user.id,
        name="docs",
        path="/docs",
        depth=0,
        parent_folder_id=None,
    )
    session.add(folder)
    await session.flush()
    return folder


class TestCreateFolder:
    async def test_create_root_folder(self, file_repo, seeded_user):
        folder = await file_repo.create_folder(seeded_user.id, "my-folder")
        assert folder.id is not None
        assert folder.name == "my-folder"
        assert folder.path == "/my-folder"
        assert folder.depth == 0
        assert folder.parent_folder_id is None
        assert folder.owner_user_id == seeded_user.id
        assert folder.is_deleted is False

    async def test_create_nested_folder(self, file_repo, root_folder, seeded_user):
        sub = await file_repo.create_folder(seeded_user.id, "sub", parent_id=root_folder.id)
        assert sub.id is not None
        assert sub.name == "sub"
        assert sub.path == "/docs/sub"
        assert sub.depth == 1
        assert sub.parent_folder_id == root_folder.id

    async def test_create_nested_folder_deep(self, file_repo, root_folder, seeded_user):
        sub = await file_repo.create_folder(seeded_user.id, "a", parent_id=root_folder.id)
        sub2 = await file_repo.create_folder(seeded_user.id, "b", parent_id=sub.id)
        assert sub2.path == "/docs/a/b"
        assert sub2.depth == 2

    async def test_create_folder_parent_not_found(self, file_repo, seeded_user):
        with pytest.raises(ValueError, match="Parent folder not found"):
            await file_repo.create_folder(seeded_user.id, "orphan", parent_id=uuid.uuid4())

    async def test_create_folder_parent_deleted(self, file_repo, session, seeded_user):
        folder = FileFolder(
            owner_user_id=seeded_user.id,
            name="deleted-parent",
            path="/deleted-parent",
            depth=0,
            is_deleted=True,
        )
        session.add(folder)
        await session.flush()

        with pytest.raises(ValueError, match="Parent folder not found"):
            await file_repo.create_folder(seeded_user.id, "child", parent_id=folder.id)

    async def test_create_folder_wrong_owner(self, file_repo, root_folder):
        other_user_id = uuid.uuid4()
        with pytest.raises(ValueError, match="Access denied"):
            await file_repo.create_folder(other_user_id, "intruder", parent_id=root_folder.id)


class TestGetFolderTree:
    async def test_get_folder_tree_empty(self, file_repo, seeded_user):
        tree = await file_repo.get_folder_tree(seeded_user.id)
        assert tree == []

    async def test_get_folder_tree_with_folders(self, file_repo, root_folder, seeded_user):
        await file_repo.create_folder(seeded_user.id, "images", parent_id=root_folder.id)
        await file_repo.create_folder(seeded_user.id, "videos", parent_id=root_folder.id)
        tree = await file_repo.get_folder_tree(seeded_user.id)
        assert len(tree) == 3
        paths = {f.path for f in tree}
        assert "/docs" in paths
        assert "/docs/images" in paths
        assert "/docs/videos" in paths

    async def test_get_folder_tree_excludes_deleted(self, file_repo, session, root_folder, seeded_user):
        deleted = FileFolder(
            owner_user_id=seeded_user.id,
            name="trash",
            path="/trash",
            depth=0,
            is_deleted=True,
        )
        session.add(deleted)
        await session.flush()

        tree = await file_repo.get_folder_tree(seeded_user.id)
        paths = {f.path for f in tree}
        assert "/docs" in paths
        assert "/trash" not in paths

    async def test_get_folder_tree_other_user_empty(self, file_repo, root_folder):
        other_id = uuid.uuid4()
        tree = await file_repo.get_folder_tree(other_id)
        assert tree == []


class TestRenameFolder:
    async def test_rename_folder_updates_name_and_path(self, file_repo, root_folder):
        updated = await file_repo.rename_folder(root_folder.id, "new-docs")
        assert updated.name == "new-docs"
        assert updated.path == "/new-docs"

    async def test_rename_folder_not_found(self, file_repo):
        with pytest.raises(ValueError, match="Folder not found"):
            await file_repo.rename_folder(uuid.uuid4(), "x")

    async def test_rename_folder_cascades_to_subfolders(self, file_repo, root_folder, seeded_user):
        sub = await file_repo.create_folder(seeded_user.id, "sub", parent_id=root_folder.id)
        deep = await file_repo.create_folder(seeded_user.id, "deep", parent_id=sub.id)

        await file_repo.rename_folder(root_folder.id, "renamed")

        tree = await file_repo.get_folder_tree(seeded_user.id)
        paths = {f.path for f in tree}
        assert "/renamed" in paths
        assert "/renamed/sub" in paths
        assert "/renamed/sub/deep" in paths
        assert "/docs" not in paths
        assert "/docs/sub" not in paths


class TestDeleteFolder:
    async def test_delete_folder_soft_deletes(self, file_repo, root_folder):
        deleted = await file_repo.delete_folder(root_folder.id)
        assert deleted.is_deleted is True
        assert deleted.id == root_folder.id

    async def test_delete_folder_not_found(self, file_repo):
        with pytest.raises(ValueError, match="Folder not found"):
            await file_repo.delete_folder(uuid.uuid4())

    async def test_delete_folder_cascades_to_children(self, file_repo, root_folder, seeded_user):
        sub = await file_repo.create_folder(seeded_user.id, "sub", parent_id=root_folder.id)
        deep = await file_repo.create_folder(seeded_user.id, "deep", parent_id=sub.id)

        await file_repo.delete_folder(root_folder.id)

        tree = await file_repo.get_folder_tree(seeded_user.id)
        assert len(tree) == 0

    async def test_delete_subfolder_parent_count_unchanged(self, file_repo, root_folder, seeded_user):
        sub = await file_repo.create_folder(seeded_user.id, "sub", parent_id=root_folder.id)

        await file_repo.delete_folder(sub.id)

        tree = await file_repo.get_folder_tree(seeded_user.id)
        assert len(tree) == 1
        assert tree[0].path == "/docs"


class TestAddFile:
    async def test_add_file_in_root(self, file_repo, seeded_user):
        file_data = {
            "owner_user_id": seeded_user.id,
            "folder_id": None,
            "storage_key": "files/abc",
            "filename": "readme.txt",
            "original_filename": "readme.txt",
            "media_type": "text/plain",
            "size_bytes": 100,
            "sha256": "a" * 64,
            "created_by": seeded_user.id,
        }
        file_obj = await file_repo.add_file(None, file_data)
        assert file_obj.id is not None
        assert file_obj.filename == "readme.txt"
        assert file_obj.size_bytes == 100

    async def test_add_file_updates_folder_counts(self, file_repo, root_folder, seeded_user):
        file_data = {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/def",
            "filename": "data.csv",
            "original_filename": "data.csv",
            "media_type": "text/csv",
            "size_bytes": 500,
            "sha256": "b" * 64,
            "created_by": seeded_user.id,
        }
        file_obj = await file_repo.add_file(root_folder.id, file_data)
        assert file_obj.folder_id == root_folder.id

        from sqlalchemy import select
        result = await file_repo.session.execute(select(FileFolder).where(FileFolder.id == root_folder.id))
        updated_folder = result.scalar_one()
        assert updated_folder.child_file_count == 1
        assert updated_folder.total_size_bytes == 500

    async def test_add_multiple_files_counts_accumulate(self, file_repo, root_folder, seeded_user):
        for i in range(3):
            await file_repo.add_file(root_folder.id, {
                "owner_user_id": seeded_user.id,
                "folder_id": root_folder.id,
                "storage_key": f"files/{i}",
                "filename": f"file_{i}.txt",
                "original_filename": f"file_{i}.txt",
                "media_type": "text/plain",
                "size_bytes": 200,
                "sha256": "c" * 64,
                "created_by": seeded_user.id,
            })

        from sqlalchemy import select
        result = await file_repo.session.execute(select(FileFolder).where(FileFolder.id == root_folder.id))
        updated_folder = result.scalar_one()
        assert updated_folder.child_file_count == 3
        assert updated_folder.total_size_bytes == 600


class TestListFiles:
    async def test_list_files_empty(self, file_repo, seeded_user):
        page = await file_repo.list_files(owner_id=seeded_user.id)
        assert page.total == 0
        assert page.items == []

    async def test_list_files_with_data(self, file_repo, root_folder, seeded_user):
        await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/f1",
            "filename": "alpha.txt",
            "original_filename": "alpha.txt",
            "media_type": "text/plain",
            "size_bytes": 100,
            "sha256": "d" * 64,
            "created_by": seeded_user.id,
        })
        await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/f2",
            "filename": "beta.csv",
            "original_filename": "beta.csv",
            "media_type": "text/csv",
            "size_bytes": 200,
            "sha256": "e" * 64,
            "created_by": seeded_user.id,
        })

        page = await file_repo.list_files(owner_id=seeded_user.id)
        assert page.total == 2
        assert len(page.items) == 2

    async def test_list_files_filter_by_folder(self, file_repo, root_folder, seeded_user):
        sub = await file_repo.create_folder(seeded_user.id, "sub", parent_id=root_folder.id)

        await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/f1",
            "filename": "in_root.txt",
            "original_filename": "in_root.txt",
            "media_type": "text/plain",
            "size_bytes": 100,
            "sha256": "d" * 64,
            "created_by": seeded_user.id,
        })
        await file_repo.add_file(sub.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": sub.id,
            "storage_key": "files/f2",
            "filename": "in_sub.txt",
            "original_filename": "in_sub.txt",
            "media_type": "text/plain",
            "size_bytes": 200,
            "sha256": "e" * 64,
            "created_by": seeded_user.id,
        })

        root_page = await file_repo.list_files(folder_id=root_folder.id)
        assert root_page.total == 1
        assert root_page.items[0].filename == "in_root.txt"

        sub_page = await file_repo.list_files(folder_id=sub.id)
        assert sub_page.total == 1
        assert sub_page.items[0].filename == "in_sub.txt"

    async def test_list_files_filter_by_keyword(self, file_repo, root_folder, seeded_user):
        await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/f1",
            "filename": "report_2025.pdf",
            "original_filename": "report_2025.pdf",
            "media_type": "application/pdf",
            "size_bytes": 100,
            "sha256": "d" * 64,
            "created_by": seeded_user.id,
        })
        await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/f2",
            "filename": "notes.txt",
            "original_filename": "notes.txt",
            "media_type": "text/plain",
            "size_bytes": 200,
            "sha256": "e" * 64,
            "created_by": seeded_user.id,
        })

        page = await file_repo.list_files(owner_id=seeded_user.id, keyword="report")
        assert page.total == 1
        assert page.items[0].filename == "report_2025.pdf"

    async def test_list_files_filter_by_media_type(self, file_repo, root_folder, seeded_user):
        await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/f1",
            "filename": "img.png",
            "original_filename": "img.png",
            "media_type": "image/png",
            "size_bytes": 100,
            "sha256": "d" * 64,
            "created_by": seeded_user.id,
        })
        await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/f2",
            "filename": "doc.txt",
            "original_filename": "doc.txt",
            "media_type": "text/plain",
            "size_bytes": 200,
            "sha256": "e" * 64,
            "created_by": seeded_user.id,
        })

        page = await file_repo.list_files(owner_id=seeded_user.id, media_type="image/png")
        assert page.total == 1
        assert page.items[0].filename == "img.png"

    async def test_list_files_pagination(self, file_repo, root_folder, seeded_user):
        for i in range(5):
            await file_repo.add_file(root_folder.id, {
                "owner_user_id": seeded_user.id,
                "folder_id": root_folder.id,
                "storage_key": f"files/f{i}",
                "filename": f"file_{i}.txt",
                "original_filename": f"file_{i}.txt",
                "media_type": "text/plain",
                "size_bytes": 100,
                "sha256": "f" * 64,
                "created_by": seeded_user.id,
            })

        page1 = await file_repo.list_files(owner_id=seeded_user.id, page=1, page_size=2)
        assert page1.total == 5
        assert len(page1.items) == 2
        assert page1.page == 1

        page2 = await file_repo.list_files(owner_id=seeded_user.id, page=2, page_size=2)
        assert len(page2.items) == 2

        page3 = await file_repo.list_files(owner_id=seeded_user.id, page=3, page_size=2)
        assert len(page3.items) == 1


class TestMoveFile:
    async def test_move_file_to_another_folder(self, file_repo, root_folder, seeded_user):
        sub = await file_repo.create_folder(seeded_user.id, "sub", parent_id=root_folder.id)

        file_obj = await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/move1",
            "filename": "movable.txt",
            "original_filename": "movable.txt",
            "media_type": "text/plain",
            "size_bytes": 300,
            "sha256": "g" * 64,
            "created_by": seeded_user.id,
        })

        moved = await file_repo.move_file(file_obj.id, sub.id)
        assert moved.folder_id == sub.id

        from sqlalchemy import select
        old = (await file_repo.session.execute(select(FileFolder).where(FileFolder.id == root_folder.id))).scalar_one()
        new = (await file_repo.session.execute(select(FileFolder).where(FileFolder.id == sub.id))).scalar_one()
        assert old.child_file_count == 0
        assert old.total_size_bytes == 0
        assert new.child_file_count == 1
        assert new.total_size_bytes == 300

    async def test_move_file_to_root(self, file_repo, root_folder, seeded_user):
        file_obj = await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/move2",
            "filename": "to_root.txt",
            "original_filename": "to_root.txt",
            "media_type": "text/plain",
            "size_bytes": 150,
            "sha256": "h" * 64,
            "created_by": seeded_user.id,
        })

        moved = await file_repo.move_file(file_obj.id, None)
        assert moved.folder_id is None

        from sqlalchemy import select
        old_folder = (await file_repo.session.execute(select(FileFolder).where(FileFolder.id == root_folder.id))).scalar_one()
        assert old_folder.child_file_count == 0
        assert old_folder.total_size_bytes == 0

    async def test_move_file_not_found(self, file_repo, root_folder):
        with pytest.raises(ValueError, match="File not found"):
            await file_repo.move_file(uuid.uuid4(), root_folder.id)


class TestDeleteFile:
    async def test_delete_file_soft_deletes(self, file_repo, root_folder, seeded_user):
        file_obj = await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/del1",
            "filename": "delete_me.txt",
            "original_filename": "delete_me.txt",
            "media_type": "text/plain",
            "size_bytes": 100,
            "sha256": "i" * 64,
            "created_by": seeded_user.id,
        })

        deleted = await file_repo.delete_file(file_obj.id)
        assert deleted.is_deleted is True

    async def test_delete_file_updates_folder_counts(self, file_repo, root_folder, seeded_user):
        file_obj = await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/del2",
            "filename": "delete_counts.txt",
            "original_filename": "delete_counts.txt",
            "media_type": "text/plain",
            "size_bytes": 400,
            "sha256": "j" * 64,
            "created_by": seeded_user.id,
        })

        await file_repo.delete_file(file_obj.id)

        from sqlalchemy import select
        folder = (await file_repo.session.execute(select(FileFolder).where(FileFolder.id == root_folder.id))).scalar_one()
        assert folder.child_file_count == 0
        assert folder.total_size_bytes == 0

    async def test_delete_file_not_found(self, file_repo):
        with pytest.raises(ValueError, match="File not found"):
            await file_repo.delete_file(uuid.uuid4())

    async def test_delete_file_deleted_already(self, file_repo, root_folder, seeded_user):
        file_obj = await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/del3",
            "filename": "already_gone.txt",
            "original_filename": "already_gone.txt",
            "media_type": "text/plain",
            "size_bytes": 50,
            "sha256": "k" * 64,
            "created_by": seeded_user.id,
        })
        file_obj.is_deleted = True
        file_repo.session.add(file_obj)
        await file_repo.session.flush()

        with pytest.raises(ValueError, match="File not found"):
            await file_repo.delete_file(file_obj.id)


class TestDeleteFilesBatch:
    async def test_delete_files_batch(self, file_repo, root_folder, seeded_user):
        f1 = await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/b1",
            "filename": "batch1.txt",
            "original_filename": "batch1.txt",
            "media_type": "text/plain",
            "size_bytes": 100,
            "sha256": "l" * 64,
            "created_by": seeded_user.id,
        })
        f2 = await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/b2",
            "filename": "batch2.txt",
            "original_filename": "batch2.txt",
            "media_type": "text/plain",
            "size_bytes": 200,
            "sha256": "m" * 64,
            "created_by": seeded_user.id,
        })

        count = await file_repo.delete_files_batch([f1.id, f2.id])
        assert count == 2

        from sqlalchemy import select
        folder = (await file_repo.session.execute(select(FileFolder).where(FileFolder.id == root_folder.id))).scalar_one()
        assert folder.child_file_count == 0
        assert folder.total_size_bytes == 0

    async def test_delete_files_batch_partial_match(self, file_repo, root_folder, seeded_user):
        f1 = await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/b3",
            "filename": "batch3.txt",
            "original_filename": "batch3.txt",
            "media_type": "text/plain",
            "size_bytes": 100,
            "sha256": "n" * 64,
            "created_by": seeded_user.id,
        })

        count = await file_repo.delete_files_batch([f1.id, uuid.uuid4()])
        assert count == 1

    async def test_delete_files_batch_empty(self, file_repo):
        count = await file_repo.delete_files_batch([])
        assert count == 0

    async def test_delete_files_batch_already_deleted(self, file_repo, root_folder, seeded_user):
        f1 = await file_repo.add_file(root_folder.id, {
            "owner_user_id": seeded_user.id,
            "folder_id": root_folder.id,
            "storage_key": "files/b4",
            "filename": "batch4.txt",
            "original_filename": "batch4.txt",
            "media_type": "text/plain",
            "size_bytes": 100,
            "sha256": "o" * 64,
            "created_by": seeded_user.id,
        })
        f1.is_deleted = True
        file_repo.session.add(f1)
        await file_repo.session.flush()

        count = await file_repo.delete_files_batch([f1.id])
        assert count == 0
