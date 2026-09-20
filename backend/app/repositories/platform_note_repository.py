from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_note import PlatformNote


async def upsert(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    platform: str,
    keyword: str,
    sample: dict,
) -> bool:
    """按 (owner_user_id, url) upsert。返回是否执行成功（异常不吞，由调用方处理）。"""
    now = datetime.now(UTC)
    url = sample.get("url")
    if not url or not sample.get("title"):
        return False
    values = {
        "owner_user_id": owner_user_id,
        "platform": platform,
        "keyword": keyword,
        "url": str(url),
        "title": str(sample["title"])[:500],
        "content": (str(sample.get("content"))[:20000] if sample.get("content") else None),
        "image_urls": sample.get("image_urls") or None,
        "like_count": sample.get("like_count") or sample.get("likes"),
        "collect_count": sample.get("collect_count"),
        "comment_count": sample.get("comment_count"),
        "author": (str(sample.get("author"))[:200] if sample.get("author") else None),
        "published_at": sample.get("published_at"),
        "topic_tags": sample.get("topic_tags") or None,
        "collected_at": now,
        "updated_at": now,
    }
    stmt = (
        insert(PlatformNote)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_platform_notes_owner_url",
            set_={
                "title": values["title"],
                "content": values["content"],
                "image_urls": values["image_urls"],
                "like_count": values["like_count"],
                "collect_count": values["collect_count"],
                "comment_count": values["comment_count"],
                "author": values["author"],
                "published_at": values["published_at"],
                "topic_tags": values["topic_tags"],
                "keyword": values["keyword"],
                "updated_at": now,
            },
        )
    )
    await session.execute(stmt)
    return True


async def count_platform(
    session: AsyncSession, owner_user_id: uuid.UUID, platform: str
) -> int:
    result = await session.execute(
        select(func.count(func.distinct(PlatformNote.url))).where(
            PlatformNote.owner_user_id == owner_user_id,
            PlatformNote.platform == platform,
        )
    )
    return int(result.scalar() or 0)


async def list_notes(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    keyword: str | None = None,
    platform: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PlatformNote], int]:
    conditions = [PlatformNote.owner_user_id == owner_user_id]
    if keyword:
        conditions.append(PlatformNote.keyword == keyword)
    if platform:
        conditions.append(PlatformNote.platform == platform)
    total = int(
        (
            await session.execute(
                select(func.count(PlatformNote.id)).where(*conditions)
            )
        ).scalar()
        or 0
    )
    rows = (
        (
            await session.execute(
                select(PlatformNote)
                .where(*conditions)
                .order_by(PlatformNote.collected_at.desc())
                .limit(min(limit, 200))
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total
