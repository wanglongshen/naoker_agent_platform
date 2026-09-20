import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from openai import APIError, APITimeoutError, AuthenticationError


def _make_request() -> httpx.Request:
    return httpx.Request("POST", "http://test")


def _auth_error(message: str) -> AuthenticationError:
    return AuthenticationError(message, response=httpx.Response(401, request=_make_request()), body=None)


def _timeout_error() -> APITimeoutError:
    return APITimeoutError(request=_make_request())


def _api_error(message: str, status_code: int) -> APIError:
    err = APIError(message, request=_make_request(), body=None)
    err.status_code = status_code
    return err


def _plan_steps(plan: dict) -> list | None:
    """模型对顶层键名不固定（plan/steps），取第一个列表字段作为步骤。"""
    for value in plan.values():
        if isinstance(value, list):
            return value
    return None

from app.core.config import get_settings
from app.services.agent.llm import (
    DeepSeekClient,
    ProviderAuthenticationError,
    ProviderResponseError,
    RetryableStreamingError,
)
from app.services.langchain_demo.client import LangChainClient
from app.services.langchain_demo.samples import SAMPLES


class FakeChatModel:
    """契约层 fake：astream/ainvoke 返回预定义 chunk；可注入异常。"""

    def __init__(self, chunks=None, error=None, name=None):
        self._chunks = chunks if chunks is not None else [{"content": "hello", "usage": None}]
        self._error = error
        self.name = name
        self.client = None  # 与 ChatOpenAI 的 .client.close() 契约对齐

    async def astream(self, messages):
        if self._error:
            raise self._error
        for item in self._chunks:
            usage = None
            if item.get("usage"):
                usage = {
                    "input_tokens": item["usage"]["prompt_tokens"],
                    "output_tokens": item["usage"]["completion_tokens"],
                    "total_tokens": item["usage"]["total_tokens"],
                }
            yield AIMessageChunk(content=item["content"], usage_metadata=usage)

    async def ainvoke(self, messages):
        if self._error:
            raise self._error
        return AIMessage(content="".join(i["content"] for i in self._chunks))


