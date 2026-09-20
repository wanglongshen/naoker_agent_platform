import uuid

import pytest

from sqlalchemy import func, select

from app.models.feishu_config import FeishuConfig
from app.services.feishu.config_service import FeishuConfigService


async def _count(db) -> int:
    return (
        await db.execute(select(func.count()).select_from(FeishuConfig))
    ).scalar_one()


class TestFeishuConfigService:
    @pytest.mark.anyio
    async def test_create_first_becomes_default(self, test_db):
        async with test_db() as s:
            cfg = await FeishuConfigService.create(s, "公司A", "cli_test_a", "secret-a")
            assert cfg.is_default is True
            assert cfg.name == "公司A"
            assert await _count(s) == 1

    @pytest.mark.anyio
    async def test_create_second_does_not_override_default(self, test_db):
        async with test_db() as s:
            await FeishuConfigService.create(s, "公司A", "cli_a", "s1")
            cfg2 = await FeishuConfigService.create(s, "公司B", "cli_b", "s2")
            assert cfg2.is_default is False
            default = await FeishuConfigService.get_default(s)
            assert default.app_id == "cli_a"

    @pytest.mark.anyio
    async def test_activate_makes_single_default(self, test_db):
        async with test_db() as s:
            cfg1 = await FeishuConfigService.create(s, "公司A", "cli_a", "s1")
            cfg2 = await FeishuConfigService.create(s, "公司B", "cli_b", "s2")
            ok = await FeishuConfigService.activate(s, cfg2.id)
            assert ok is True
            defaults = [c for c in await FeishuConfigService.list_all(s) if c.is_default]
            assert len(defaults) == 1
            assert defaults[0].id == cfg2.id

    @pytest.mark.anyio
    async def test_delete_default_transfers_to_next(self, test_db):
        async with test_db() as s:
            cfg1 = await FeishuConfigService.create(s, "公司A", "cli_a", "s1")
            cfg2 = await FeishuConfigService.create(s, "公司B", "cli_b", "s2")
            await FeishuConfigService.activate(s, cfg2.id)
            await FeishuConfigService.delete(s, cfg2.id)
            default = await FeishuConfigService.get_default(s)
            assert default is not None and default.id == cfg1.id

    @pytest.mark.anyio
    async def test_secret_roundtrip(self, test_db):
        async with test_db() as s:
            cfg = await FeishuConfigService.create(s, "公司A", "cli_a", "super-secret-42")
            assert FeishuConfigService.decrypt_secret(cfg) == "super-secret-42"

    @pytest.mark.anyio
    async def test_update_partial(self, test_db):
        async with test_db() as s:
            cfg = await FeishuConfigService.create(s, "公司A", "cli_a", "s1")
            updated = await FeishuConfigService.update(s, cfg.id, name="公司A新")
            assert updated.name == "公司A新"
            assert updated.app_id == "cli_a"
