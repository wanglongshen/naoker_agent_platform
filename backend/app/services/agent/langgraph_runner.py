from __future__ import annotations

from typing import Annotated, Any, TypedDict


class WorkflowState(TypedDict, total=False):
    instruction: str
    rules: Any
    stage: str
    stages_done: list[str]
    task_type: str | None
    admission: str | None
    stage_actions: int
    research_ok: bool
    save_ok: bool
    version_rule: Any
    version_number: str | None
    saved_files: list[str]
    required_source_paths: list[str]
    read_receipts: list[dict[str, Any]]
    save_receipts: list[dict[str, Any]]
    verified_save_receipts: list[dict[str, Any]]
    blueprint_receipt: dict[str, Any] | None
    dependency_receipts: list[dict[str, Any]]
    material_inventory_done: bool
    quality_review_rounds: int
    pending_review_hint: str | None
    observation_history: list[str]
    platform_samples: dict[str, int]
    platform_sample_urls: dict[str, set[str]]
    platform_waived: set[str]
    hung_from_stage: str | None


class AttemptCtx(TypedDict, total=False):
    project_name: str
    blueprint_injected: bool
    skeleton_injected: bool
    researched: bool
    skeleton: str
    blueprint_full: str
    llm_tokens: int


class GraphState(TypedDict, total=False):
    workflow: Annotated[dict, "last"]
    attempt_ctx: Annotated[dict, "last"]
    step_index: Annotated[int, "last"]
    previous_observation: Annotated[dict | None, "last"]
    wrote_file: Annotated[bool, "last"]
    step_journal: Annotated[list[str], "last"]
    web_enabled: Annotated[bool, "last"]
    effective_max_steps: Annotated[int, "last"]
    session_history: Annotated[list[dict[str, str]], "last"]
    attachments: Annotated[list[dict[str, Any]], "last"]
    terminal: Annotated[dict | None, "last"]
    pending_action: Annotated[dict | None, "last"]
    pre_generated_thought: Annotated[str | None, "last"]
    _gate_retry: Annotated[bool, "last"]
    _retryable: Annotated[bool, "last"]
    step_duration_seconds: Annotated[float, "last"]


def build_state() -> dict:
    return {
        "workflow": {},
        "attempt_ctx": {},
        "step_index": 0,
        "previous_observation": None,
        "wrote_file": False,
        "step_journal": [],
        "web_enabled": True,
        "effective_max_steps": 0,
        "session_history": [],
        "attachments": [],
        "terminal": None,
        "pending_action": None,
        "pre_generated_thought": None,
        "_gate_retry": False,
        "_retryable": False,
        "step_duration_seconds": 0.0,
    }


_WF_FIELDS = (
    "instruction", "rules", "stage", "stages_done", "task_type", "admission",
    "stage_actions", "research_ok", "save_ok", "version_rule", "version_number",
    "saved_files", "required_source_paths", "read_receipts", "save_receipts",
    "verified_save_receipts", "blueprint_receipt", "dependency_receipts",
    "material_inventory_done", "quality_review_rounds", "pending_review_hint",
    "observation_history", "platform_samples", "platform_sample_urls",
    "platform_waived", "hung_from_stage",
)

CTX_FIELDS = (
    "project_name", "blueprint_injected", "skeleton_injected", "researched",
    "skeleton", "blueprint_full", "llm_tokens",
)


def workflow_to_state(st, attempt_ctx) -> dict:
    wf = {k: getattr(st, k) for k in _WF_FIELDS if hasattr(st, k)}
    ctx = {k: attempt_ctx.get(k) for k in CTX_FIELDS if k in attempt_ctx}
    return {"workflow": wf, "attempt_ctx": ctx}


def route_after_plan(graph_state: dict) -> str:
    if graph_state.get("_gate_retry") or graph_state.get("_retryable"):
        return "end"
    if graph_state.get("terminal") is not None:
        return "end"
    return "execute"


def route_after_execute(graph_state: dict) -> str:
    action = graph_state.get("pending_action") or {}
    return "finalize" if (action.get("action") or {}).get("type") == "finish" else "end"


class LangGraphRunner:
    def __init__(self, service, repo, ctx, owner_user_id=None, is_super_admin=False):
        self.service = service
        self.repo = repo
        self.ctx = ctx
        self.owner_user_id = owner_user_id
        self.is_super_admin = is_super_admin

    async def _node_plan(self, graph_state: dict) -> dict:
        runtime = {"service": self.service, "repo": self.repo, "ctx": self.ctx,
                   "owner_user_id": self.owner_user_id, "is_super_admin": self.is_super_admin}
        return await self.service._do_node_plan(graph_state, runtime)

    async def _node_execute(self, graph_state: dict) -> dict:
        runtime = {"service": self.service, "repo": self.repo, "ctx": self.ctx,
                   "owner_user_id": self.owner_user_id, "is_super_admin": self.is_super_admin}
        return await self.service._do_node_execute(graph_state, runtime)

    async def _node_finalize(self, graph_state: dict) -> dict:
        runtime = {"service": self.service, "repo": self.repo, "ctx": self.ctx,
                   "owner_user_id": self.owner_user_id, "is_super_admin": self.is_super_admin}
        return await self.service._do_node_finalize(graph_state, runtime)

    def compile(self):
        from langgraph.graph import StateGraph, START, END
        builder = StateGraph(GraphState)
        builder.add_node("plan", self._node_plan)
        builder.add_node("execute", self._node_execute)
        builder.add_node("finalize", self._node_finalize)
        builder.add_edge(START, "plan")
        builder.add_conditional_edges(
            "plan", route_after_plan,
            {"execute": "execute", "end": END},
        )
        builder.add_conditional_edges(
            "execute", route_after_execute,
            {"finalize": "finalize", "end": END},
        )
        builder.add_edge("finalize", END)
        return builder.compile()


def diff_event_streams(old: list[dict], new: list[dict]) -> list[str]:
    diffs = []
    n = max(len(old), len(new))
    for i in range(n):
        if i >= len(old):
            diffs.append(f"[+only-new @{i}] {new[i]}")
        elif i >= len(new):
            diffs.append(f"[-only-old @{i}] {old[i]}")
        else:
            o, n_ = old[i], new[i]
            if o != n_:
                diffs.append(f"[diff @{i}] old={o} new={n_}")
    return diffs
