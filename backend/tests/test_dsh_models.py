import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.base import Base
from app.models.dsh import DshInstance, DshSession

USER_A = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
async def api_db(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as s:
        yield s

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def test_dsh_instance_roundtrip(api_db):
    row = DshInstance(user_id=USER_A, port=3121, state="running", pid=4242)
    api_db.add(row)
    await api_db.commit()
    got = (await api_db.execute(select(DshInstance))).scalar_one()
    assert str(got.user_id) == USER_A
    assert got.port == 3121
    assert got.state == "running"
    assert got.pid == 4242


async def test_dsh_session_unique_user_session(api_db):
    a = DshSession(user_id=USER_A, dsh_session_id="s-1", title="t")
    b = DshSession(user_id=USER_A, dsh_session_id="s-1", title="t2")
    api_db.add(a)
    await api_db.flush()
    api_db.add(b)
    with pytest.raises(Exception):
        await api_db.commit()
    await api_db.rollback()
