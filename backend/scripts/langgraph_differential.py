"""录制回放差分：同一 fixture 驱动旧轨与图轨，逐字节 diff agent_run_events。

用法（在 backend/ 下运行）::

    python -m scripts.langgraph_differential --record 1     # 录制单个场景（旧轨 + 真实 LLM）
    python -m scripts.langgraph_differential --record all   # 录制全部场景
    python -m scripts.langgraph_differential --diff 1       # 回放双轨并比对
    python -m scripts.langgraph_differential --diff all --report <path>

录制/回放靠环境变量 LANGGRAPH_DIFF_RECORD / LANGGRAPH_DIFF_REPLAY 门控，
由 DeepSeekClient 构造时自动装配（见 app.services.agent.llm_recorder）。

回放模式（--diff）下，非确定性 web 工具（web_search/http_request/
extract_web_content/fetch_web_content/fetch_platform_search）被替换为固定返回
（REPLAY_WEB_STUB_PAYLOADS），避免两次真实网络调用产生与轨道无关的假差异；
DB/文件类工具保持真实执行。录制模式（--record）不替换。

场景配置可带 `fault: {"tool": ..., "mode": "retryable"}`：该场景下被注入的工具
在录制与回放中都始终抛 RetryableToolError（脚本层 monkeypatch，不改 app/**），
用于确定性覆盖 run_failed 分支（场景 7）。

fixture 与报告锚定仓库根 docs/langgraph-eval/（与 spec 一致，不随 cwd 漂移）。
录制环境若设置 WEB_TOOL_ALLOW_NON_GLOBAL_TARGETS=true（Clash fake-IP 场景），
脚本只打印提示、不自行设置该变量；生产默认关闭。
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import select, update

from app.core.config import get_settings
from app.services.agent import AgentLoopService
from app.services.agent.event_normalize import NORMALIZATION_RULES, diff_normalized
from app.services.agent.llm_recorder import LlmRecorder

logger = logging.getLogger("langgraph_differential")

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "docs/langgraph-eval/fixtures"
REPORT_PATH = REPO_ROOT / "docs/langgraph-eval/report.md"
WORKER_ID = "langgraph-diff-worker"
DURATION_KEY = "step_duration_seconds"
SCENARIO_SESSION_TITLE_PREFIX = "diff-scenario-"
MAX_ATTEMPTS_PER_RUN = 5
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
CLAIMABLE_RUN_STATUSES = frozenset({"queued", "retry_wait"})
_CLAIM_WAIT_TIMEOUT_SECONDS = 60.0
_CLAIM_POLL_SECONDS = 0.25

# 回放期确定性 web 工具桩：action type -> 固定返回（形状与 ToolExecutor 真实返回一致）。
# fetch_platform_search 的 platform/keyword 由入参回填（其余字段固定），
# 保证两个轨道在同一 fixture 输入下拿到逐字节一致的 observation。
REPLAY_WEB_STUB_PAYLOADS: dict[str, dict[str, Any]] = {
    "web_search": {
        "results": [
            {
                "title": "差分回放固定搜索结果",
                "url": "https://example.com/langgraph-replay/web-search",
                "content": "回放模式固定返回：真实 web_search 结果依赖网络时序，不可复现。",
            }
        ],
    },
    "http_request": {
        "status_code": 200,
        "url": "https://example.com/langgraph-replay/http-request",
        "title": "差分回放固定页面",
        "text": "回放模式固定返回：真实 http_request 响应依赖网络时序，不可复现。",
        "links": [],
    },
    "fetch_web_content": {
        "status_code": 200,
        "url": "https://example.com/langgraph-replay/fetch-web-content",
        "title": "差分回放固定渲染页",
        "text": "回放模式固定返回：fetch_web_content 依赖本机 web_renderer，不可复现。",
        "platform": "generic",
        "source": "playwright",
        "login_expired": False,
    },
    "fetch_platform_search": {
        "sample_count": 1,
        "samples": [
            {
                "title": "差分回放固定平台样本",
                "url": "https://example.com/langgraph-replay/platform-sample",
            }
        ],
        "total_available": 1,
        "stored_count": 0,
        "detail_failed": 0,
        "platform_total": 0,
        "login_required": False,
        "note": "回放模式固定返回：平台搜索依赖本机 web_renderer 与登录态，不可复现。",
    },
}

# action type -> ToolExecutor 方法名（extract_web_content 与 http_request 同实现）
WEB_ACTION_METHODS: dict[str, str] = {
    "web_search": "_web_search",
    "http_request": "_http_request",
    "extract_web_content": "_http_request",
    "fetch_web_content": "_fetch_web_content",
    "fetch_platform_search": "_fetch_platform_search",
}

SCENARIO_8_ATTACHMENT_MD = """# 星野气泡水 2026 夏季新品推广简报

