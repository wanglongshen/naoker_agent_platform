import pytest

from app.services.agent.llm import DeepSeekClient


class TestUsageSink:
    @pytest.mark.anyio
    async def test_usage_frame_delivered_to_sink(self):
        frames = [
            'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":8,"total_tokens":20}}\n\n',
            "data: [DONE]\n\n",
        ]
        client = DeepSeekClient()
        seen = []
        collected = ""
        async for chunk in client._iter_sse_content(frames, usage_sink=seen.append):
            collected += chunk
        assert collected == "你好"
        assert seen == [{"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}]

    @pytest.mark.anyio
    async def test_no_usage_frame_no_callback(self):
        frames = ['data: {"choices":[{"delta":{"content":"x"}}]}\n\n', "data: [DONE]\n\n"]
        client = DeepSeekClient()
        seen = []
        async for _ in client._iter_sse_content(frames, usage_sink=seen.append):
            pass
        assert seen == []

    @pytest.mark.anyio
    async def test_usage_in_same_frame_as_content(self):
        frames = [
            'data: {"choices":[{"delta":{"content":"ok"}}],"usage":{"total_tokens":5}}\n\n',
        ]
        client = DeepSeekClient()
        seen = []
        collected = ""
        async for chunk in client._iter_sse_content(frames, usage_sink=seen.append):
            collected += chunk
        assert collected == "ok"
        assert seen == [{"total_tokens": 5}]
