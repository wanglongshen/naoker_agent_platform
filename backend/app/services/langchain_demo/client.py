from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from langchain_openai import ChatOpenAI
from openai import APIError, APITimeoutError, AuthenticationError

from app.core.config import get_settings
from app.services.agent.llm import (
    DeepSeekClient,
    ProviderAuthenticationError,
    ProviderResponseError,
    RetryableStreamingError,
)

settings = get_settings()

# 复用生产 JSON 容错解析（_parse_json_content 不依赖 self，可 unbound 调用）
_parse_json_content = DeepSeekClient._parse_json_content


class LangChainClient:
    """与 DeepSeekClient 三方法签名一致的 LangChain 实验实现。"""

    def __init__(self) -> None:
        common = dict(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key or "unset",
            base_url=settings.deepseek_base_url.rstrip("/"),
            temperature=0.1,
            max_tokens=8192,
            stream_usage=True,
            streaming=True,
        )
        self._llm = ChatOpenAI(**common)
        self._plan_llm = ChatOpenAI(
            **common, extra_body={"response_format": {"type": "json_object"}}
        )

    async def close(self) -> None:
        for attr in ("_llm", "_plan_llm"):
            llm = getattr(self, attr, None)
            client = getattr(llm, "client", None)
            if client is not None and hasattr(client, "close"):
                await client.close()

    @staticmethod
    def _map_error(exc: Exception) -> Exception:
        if isinstance(exc, AuthenticationError):
            return ProviderAuthenticationError("deepseek_auth_error")
        if isinstance(exc, APITimeoutError):
            return RetryableStreamingError("deepseek_timeout")
        if isinstance(exc, APIError):
            status = getattr(exc, "status_code", None)
            if status in {400, 404, 422}:
                return ProviderResponseError("deepseek_request_rejected")
            return RetryableStreamingError(f"deepseek_retryable_status: {status}")
        return RetryableStreamingError(f"langchain_error: {type(exc).__name__}")

    async def stream_text(
        self,
        messages: list[dict[str, str]],
        usage_sink: Callable[[dict], None] | None = None,
    ) -> AsyncIterator[str]:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        try:
            async for chunk in self._llm.astream(messages):
                usage = getattr(chunk, "usage_metadata", None)
                if usage is not None and usage_sink is not None:
                    usage_sink(
                        {
                            "prompt_tokens": usage.get("input_tokens", 0),
                            "completion_tokens": usage.get("output_tokens", 0),
                            "total_tokens": usage.get("total_tokens", 0),
                        }
                    )
                content = chunk.content
                if isinstance(content, str) and content:
                    yield content
        except (AuthenticationError, APIError, APITimeoutError) as exc:
            raise self._map_error(exc) from exc

    async def complete(self, messages: list[dict[str, str]]) -> str:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        try:
            response = await self._llm.ainvoke(messages)
            content = response.content
            return content if isinstance(content, str) else ""
        except (AuthenticationError, APIError, APITimeoutError) as exc:
            raise self._map_error(exc) from exc

    async def create_plan(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        try:
            response = await self._plan_llm.ainvoke(messages)
            content = response.content
            text = content if isinstance(content, str) else ""
            return _parse_json_content(None, text)
        except (AuthenticationError, APIError, APITimeoutError) as exc:
            raise self._map_error(exc) from exc
