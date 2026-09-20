import uuid
from datetime import UTC, datetime

import pytest
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


@pytest.mark.asyncio
async def test_platform_note_create_and_unique_constraint(api_db):
    from app.models.platform_note import PlatformNote
    from app.models.rbac import User
    from sqlalchemy import select

    owner = (await api_db.execute(select(User.id).limit(1))).scalar_one()
    now = datetime.now(UTC)
    note = PlatformNote(
        owner_user_id=owner,
        platform="xiaohongshu",
        keyword="成毅",
        url="https://www.xiaohongshu.com/explore/abc123",
        title="测试笔记",
        content="正文内容",
        image_urls=["https://img.example.com/1.jpg"],
        like_count=10,
        collect_count=5,
        comment_count=2,
        author="作者A",
        topic_tags=["成毅", "旅行"],
        collected_at=now,
    )
    api_db.add(note)
    await api_db.commit()

    rows = (await api_db.execute(select(PlatformNote).where(PlatformNote.owner_user_id == owner))).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "测试笔记"
    assert rows[0].image_urls == ["https://img.example.com/1.jpg"]
    assert rows[0].topic_tags == ["成毅", "旅行"]
    assert rows[0].project_id is None

    # 同 owner 同 url 违反唯一约束
    dup = PlatformNote(
        owner_user_id=owner,
        platform="douyin",
        keyword="x",
        url="https://www.xiaohongshu.com/explore/abc123",
        title="重复",
    )
    api_db.add(dup)
    with pytest.raises(Exception):
        await api_db.commit()
    await api_db.rollback()
