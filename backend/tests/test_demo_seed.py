import pytest
from sqlalchemy import select

from app.db.seed_demo_data import seed_demo_data
from app.models.rbac import Role


@pytest.mark.asyncio
async def test_demo_seed_synchronizes_chinese_demo_role_labels(session) -> None:
    await seed_demo_data(session)

    role = await session.scalar(select(Role).where(Role.code == "role_manager"))
    assert role.name == "角色管理员"
    assert role.description == "负责角色维护与权限分配"


class TestDemoRolesUpdated:
    @pytest.mark.asyncio
    async def test_demo_data_no_longer_creates_legacy_roles(self, session) -> None:
        await seed_demo_data(session)

        legacy = (
            await session.scalars(
                select(Role).where(
                    Role.code.in_(["operations_specialist", "read_only_visitor"])
                )
            )
        ).all()
        assert all(r.is_deleted for r in legacy) or len(legacy) == 0
