"""向量存储：v1 用精确余弦检索（决策 D1：本机无 pgvector，语料 ≈14k chunks 精确检索更快更准）。

PgVectorStore 升级位：当 chunks > 20 万或需要 ANN 时新增实现，协议不变。
"""

from __future__ import annotations

import uuid
from typing import Awaitable, Callable, Protocol

import numpy as np


def to_bytes(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_bytes(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.float32)


class VectorStore(Protocol):
    async def search(
        self,
        query_vector: bytes,
        top_k: int,
        allowed_ids: set[uuid.UUID] | None = None,
    ) -> list[tuple[uuid.UUID, float]]: ...

    def invalidate(self) -> None: ...


class NumpyVectorStore:
    def __init__(
        self,
        loader: Callable[[], Awaitable[list[tuple[uuid.UUID, bytes]]]],
        version_probe: Callable[[], Awaitable[tuple]] | None = None,
    ) -> None:
        self._loader = loader
        self._version_probe = version_probe
        self._version: tuple | None = None
        self._ids: list[uuid.UUID] = []
        self._matrix: np.ndarray | None = None

    async def _ensure(self) -> None:
        if self._matrix is not None:
            if self._version_probe is None:
                return
            version = await self._version_probe()
            if version == self._version:
                return
            self._version = version
        elif self._version_probe is not None:
            self._version = await self._version_probe()
        rows = await self._loader()
        self._ids = [r[0] for r in rows]
        self._matrix = (
            np.vstack([from_bytes(r[1]) for r in rows])
            if rows
            else np.zeros((0, 1), dtype=np.float32)
        )

    async def search(
        self,
        query_vector: bytes,
        top_k: int,
        allowed_ids: set[uuid.UUID] | None = None,
    ) -> list[tuple[uuid.UUID, float]]:
        await self._ensure()
        if not self._ids:
            return []
        query = from_bytes(query_vector)
        ids = self._ids
        matrix = self._matrix
        if allowed_ids is not None:
            mask = np.array(
                [chunk_id in allowed_ids for chunk_id in self._ids], dtype=bool
            )
            if not mask.any():
                return []
            ids = [chunk_id for chunk_id, keep in zip(self._ids, mask) if keep]
            matrix = self._matrix[mask]
        scores = matrix @ query
        order = np.argsort(-scores)[:top_k]
        return [(ids[i], float(scores[i])) for i in order]

    def invalidate(self) -> None:
        self._matrix = None
        self._ids = []
