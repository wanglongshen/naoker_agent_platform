import json
from pathlib import Path

from scripts.dsh_sessions_reset import clear_sessions


def _write_session(home: Path, session_id: str) -> Path:
    session_dir = home / "sessions" / session_id
    session_dir.mkdir(parents=True)
    payload = "\n".join(
        [
            json.dumps({"type": "session", "version": 1, "id": session_id, "createdAt": 1700000000000}),
            json.dumps({"type": "turn/start", "time": 1700000001000, "data": {"turn": 1}}),
        ]
    )
    (session_dir / "session.jsonl").write_text(payload, encoding="utf-8")
    return session_dir


def test_clear_sessions_removes_all_session_dirs(tmp_path):
    home = tmp_path / "home"
    _write_session(home, "s-1")
    _write_session(home, "s-2")
    assert clear_sessions(home) == 2
    assert list((home / "sessions").iterdir()) == []


def test_clear_sessions_is_idempotent_on_missing_root(tmp_path):
    assert clear_sessions(tmp_path / "nope") == 0


def test_clear_sessions_counts_nested_project_layout(tmp_path):
    home = tmp_path / "home"
    project = home / "sessions" / "--C-project--"
    for session_id in ("session-a", "session-b"):
        session_dir = project / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "session.jsonl.zstd").write_bytes(b"")
    assert clear_sessions(home) == 2
    assert list((home / "sessions").iterdir()) == []
