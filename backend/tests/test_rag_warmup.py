"""D4：RAG 冷启动后台预热。

覆盖：预热触发模型加载与向量矩阵加载、失败不影响启动、配置开关默认开启。
"""

import pytest

from app.core.config import Settings
from app.services.rag.search import RagSearchService


class _FakeProvider:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[bytes]:
        self.calls.append(list(texts))
        return [b"" for _ in texts]


class _FakeStore:
    def __init__(self) -> None:
        self.ensured = 0

    async def _ensure(self) -> None:
        self.ensured += 1

    async def search(self, vector, top_k, allowed_ids=None):  # noqa: ANN001
        return []

    def invalidate(self) -> None:
        return None


@pytest.mark.asyncio
async def test_warmup_embeds_and_loads_store() -> None:
    provider = _FakeProvider()
    store = _FakeStore()
    service = RagSearchService(repo=object(), provider=provider, store=store)

    await service.warmup()

    assert provider.calls == [["warmup"]]
    assert store.ensured == 1


@pytest.mark.asyncio
async def test_warmup_rag_swallows_failure(monkeypatch, caplog) -> None:
    class _Boom:
        async def warmup(self) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr("app.api.rag.get_search_service", lambda: _Boom())

    from app.main import _warmup_rag

    await _warmup_rag()  # 必须不抛异常

    assert any("rag_warmup_failed" in record.getMessage() for record in caplog.records)


def test_warmup_flag_defaults_on() -> None:
    assert Settings().rag_warmup_on_startup is True
