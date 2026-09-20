from __future__ import annotations

import json
import uuid

import pytest


def test_notify_payload_is_run_id_and_seq_only():
    run_id = uuid.uuid4()
    seq = 42
    payload = {"run_id": str(run_id), "seq": seq}
    encoded = json.dumps(payload)
    assert encoded == json.dumps({"run_id": str(run_id), "seq": seq})
    parsed = json.loads(encoded)
    assert parsed == {"run_id": str(run_id), "seq": seq}
    assert "text" not in parsed
    assert "answer" not in parsed
    assert "delta" not in parsed


def test_notify_payload_rejects_invalid_uuid():
    payload = json.dumps({"run_id": "not-a-uuid", "seq": 1})
    assert "not-a-uuid" in payload
