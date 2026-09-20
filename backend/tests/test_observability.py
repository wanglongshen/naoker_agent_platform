import pytest
from app.services.observability import (
    WORKER_CLAIMED,
    WORKER_ERRORS,
    render_metrics,
)


class TestMetrics:
    def test_render_metrics_contains_agent_worker_prefix(self):
        text = render_metrics()
        assert "agent_worker" in text

    def test_counter_increments_and_renders(self):
        WORKER_CLAIMED.reset()
        WORKER_CLAIMED.inc(3)
        text = render_metrics()
        assert "agent_worker_claimed_total 3.0" in text or "agent_worker_claimed_total 3" in text

    def test_error_counter_exists(self):
        text = render_metrics()
        assert "agent_worker_error_total" in text