## 一、产品概况
- 产品名：星野气泡水（白桃乌龙 / 青柠海盐 / 葡萄柚三种口味）
- 定位：0 糖 0 卡 0 脂，主打「轻负担的夏日清爽」
- 规格：330ml 罐装 / 500ml 瓶装；建议零售价 4.5 元 / 6 元
- 上市时间：2026 年 6 月 1 日，首批覆盖华东、华南 12 个重点城市

## 二、目标人群
1. 18-30 岁都市白领与学生，关注体重管理与成分表；
2. 健身与轻食人群，运动后补水场景；
3. 便利店即饮消费人群，追求尝鲜与新口味。

## 三、核心卖点
- 真果萃取 + 微气泡工艺，口感清爽不齁甜；
- 每罐热量低于 5 千卡，配料表仅 6 项；
- 联名插画包装，三种口味三种主题色，适合拍照分享。

## 四、渠道策略
- 线上：天猫/京东旗舰店首发，抖音直播间达人种草，小红书 KOC 铺量；
- 线下：全家、罗森、7-11 冷柜陈列，写字楼自动贩卖机试点；
- 促销：首周第二件半价，集齐三款口味可兑换限定帆布袋。

## 五、传播主题与口号
主题：「这个夏天，轻一点」
口号：轻气泡，轻负担，轻生活。

## 六、预算与节奏
- 总预算 300 万元：线上投放 180 万、线下陈列 70 万、物料与活动 50 万；
- 节奏：5 月预热（悬念海报 + 达人预告）、6 月爆发（首发直播 + 门店活动）、7-8 月延续（口味投票 + UGC 征集）。

