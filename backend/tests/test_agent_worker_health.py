import pytest


def test_worker_health_reports_counts_without_secrets(capsys, monkeypatch):
    async def fake_load_counts():
        return {"queued": 2, "running": 1, "expired": 0}

    from scripts import agent_worker_health as health
    monkeypatch.setattr(health, "load_counts", lambda: fake_load_counts())
    health.main()
    output = capsys.readouterr().out
    assert "queued=2" in output
    assert "running=1" in output
    assert "sk-" not in output
