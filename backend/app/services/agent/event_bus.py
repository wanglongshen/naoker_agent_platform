from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Union
from uuid import UUID, uuid4


@dataclass(frozen=True)
class EventItem:
    run_id: UUID
    seq: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    id: UUID | None = None
    attempt_id: UUID | None = None


QueueItem = EventItem


class EventBus:
    def __init__(self, max_queue_size: int = 1000) -> None:
        self._subscribers: dict[UUID, dict[str, asyncio.Queue[QueueItem]]] = {}
        self._lock = asyncio.Lock()
        self._max_queue_size = max_queue_size

    async def publish(self, item: QueueItem) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(item.run_id, {}).items())

        for subscriber_id, queue in subscribers:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                await self.unsubscribe(item.run_id, subscriber_id)

    async def subscribe(self, run_id: UUID) -> tuple[str, asyncio.Queue[QueueItem]]:
        subscriber_id = str(uuid4())
        queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=self._max_queue_size)
        async with self._lock:
            self._subscribers.setdefault(run_id, {})[subscriber_id] = queue
        return subscriber_id, queue

    async def unsubscribe(self, run_id: UUID, subscriber_id: str) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(run_id)
            if subscribers is None:
                return
            subscribers.pop(subscriber_id, None)
            if not subscribers:
                del self._subscribers[run_id]


event_bus = EventBus()
