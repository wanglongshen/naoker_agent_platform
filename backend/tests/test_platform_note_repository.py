import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.seed import seed_rbac
from app.models.base import Base


@pytest.fixture
async def api_db(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as s:
        await seed_rbac(s)
        await s.commit()
        yield s

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _new_owner(session) -> uuid.UUID:
    from app.models.rbac import User

    user = User(
        username=f"pn_owner_{uuid.uuid4().hex[:8]}",
        display_name="PlatformNoteOwner",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    return user.id


@pytest.mark.asyncio
async def test_upsert_inserts_then_updates_same_url(api_db):
    from app.models.platform_note import PlatformNote
    from app.repositories.platform_note_repository import (
        count_platform,
        upsert,
    )

    owner = await _new_owner(api_db)
    sample = {
        "title": "第一条",
        "author": "作者A",
        "url": "https://www.xiaohongshu.com/explore/n1",
        "likes": 10,
        "collect_count": 5,
        "comment_count": 2,
        "cover_image": None,
        "topic_tags": [],
        "content": "正文v1",
        "published_at": None,
    }
    assert await upsert(api_db, owner, "xiaohongshu", "成毅", sample) is True
    await api_db.commit()

    sample2 = {**sample, "title": "第一条(更新)", "content": "正文v2", "likes": 99}
    assert await upsert(api_db, owner, "xiaohongshu", "成毅", sample2) is True
    await api_db.commit()

    rows = (
        await api_db.execute(
            select(PlatformNote).where(PlatformNote.owner_user_id == owner)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "第一条(更新)"
    assert rows[0].content == "正文v2"
    assert rows[0].like_count == 99
    assert await count_platform(api_db, owner, "xiaohongshu") == 1


@pytest.mark.asyncio
async def test_count_platform_isolates_owner_and_platform(api_db):
    from app.repositories.platform_note_repository import count_platform, upsert

    owner_a = await _new_owner(api_db)
    owner_b = await _new_owner(api_db)
    base = {"title": "t", "author": "", "url_prefix": "https://www.xiaohongshu.com/explore/"}
    for i, url in enumerate(["n1", "n2", "n3"]):
        await upsert(api_db, owner_a, "xiaohongshu", "k", {**base, "url": base["url_prefix"] + url})
    await upsert(api_db, owner_b, "xiaohongshu", "k", {**base, "url": base["url_prefix"] + "n9"})
    await upsert(api_db, owner_a, "douyin", "k", {**base, "url": "https://www.douyin.com/video/1"})
    await api_db.commit()
    assert await count_platform(api_db, owner_a, "xiaohongshu") == 3
    assert await count_platform(api_db, owner_b, "xiaohongshu") == 1
    assert await count_platform(api_db, owner_a, "douyin") == 1
