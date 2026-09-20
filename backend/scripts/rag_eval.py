"""RAG 黄金测试集生成与评测 CLI。

用法（在 backend 目录下运行）：
    python -m scripts.rag_eval --generate-questions --per-doc 4
    python -m scripts.rag_eval --k 5 --report docs/rag-eval/report.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_PATH = Path("docs/rag-eval/report.md")
DEFAULT_K = 5
RECALL_TARGET = 0.90
P95_BUDGET_MS = 500.0
MAX_BODY_CHARS = 8000
PAGE_SIZE = 50

GENERATE_SYSTEM_PROMPT = (
    "你是知识库评测集构建助手。请根据给定文档内容，生成可由该文档直接回答的中文问题；"
    "问题要具体、自然、口语化，不要出现“本文”“该文档”等字样。"
    "只输出 JSON 字符串数组，不要输出任何解释。"
)


class LlmLike(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


@dataclass
class EvalReport:
    total: int
    hits: int
    recall: float
    p95_ms: float
    misses: list[dict]


def recall_at_k(hits: list[Any], expected_doc_ids: list[Any], k: int = 5) -> float:
    """前 k 个命中里任一 doc_id 命中 expected 即 1.0，否则 0.0。"""
    expected = {str(doc_id) for doc_id in (expected_doc_ids or [])}
    if not expected:
        return 0.0
    for hit in list(hits or [])[: max(0, k)]:
        if str(hit.doc_id) in expected:
            return 1.0
    return 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[min(rank, len(ordered) - 1)]


async def evaluate(repo: Any, service: Any, *, k: int = DEFAULT_K) -> EvalReport:
    questions = await repo.list_eval_questions()
    latencies: list[float] = []
    misses: list[dict] = []
    hit_count = 0

    for question in questions:
        started = time.perf_counter()
        hits = await service.search(question.query, top_k=k)
        latencies.append((time.perf_counter() - started) * 1000)
        expected = list(question.expected_doc_ids or [])
        if recall_at_k(hits, expected, k) == 1.0:
            hit_count += 1
            continue
        misses.append(
            {
                "query": question.query,
                "expected_doc_ids": [str(doc_id) for doc_id in expected],
                "actual_doc_ids": [str(hit.doc_id) for hit in hits],
                "actual_titles": [hit.title for hit in hits],
            }
        )

    total = len(questions)
    return EvalReport(
        total=total,
        hits=hit_count,
        recall=(hit_count / total) if total else 0.0,
        p95_ms=round(_percentile(latencies, 0.95), 2),
        misses=misses,
    )


def parse_questions(text: str) -> list[str]:
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    questions: list[str] = []
    for line in raw.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.、)])\s*", "", line).strip()
        if cleaned:
            questions.append(cleaned)
    return questions


def _document_text(chunks: list[Any]) -> str:
    parts = [getattr(chunk, "content", "") or "" for chunk in chunks]
    return "\n\n".join(part for part in parts if part.strip())


def _document_body(doc: Any, chunks: list[Any]) -> str:
    return _document_text(chunks)[:MAX_BODY_CHARS]


def _build_generate_messages(
    title: str, body: str, per_doc: int
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"文档标题：{title}\n\n文档内容：\n{body}\n\n"
                f"请生成 {per_doc} 个问题（数量在 3-5 个之间）。"
            ),
        },
    ]


async def _collect_ready_documents(repo: Any) -> list[tuple[Any, str]]:
    """分页取全部 ready 文档，返回 (doc, 正文全文)，按正文长度降序。"""
    documents: list[tuple[Any, str]] = []
    page = 1
    while True:
        result = await repo.list_documents(
            status="ready", page=page, page_size=PAGE_SIZE
        )
        items = list(result.items)
        if not items:
            break
        for doc in items:
            documents.append((doc, _document_text(await repo.list_chunks(doc.id))))
        if len(items) < PAGE_SIZE:
            break
        page += 1
    documents.sort(key=lambda item: len(item[1]), reverse=True)
    return documents


async def _generate_for_document(
    repo: Any,
    complete: Any,
    doc: Any,
    body: str,
    target: int,
    seen: set[str],
) -> int:
    raw = await complete(_build_generate_messages(doc.title, body, target))
    created = 0
    for question in parse_questions(raw)[:target]:
        if question in seen:
            continue
        seen.add(question)
        await repo.create_eval_question(question, [doc.id])
        created += 1
    return created


async def generate_questions(
    repo: Any,
    provider_or_service: LlmLike,
    *,
    per_doc: int = 4,
    limit: int | None = None,
    max_docs: int | None = None,
    min_chars: int = 0,
    clear: bool = False,
) -> int:
    """对 ready 文档用 LLM 生成问题并写入 rag_eval_set，返回写入条数。

    默认沿用历史行为（按 created_at DESC 分页处理，`limit` 为处理上限）；
    传入 `max_docs` 或 `min_chars > 0` 时改为「按正文长度降序」选取文档，
    并用 `min_chars` 过滤短文档、`max_docs` 截断篇数。
    """
    complete = getattr(provider_or_service, "complete", None)
    if complete is None:
        raise TypeError("provider_or_service 需提供 async complete(messages) 方法")
    if clear:
        from sqlalchemy import text

        await repo.session.execute(text("DELETE FROM rag_eval_set"))
        await repo.session.commit()
    target = max(1, min(int(per_doc), 5))
    created = 0
    seen: set[str] = set()

    if max_docs is None and min_chars <= 0:
        processed = 0
        page = 1
        while True:
            result = await repo.list_documents(
                status="ready", page=page, page_size=PAGE_SIZE
            )
            items = list(result.items)
            if not items:
                break
            for doc in items:
                if limit is not None and processed >= limit:
                    return created
                processed += 1
                body = _document_body(doc, await repo.list_chunks(doc.id))
                if not body:
                    continue
                created += await _generate_for_document(
                    repo, complete, doc, body, target, seen
                )
            if len(items) < PAGE_SIZE:
                break
            page += 1
        return created

    candidates = await _collect_ready_documents(repo)
    if min_chars > 0:
        candidates = [item for item in candidates if len(item[1]) >= min_chars]
    if max_docs is not None:
        candidates = candidates[: max(1, int(max_docs))]
    for index, (doc, full_text) in enumerate(candidates):
        if limit is not None and index >= limit:
            break
        body = full_text[:MAX_BODY_CHARS]
        if not body.strip():
            continue
        created += await _generate_for_document(
            repo, complete, doc, body, target, seen
        )
    return created


def _escape_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_report(report: EvalReport, *, k: int = DEFAULT_K) -> str:
    passed = report.recall >= RECALL_TARGET and report.p95_ms <= P95_BUDGET_MS
    lines = [
        "# RAG 黄金测试集评测报告",
        "",
        f"- 生成时间：{datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"- 问题总数：{report.total}",
        f"- 命中数：{report.hits}",
        f"- Recall@{k}：{report.recall:.4f}",
        f"- P95 延迟：{report.p95_ms:.2f} ms",
        (
            f"- 验收线：Recall@{k} ≥ {RECALL_TARGET:.2f} 且 "
            f"P95 ≤ {P95_BUDGET_MS:.0f}ms → {'通过' if passed else '未通过'}"
        ),
        "",
        "## Misses",
        "",
    ]
    if not report.misses:
        lines.append("无未命中问题。")
    else:
        lines.extend(
            [
                "| # | Query | Expected doc ids | 实际命中标题 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for index, miss in enumerate(report.misses, start=1):
            expected = ", ".join(miss.get("expected_doc_ids") or [])
            actual = "；".join(miss.get("actual_titles") or []) or "（无命中）"
            lines.append(
                f"| {index} | {_escape_cell(miss.get('query', ''))} | "
                f"{_escape_cell(expected)} | {_escape_cell(actual)} |"
            )
    lines.append("")
    return "\n".join(lines)


async def _run_eval(k: int) -> EvalReport:
    from app.db.session import async_session_factory
    from app.repositories.rag_repository import RagRepository
    from app.services.rag.embedding import build_embedding_provider
    from app.services.rag.search import RagSearchService
    from app.services.rag.store import NumpyVectorStore

    async with async_session_factory() as session:
        repo = RagRepository(session)
        store = NumpyVectorStore(repo.iter_embeddings)
        service = RagSearchService(repo, build_embedding_provider(), store)
        return await evaluate(repo, service, k=k)


async def _run_generate(
    per_doc: int,
    limit: int | None,
    *,
    max_docs: int | None = None,
    min_chars: int = 0,
    clear: bool = False,
) -> int:
    from app.db.session import async_session_factory
    from app.repositories.rag_repository import RagRepository
    from app.services.agent.llm import DeepSeekClient

    client = DeepSeekClient()
    try:
        async with async_session_factory() as session:
            repo = RagRepository(session)
            return await generate_questions(
                repo,
                client,
                per_doc=per_doc,
                limit=limit,
                max_docs=max_docs,
                min_chars=min_chars,
                clear=clear,
            )
    finally:
        await client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAG 黄金测试集生成与评测")
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="recall@k 的 k（默认 5）")
    parser.add_argument(
        "--report", type=Path, default=DEFAULT_REPORT_PATH, help="报告输出路径"
    )
    parser.add_argument(
        "--generate-questions", action="store_true", help="用 LLM 生成评测问题并写库"
    )
    parser.add_argument("--per-doc", type=int, default=4, help="每篇文档生成的问题数")
    parser.add_argument("--limit", type=int, default=None, help="最多处理的文档数")
    parser.add_argument(
        "--max-docs",
        type=int,
        default=None,
        help="最多取 N 篇文档出题（按正文长度降序优先取长文档）",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=0,
        help="跳过正文（chunks 内容总长）短于 N 的文档",
    )
    parser.add_argument(
        "--clear", action="store_true", help="出题前清空 rag_eval_set"
    )
    args = parser.parse_args(argv)

    if args.generate_questions:
        started = time.perf_counter()
        created = asyncio.run(
            _run_generate(
                args.per_doc,
                args.limit,
                max_docs=args.max_docs,
                min_chars=args.min_chars,
                clear=args.clear,
            )
        )
        elapsed = time.perf_counter() - started
        print(f"[生成] 写入评测问题：{created} 条，耗时 {elapsed:.1f}s")
        return 0

    report = asyncio.run(_run_eval(args.k))
    report_path = args.report if args.report.is_absolute() else REPO_ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(report, k=args.k), encoding="utf-8")
    print(
        f"[评测] 总数 {report.total}，命中 {report.hits}，"
        f"recall@{args.k}={report.recall:.4f}，P95={report.p95_ms:.2f}ms"
    )
    print(f"[评测] 报告：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
