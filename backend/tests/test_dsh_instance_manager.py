import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.models.base import Base
from app.models.dsh import DshInstance

pytestmark = pytest.mark.asyncio


class FakeProcess:
    """minimal subprocess stand-in with call counters."""

    def __init__(self, pid=7777, hang_wait=False):
        self.pid = pid
        self.terminated = 0
        self.killed = 0
        self._hang_wait = hang_wait

    async def wait(self):
        if self._hang_wait:
            await asyncio.sleep(5)
        return 0

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1


@pytest.fixture
async def api_db(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _make_manager(**kwargs):
    from app.services.dsh.instance_manager import DshInstanceManager

    settings = get_settings()
    return DshInstanceManager(
        settings=settings,
        probe_timeout=kwargs.pop("probe_timeout", 0.2),
        probe_interval=kwargs.pop("probe_interval", 0.02),
        stop_grace=kwargs.pop("stop_grace", 0.3),
        **kwargs,
    )


async def test_resolve_port_in_range_and_deterministic():
    m = _make_manager()
    ports = {m.resolve_port("u-1"), m.resolve_port("u-2"), m.resolve_port("u-99")}
    assert all(3100 <= p <= 3399 for p in ports)
    assert m.resolve_port("u-1") == m.resolve_port("u-1")


@pytest.mark.anyio
async def test_health_wait_awaits_default_async_probe():
    """回归（2026-09-15）：默认探针是 async，未 await 时协程恒真 → 未就绪也被判定 running。"""
    m = _make_manager(probe_timeout=0.15, probe_interval=0.02)
    assert await m._health_wait(59999) is False


@pytest.mark.anyio
async def test_health_wait_supports_async_probe_true():
    m = _make_manager(probe_timeout=0.5, probe_interval=0.02)

    async def probe(port=0):
        return True

    m.probe = probe
    assert await m._health_wait(1) is True


def test_spawn_command_dev_bin_shape():
    m = _make_manager()
    m.settings.dsh_instance_mode = "dev_bin"
    cmd = m.spawn_command("u-1", home="/tmp/home", port=3121, trusted_host="localhost:3000")
    assert cmd[0] in ("dsh", "node")  # node 直调 npm 全局 bin.js（dev_bin 实际形态）
    assert cmd[-1] == "localhost:3000"
    assert "--host" in cmd and "127.0.0.1" in cmd
    assert "--no-open" in cmd
    assert str(3121) in cmd


def test_spawn_command_vendored_shape():
    m = _make_manager()
    m.settings.dsh_instance_mode = "vendored"
    cmd = m.spawn_command("u-1", home="/tmp/home", port=3131, trusted_host="localhost:3000")
    assert cmd[0] == "node"
    assert "deepseek-harness/apps/cli/lib/bin.js" in str(cmd)
    assert "--trusted-host" in cmd


async def test_ensure_running_idempotent(api_db):
    m = _make_manager()
    spawns = []
    fake = FakeProcess()

    async def factory(cmd, env, cwd, **kw):
        spawns.append(cmd)
        return fake

    m.process_factory = factory
    m.probe = lambda port=0: True

    inst = await m.ensure_running(user_id=uuid.uuid4(), db=api_db)
    assert inst.state == "running" and inst.pid == 7777
    again = await m.ensure_running(user_id=inst.user_id, db=api_db)
    assert len(spawns) == 1
    assert again.id == inst.id


async def test_ensure_running_spawns_with_absolute_home_env(api_db):
    m = _make_manager()
    envs = []

    async def factory(cmd, env, cwd, **kw):
        envs.append(env)
        return FakeProcess()

    m.process_factory = factory
    m.probe = lambda port=0: True

    uid = uuid.uuid4()
    await m.ensure_running(user_id=uid, db=api_db)
    home = envs[0]["DSH_HOME"]
    assert os.path.isabs(home), f"DSH_HOME must be absolute, got {home!r}"
    assert home.replace("\\", "/").endswith(f"var/dsh/{uid}")


async def test_ensure_running_failure_records_error(api_db):
    m = _make_manager(probe_timeout=0.05, probe_interval=0.01)
    fake = FakeProcess()
    m.process_factory = None  # created below
    async def factory(cmd, env, cwd, **kw):
        return fake

    m.process_factory = factory
    m.probe = lambda port=0: False

    uid = uuid.uuid4()
    inst = await m.ensure_running(user_id=uid, db=api_db)
    assert inst.state == "error"
    assert inst.error_hint is not None
    assert fake.terminated >= 1


async def test_stop_graceful_and_force(api_db):
    m = _make_manager(probe_timeout=0.05, stop_grace=0.05)
    fake = FakeProcess()
    m.process_factory = None
    async def factory(cmd, env, cwd, **kw):
        return fake

    m.process_factory = factory
    m.probe = lambda port=0: True
    uid = uuid.uuid4()
    inst = await m.ensure_running(user_id=uid, db=api_db)
    m._running[str(uid)] = fake

    await m.stop(user_id=uid, db=api_db)
    assert inst.state == "stopped"
    assert fake.killed == 0  # graceful path: terminate only

    fake2 = FakeProcess(hang_wait=True)
    m._running[str(uid)] = fake2
    await m.stop(user_id=uid, db=api_db)
    assert fake2.terminated >= 1


async def test_sweep_idle_stops_only_expired(api_db):
    m = _make_manager(probe_timeout=0.05, stop_grace=0.05)
    uid_old = uuid.uuid4()
    old = DshInstance(user_id=uid_old, port=3180, state="running", pid=1111,
                      last_active_at=datetime.now(UTC) - timedelta(seconds=7200))
    api_db.add(old)
    await api_db.commit()

    fake_old = FakeProcess()
    m._running[str(uid_old)] = fake_old
    await m.sweep_idle(db=api_db)

    row = (await api_db.execute(
        select(DshInstance).where(DshInstance.user_id == uid_old))).scalar_one()
    assert row.state == "stopped"
    assert fake_old.terminated >= 1


async def test_touch_updates_last_active(api_db):
    m = _make_manager(probe_timeout=0.05)
    uid = uuid.uuid4()
    api_db.add(DshInstance(user_id=uid, port=3190, state="running", pid=2222))
    await api_db.commit()
    await m.touch(user_id=uid, db=api_db)
    row = (await api_db.execute(
        select(DshInstance).where(DshInstance.user_id == uid))).scalar_one()
    assert row.last_active_at is not None

async def _serve_ephemeral() -> tuple[asyncio.AbstractServer, int]:
    async def handler(reader, writer):
        writer.close()
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_check_alive_marks_dead_instance_stopped(api_db):
    m = _make_manager()
    uid = uuid.uuid4()
    api_db.add(DshInstance(user_id=uid, port=3195, state="running", pid=3333))
    await api_db.commit()
    row = await m.check_alive(uid, api_db)
    assert row.state == "stopped"
    assert row.pid is None
    assert row.error_hint == "process_exited"


async def test_check_alive_keeps_alive_instance(api_db):
    server, port = await _serve_ephemeral()
    try:
        m = _make_manager()
        uid = uuid.uuid4()
        api_db.add(DshInstance(user_id=uid, port=port, state="running", pid=4444))
        await api_db.commit()
        row = await m.check_alive(uid, api_db)
        assert row.state == "running"
    finally:
        server.close()
        await server.wait_closed()


async def test_ensure_running_adopts_existing_process(api_db):
    server, port = await _serve_ephemeral()
    try:
        m = _make_manager()
        spawns = []

        async def factory(cmd, env, cwd, **kw):
            spawns.append(cmd)

        m.process_factory = factory
        m.resolve_port = lambda uid: port
        inst = await m.ensure_running(user_id=uuid.uuid4(), db=api_db)
        assert inst.state == "running"
        assert spawns == []
    finally:
        server.close()
        await server.wait_closed()

async def test_default_process_factory_works_on_selector_loop(tmp_path):
    """Windows + Selector 循环（uvicorn --reload）下 Popen 兜底必须可跑。"""
    m = _make_manager()
    log = tmp_path / "probe.log"
    proc = await m._default_process_factory(
        ["cmd", "/c", "echo", "hello"], env=dict(os.environ), cwd=str(tmp_path),
        log_path=str(log))
    rc = await proc.wait()
    assert rc == 0
    assert "hello" in log.read_text(encoding="utf-8", errors="replace")
