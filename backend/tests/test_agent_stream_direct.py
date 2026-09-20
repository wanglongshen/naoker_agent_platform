import uuid
from datetime import datetime, timezone

import pytest

from app.api.agent_stream import _encode_sse_event
from app.models.agent import AgentRunEvent
from app.services.agent.event_bus import EventItem


class TestEncodeSSEEvent:
    def test_encode_agent_run_event(self):
        event = AgentRunEvent(
            id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            seq=42,
            event_type="answer_delta",
            payload={"delta": "hello"},
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        encoded = _encode_sse_event(event)
        assert encoded is not None
        assert 'event: answer_delta' in encoded
        assert 'id: 42' in encoded
        assert 'data: {' in encoded
        assert '"delta": "hello"' in encoded

    def test_encode_committed_event(self):
        event = EventItem(
            id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            seq=7,
            event_type="run_started",
            payload={"step": 1},
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        encoded = _encode_sse_event(event)
        assert encoded is not None
        assert 'event: run_started' in encoded
        assert 'id: 7' in encoded
        assert '"step": 1' in encoded

    def test_encode_committed_event_without_id_returns_none(self):
        event = EventItem(
            run_id=uuid.uuid4(),
            seq=7,
            event_type="run_started",
            payload={"step": 1},
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert _encode_sse_event(event) is None

    def test_encode_invalid_object_returns_none(self):
        assert _encode_sse_event("not_an_event") is None
        assert _encode_sse_event({"seq": 1}) is None
        assert _encode_sse_event(None) is None

    def test_encode_sse_format(self):
        event = AgentRunEvent(
            id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            seq=1,
            event_type="run_queued",
            payload={},
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        encoded = _encode_sse_event(event)
        assert encoded is not None
        assert encoded.startswith("id: 1\n")
        assert encoded.endswith("\n\n")
        assert "\nevent: run_queued\n" in encoded
        assert "\ndata: {" in encoded

    def test_encode_includes_attempt_id(self):
        event = AgentRunEvent(
            id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            seq=99,
            event_type="thought_start",
            payload={"content": "thinking..."},
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        encoded = _encode_sse_event(event)
        assert encoded is not None
        assert '"attempt_id": null' in encoded
