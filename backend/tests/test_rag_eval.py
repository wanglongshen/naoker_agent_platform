from __future__ import annotations

import uuid

import pytest

from scripts.rag_eval import (
    EvalReport,
    evaluate,
    generate_questions,
    parse_questions,
    recall_at_k,
)


class Hit:
    def __init__(self, doc_id, title: str = "文档"):
        self.doc_id = doc_id
        self.title = title


def test_recall_at_k_counts_hit_within_topk():
    d1, d2 = uuid.uuid4(), uuid.uuid4()
    assert recall_at_k([Hit(d1), Hit(d2)], [d2], k=1) == 0.0
    assert recall_at_k([Hit(d1), Hit(d2)], [d2], k=2) == 1.0


def test_recall_at_k_handles_string_ids_and_empty_inputs():
    d1 = uuid.uuid4()
    assert recall_at_k([Hit(d1)], [str(d1)], k=5) == 1.0
    assert recall_at_k([], [d1], k=5) == 0.0
    assert recall_at_k([Hit(d1)], [], k=5) == 0.0


class FakeQuestion:
    def __init__(self, query: str, expected: list):
        self.query = query
        self.expected_doc_ids = expected


class FakeEvalRepo:
    def __init__(self, questions: list[FakeQuestion]):
        self._questions = questions

    async def list_eval_questions(self):
        return list(self._questions)


class FakeSearchService:
    def __init__(self, hits_by_query: dict[str, list[Hit]]):
        self.hits_by_query = hits_by_query
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, top_k: int = 5):
        self.calls.append((query, top_k))
        return list(self.hits_by_query.get(query, []))[:top_k]


@pytest.mark.anyio
async def test_evaluate_reports_recall_p95_and_misses():
    hit_doc, miss_doc, other_doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    questions = [
        FakeQuestion("能命中的问题", [hit_doc]),
        FakeQuestion("命不中的问题", [miss_doc]),
    ]
    service = FakeSearchService(
        {
            "能命中的问题": [Hit(hit_doc, "命中文档")],
            "命不中的问题": [Hit(other_doc, "别的文档")],
        }
    )

    report = await evaluate(FakeEvalRepo(questions), service, k=5)

    assert isinstance(report, EvalReport)
    assert report.total == 2
    assert report.hits == 1
    assert report.recall == 0.5
    assert report.p95_ms >= 0.0
    assert len(report.misses) == 1
    miss = report.misses[0]
    assert miss["query"] == "命不中的问题"
    assert miss["expected_doc_ids"] == [str(miss_doc)]
    assert miss["actual_doc_ids"] == [str(other_doc)]
    assert miss["actual_titles"] == ["别的文档"]
    assert service.calls == [("能命中的问题", 5), ("命不中的问题", 5)]


@pytest.mark.anyio
async def test_evaluate_respects_top_k_window():
    doc_a, doc_b = uuid.uuid4(), uuid.uuid4()
    repo = FakeEvalRepo([FakeQuestion("问题", [doc_b])])
    service = FakeSearchService({"问题": [Hit(doc_a), Hit(doc_b)]})

    assert (await evaluate(repo, service, k=1)).recall == 0.0
    assert (await evaluate(repo, service, k=2)).recall == 1.0


@pytest.mark.anyio
async def test_evaluate_empty_set():
    report = await evaluate(FakeEvalRepo([]), FakeSearchService({}), k=5)
    assert report.total == 0
    assert report.hits == 0
    assert report.recall == 0.0
    assert report.p95_ms == 0.0
    assert report.misses == []


class FakeChunk:
    def __init__(self, content: str):
        self.content = content


class FakeDoc:
    def __init__(self, doc_id, title: str):
        self.id = doc_id
        self.title = title


class FakePage:
    def __init__(self, items: list):
        self.items = items
        self.total = len(items)


class FakeGenerateRepo:
    def __init__(self, docs: list[FakeDoc], chunks: dict):
        self.docs = docs
        self.chunks = chunks
        self.created: list[tuple[str, list]] = []

    async def list_documents(self, status=None, page: int = 1, page_size: int = 50):
        assert status == "ready"
        start = (page - 1) * page_size
        return FakePage(self.docs[start : start + page_size])

    async def list_chunks(self, doc_id):
        return self.chunks.get(doc_id, [])

    async def create_eval_question(self, query, expected_doc_ids, created_by=None):
        self.created.append((query, list(expected_doc_ids)))
        return None


class FakeLlm:
    def __init__(self, payload: str):
        self.payload = payload
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages):
        self.calls.append(messages)
        return self.payload


@pytest.mark.anyio
async def test_generate_questions_writes_eval_set_with_doc_id():
    doc = FakeDoc(uuid.uuid4(), "投放策略")
    repo = FakeGenerateRepo([doc], {doc.id: [FakeChunk("出价方法正文。")]})
    llm = FakeLlm('```json\n["问题一？", "问题二？", "问题三？"]\n```')

    created = await generate_questions(repo, llm, per_doc=3)

    assert created == 3
    assert repo.created == [
        ("问题一？", [doc.id]),
        ("问题二？", [doc.id]),
        ("问题三？", [doc.id]),
    ]
    assert llm.calls and "投放策略" in llm.calls[0][1]["content"]


@pytest.mark.anyio
async def test_generate_questions_honors_limit_and_parses_plain_lines():
    docs = [FakeDoc(uuid.uuid4(), "文档A"), FakeDoc(uuid.uuid4(), "文档B")]
    repo = FakeGenerateRepo(docs, {doc.id: [FakeChunk("正文")] for doc in docs})
    llm = FakeLlm("1. 问题甲\n2. 问题乙")

    created = await generate_questions(repo, llm, per_doc=5, limit=1)

    assert created == 2
    assert repo.created == [("问题甲", [docs[0].id]), ("问题乙", [docs[0].id])]


@pytest.mark.anyio
async def test_generate_questions_rejects_non_llm_dependency():
    repo = FakeGenerateRepo([], {})
    with pytest.raises(TypeError):
        await generate_questions(repo, object())


def test_parse_questions_handles_json_and_bullets():
    assert parse_questions('["A", "B"]') == ["A", "B"]
    assert parse_questions("- A\n- B") == ["A", "B"]
    assert parse_questions("") == []
