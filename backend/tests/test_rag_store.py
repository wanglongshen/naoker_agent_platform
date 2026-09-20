from __future__ import annotations

import uuid

import numpy as np
import pytest

from app.services.rag.store import NumpyVectorStore, to_bytes


def _vec(*values: float) -> bytes:
    arr = np.array(values, dtype=np.float32)
    arr = arr / np.linalg.norm(arr)
    return to_bytes(arr)


@pytest.mark.anyio
async def test_numpy_store_returns_cosine_topk():
    ids = [uuid.uuid4() for _ in range(3)]
    rows = [
        (ids[0], _vec(1, 0, 0)),
        (ids[1], _vec(0.9, 0.1, 0)),
        (ids[2], _vec(0, 1, 0)),
    ]

    async def loader():
        return rows

    store = NumpyVectorStore(loader)
    hits = await store.search(_vec(1, 0, 0), top_k=2)
    assert [h[0] for h in hits] == [ids[0], ids[1]]
    assert hits[0][1] > hits[1][1]


@pytest.mark.anyio
async def test_numpy_store_restricts_search_to_allowed_ids():
    ids = [uuid.uuid4() for _ in range(3)]
    rows = [
        (ids[0], _vec(1, 0, 0)),
        (ids[1], _vec(0.9, 0.1, 0)),
        (ids[2], _vec(0, 1, 0)),
    ]

    async def loader():
        return rows

    store = NumpyVectorStore(loader)

    global_hits = await store.search(_vec(1, 0, 0), top_k=2)
    assert [h[0] for h in global_hits] == [ids[0], ids[1]]

    excluded = await store.search(_vec(1, 0, 0), top_k=2, allowed_ids={ids[2]})
    assert [h[0] for h in excluded] == [ids[2]]

    subset = await store.search(_vec(1, 0, 0), top_k=2, allowed_ids={ids[1], ids[2]})
    assert [h[0] for h in subset] == [ids[1], ids[2]]

    assert await store.search(_vec(1, 0, 0), top_k=2, allowed_ids=set()) == []


@pytest.mark.anyio
async def test_numpy_store_probe_same_version_keeps_cache():
    ids = [uuid.uuid4(), uuid.uuid4()]
    calls = {"loader": 0}
    state = {"version": ("v", 1)}

    async def loader():
        calls["loader"] += 1
        return [(ids[0], _vec(1, 0))]

    async def probe():
        return state["version"]

    store = NumpyVectorStore(loader, version_probe=probe)
    assert len(await store.search(_vec(1, 0), top_k=5)) == 1
    assert len(await store.search(_vec(1, 0), top_k=5)) == 1
    assert calls["loader"] == 1


@pytest.mark.anyio
async def test_numpy_store_probe_changed_version_reloads():
    ids = [uuid.uuid4(), uuid.uuid4()]
    calls = {"loader": 0}
    state = {"rows": [(ids[0], _vec(1, 0))], "version": ("v", 1)}

    async def loader():
        calls["loader"] += 1
        return state["rows"]

    async def probe():
        return state["version"]

    store = NumpyVectorStore(loader, version_probe=probe)
    assert [h[0] for h in await store.search(_vec(1, 0), top_k=5)] == [ids[0]]

    state["rows"] = [(ids[0], _vec(1, 0)), (ids[1], _vec(0.5, 0.5))]
    state["version"] = ("v", 2)

    hits = await store.search(_vec(1, 0), top_k=5)
    assert {h[0] for h in hits} == {ids[0], ids[1]}
    assert calls["loader"] == 2


@pytest.mark.anyio
async def test_numpy_store_without_probe_loads_once():
    ids = [uuid.uuid4(), uuid.uuid4()]
    calls = {"loader": 0}

    async def loader():
        calls["loader"] += 1
        return [(ids[0], _vec(1, 0))]

    store = NumpyVectorStore(loader)
    assert len(await store.search(_vec(1, 0), top_k=5)) == 1
    assert len(await store.search(_vec(1, 0), top_k=5)) == 1
    assert calls["loader"] == 1


@pytest.mark.anyio
async def test_numpy_store_reloads_after_invalidate():
    ids = [uuid.uuid4(), uuid.uuid4()]
    state = {"rows": [(ids[0], _vec(1, 0))]}

    async def loader():
        return state["rows"]

    store = NumpyVectorStore(loader)
    assert len(await store.search(_vec(1, 0), top_k=5)) == 1
    state["rows"] = [(ids[0], _vec(1, 0)), (ids[1], _vec(0.5, 0.5))]
    assert len(await store.search(_vec(1, 0), top_k=5)) == 1  # 未失效
    store.invalidate()
    assert len(await store.search(_vec(1, 0), top_k=5)) == 2
