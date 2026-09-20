"""平台级方案生产线：LangGraph 状态机定义。

编排层（本模块）与执行层（`app.services.dsh.executor`）分离：任务链负责阶段顺序、
重试与数据一致性，DSH 只负责把单个子任务跑完。
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

STAGES = (
    "collect_input",
    "research_agenda",
    "run_research",
    "draft_plan",
    "review_gate",
    "polish",
    "deliver",
    "bill",
)


class ChainState(TypedDict, total=False):
    """任务链状态：每个字段独立通道（last-value-wins），节点只返回自己更新的键。"""

    chain_id: str
    brief: str
    agenda: list[str]
    research: list[str]
    draft: str
    draft_round: int
    review_pass: bool
    review_issues: list[str]
    final_markdown: str
    result_file_id: str
    billed_tokens: int
    billed_points: int


def build_chain_graph(service):
    """按 service 的节点实现编译任务链图。"""
    graph = StateGraph(ChainState)
    graph.add_node("collect_input", service._stage_collect_input)
    graph.add_node("research_agenda", service._stage_research_agenda)
    graph.add_node("run_research", service._stage_run_research)
    graph.add_node("draft_plan", service._stage_draft_plan)
    graph.add_node("review_gate", service._stage_review_gate)
    graph.add_node("polish", service._stage_polish)
    graph.add_node("deliver", service._stage_deliver)
    graph.add_node("bill", service._stage_bill)

    graph.add_edge(START, "collect_input")
    graph.add_edge("collect_input", "research_agenda")
    graph.add_edge("research_agenda", "run_research")
    graph.add_edge("run_research", "draft_plan")
    graph.add_edge("draft_plan", "review_gate")
    graph.add_conditional_edges(
        "review_gate",
        service._route_after_review,
        {"draft": "draft_plan", "polish": "polish"},
    )
    graph.add_edge("polish", "deliver")
    graph.add_edge("deliver", "bill")
    graph.add_edge("bill", END)
    return graph.compile()
