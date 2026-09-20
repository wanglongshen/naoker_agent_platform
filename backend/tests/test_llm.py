import pytest

from app.core.config import get_settings


class TestMaxTokens:
    @pytest.mark.anyio
    async def test_stream_text_payload_includes_max_tokens(self, monkeypatch):
        from app.services.agent.llm import DeepSeekClient

        settings = get_settings()
        monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
        monkeypatch.setattr(settings, "deepseek_base_url", "http://test")

        captured = {}

        class FakeStream:
            def __init__(self, json):
                self.status_code = 200
                captured["json"] = json

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                return
                yield

        def fake_stream(method, url, headers=None, json=None, **kwargs):
            return FakeStream(json)

        client = DeepSeekClient()
        monkeypatch.setattr(client._client, "stream", fake_stream)

        async for _ in client.stream_text([{"role": "user", "content": "hi"}]):
            pass

        assert captured["json"]["max_tokens"] == 8192

    @pytest.mark.anyio
    async def test_create_plan_payload_includes_max_tokens(self, monkeypatch):
        from app.services.agent.llm import DeepSeekClient

        settings = get_settings()
        monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
        monkeypatch.setattr(settings, "deepseek_base_url", "http://test")

        captured = {}

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        async def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
            captured["json"] = json
            return FakeResponse()

        client = DeepSeekClient()
        monkeypatch.setattr(client._client, "post", fake_post)

        await client.create_plan([{"role": "user", "content": "hi"}])

        assert captured["json"]["max_tokens"] == 8192
