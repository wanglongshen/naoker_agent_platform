from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from app.services.agent.event_bus import EventItem, event_bus


@pytest.mark.anyio
async def test_wake_up_emits_events_without_compensation_wait():
    """A local queue wake-up should trigger event emission immediately."""
    from app.services.agent.event_bus import event_bus as _eb

    run_id = uuid.uuid4()
    subscriber_id, queue = await _eb.subscribe(run_id)
    try:
        await _eb.publish(EventItem(
            run_id=run_id,
            seq=1,
            event_type="answer_delta",
            payload={"delta": "test"},
            created_at=datetime.now(timezone.utc),
        ))
        item = await asyncio.wait_for(queue.get(), timeout=0.05)
        assert item is not None
        assert item.seq == 1
    finally:
        await _eb.unsubscribe(run_id, subscriber_id)


def test_heartbeat_interval_is_30_seconds():
    from app.api.agent_stream import HEARTBEAT_INTERVAL

    assert HEARTBEAT_INTERVAL == 30.0
