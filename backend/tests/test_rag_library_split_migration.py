import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.rag import RagDocument, RagLibrary
from app.services.rag.library_routing import LIBRARY_SEEDS

OLD_LIBRARY_ID = uuid.UUID("6f1d2c3a-1111-4a2b-9c3d-000000000001")


@pytest.fixture
async def rag_session_factory():
    """独立 engine（不复用 app.db.session 全局连接池），避免全套运行时跨事件循环复用连接。"""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_eight_libraries_exist_after_migration(rag_session_factory):
    async with rag_session_factory() as session:
        names = (await session.execute(select(RagLibrary.name))).scalars().all()
    for seed in LIBRARY_SEEDS:
        assert seed.name in names


@pytest.mark.asyncio
async def test_old_default_library_is_deleted(rag_session_factory):
    async with rag_session_factory() as session:
        library = await session.get(RagLibrary, OLD_LIBRARY_ID)
    assert library is None


@pytest.mark.asyncio
async def test_no_orphan_documents(rag_session_factory):
    async with rag_session_factory() as session:
        orphan = (
            await session.execute(
                select(func.count())
                .select_from(RagDocument)
                .where(RagDocument.library_id == OLD_LIBRARY_ID)
            )
        ).scalar_one()
    assert orphan == 0


@pytest.mark.asyncio
async def test_every_document_belongs_to_one_of_eight_libraries(rag_session_factory):
    ids = [seed.id for seed in LIBRARY_SEEDS]
    async with rag_session_factory() as session:
        outside = (
            await session.execute(
                select(func.count())
                .select_from(RagDocument)
                .where(RagDocument.library_id.notin_(ids))
            )
        ).scalar_one()
    assert outside == 0
