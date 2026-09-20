import uuid
from types import SimpleNamespace

import pytest

from app.services.rag.library_routing import SLUG_TO_SEED
from app.workers.rag_ingest_worker import _process_import_job


class FakeRepo:
    def __init__(self):
        self.ingested: list[tuple[str, uuid.UUID]] = []
        self.updates: list[dict] = []

    async def get_document_by_sha256(self, sha256):
        return None

    async def update_job(self, job_id, **fields):
        self.updates.append(fields)
        return None


@pytest.mark.asyncio
async def test_routed_job_sends_each_item_to_its_library(monkeypatch):
    captured: list[tuple[str, uuid.UUID]] = []

    async def fake_ingest_one(repo, provider, **kwargs):
        captured.append((kwargs["title"], kwargs["library_id"]))
        return SimpleNamespace(id=uuid.uuid4()), 3

    monkeypatch.setattr(
        "app.workers.rag_ingest_worker.ingest_one", fake_ingest_one
    )

    repo = FakeRepo()
    job = SimpleNamespace(
        id=uuid.uuid4(),
        library_id=SLUG_TO_SEED["general"].id,
        created_by=None,
    )
    items = [
        {"title": "巨量千川直播全域投放使用宝典", "tags": ["商品推广(千川)"], "file": "a.md", "sha256": "a" * 64},
        {"title": "商家申诉举证标准", "tags": ["规则解读"], "file": "b.md", "sha256": "b" * 64},
        {"title": "服务商抖店服务市场入驻与合作指南", "tags": [], "file": "c.md", "sha256": "c" * 64},
    ]
    payload = {"routed": True, "markdown_root": "C:/tmp", "items": items}

    await _process_import_job(repo, provider=None, job=job, payload=payload, processed=0)

    assert captured == [
        ("巨量千川直播全域投放使用宝典", SLUG_TO_SEED["qianchuan"].id),
        ("商家申诉举证标准", SLUG_TO_SEED["platform-rules"].id),
        ("服务商抖店服务市场入驻与合作指南", SLUG_TO_SEED["mall"].id),
    ]


@pytest.mark.asyncio
async def test_non_routed_job_still_uses_job_library(monkeypatch):
    captured: list[uuid.UUID] = []

    async def fake_ingest_one(repo, provider, **kwargs):
        captured.append(kwargs["library_id"])
        return SimpleNamespace(id=uuid.uuid4()), 1

    monkeypatch.setattr(
        "app.workers.rag_ingest_worker.ingest_one", fake_ingest_one
    )

    target = SLUG_TO_SEED["live"].id
    repo = FakeRepo()
    job = SimpleNamespace(id=uuid.uuid4(), library_id=target, created_by=None)
    items = [{"title": "直播间运营白皮书", "tags": [], "file": "d.md", "sha256": "d" * 64}]

    await _process_import_job(
        repo, provider=None, job=job, payload={"markdown_root": "C:/tmp", "items": items}, processed=0
    )

    assert captured == [target]
