from __future__ import annotations


def test_normalize_replaces_volatile_fields():
    from app.services.agent.event_normalize import normalize_events

    events = [
        {"id": "11111111-1111-1111-1111-111111111111", "event_type": "step_started",
         "created_at": "2026-09-14T10:00:00.123456+00:00",
         "payload": {"stream_id": "error-22222222-2222-2222-2222-222222222222", "step_index": 0}},
        {"id": "33333333-3333-3333-3333-333333333333", "event_type": "answer_delta",
         "created_at": "2026-09-14T10:00:01.000000+00:00",
         "payload": {"delta": "文本", "offset": 0, "run_id": "44444444-4444-4444-4444-444444444444"}},
    ]
    out = normalize_events(events)
    assert out[0]["id"] == "<id>"
    assert out[0]["created_at"] == "<ts>"
    assert out[0]["payload"]["stream_id"] == "stream-1"
    assert out[1]["payload"]["delta"] == "文本"
    assert out[1]["payload"]["run_id"] == "<uuid>"


def test_normalize_keeps_semantics_and_diff_empty():
    from app.services.agent.event_normalize import diff_normalized, normalize_events

    a = [{"event_type": "x", "payload": {"n": 1}}]
    b = [{"event_type": "x", "payload": {"n": 1}}]
    assert diff_normalized(normalize_events(a), normalize_events(b)) == []
    c = [{"event_type": "x", "payload": {"n": 2}}]
    assert diff_normalized(normalize_events(a), normalize_events(c)) != []


def test_normalize_stream_ids_by_first_appearance():
    from app.services.agent.event_normalize import diff_normalized, normalize_events

    run_a = [
        {"event_type": "plan_started", "payload": {"stream_id": "plan-aaaaaaaaaaaa"}},
        {"event_type": "plan_completed", "payload": {"stream_id": "plan-aaaaaaaaaaaa"}},
        {"event_type": "plan_started", "payload": {"stream_id": "plan-bbbbbbbbbbbb"}},
    ]
    run_b = [
        {"event_type": "plan_started", "payload": {"stream_id": "plan-cccccccccccc"}},
        {"event_type": "plan_completed", "payload": {"stream_id": "plan-cccccccccccc"}},
        {"event_type": "plan_started", "payload": {"stream_id": "plan-dddddddddddd"}},
    ]
    assert diff_normalized(normalize_events(run_a), normalize_events(run_b)) == []

    regressed = [
        {"event_type": "plan_started", "payload": {"stream_id": "plan-eeeeeeeeeeee"}},
        {"event_type": "plan_completed", "payload": {"stream_id": "plan-ffffffffffff"}},
        {"event_type": "plan_started", "payload": {"stream_id": "plan-ffffffffffff"}},
    ]
    assert diff_normalized(normalize_events(run_a), normalize_events(regressed)) != []
