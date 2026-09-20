"""任务链服务：8 个阶段的实现与落库。

阶段语义（与设计一致）：collect_input → research_agenda → run_research（并行 DSH 子任务）
→ draft_plan（DSH 子任务）→ review_gate（结构 + 质检校验，未过回 draft_plan，最多
review_max_rounds 轮）→ polish（DSH 修订）→ deliver（落 file_objects）→ bill（积分扣减）。

依赖全部可注入（executor / llm / file_repo / points / instance_manager），便于测试用
fake 替换；生产路径由惰性属性提供默认实现。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.core.config import get_settings
from app.repositories.file_repository import FileRepository
from app.repositories.task_chain_repository import TaskChainRepository
from app.services.agent.plan_structure import DEFAULT_MODULES, build_plan_summary, quality_check, validate_plan_structure
from app.services.dsh.usage import collect_dsh_usage
from app.services.file_service import _resolve_storage_path
from app.services.task_chain.graph import STAGES, build_chain_graph

logger = logging.getLogger("task_chain.service")

RESEARCH_FALLBACK = ("行业趋势与市场机会", "竞品投放策略", "平台规则与合规要点")


class ExecutorLike(Protocol):
    async def run(self, *, user_id: uuid.UUID, task: str, timeout_seconds: float | None = None, home_dir: Any = None): ...


class LlmLike(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


class TaskChainService:
    """单条任务链的执行者；一个实例服务一条链（含其 DB session）。"""

    review_max_rounds = 2

    def __init__(
        self,
        repo: TaskChainRepository,
        *,
        executor: ExecutorLike | None = None,
        llm: LlmLike | None = None,
        file_repo: FileRepository | None = None,
        points: Any | None = None,
        instance_manager: Any | None = None,
    ) -> None:
        self.repo = repo
        self.db = repo.db
        self._executor = executor
        self._llm = llm
        self._file_repo = file_repo
        self._points = points
        self._manager = instance_manager
        self.settings = get_settings()

    # ---------- 惰性依赖 ----------

    @property
    def executor(self) -> ExecutorLike:
        if self._executor is None:
            from app.services.dsh.executor import DshTaskExecutor

            self._executor = DshTaskExecutor()
        return self._executor

    @property
    def llm(self) -> LlmLike:
        if self._llm is None:
            from app.services.agent.llm import DeepSeekClient

            self._llm = DeepSeekClient()
        return self._llm

    @property
    def file_repo(self) -> FileRepository:
        if self._file_repo is None:
            self._file_repo = FileRepository(self.db)
        return self._file_repo

    @property
    def points(self) -> Any:
        if self._points is None:
            from app.services import points as points_module

            self._points = points_module
        return self._points

    @property
    def manager(self) -> Any:
        if self._manager is None:
            from app.services.dsh import get_manager

            self._manager = get_manager()
        return self._manager

    # ---------- 入口 ----------

    async def run_chain(self, chain_id: uuid.UUID) -> None:
        chain = await self.repo.get_chain(chain_id)
        if chain is None:
            raise ValueError(f"task chain not found: {chain_id}")
        await self.repo.set_chain_status(chain_id, "running", started_at=datetime.now(UTC))
        try:
            await build_chain_graph(self).ainvoke({"chain_id": str(chain_id)})
        except Exception as exc:  # noqa: BLE001 - 链级失败必须落库后不外抛
            logger.exception("task chain failed chain=%s", chain_id)
            await self.repo.set_chain_status(
                chain_id,
                "failed",
                error=str(exc)[:500],
                finished_at=datetime.now(UTC),
            )
            return
        await self.repo.set_chain_status(chain_id, "succeeded", finished_at=datetime.now(UTC))

    # ---------- 内部工具 ----------

    async def _chain(self, state: dict) -> Any:
        chain = await self.repo.get_chain(uuid.UUID(state["chain_id"]))
        if chain is None:
            raise ValueError("task chain missing")
        return chain

    async def _begin(self, chain: Any, stage_name: str) -> Any:
        seq = len(await self.repo.list_stages(chain.id)) + 1
        stage = await self.repo.add_stage(chain.id, stage_name, seq)
        await self.repo.update_stage(stage.id, status="running", started_at=datetime.now(UTC))
        await self.repo.set_chain_status(chain.id, chain.status, current_stage=stage_name)
        return stage

    async def _finish(self, stage: Any, *, output_payload: dict | None = None, tokens: int = 0) -> None:
        await self.repo.update_stage(
            stage.id,
            status="succeeded",
            output_payload=output_payload or {},
            tokens=tokens,
            finished_at=datetime.now(UTC),
        )

    async def _fail_stage(self, stage: Any, message: str) -> None:
        await self.repo.update_stage(
            stage.id,
            status="failed",
            error=message[:500],
            finished_at=datetime.now(UTC),
        )

    async def _refresh_injection(self, user_id: uuid.UUID) -> None:
        try:
            await self.manager.refresh_injection(user_id, self.db)
        except Exception:  # noqa: BLE001 - 注入失败只影响平台工具，不阻塞子任务
            logger.exception("refresh_injection failed user=%s", user_id)

    async def _run_subtask(self, user_id: uuid.UUID, task: str) -> str | None:
        result = await self.executor.run(
            user_id=user_id, task=task, home_dir=self._headless_home(user_id)
        )
        if result.exit_code == 0 and result.final_text:
            return result.final_text
        logger.warning("dsh subtask failed user=%s code=%s", user_id, result.exit_code)
        return None

    def _headless_home(self, user_id: uuid.UUID) -> Path:
        """任务链 headless 子任务的独立 DSH_HOME（与 Web 实例隔离，A8）。"""
        return self.settings.dsh_home_root_path / f"{user_id}-headless"

    def _blueprint_block(self, chain: Any) -> str:
        blueprint = (chain.input_payload or {}).get("blueprint")
        if not blueprint:
            return ""
        summary = build_plan_summary(str(blueprint))
        return f"\n蓝图摘要：\n{summary}\n" if summary else ""

    def _modules(self, chain: Any) -> list[str]:
        modules = (chain.input_payload or {}).get("modules")
        if isinstance(modules, list) and modules:
            return [str(m) for m in modules]
        return list(DEFAULT_MODULES)

    # ---------- 节点 ----------

    async def _stage_collect_input(self, state: dict) -> dict:
        chain = await self._chain(state)
        stage = await self._begin(chain, "collect_input")
        payload = dict(chain.input_payload or {})
        parts = [f"任务目标：{chain.goal}"]
        for key, label in (("brand", "品牌"), ("product", "产品"), ("budget", "预算"), ("platforms", "投放平台")):
            if payload.get(key):
                parts.append(f"{label}：{payload[key]}")
        attachments = payload.get("attachment_texts") or []
        for index, text in enumerate(attachments, 1):
            parts.append(f"附件{index}节选：{str(text)[:2000]}")
        brief = "\n".join(parts)
        await self._finish(stage, output_payload={"brief": brief, "attachment_count": len(attachments)})
        return {"brief": brief}

    async def _stage_research_agenda(self, state: dict) -> dict:
        chain = await self._chain(state)
        stage = await self._begin(chain, "research_agenda")
        prompt = (
            "你是广告营销方案调研规划助手。基于下面的任务简报，输出 3-5 条调研清单，"
            "每条单独一行并以「- 」开头，聚焦行业趋势、竞品投放、平台规则、目标人群、预算分配。\n\n"
            f"{state['brief']}"
        )
        agenda: list[str] = []
        try:
            raw = await self.llm.complete([{"role": "user", "content": prompt}])
            agenda = [line.strip().lstrip("-").strip() for line in raw.splitlines() if line.strip().startswith("-")]
            agenda = [item for item in agenda if item][:5]
        except Exception:  # noqa: BLE001 - 规划失败回退固定清单
            logger.exception("research agenda llm failed chain=%s", chain.id)
        if not agenda:
            agenda = list(RESEARCH_FALLBACK)
        await self._finish(stage, output_payload={"agenda": agenda})
        return {"agenda": agenda}

    async def _stage_run_research(self, state: dict) -> dict:
        chain = await self._chain(state)
        stage = await self._begin(chain, "run_research")
        await self._refresh_injection(chain.user_id)
        agenda = list(state.get("agenda") or RESEARCH_FALLBACK)

        async def one(topic: str) -> str | None:
            task = (
                f"调研任务：{topic}\n背景简报：{state['brief']}\n"
                "请输出要点式调研结论（不超过 400 字），只讲可执行结论。"
            )
            for _attempt in (1, 2):
                text = await self._run_subtask(chain.user_id, task)
                if text:
                    return text
            return None

        results = await asyncio.gather(*(one(topic) for topic in agenda))
        texts = [item for item in results if item]
        if not texts:
            await self._fail_stage(stage, "all research subtasks failed")
            raise RuntimeError("all research subtasks failed")
        await self._finish(stage, output_payload={"topics": agenda, "results": texts})
        return {"research": texts}

    async def _stage_draft_plan(self, state: dict) -> dict:
        chain = await self._chain(state)
        stage = await self._begin(chain, "draft_plan")
        await self._refresh_injection(chain.user_id)
        round_no = int(state.get("draft_round") or 0) + 1
        issues = list(state.get("review_issues") or [])
        research_block = "\n\n".join(state.get("research") or [])
        task = (
            "请撰写一份广告营销方案，输出 Markdown，含清晰的小标题结构。\n"
            f"任务简报：\n{state['brief']}\n\n"
            f"调研结论：\n{research_block}\n"
            f"{self._blueprint_block(chain)}\n"
            "要求：结构完整、有预算数字与执行步骤、避免空洞套话。"
        )
        if issues:
            task += "\n上一轮评审问题（必须逐条修复）：\n" + "\n".join(f"- {item}" for item in issues)
        draft = await self._run_subtask(chain.user_id, task)
        if not draft:
            await self._fail_stage(stage, "draft subtask failed")
            raise RuntimeError("draft subtask failed")
        await self._finish(stage, output_payload={"round": round_no, "chars": len(draft)})
        return {"draft": draft, "draft_round": round_no}

    async def _stage_review_gate(self, state: dict) -> dict:
        chain = await self._chain(state)
        stage = await self._begin(chain, "review_gate")
        modules = self._modules(chain)
        draft = state.get("draft") or ""
        issues = list(validate_plan_structure(draft, modules)) + list(quality_check(draft, modules))
        passed = not issues
        await self._finish(stage, output_payload={"pass": passed, "issues": issues, "round": state.get("draft_round")})
        return {"review_pass": passed, "review_issues": issues}

    def _route_after_review(self, state: dict) -> str:
        if state.get("review_pass"):
            return "polish"
        if int(state.get("draft_round") or 0) < self.review_max_rounds:
            return "draft"
        return "polish"

    async def _stage_polish(self, state: dict) -> dict:
        chain = await self._chain(state)
        stage = await self._begin(chain, "polish")
        draft = state.get("draft") or ""
        issues = list(state.get("review_issues") or [])
        if not issues:
            await self._finish(stage, output_payload={"skipped": True})
            return {"final_markdown": draft}
        await self._refresh_injection(chain.user_id)
        task = (
            "请在保持既有结构的前提下，按下面的评审问题修订这份方案，"
            "直接输出修订后的完整 Markdown：\n"
            + "\n".join(f"- {item}" for item in issues)
            + f"\n\n方案原文：\n{draft}"
        )
        polished = await self._run_subtask(chain.user_id, task)
        final = polished or draft
        await self._finish(stage, output_payload={"used_draft_fallback": polished is None})
        return {"final_markdown": final}

    async def _stage_deliver(self, state: dict) -> dict:
        chain = await self._chain(state)
        stage = await self._begin(chain, "deliver")
        markdown = state.get("final_markdown") or state.get("draft") or ""
        content = markdown.encode("utf-8")
        file_id = uuid.uuid4()
        filename = f"方案_{datetime.now(UTC):%Y%m%d%H%M%S}.md"
        storage_path = _resolve_storage_path(chain.user_id, file_id)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(storage_path.write_bytes, content)
        file_obj = await self.file_repo.add_file(
            None,
            {
                "id": file_id,
                "owner_user_id": chain.user_id,
                "folder_id": None,
                "storage_key": storage_path.as_posix(),
                "filename": filename,
                "original_filename": filename,
                "media_type": "text/markdown",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "created_by": chain.user_id,
                "extracted_text": markdown[:50000],
                "preview_status": "ready",
            },
        )
        await self.repo.set_chain_status(
            chain.id,
            chain.status,
            result_file_id=file_obj.id,
            final_answer=markdown[:2000],
        )
        await self._finish(
            stage,
            output_payload={"file_id": str(file_obj.id), "filename": filename, "chars": len(markdown)},
        )
        return {"result_file_id": str(file_obj.id)}

    async def _stage_bill(self, state: dict) -> dict:
        chain = await self._chain(state)
        stage = await self._begin(chain, "bill")
        platform_tokens = int(state.get("llm_tokens") or 0)
        dsh_tokens = 0
        try:
            started_at = chain.started_at or chain.created_at
            if started_at is not None and started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            dsh_tokens = collect_dsh_usage(
                self._headless_home(chain.user_id),
                since=started_at.timestamp() if started_at is not None else 0.0,
                until=datetime.now(UTC).timestamp(),
            )
        except Exception:  # noqa: BLE001 - usage 采集失败按 0 处理，不阻断计费
            logger.exception("collect dsh usage failed chain=%s", chain.id)
        tokens = platform_tokens + int(dsh_tokens)
        if tokens <= 0:
            logger.warning("dsh usage empty chain=%s, fallback flat points", chain.id)
            tokens = int(self.settings.task_chain_flat_points) * int(self.settings.points_tokens_per_point)
        points_cost = 0
        try:
            points_cost = int(self.points.tokens_to_points(tokens))
            await self.points.deduct_for_run(self.db, chain.user_id, chain.id, tokens)
        except Exception:  # noqa: BLE001 - 计费失败不阻断交付
            logger.exception("deduct points failed chain=%s", chain.id)
        await self.repo.set_chain_status(chain.id, chain.status, total_tokens=tokens, points_cost=points_cost)
        await self._finish(
            stage,
            output_payload={
                "tokens": tokens,
                "points": points_cost,
                "platform_tokens": platform_tokens,
                "dsh_tokens": dsh_tokens,
            },
        )
        return {"billed_tokens": tokens, "billed_points": points_cost}

    # ---------- 对外只读 ----------

    def stages_expected_order(self) -> tuple[str, ...]:
        return STAGES
