"""Embedding 供给：本地 sentence-transformers 或 OpenAI 兼容 HTTP 后端（决策 D2）。

统一返回 float32 小端字节（与 `rag_chunks.embedding` bytea 列一致），向量已 L2 归一化，
检索端直接点积即余弦相似度（见 `store.py`）。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Protocol

import httpx
import numpy as np

from app.core.config import get_settings


def vector_to_bytes(vector: Any) -> bytes:
    """float32 小端字节；非零向量做 L2 归一化。"""
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 0:
        arr = arr / norm
    return arr.tobytes()


def _to_dim_bytes(vector: Any, dim: int, source: str) -> bytes:
    raw = vector_to_bytes(vector)
    actual = len(raw) // 4
    if actual != dim:
        raise ValueError(
            f"embedding 维度不匹配：{source} 输出 {actual} 维，"
            f"期望 {dim} 维（配置 rag_embedding_dim）"
        )
    return raw


class EmbeddingProvider(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[bytes]: ...


class LocalSentenceTransformerProvider:
    """懒加载本地 SentenceTransformer；encode 走线程池，避免阻塞事件循环。"""

    def __init__(self, model_name: str, dim: int) -> None:
        self.model_name = model_name
        self.dim = dim
        self._model: Any | None = None
        self._load_lock = threading.Lock()

    def _load_model(self) -> Any:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - 依赖缺失时给可读提示
            raise RuntimeError(
                "未安装 sentence-transformers，无法使用本地 embedding；"
                "请先 pip install sentence-transformers，或改用 rag_embedding_provider=http"
            ) from exc
        try:
            return SentenceTransformer(self.model_name)
        except Exception as exc:
            raise RuntimeError(
                f"加载本地 embedding 模型失败：{self.model_name}（{exc}）；"
                "可改用 rag_embedding_provider=http 走远程服务"
            ) from exc

    def _ensure_model(self) -> Any:
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    self._model = self._load_model()
        return self._model

    async def embed(self, texts: list[str]) -> list[bytes]:
        if not texts:
            return []
        model = await asyncio.to_thread(self._ensure_model)
        vectors = await asyncio.to_thread(
            model.encode, texts, normalize_embeddings=True, batch_size=32
        )
        return [_to_dim_bytes(v, self.dim, f"模型 {self.model_name}") for v in vectors]


class HttpEmbeddingProvider:
    """OpenAI 兼容 embedding 服务：POST {base_url}/embeddings。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dim: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self._client = client

    async def embed(self, texts: list[str]) -> list[bytes]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "input": texts}
        url = f"{self.base_url}/embeddings"
        if self._client is not None:
            response = await self._client.post(url, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        items = sorted(response.json().get("data", []), key=lambda item: item.get("index", 0))
        if len(items) != len(texts):
            raise RuntimeError(f"embedding 服务返回 {len(items)} 条，期望 {len(texts)} 条")
        return [
            _to_dim_bytes(item["embedding"], self.dim, f"服务 {self.model}") for item in items
        ]


def build_embedding_provider() -> EmbeddingProvider:
    """按 settings.rag_embedding_provider 构建 provider（local|http）。"""
    settings = get_settings()
    provider = (settings.rag_embedding_provider or "local").strip().lower()
    if provider == "local":
        return LocalSentenceTransformerProvider(settings.rag_embedding_model, settings.rag_embedding_dim)
    if provider == "http":
        if not settings.rag_embedding_base_url:
            raise ValueError("rag_embedding_provider=http 需要配置 rag_embedding_base_url")
        return HttpEmbeddingProvider(
            settings.rag_embedding_base_url,
            settings.rag_embedding_api_key,
            settings.rag_embedding_model,
            settings.rag_embedding_dim,
        )
    raise ValueError(f"不支持的 rag_embedding_provider：{settings.rag_embedding_provider!r}（可选 local|http）")
