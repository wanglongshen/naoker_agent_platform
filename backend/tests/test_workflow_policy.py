import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.services.agent.workflow_policy import WorkflowPolicy


@pytest.fixture(autouse=True)
def _isolate_workflow_doc_storage(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)


async def _make_super_admin(session) -> uuid.UUID:
    from app.models.rbac import Role, User, UserRole
    from app.core.config import get_settings

    settings = get_settings()
    role = await session.scalar(select(Role).where(Role.code == "super_admin"))
    assert role is not None
    user = await session.scalar(
        select(User).where(User.username == settings.initial_admin_username)
    )
    if user is not None:
        return user.id
    from argon2 import PasswordHasher

    ph = PasswordHasher()
    user = User(
        username=settings.initial_admin_username,
        display_name="WF Admin",
        password_hash=ph.hash("Test1234"),
    )
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=role.id))
    await session.flush()
    return user.id


async def _write_doc(session, owner_id, folder_name, filename, content):
    from pathlib import Path
    from app.models.file import FileFolder, FileObject

    folder = await session.scalar(
        select(FileFolder).where(
            FileFolder.owner_user_id == owner_id,
            FileFolder.name == folder_name,
            FileFolder.parent_folder_id.is_(None),
            FileFolder.is_deleted == False,
        )
    )
    if folder is None:
        folder = FileFolder(
            owner_user_id=owner_id,
            name=folder_name,
            path=f"/{folder_name}",
            depth=0,
            created_by=owner_id,
        )
        session.add(folder)
        await session.flush()

    storage_dir = Path("./var/files") / str(owner_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / f"{uuid.uuid4().hex}"
    storage_path.write_text(content, encoding="utf-8")

    file_obj = FileObject(
        id=uuid.uuid4(),
        owner_user_id=owner_id,
        folder_id=folder.id,
        storage_key=str(storage_path),
        filename=filename,
        original_filename=filename,
        media_type="text/markdown",
        size_bytes=len(content.encode("utf-8")),
        sha256="0" * 64,
        created_by=owner_id,
    )
    session.add(file_obj)
    await session.flush()
    return file_obj


async def _write_blueprint(session, owner_id, content):
    return await _write_doc(
        session, owner_id, "00_Agent规范与模板", "脑壳儿_Agent运行蓝图_v1.1.md", content
    )


async def _write_plan_dependencies(session, owner_id, *, exclude=()):
    filenames = (
        "脑壳儿_案例库索引.md",
        "脑壳儿_方案输出模板.md",
        "脑壳儿_方案评分规范.md",
        "脑壳儿_中国市场调研资料源规范.md",
    )
    for filename in filenames:
        if filename in exclude:
            continue
        await _write_doc(
            session, owner_id, "00_Agent规范与模板", filename, f"# {filename}\n测试规范正文"
        )


_STEP0_TABLE = (
    "### Step 0：判断任务类型\n\n"
    "| 任务类型 | 判断特征 | 默认动作 |\n"
    "| 完整方案需求 | 要求生成方案/策划 | 直接产出正式方案 |\n"
    "| 纯框架问题 | 概念性问题 | 直接用脑壳儿心智模型回答 |\n"
    "| 矩阵号代运营方案 | 矩阵号/代运营 | 直接产出正式方案 |\n"
)

_STEP8 = (
    "### Step 8：风险校验\n\n"
    "- 禁止编造数据，竞品必查\n"
    "- 客户版不写内部工作内容\n"
)

# 尾部超过 12000 截断点：若注入被截断，该 marker 不会出现
_BLUEPRINT_TAIL = "蓝图层尾MARKER" + "z" * 12500

_ROUTE_RULES_DEFAULT = (
    "调研;;研究=>00_Agent规范与模板/脑壳儿_中国市场调研资料源规范.md"
)


class TestGetInstruction:
    def test_real_save_request_is_always_treated_as_plan(self):
        from app.services.agent.workflow_policy import WorkflowPolicy

        goal = "读取 brief_test.md，然后写一份方案，保存到 brief/文件夹中，最后把保存结果告诉我"
        paths = WorkflowPolicy().required_doc_paths(goal, None)

        assert len(paths) == 4
        assert any("方案输出模板" in path for path in paths)
        assert any("方案评分规范" in path for path in paths)

    async def test_plan_class_injects_full_blueprint(self, test_db):
        async with test_db() as s:
            owner_id = await _make_super_admin(s)
            blueprint = _STEP0_TABLE + "\n" + _STEP8 + "\n" + _BLUEPRINT_TAIL
            await _write_blueprint(s, owner_id, blueprint)
            await _write_plan_dependencies(s, owner_id)
            await s.commit()

        policy = WorkflowPolicy()
        async with test_db() as s:
            instruction = await policy.get_instruction(s, "写一份方案保存到 brief/")

        assert len(_BLUEPRINT_TAIL) > 12000  # 确保断言有区分度
        assert "【系统工作流约束" in instruction
        assert "脑壳儿_Agent运行蓝图（完整原文" in instruction
        assert "禁止编造数据，竞品必查" in instruction  # Step 8 红线文本
        assert _BLUEPRINT_TAIL in instruction  # 全文注入，未截断

    async def test_non_plan_gets_route_docs_only(self, test_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "workflow_route_rules", _ROUTE_RULES_DEFAULT)
        async with test_db() as s:
            owner_id = await _make_super_admin(s)
            await _write_blueprint(
                s, owner_id, _STEP0_TABLE + "\n" + _STEP8 + "\n" + _BLUEPRINT_TAIL
            )
            await _write_plan_dependencies(
                s, owner_id, exclude=("脑壳儿_中国市场调研资料源规范.md",)
            )
            await _write_doc(
                s, owner_id, "00_Agent规范与模板",
                "脑壳儿_中国市场调研资料源规范.md", "调研资料源规范内容",
            )
            await s.commit()

        policy = WorkflowPolicy()
        async with test_db() as s:
            instruction = await policy.get_instruction(s, "帮我做市场调研")

        assert "调研资料源规范内容" in instruction
        assert "脑壳儿_Agent运行蓝图（完整原文" not in instruction
        assert "蓝图层尾MARKER" not in instruction

    async def test_plan_class_also_gets_route_docs(self, test_db, monkeypatch):
        monkeypatch.setattr(
            get_settings(), "workflow_route_rules",
            "矩阵号;;代运营=>00_Agent规范与模板/脑壳儿_矩阵号代运营方案输出规范.md",
        )
        async with test_db() as s:
            owner_id = await _make_super_admin(s)
            await _write_blueprint(
                s, owner_id, _STEP0_TABLE + "\n" + _STEP8 + "\n" + _BLUEPRINT_TAIL
            )
            await _write_plan_dependencies(s, owner_id)
            await _write_doc(
                s, owner_id, "00_Agent规范与模板",
                "脑壳儿_矩阵号代运营方案输出规范.md", "矩阵号九模块",
            )
            await s.commit()

        policy = WorkflowPolicy()
        async with test_db() as s:
            instruction = await policy.get_instruction(s, "帮我写一份矩阵号代运营方案")

        assert "脑壳儿_Agent运行蓝图（完整原文" in instruction
        assert "蓝图层尾MARKER" in instruction
        assert "矩阵号九模块" in instruction

    async def test_disabled_returns_empty(self, test_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "workflow_docs_enabled", False)
        policy = WorkflowPolicy()
        async with test_db() as s:
            assert await policy.get_instruction(s, "写一份方案") == ""

    async def test_route_docs_still_truncated_at_12000(self, test_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "workflow_route_rules", _ROUTE_RULES_DEFAULT)
        async with test_db() as s:
            owner_id = await _make_super_admin(s)
            await _write_blueprint(s, owner_id, _STEP0_TABLE + "\n" + _BLUEPRINT_TAIL)
            await _write_doc(
                s, owner_id, "00_Agent规范与模板",
                "脑壳儿_中国市场调研资料源规范.md", "规范" + "x" * 13000 + "规范尾MARKER",
            )
            await s.commit()

        policy = WorkflowPolicy()
        async with test_db() as s:
            instruction = await policy.get_instruction(s, "帮我做市场调研")

        assert "规范尾MARKER" not in instruction


class TestGetRules:
    async def test_get_rules_returns_parsed_rules(self, test_db):
        async with test_db() as s:
            owner_id = await _make_super_admin(s)
            blueprint = _STEP0_TABLE + "\n" + _STEP8 + "\n" + _BLUEPRINT_TAIL
            await _write_blueprint(s, owner_id, blueprint)
            await _write_plan_dependencies(s, owner_id)
            await s.commit()

        policy = WorkflowPolicy()
        async with test_db() as s:
            rules = await policy.get_rules(s, "写一份方案保存到 brief/")

        assert rules is not None
        assert rules.sha256
        assert any(t.type_name == "完整方案需求" for t in rules.task_types)
        assert any("禁止编造数据" in line for line in rules.red_lines)
        assert rules.structure is not None

    async def test_get_rules_none_when_disabled(self, test_db, monkeypatch):
        monkeypatch.setattr(get_settings(), "workflow_docs_enabled", False)
        policy = WorkflowPolicy()
        async with test_db() as s:
            assert await policy.get_rules(s, "写一份方案") is None

    async def test_get_rules_caches_by_fingerprint(self, test_db):
        async with test_db() as s:
            owner_id = await _make_super_admin(s)
            blueprint = _STEP0_TABLE + "\n" + _STEP8 + "\n" + _BLUEPRINT_TAIL
            await _write_blueprint(s, owner_id, blueprint)
            await _write_plan_dependencies(s, owner_id)
            await s.commit()

        policy = WorkflowPolicy()
        async with test_db() as s:
            first = await policy.get_rules(s, "写一份方案")
            second = await policy.get_rules(s, "写一份方案")

        assert first is second


class TestInvalidate:
    async def test_invalidate_clears_internal_caches(self, test_db):
        async with test_db() as s:
            owner_id = await _make_super_admin(s)
            blueprint = _STEP0_TABLE + "\n" + _STEP8 + "\n" + _BLUEPRINT_TAIL
            await _write_blueprint(s, owner_id, blueprint)
            await _write_plan_dependencies(s, owner_id)
            await s.commit()

        policy = WorkflowPolicy()
        async with test_db() as s:
            await policy.get_instruction(s, "写一份方案保存到 brief/")
            assert policy._cache != {}
            policy.invalidate()
            assert policy._cache == {}
            assert policy._super_admin_id is None
            rules = await policy.get_rules(s, "写一份方案")
            assert rules is not None  # 失效后仍可重新加载