## 七、成功指标
- 首月销量 50 万罐；社交平台话题曝光 3000 万次；
- 新客占比不低于 60%，复购率目标 15%。
"""

SCENARIOS: list[dict] = [
    {"id": 1, "name": "普通问答 fast path", "goal": "你好，介绍一下你自己", "settings": {"fast_path_enabled": True}, "attachments": []},
    {"id": 2, "name": "方案类全流程", "goal": "基于已有资料写一份新品上市的广告营销方案", "settings": {}, "attachments": []},
    {"id": 3, "name": "必读文件未读→先追问", "goal": "基于已有资料写一份传播方案", "settings": {}, "attachments": []},
    {"id": 4, "name": "研究前置门禁", "goal": "写一份竞品分析方案", "settings": {}, "attachments": []},
    {"id": 5, "name": "版本规则", "goal": "把方案更新到 V2 版本", "settings": {}, "attachments": []},
    {"id": 6, "name": "结构校验拒稿→骨架补全", "goal": "写一份投放策略方案", "settings": {}, "attachments": []},
    {"id": 7, "name": "重试耗尽 run_failed", "goal": "写一份年度营销方案", "settings": {}, "attachments": [], "fault": {"tools": ["web_search", "http_request", "extract_web_content", "fetch_web_content", "fetch_platform_search"], "mode": "retryable"}},
    {"id": 8, "name": "附件引用", "goal": "参考我上传的附件写一份推广方案", "settings": {}, "attachments": [{"filename": "星野气泡水-夏季新品推广简报.md", "content": SCENARIO_8_ATTACHMENT_MD}]},
    {"id": 9, "name": "质检闭环", "goal": "写一份完整的品牌营销方案", "settings": {"quality_review_max_rounds": 2}, "attachments": []},
    {"id": 10, "name": "计费/usage", "goal": "写一份简短的营销方案", "settings": {}, "attachments": []},
]

# 测试可注入 pytest 的 async_sessionmaker；CLI 路径留空，由脚本自建 test DB。
_session_factory_override = None
_script_session_factory = None


# --------------------------------------------------------------------------- #
# DB setup（照抄 tests/conftest.py 的 test_engine / test_db 连接方式）
# --------------------------------------------------------------------------- #
async def _build_script_session_factory():
    from urllib.parse import urlparse, urlunparse

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import app.models  # noqa: F401  注册全部 ORM 表
    import app.models.points  # noqa: F401
    from app.db.seed import seed_rbac
    from app.models.base import Base

    settings = get_settings()
    database_url = settings.test_database_url or settings.database_url
    parsed = urlparse(database_url)
    db_name = parsed.path.lstrip("/")
    admin_url = urlunparse(parsed._replace(path="/postgres"))

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            found = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db"), {"db": db_name}
            )
            if found.fetchone() is None:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await admin_engine.dispose()

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await seed_rbac(session)
        await session.commit()

    if settings.test_database_url and settings.test_database_url != settings.database_url:
        from scripts.diff_seed import seed_workflow_docs

        stats = await seed_workflow_docs(factory, settings.database_url)
        logger.info(
            "workflow docs seeded: folders %s/%s files %s/%s",
            stats["folders_inserted"],
            stats["folders_total"],
            stats["files_inserted"],
            stats["files_total"],
        )
    return factory


async def _get_session_factory():
    global _script_session_factory
    if _session_factory_override is not None:
        return _session_factory_override
    if _script_session_factory is None:
        _script_session_factory = await _build_script_session_factory()
    return _script_session_factory


# --------------------------------------------------------------------------- #
# 回放确定性 web 桩 + 场景级故障注入（脚本层 monkeypatch，不改 app/**）
# --------------------------------------------------------------------------- #
def _replay_enabled(explicit: bool | None) -> bool:
    """显式 replay 优先；否则以 LANGGRAPH_DIFF_REPLAY 环境变量为准。"""
    if explicit is not None:
        return explicit
    return bool(os.environ.get("LANGGRAPH_DIFF_REPLAY"))


def _replay_stub_result(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    stub = copy.deepcopy(REPLAY_WEB_STUB_PAYLOADS[action_type])
    if action_type == "fetch_platform_search":
        return {
            "platform": str(payload.get("platform", "")),
            "keyword": str(payload.get("keyword", "")),
            **stub,
        }
    return stub


@contextmanager
def _replay_web_stubs() -> Iterator[None]:
    """把非确定性 web 工具替换为固定返回；退出时恢复原方法。"""
    from app.services.agent.tool_executor import ToolExecutor

    saved: dict[str, Any] = {}
    for action_type, method_name in WEB_ACTION_METHODS.items():
        if method_name in saved:
            continue
        saved[method_name] = getattr(ToolExecutor, method_name)

        def _make_stub(_action_type: str):
            async def _stub(self, payload, *_args, **_kwargs):
                return _replay_stub_result(_action_type, payload or {})

            return _stub

        setattr(ToolExecutor, method_name, _make_stub(action_type))
    try:
        yield
    finally:
        for method_name, method in saved.items():
            setattr(ToolExecutor, method_name, method)


@contextmanager
def _fault_injection(fault: dict | None) -> Iterator[None]:
    """场景级确定性故障：被注入工具每次 execute 都抛 RetryableToolError。

    fault 形如 {"tool": "web_search", "mode": "retryable"}；录制与回放均生效。
    """
    if not fault:
        yield
        return
    raw_tools = fault.get("tools")
    if raw_tools is None:
        raw_tools = [fault.get("tool")] if fault.get("tool") else []
    tools = {str(item) for item in raw_tools if item}
    mode = str(fault.get("mode") or "")
    if not tools:
        raise ValueError("场景 fault 配置缺少 tool/tools 字段")
    if mode != "retryable":
        raise ValueError(f"不支持的故障注入 mode={mode!r}（当前仅支持 'retryable'）")

    from app.services.agent.tool_executor import RetryableToolError, ToolExecutor

    original_execute = ToolExecutor.execute

    async def _faulted_execute(self, action, *args, **kwargs):
        if action.get("type") in tools:
            raise RetryableToolError(f"injected_retryable_fault: {action.get('type')}")
        return await original_execute(self, action, *args, **kwargs)

    ToolExecutor.execute = _faulted_execute
    try:
        yield
    finally:
        ToolExecutor.execute = original_execute


# --------------------------------------------------------------------------- #
# 场景运行
# --------------------------------------------------------------------------- #
@contextmanager
def _scenario_settings(overrides: dict) -> Iterator[None]:
    """临时覆盖 settings 属性。

    注意：app 模块（loop/tool_executor）在 import 时持有 settings 对象的引用；
    若进程内有人调用过 `get_settings.cache_clear()`（例如 test_alembic_config.py），
    `get_settings()` 会返回新对象，只 patch 它会打不中模块持有的旧对象。因此这里
    同时 patch 模块级 settings 引用，保证覆盖对真实执行路径生效。
    """
    settings = get_settings()
    targets = [settings]
    for module_name in ("app.services.agent.loop", "app.services.agent.tool_executor"):
        module = sys.modules.get(module_name)
        module_settings = getattr(module, "settings", None) if module is not None else None
        if module_settings is not None and module_settings is not settings:
            targets.append(module_settings)

    saved: list[tuple[Any, str, Any]] = []
    for key, value in overrides.items():
        if not hasattr(settings, key):
            raise KeyError(f"scenario settings 中存在未知配置项: {key}")
        for target in targets:
            saved.append((target, key, getattr(target, key)))
            setattr(target, key, value)
    try:
        yield
    finally:
        for target, key, value in saved:
            setattr(target, key, value)


async def _create_attachments(session, owner_user_id, session_id, specs: list) -> list[uuid.UUID]:
    from app.models.agent import AgentAttachment

    settings = get_settings()
    attachment_ids: list[uuid.UUID] = []
    for spec in specs:
        if not isinstance(spec, dict):
            raise ValueError(
                f"场景附件必须为 {{'filename': ..., 'content': ...}} 字典；"
                f"当前为占位符 {spec!r}，录制前请替换为真实附件内容"
            )
        filename = str(spec["filename"])
        content = str(spec["content"])
        attachment_id = uuid.uuid4()
        storage_path = Path(settings.agent_storage_root) / "attachments" / attachment_id.hex
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_text(content, encoding="utf-8")
        session.add(
            AgentAttachment(
                id=attachment_id,
                owner_user_id=owner_user_id,
                session_id=session_id,
                storage_key=str(storage_path),
                filename=filename,
                original_filename=filename,
                media_type=str(spec.get("media_type", "text/markdown")),
                size_bytes=len(content.encode("utf-8")),
                sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                extraction_status="ready",
                extracted_text=content,
                expires_at=datetime.now(UTC) + timedelta(days=90),
            )
        )
        await session.flush()
        attachment_ids.append(attachment_id)
    return attachment_ids


async def _setup_run(factory, scenario: dict) -> uuid.UUID:
    from argon2 import PasswordHasher

    from app.models.agent import AgentSession
    from app.models.rbac import User
    from app.repositories.agent_repository import AgentRepository
    from app.services.points import get_or_create_points

    ph = PasswordHasher()
    async with factory() as session:
        user = User(
            username=f"langgraph_diff_{uuid.uuid4().hex[:10]}",
            display_name="LangGraph Differential",
            password_hash=ph.hash("Diff1234"),
        )
        session.add(user)
        await session.flush()
        # 预置初始积分：与生产注册流程一致，否则成功 run 的扣费必然 InsufficientPointsError
        await get_or_create_points(session, user.id)

        agent_session = AgentSession(
            owner_user_id=user.id, title=f"diff-scenario-{scenario['id']}"
        )
        session.add(agent_session)
        await session.flush()

        attachment_ids = await _create_attachments(
            session, user.id, agent_session.id, list(scenario.get("attachments") or [])
        )
        repo = AgentRepository(session)
        run, _attempt, _event = await repo.create_run_with_attempt(
            agent_session,
            str(scenario["goal"]),
            True,
            attachment_ids,
            str(scenario.get("mode", "expert")),
        )
        await session.commit()
        return run.id


async def _run_status(factory, run_id: uuid.UUID) -> str | None:
    from app.models.agent import AgentRun

    async with factory() as session:
        return await session.scalar(select(AgentRun.status).where(AgentRun.id == run_id))


async def _cleanup_stale_diff_runs(factory) -> int:
    """清理遗留的 diff-scenario-% 未终态 attempt/run（T5 踩坑：上一条 queued attempt 会被下一条 claim）。

    严格限定 session.title LIKE 'diff-scenario-%'，不碰其他 run。
    """
    from app.models.agent import AgentRun, AgentRunAttempt, AgentSession

    now = datetime.now(UTC)
    async with factory() as session:
        stale_ids = list(
            (
                await session.scalars(
                    select(AgentRun.id)
                    .join(AgentSession, AgentSession.id == AgentRun.session_id)
                    .where(
                        AgentSession.title.like(f"{SCENARIO_SESSION_TITLE_PREFIX}%"),
                        AgentRun.status.not_in(list(TERMINAL_RUN_STATUSES)),
                    )
                )
            ).all()
        )
        if not stale_ids:
            return 0
        await session.execute(
            update(AgentRunAttempt)
            .where(
                AgentRunAttempt.run_id.in_(stale_ids),
                AgentRunAttempt.status.in_(["queued", "running"]),
            )
            .values(
                status="failed",
                failure_code="stale_cleanup",
                finished_at=now,
                updated_at=now,
            )
        )
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id.in_(stale_ids))
            .values(status="failed", updated_at=now)
        )
        await session.commit()
    logger.info("cleaned %s stale diff run(s): %s", len(stale_ids), stale_ids)
    return len(stale_ids)


async def _claim_run(factory, run_id: uuid.UUID) -> uuid.UUID | None:
    """claim 该 run 的下一个 attempt；等待 retry 退避窗口，run 已终态时返回 None。"""
    from app.repositories.agent_repository import AgentRepository

    deadline = time.monotonic() + _CLAIM_WAIT_TIMEOUT_SECONDS
    while True:
        async with factory() as session:
            repo = AgentRepository(session)
            claimed = await repo.claim_next_attempt(WORKER_ID)
            await session.commit()

        if claimed is not None:
            if claimed.run_id != run_id:
                raise RuntimeError(
                    f"claim_next_attempt 抢到了陈旧 attempt {claimed.id}（run={claimed.run_id}），"
                    f"期望 run={run_id}；_cleanup_stale_diff_runs 未生效？"
                )
            return claimed.id

        status = await _run_status(factory, run_id)
        if status not in CLAIMABLE_RUN_STATUSES:
            return None
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"等待 run={run_id} 的 attempt 可 claim 超时（status={status}）"
            )
        await asyncio.sleep(_CLAIM_POLL_SECONDS)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "<duration>"
                if key == DURATION_KEY and isinstance(item, (int, float))
                else _canonical_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    return value


def _canonical_event(event, ordinal: int) -> dict:
    return {
        "seq": ordinal + 1,
        "id": str(event.id),
        "run_id": str(event.run_id),
        "attempt_id": str(event.attempt_id) if event.attempt_id is not None else None,
        "event_type": event.event_type,
        "payload": _canonical_value(event.payload or {}),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def run_scenario(
    scenario: dict,
    *,
    graph: bool,
    recorder: LlmRecorder | None,
    replay: bool | None = None,
) -> list[dict]:
    """真实 test DB 跑该 run 的全部 attempt，返回全量事件（list[dict]）。

    循环 claim/process 直到 run 进入终态（succeeded/failed/cancelled）、
    awaiting_question 等不可 claim 状态，或达到 MAX_ATTEMPTS_PER_RUN。

    replay=True（或设置 LANGGRAPH_DIFF_REPLAY）时替换非确定性 web 工具；
    scenario["fault"] 存在时注入确定性可重试故障（录制/回放均生效）。
    """
    factory = await _get_session_factory()

    from app.repositories.agent_repository import AgentRepository
    from app.services.agent import loop as loop_module
    from app.services.agent import tool_executor as tool_module

    previous_loop_factory = loop_module.async_session_factory
    previous_tool_factory = tool_module.async_session_factory
    loop_module.async_session_factory = factory
    tool_module.async_session_factory = factory
    replay_ctx = _replay_web_stubs() if _replay_enabled(replay) else nullcontext()
    try:
        with replay_ctx, _fault_injection(scenario.get("fault")):
            with _scenario_settings(dict(scenario.get("settings") or {})):
                await _cleanup_stale_diff_runs(factory)
                run_id = await _setup_run(factory, scenario)

                from app.services.agent.llm_recorder import reset_shared_recorders

                reset_shared_recorders()
                service = AgentLoopService()
                service.langgraph_enabled = graph
                if recorder is not None:
                    service.llm_client._recorder = recorder
                try:
                    for _ in range(MAX_ATTEMPTS_PER_RUN):
                        status = await _run_status(factory, run_id)
                        if status not in CLAIMABLE_RUN_STATUSES:
                            break
                        claim_id = await _claim_run(factory, run_id)
                        if claim_id is None:
                            break
                        try:
                            await service.process_attempt(claim_id, WORKER_ID)
                        except Exception:
                            logger.exception(
                                "process_attempt 抛错（run=%s attempt=%s）", run_id, claim_id
                            )
                            if await _run_status(factory, run_id) not in TERMINAL_RUN_STATUSES:
                                raise
                finally:
                    close = getattr(service.llm_client, "close", None)
                    if close is not None:
                        await close()

                async with factory() as session:
                    events = await AgentRepository(session).list_events(run_id)
                    return [_canonical_event(event, index) for index, event in enumerate(events)]
    finally:
        loop_module.async_session_factory = previous_loop_factory
        tool_module.async_session_factory = previous_tool_factory


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_selection(value: str) -> list[dict]:
    if value == "all":
        return list(SCENARIOS)
    try:
        scenario_id = int(value)
    except ValueError as exc:
        raise SystemExit(f"--record/--diff 只接受场景 id 或 all，收到: {value!r}") from exc
    for scenario in SCENARIOS:
        if scenario["id"] == scenario_id:
            return [scenario]
    raise SystemExit(f"未知场景 id {scenario_id}（有效范围 1..{len(SCENARIOS)}）")


def _fixture_path(scenario: dict) -> Path:
    return FIXTURE_DIR / f"scenario-{scenario['id']}.json"


async def _record(selection: str) -> None:
    for scenario in _parse_selection(selection):
        fixture = _fixture_path(scenario)
        os.environ["LANGGRAPH_DIFF_RECORD"] = str(fixture)
        os.environ.pop("LANGGRAPH_DIFF_REPLAY", None)
        try:
            events = await run_scenario(scenario, graph=False, recorder=None, replay=False)
        finally:
            os.environ.pop("LANGGRAPH_DIFF_RECORD", None)
        if not fixture.is_file():
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text(
                json.dumps({"scenario": fixture.stem, "calls": []}, ensure_ascii=False),
                encoding="utf-8",
            )
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        print(
            f"[record] scenario {scenario['id']} {scenario['name']}: "
            f"events={len(events)} llm_calls={len(payload.get('calls', []))} -> {fixture}"
        )


async def _diff(selection: str, report_path: Path) -> None:
    sections: list[str] = []
    clean = True
    for scenario in _parse_selection(selection):
        fixture = _fixture_path(scenario)
        if not fixture.is_file():
            raise SystemExit(
                f"fixture 不存在: {fixture}；请先运行 --record {scenario['id']}"
            )
        os.environ["LANGGRAPH_DIFF_REPLAY"] = str(fixture)
        os.environ.pop("LANGGRAPH_DIFF_RECORD", None)
        try:
            old_events = await run_scenario(scenario, graph=False, recorder=None, replay=True)
            graph_events = await run_scenario(scenario, graph=True, recorder=None, replay=True)
        finally:
            os.environ.pop("LANGGRAPH_DIFF_REPLAY", None)

        diffs = diff_normalized(old_events, graph_events)
        clean = clean and not diffs
        sections.append(_format_scenario_report(scenario, old_events, graph_events, diffs))
        print(
            f"[diff] scenario {scenario['id']} {scenario['name']}: "
            f"old={len(old_events)} graph={len(graph_events)} diffs={len(diffs)}"
        )

    _append_report(report_path, "\n".join(sections))
    print(f"[diff] report -> {report_path}")
    if not clean:
        raise SystemExit(1)


def _format_scenario_report(
    scenario: dict, old_events: list[dict], graph_events: list[dict], diffs: list[str]
) -> str:
    lines = [
        f"## 场景 {scenario['id']}: {scenario['name']}",
        "",
        f"- goal: `{scenario['goal']}`",
        f"- 旧轨事件数: {len(old_events)}",
        f"- 图轨事件数: {len(graph_events)}",
    ]
    if diffs:
        lines.append(f"- 结果: FAIL（{len(diffs)} 处差异）")
        lines.extend(["", "```", *diffs[:50]])
        if len(diffs) > 50:
            lines.append(f"... 其余 {len(diffs) - 50} 条差异已省略")
        lines.append("```")
    else:
        lines.append("- 结果: PASS（0 差异）")
    lines.append("")
    return "\n".join(lines)


def _append_report(report_path: Path, body: str) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    first_write = not report_path.exists()
    with report_path.open("a", encoding="utf-8") as fh:
        if first_write:
            fh.write("# LangGraph 差分校准报告\n\n")
            fh.write("## 归一化规则（event_normalize.NORMALIZATION_RULES）\n\n")
            for rule in NORMALIZATION_RULES:
                fh.write(f"- {rule}\n")
            fh.write("\n### 驱动层额外归一化（run_scenario 采集时应用）\n\n")
            fh.write("- `seq` → 该 run 内的 1-based 序号（DB sequence 为全局序列，非 run 内序号）\n")
            fh.write("- payload 中 `step_duration_seconds`（数值）→ `<duration>`（墙钟耗时，两次运行必不相同）\n\n")
            fh.write("### 回放期确定性 web 工具桩（仅 --diff 生效）\n\n")
            fh.write("真实网络/渲染器结果不可复现，回放时下列工具被替换为固定返回，避免与轨道无关的假差异：\n\n")
            for action_type, stub in REPLAY_WEB_STUB_PAYLOADS.items():
                if action_type == "fetch_platform_search":
                    stub = {"platform": "<input.platform>", "keyword": "<input.keyword>", **stub}
                fh.write(f"- `{action_type}` → `{json.dumps(stub, ensure_ascii=False)}`\n")
            fh.write("\nDB/文件类工具（read_file/write_file/edit_file/list_files）保持真实执行；`--record` 不替换。\n\n")
            fh.write("### 场景级确定性故障注入\n\n")
            fh.write(
                "- 场景配置 `fault: {\"tool\"|\"tools\": ..., \"mode\": \"retryable\"}` 时，命中工具每次执行都抛 "
                "`RetryableToolError`；录制与回放均生效（脚本层 monkeypatch，不改 app/**）。\n"
            )

            def _fault_label(s: dict) -> str:
                fault = s["fault"]
                tools = fault.get("tools") or ([fault.get("tool")] if fault.get("tool") else [])
                return "/".join(str(t) for t in tools if t)

            faulted = [f"场景 {s['id']}（`{_fault_label(s)}`）" for s in SCENARIOS if s.get("fault")]
            fh.write(f"- 当前启用注入的场景：{'、'.join(faulted) if faulted else '无'}。\n\n")
        fh.write(body)


def _print_web_override_hint() -> None:
    raw = os.environ.get("WEB_TOOL_ALLOW_NON_GLOBAL_TARGETS", "")
    if raw.strip().lower() in {"1", "true", "yes", "on"}:
        print(
            "[env] WEB_TOOL_ALLOW_NON_GLOBAL_TARGETS 已启用："
            "web 工具将放行非公网解析（仅本地录制/差分；脚本不自行设置该变量）"
        )


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", default=None, help="录制场景 id 或 all（旧轨 + 真实 LLM）")
    parser.add_argument("--diff", default=None, help="回放差分场景 id 或 all")
    parser.add_argument("--report", default=str(REPORT_PATH), help="报告输出路径")
    args = parser.parse_args()

    _print_web_override_hint()
    if args.record:
        asyncio.run(_record(args.record))
    elif args.diff:
        asyncio.run(_diff(args.diff, Path(args.report)))
    else:
        parser.error("需要 --record <id|all> 或 --diff <id|all>")


if __name__ == "__main__":
    main()
