from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

import orjson

if TYPE_CHECKING:
    from app.services.agent.event_bus import EventBus, EventItem

logger = logging.getLogger("redis_bridge")

STREAM_NAME = "agent:events"
CONSUMER_GROUP = "sse-consumers"


class RedisBridge:
    def __init__(
        self,
        redis_url: str,
        event_bus: "EventBus",
        *,
        batch_window_ms: int = 32,
        batch_max_size: int = 20,
    ) -> None:
        self._redis_url = redis_url
        self._event_bus = event_bus
        self._batch_window_ms = batch_window_ms
        self._batch_max_size = batch_max_size

        self._conn = None
        self._consumer_name = f"{socket.gethostname()}:{os.getpid()}"
        self._connected = False
        self._sub_task: asyncio.Task | None = None
        self._batch_buffer: list[tuple[UUID, "EventItem"]] = []
        self._batch_last_flush = 0.0
        self._flush_task: asyncio.Task | None = None

    @staticmethod
    def _event_item_to_dict(item: "EventItem") -> dict:
        d = asdict(item)
        d["run_id"] = str(item.run_id)
        d["id"] = str(item.id) if item.id else None
        d["attempt_id"] = str(item.attempt_id) if item.attempt_id else None
        d["created_at"] = item.created_at.isoformat()
        return d

    @staticmethod
    def _dict_to_event_item(d: dict) -> "EventItem":
        from app.services.agent.event_bus import EventItem
        return EventItem(
            run_id=UUID(d["run_id"]),
            seq=d["seq"],
            event_type=d["event_type"],
            payload=d["payload"],
            created_at=datetime.fromisoformat(d["created_at"]),
            id=UUID(d["id"]) if d.get("id") else None,
            attempt_id=UUID(d["attempt_id"]) if d.get("attempt_id") else None,
        )

    async def connect(self) -> None:
        if self._connected:
            return
        try:
            import redis.asyncio as aioredis
            self._conn = aioredis.from_url(self._redis_url)
            await self._conn.ping()
            try:
                await self._conn.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
            except aioredis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise
            self._connected = True
            self._batch_last_flush = time.monotonic()
            self._flush_task = asyncio.create_task(self._batch_flush_loop())
            logger.info("redis_bridge_connected", extra={"url": self._redis_url, "consumer": self._consumer_name})
        except Exception:
            logger.warning("redis_bridge_connect_failed", exc_info=True)
            self._connected = False

    async def disconnect(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
            self._flush_task = None
        if self._batch_buffer:
            await self._flush_batch()
        if self._sub_task:
            self._sub_task.cancel()
            self._sub_task = None
        if self._conn:
            await self._conn.aclose()
            self._conn = None
        self._connected = False

    async def publish(self, channel: str, item: "EventItem") -> None:
        if not self._connected:
            return
        self._batch_buffer.append((item.run_id, item))

    async def subscribe(self, pattern: str) -> None:
        if not self._connected:
            return
        self._sub_task = asyncio.create_task(self._subscribe_loop())

    def _should_flush(self) -> int | None:
        size = len(self._batch_buffer)
        if size == 0:
            return None
        if size >= self._batch_max_size:
            return size
        elapsed = (time.monotonic() - self._batch_last_flush) * 1000
        if elapsed >= self._batch_window_ms:
            return size
        return None

    async def _batch_flush_loop(self) -> None:
        while True:
            while True:
                flush_count = self._should_flush()
                if flush_count is None:
                    break
                await self._flush_batch(flush_count)
            await asyncio.sleep(self._batch_window_ms / 1000)

    async def _flush_batch(self, count: int | None = None) -> None:
        if not self._batch_buffer or not self._connected:
            return
        if count is None:
            count = len(self._batch_buffer)
        items = self._batch_buffer[:count]
        self._batch_buffer = self._batch_buffer[count:]
        self._batch_last_flush = time.monotonic()
        if not items:
            return

        payloads = [
            {
                "run_id": str(rid),
                "event": orjson.dumps(self._event_item_to_dict(item)).decode("utf-8"),
            }
            for rid, item in items
        ]
        pipe = self._conn.pipeline()
        for p in payloads:
            pipe.xadd(STREAM_NAME, p, maxlen=10000)
        try:
            await pipe.execute()
        except Exception:
            logger.warning("redis_stream_xadd_failed", exc_info=True)

    async def _subscribe_loop(self) -> None:
        import redis.asyncio as aioredis

        while self._connected:
            try:
                result = await self._conn.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=self._consumer_name,
                    streams={STREAM_NAME: ">"},
                    block=100,
                    count=50,
                )
                if result is None:
                    continue
                for stream_name, messages in result:
                    for msg_id, fields in messages:
                        try:
                            run_id_str = fields.get("run_id", "")
                            event_dict = fields.get("event", {})
                            if isinstance(event_dict, bytes):
                                event_dict = orjson.loads(event_dict)
                            elif isinstance(event_dict, dict):
                                pass
                            else:
                                continue
                            event_item = self._dict_to_event_item(event_dict)
                            await self._event_bus.publish(event_item)
                        except Exception:
                            logger.warning("redis_stream_parse_failed", exc_info=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("redis_subscribe_loop_error", exc_info=True)
                await asyncio.sleep(1)
