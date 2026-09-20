from __future__ import annotations

import json

import httpx
import numpy as np
import pytest

from app.services.rag.embedding import (
    HttpEmbeddingProvider,
    LocalSentenceTransformerProvider,
    build_embedding_provider,
)


@pytest.mark.anyio
async def test_local_provider_encodes_normalized_vectors(monkeypatch):
    provider = LocalSentenceTransformerProvider("fake-model", 4)

    class FakeModel:
        def encode(self, texts, normalize_embeddings=True, batch_size=32):
            return np.array([[3.0, 0.0, 0.0, 0.0]] * len(texts), dtype=np.float32)

    monkeypatch.setattr(provider, "_load_model", lambda: FakeModel())
    vectors = await provider.embed(["a", "b"])
    assert len(vectors) == 2
    arr = np.frombuffer(vectors[0], dtype=np.float32)
    assert pytest.approx(float(np.linalg.norm(arr)), rel=1e-3) == 1.0


@pytest.mark.anyio
async def test_http_provider_posts_openai_compatible_payload():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [3.0, 0.0, 0.0, 0.0]},
                    {"index": 1, "embedding": [0.0, 4.0, 0.0, 0.0]},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        provider = HttpEmbeddingProvider(
            "https://api.example.com/v1/", "secret", "text-embedding-3-small", 4, client=client
        )
        vectors = await provider.embed(["a", "b"])
    finally:
        await client.aclose()

    assert len(vectors) == 2
    request = calls[0]
    assert str(request.url) == "https://api.example.com/v1/embeddings"
    assert request.headers["authorization"] == "Bearer secret"
    body = json.loads(request.content)
    assert body == {"model": "text-embedding-3-small", "input": ["a", "b"]}
    first = np.frombuffer(vectors[0], dtype=np.float32)
    assert pytest.approx(float(np.linalg.norm(first)), rel=1e-3) == 1.0


def test_build_provider_switchable_by_settings(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rag_embedding_provider", "http")
    monkeypatch.setattr(get_settings(), "rag_embedding_base_url", "https://api.example.com/v1")
    monkeypatch.setattr(get_settings(), "rag_embedding_api_key", "k")
    provider = build_embedding_provider()
    assert provider.dim == 512


def test_build_provider_defaults_to_local(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rag_embedding_provider", "local")
    provider = build_embedding_provider()
    assert isinstance(provider, LocalSentenceTransformerProvider)
    assert provider.dim == 512
