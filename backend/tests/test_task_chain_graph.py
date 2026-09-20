from __future__ import annotations

import uuid

import pytest

MODULES = ["市场分析", "投放策略", "预算分配"]

_SECTION = (
    "本模块基于行业公开数据与竞品投放复盘给出可执行结论：目标人群以一二线城市二十五至三十五岁人群为主，"
    "内容侧优先短视频种草与达人矩阵组合，投放侧按三七比例分配信息流与搜索，预算按阶段释放并设置止损线，"
    "执行节奏以两周为一个迭代周期，每周期复盘素材点击率、转化成本与内容互动率三项指标。"
    "首期预算 300 万元，其中达人合作 120 万元、信息流投放 150 万元、内容制作 30 万元，"
    "预期点击率提升 20%，转化成本下降 15%，并以每周一次的数据复盘驱动下一轮预算调整。"
)


def _plan(modules: list[str] | None = None, extra: str = "") -> str:
    modules = modules or MODULES
    body = "\n\n".join(f"## {name}\n{_SECTION}{extra}" for name in modules)
    return f"# 新品上市方案\n\n{body}\n"


class FakeExecutor:
    def __init__(self, draft_builder=None):
        self.tasks: list[str] = []
        self.homes: list = []
        self._draft_builder = draft_builder or (lambda call: _plan())

    async def run(self, *, user_id, task, timeout_seconds=None, home_dir=None):
        from app.services.dsh.executor import DshTaskResult

        self.tasks.append(task)
        self.homes.append(home_dir)
        if task.startswith("调研任务"):
            return DshTaskResult("调研结论：行业趋势向好，竞品以达人矩阵为主。", 0, "", "", 0.05)
        draft_calls = sum(1 for item in self.tasks if item.startswith("请撰写"))
        return DshTaskResult(self._draft_builder(draft_calls), 0, "", "", 0.05)


class FakeLlm:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        return "- 行业趋势\n- 竞品投放\n- 平台规则"


class FakePoints:
    def __init__(self) -> None:
        self.deducted: list[tuple] = []

    def tokens_to_points(self, tokens: int) -> int:
        return max(1, tokens // 10000)

    async def deduct_for_run(self, db, user_id, run_id, tokens):
        self.deducted.append((user_id, run_id, tokens))
        return 1


async def _make_chain(db, **payload):
    from app.models.rbac import User
    from app.repositories.task_chain_repository import TaskChainRepository

    user = User(
        id=uuid.uuid4(),
        username=f"tc-{uuid.uuid4().hex[:8]}",
        display_name="任务链测试用户",
        password_hash="x",
    )
    db.add(user)
    await db.commit()
    repo = TaskChainRepository(db)
    chain = await repo.create_chain(
        user_id=user.id,
        goal="写一份新品上市方案",
        input_payload={"modules": MODULES, "brand": "示例品牌", **payload},
    )
    return repo, chain


@pytest.mark.anyio
async def test_chain_runs_all_stages_and_delivers(test_db, monkeypatch, tmp_path):
    from app.services import task_chain as package
    from app.services.task_chain.service import TaskChainService

    monkeypatch.setattr(
        package.service,
        "_resolve_storage_path",
        lambda user_id, file_id: tmp_path / str(user_id) / str(file_id),
    )

    async with test_db() as db:
        repo, chain = await _make_chain(db)
        executor = FakeExecutor()
        points = FakePoints()
        llm = FakeLlm()
        service = TaskChainService(repo, executor=executor, llm=llm, points=points)

        await service.run_chain(chain.id)

        refreshed = await repo.get_chain(chain.id)
        stages = await repo.list_stages(chain.id)

    assert refreshed.status == "succeeded", refreshed.error
    assert [stage.stage for stage in stages] == list(service.stages_expected_order())
    assert all(stage.status == "succeeded" for stage in stages)
    assert refreshed.result_file_id is not None
    assert refreshed.final_answer
    assert refreshed.total_tokens > 0 and refreshed.points_cost > 0
    assert len(points.deducted) == 1
    assert points.deducted[0][1] == chain.id
    assert llm.calls == 1
    assert any(task.startswith("调研任务") for task in executor.tasks)
    assert any(task.startswith("请撰写") for task in executor.tasks)


@pytest.mark.anyio
async def test_review_gate_retries_draft_before_polish(test_db, monkeypatch, tmp_path):
    from app.services import task_chain as package
    from app.services.task_chain.service import TaskChainService

    monkeypatch.setattr(
        package.service,
        "_resolve_storage_path",
        lambda user_id, file_id: tmp_path / str(user_id) / str(file_id),
    )

    async with test_db() as db:
        repo, chain = await _make_chain(db)
        executor = FakeExecutor(draft_builder=lambda call: "太短了" if call == 1 else _plan())
        service = TaskChainService(repo, executor=executor, llm=FakeLlm(), points=FakePoints())

        await service.run_chain(chain.id)

        refreshed = await repo.get_chain(chain.id)
        stages = await repo.list_stages(chain.id)

    assert refreshed.status == "succeeded", refreshed.error
    names = [stage.stage for stage in stages]
    assert names.count("draft_plan") == 2
    assert names.count("review_gate") == 2
    assert names[-1] == "bill"


@pytest.mark.anyio
async def test_headless_subtasks_use_isolated_home(test_db, monkeypatch, tmp_path):
    from app.services import task_chain as package
    from app.services.task_chain.service import TaskChainService

    monkeypatch.setattr(
        package.service,
        "_resolve_storage_path",
        lambda user_id, file_id: tmp_path / str(user_id) / str(file_id),
    )

    async with test_db() as db:
        repo, chain = await _make_chain(db)
        executor = FakeExecutor()
        service = TaskChainService(repo, executor=executor, llm=FakeLlm(), points=FakePoints())

        await service.run_chain(chain.id)
        user_id = chain.user_id

    expected = service.settings.dsh_home_root_path / f"{user_id}-headless"
    web_home = service.settings.dsh_home_root_path / str(user_id)
    assert executor.homes
    assert all(home == expected for home in executor.homes)
    assert expected != web_home


@pytest.mark.anyio
async def test_bill_reads_usage_from_headless_home(test_db, monkeypatch, tmp_path):
    from app.services import task_chain as package
    from app.services.task_chain.service import TaskChainService

    monkeypatch.setattr(
        package.service,
        "_resolve_storage_path",
        lambda user_id, file_id: tmp_path / str(user_id) / str(file_id),
    )
    seen: dict = {}

    def fake_collect(home_dir, *, since, until):
        seen["home"] = home_dir
        return 12345

    monkeypatch.setattr(package.service, "collect_dsh_usage", fake_collect)

    async with test_db() as db:
        repo, chain = await _make_chain(db)
        service = TaskChainService(repo, executor=FakeExecutor(), llm=FakeLlm(), points=FakePoints())

        await service.run_chain(chain.id)
        refreshed = await repo.get_chain(chain.id)
        user_id = chain.user_id

    expected = service.settings.dsh_home_root_path / f"{user_id}-headless"
    assert seen["home"] == expected
    assert refreshed.total_tokens == 12345