@pytest.fixture
def client(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(settings, "deepseek_base_url", "http://test")
    monkeypatch.setattr(settings, "deepseek_model", "deepseek-chat")
    c = LangChainClient()
    c._llm = FakeChatModel(name="plain")
    c._plan_llm = FakeChatModel(name="plan")
    return c


class TestSignatureParity:
    def test_three_methods_exist_with_matching_params(self):
        import inspect

        lc = LangChainClient
        assert {"stream_text", "complete", "create_plan", "close"} <= set(dir(lc))
        assert list(inspect.signature(lc.stream_text).parameters) == ["self", "messages", "usage_sink"]
        assert list(inspect.signature(lc.complete).parameters) == ["self", "messages"]
        assert list(inspect.signature(lc.create_plan).parameters) == ["self", "messages"]

    def test_exceptions_reused_from_production_llm(self):
        from app.services.langchain_demo import client as lc_module

        assert lc_module.ProviderAuthenticationError is ProviderAuthenticationError
        assert lc_module.ProviderResponseError is ProviderResponseError
        assert lc_module.RetryableStreamingError is RetryableStreamingError


class TestStreamText:
    @pytest.mark.anyio
    async def test_yields_chunks_in_order(self, client):
        client._llm = FakeChatModel(
            chunks=[{"content": "你好", "usage": None}, {"content": "世界", "usage": None}]
        )
        got = [chunk async for chunk in client.stream_text([{"role": "user", "content": "hi"}])]
        assert got == ["你好", "世界"]

    @pytest.mark.anyio
    async def test_usage_sink_receives_mapped_usage(self, client):
        client._llm = FakeChatModel(
            chunks=[
                {"content": "a", "usage": None},
                {"content": "b", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            ]
        )
        sink = []
        async for _ in client.stream_text([{"role": "user", "content": "hi"}], usage_sink=sink.append):
            pass
        assert sink == [{"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}]

    @pytest.mark.anyio
    async def test_empty_api_key_raises_value_error(self, monkeypatch):
        # patch client 模块级 settings（client.py 绑定 import 时的单例），
        # 避免 test_alembic_config 的 cache_clear 导致实例错位（同 loop.py 的坑）
        import app.services.langchain_demo.client as lc_module

        monkeypatch.setattr(lc_module.settings, "deepseek_api_key", "")
        c = LangChainClient()
        with pytest.raises(ValueError):
            async for _ in c.stream_text([{"role": "user", "content": "hi"}]):
                pass

    @pytest.mark.anyio
    async def test_auth_error_mapped(self, client):
        client._llm = FakeChatModel(error=_auth_error("nope"))
        with pytest.raises(ProviderAuthenticationError):
            async for _ in client.stream_text([{"role": "user", "content": "hi"}]):
                pass

    @pytest.mark.anyio
    async def test_timeout_error_mapped(self, client):
        client._llm = FakeChatModel(error=_timeout_error())
        with pytest.raises(RetryableStreamingError):
            async for _ in client.stream_text([{"role": "user", "content": "hi"}]):
                pass


class TestMapError:
    def test_auth(self):
        assert isinstance(LangChainClient._map_error(_auth_error("x")), ProviderAuthenticationError)

    def test_timeout(self):
        assert isinstance(LangChainClient._map_error(_timeout_error()), RetryableStreamingError)

    def test_api_4xx_means_response_error(self):
        err = _api_error("bad", 400)
        assert isinstance(LangChainClient._map_error(err), ProviderResponseError)

    def test_api_429_means_retryable(self):
        err = _api_error("limit", 429)
        assert isinstance(LangChainClient._map_error(err), RetryableStreamingError)

    def test_unknown_error_retryable(self):
        assert isinstance(LangChainClient._map_error(RuntimeError("boom")), RetryableStreamingError)


class TestComplete:
    @pytest.mark.anyio
    async def test_returns_joined_content(self, client):
        client._llm = FakeChatModel(
            chunks=[{"content": "one ", "usage": None}, {"content": "two", "usage": None}]
        )
        assert await client.complete([{"role": "user", "content": "hi"}]) == "one two"


class TestCreatePlan:
    @pytest.mark.anyio
    async def test_parses_valid_json(self, client):
        client._plan_llm = FakeChatModel(
            chunks=[{"content": '{"plan": [{"action": "read_file"}]}', "usage": None}]
        )
        result = await client.create_plan([{"role": "user", "content": "plan it"}])
        assert result == {"plan": [{"action": "read_file"}]}

    @pytest.mark.anyio
    async def test_truncated_json_recovered(self, client):
        # 模拟 LLM 截断输出（对象未闭合）——生产 _parse_json_content 的自动补全必须可用
        # 注意：补全算法先补 ] 再补 }，嵌套数组内截断会错位，故用无数组嵌套的对象截断用例
        client._plan_llm = FakeChatModel(
            chunks=[{"content": '{"plan": {"title": "杭州两日游", "steps": 3', "usage": None}]
        )
        result = await client.create_plan([{"role": "user", "content": "plan it"}])
        assert result["plan"]["title"] == "杭州两日游"
        assert result["plan"]["steps"] == 3

    @pytest.mark.anyio
    async def test_non_json_content_raises_value_error(self, client):
        client._plan_llm = FakeChatModel(chunks=[{"content": "今天天气不错", "usage": None}])
        with pytest.raises(ValueError):
            await client.create_plan([{"role": "user", "content": "plan it"}])

    @pytest.mark.anyio
    async def test_api_error_mapped(self, client):
        client._plan_llm = FakeChatModel(error=_auth_error("nope"))
        with pytest.raises(ProviderAuthenticationError):
            await client.create_plan([{"role": "user", "content": "plan it"}])

    @pytest.mark.anyio
    async def test_plan_mode_only_for_create_plan(self, client):
        called: list[str] = []
        for attr in ("_llm", "_plan_llm"):
            model = getattr(client, attr)
            orig = model.ainvoke
            name = model.name

            async def recording(messages, _orig=orig, _name=name):
                called.append(_name)
                return await _orig(messages)

            model.ainvoke = recording
        client._plan_llm._chunks = [{"content": '{"plan": []}', "usage": None}]
        await client.create_plan([{"role": "user", "content": "plan it"}])
        assert called == ["plan"]


@pytest.mark.skipif(not get_settings().deepseek_api_key, reason="DEEPSEEK_API_KEY not configured")
class TestRealCalls:
    """真实调用层：双客户端各跑一遍，验证 usage 一致性与 JSON 可用性。"""

    @pytest.mark.anyio
    async def test_stream_usage_parity(self):
        prod = DeepSeekClient()
        lc = LangChainClient()
        try:
            prod_usage: list[dict] = []
            lc_usage: list[dict] = []
            async for _ in prod.stream_text(SAMPLES["qa"]["messages"], usage_sink=prod_usage.append):
                pass
            async for _ in lc.stream_text(SAMPLES["qa"]["messages"], usage_sink=lc_usage.append):
                pass
            assert prod_usage, "生产侧未采集到 usage（DeepSeek 未返回 include_usage 数据）"
            assert lc_usage, "langchain 侧未采集到 usage（stream_usage 透传失败）"
            last_prod = prod_usage[-1]
            last_lc = lc_usage[-1]
            # prompt_tokens 与输入严格绑定，不受输出随机性影响——两侧必须完全一致
            assert last_prod["prompt_tokens"] == last_lc["prompt_tokens"], (
                f"prompt_tokens 不一致: prod={last_prod['prompt_tokens']} langchain={last_lc['prompt_tokens']}"
            )
            # completion_tokens 随模型输出随机性波动（temperature=0.1），只做同量级断言
            assert abs(last_prod["completion_tokens"] - last_lc["completion_tokens"]) <= max(
                5, last_prod["completion_tokens"] * 0.5
            ), f"completion_tokens 差异过大: prod={last_prod['completion_tokens']} langchain={last_lc['completion_tokens']}"
        finally:
            await prod.close()
            await lc.close()

    @pytest.mark.anyio
    async def test_create_plan_parses(self):
        prod = DeepSeekClient()
        lc = LangChainClient()
        try:
            prod_plan = await prod.create_plan(SAMPLES["plan"]["messages"])
            lc_plan = await lc.create_plan(SAMPLES["plan"]["messages"])
            assert _plan_steps(prod_plan), f"prod 侧未解析出步骤列表: {prod_plan}"
            assert _plan_steps(lc_plan), f"langchain 侧未解析出步骤列表: {lc_plan}"
        finally:
            await prod.close()
            await lc.close()

    @pytest.mark.anyio
    async def test_complete_returns_text(self):
        prod = DeepSeekClient()
        lc = LangChainClient()
        try:
            prod_text = await prod.complete(SAMPLES["qa"]["messages"])
            lc_text = await lc.complete(SAMPLES["qa"]["messages"])
            assert len(prod_text) > 10 and len(lc_text) > 10
        finally:
            await prod.close()
            await lc.close()
