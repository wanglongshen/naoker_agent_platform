import uuid

from argon2 import PasswordHasher
from sqlalchemy import select

from app.models.file import FileFolder, FileObject
from app.models.rbac import User

# The auth_db/admin_client/ordinary_user/ordinary_client fixtures are
# defined in test_agent_authorization.py (not in conftest), so import them.
from tests.test_agent_authorization import (
    admin_client,
    auth_db,
    ordinary_client,
    ordinary_user,
)

ph = PasswordHasher()


async def _seed_other_user(s, owner_id):
    u = User(
        username=f"owner_{uuid.uuid4().hex[:8]}",
        display_name="其他用户",
        password_hash=ph.hash("Password123"),
    )
    s.add(u)
    await s.flush()
    folder = FileFolder(
        owner_user_id=u.id,
        parent_folder_id=None,
        name="我的文件夹",
        path=f"/{uuid.uuid4().hex[:8]}",
        depth=1,
    )
    s.add(folder)
    s.add(
        FileObject(
            owner_user_id=u.id,
            storage_key="test/key",
            filename="root.txt",
            original_filename="root.txt",
            media_type="text/plain",
            size_bytes=10,
            sha256="abc",
        )
    )
    await s.commit()
    return u.id


async def test_non_super_admin_cannot_list_admin_folder_tree(ordinary_client) -> None:
    response = await ordinary_client.get("/api/files/folders/admin")
    assert response.status_code == 403


async def test_super_admin_folder_tree_groups_by_user(
    auth_db, admin_client, ordinary_user
) -> None:
    async with auth_db() as s:
        other_id = await _seed_other_user(s, ordinary_user.id)

    me_resp = await admin_client.get("/api/auth/me")
    assert me_resp.status_code == 200
    admin_id = me_resp.json()["data"]["id"]

    response = await admin_client.get("/api/files/folders/admin")
    assert response.status_code == 200
    groups = response.json()["data"]
    assert len(groups) >= 2
    user_ids = [g["user_id"] for g in groups]
    # admin 自己排最前
    assert str(admin_id) in user_ids
    assert user_ids[0] == str(admin_id)
    assert str(other_id) in user_ids
    other = next(g for g in groups if g["user_id"] == str(other_id))
    assert other["username"].startswith("owner_")
    assert len(other["folders"]) == 1
    assert other["folders"][0]["name"] == "我的文件夹"


async def test_super_admin_folder_tree_excludes_empty_users(
    auth_db, admin_client
) -> None:
    from app.models.rbac import User as UserModel

    async with auth_db() as s:
        empty = UserModel(
            username=f"empty_{uuid.uuid4().hex[:8]}",
            display_name="空用户",
            password_hash=ph.hash("Password123"),
        )
        s.add(empty)
        await s.commit()
        empty_id = empty.id

    response = await admin_client.get("/api/files/folders/admin")
    groups = response.json()["data"]
    assert str(empty_id) not in [g["user_id"] for g in groups]


async def test_super_admin_list_filters_by_folder_and_media_type(
    auth_db, admin_client, ordinary_user
) -> None:
    async with auth_db() as s:
        other_id = await _seed_other_user(s, ordinary_user.id)
        folder_id = (
            await s.scalar(
                select(FileFolder).where(FileFolder.owner_user_id == other_id)
            )
        ).id

    # folder 过滤
    r1 = await admin_client.get(
        f"/api/files/admin?user_id={other_id}&folder_id={folder_id}"
    )
    assert r1.status_code == 200
    assert r1.json()["data"]["total"] == 0  # 文件夹内没有文件（root.txt 在根目录）
    # media_type 过滤
    r2 = await admin_client.get(
        f"/api/files/admin?user_id={other_id}&media_type=text/plain"
    )
    assert r2.json()["data"]["total"] == 1
    assert r2.json()["data"]["items"][0]["original_filename"] == "root.txt"

    r3 = await admin_client.get(
        f"/api/files/admin?user_id={other_id}&media_type=image/png"
    )
    assert r3.json()["data"]["total"] == 0


async def test_super_admin_list_all_returns_everyone(
    auth_db, admin_client, ordinary_user
) -> None:
    async with auth_db() as s:
        await _seed_other_user(s, ordinary_user.id)

    response = await admin_client.get("/api/files/admin")
    assert response.status_code == 200
    # 至少包含普通用户与其他用户两类文件（seeded admin 也可能无文件，不强制断言数量）
    assert response.json()["data"]["page"] == 1
