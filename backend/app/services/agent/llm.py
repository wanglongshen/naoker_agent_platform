from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Callable, Iterable

import httpx

from app.core.config import get_settings

settings = get_settings()
_DEEPSEEK_MAX_CONNECTIONS = 20
_DEEPSEEK_MAX_KEEPALIVE = 10


class RetryablePlannerError(Exception):
    pass


class RetryableStreamingError(Exception):
    pass


class ProviderConfigurationError(Exception):
    pass


class ProviderAuthenticationError(Exception):
    pass


class ProviderResponseError(Exception):
    pass


class DeepSeekClient:
    def __init__(self) -> None:
        limits = httpx.Limits(
            max_connections=_DEEPSEEK_MAX_CONNECTIONS,
            max_keepalive_connections=_DEEPSEEK_MAX_KEEPALIVE,
        )
        self._client = httpx.AsyncClient(limits=limits)
        from app.services.agent.llm_recorder import recorder_from_env

        self._recorder = recorder_from_env()

    async def close(self) -> None:
        await self._client.aclose()

    async def create_plan(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if self._recorder is not None and self._recorder.mode == "replay":
            return self._recorder.replay_plan(messages)

        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "max_tokens": 8192,
        }
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._client.post(url, headers=headers, json=payload, timeout=settings.http_timeout_seconds)
        except httpx.TimeoutException as exc:
            raise RetryablePlannerError("deepseek_timeout") from exc
        except httpx.RequestError as exc:
            raise RetryablePlannerError("deepseek_request_error") from exc

        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError("deepseek_auth_error")
        if response.status_code in {400, 404, 422}:
            raise ProviderResponseError("deepseek_request_rejected")
        if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
            raise RetryablePlannerError(f"deepseek_retryable_status: {response.status_code}")

        response.raise_for_status()
        data = response.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Invalid DeepSeek response structure") from exc

        if not isinstance(content, str):
            raise ValueError("DeepSeek content must be a string")

        parsed = self._parse_json_content(content)
        if self._recorder is not None and self._recorder.mode == "record":
            self._recorder.record_plan(messages, parsed)
            self._recorder.save()
        return parsed

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        normalized = content.strip()

        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            pass

        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", normalized, re.DOTALL)
        if fenced_match:
            fenced_json = fenced_match.group(1)
            try:
                return json.loads(fenced_json)
            except json.JSONDecodeError:
                pass

        first_brace = normalized.find("{")
        last_brace = normalized.rfind("}")
        if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
            candidate = normalized[first_brace : last_brace + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # Truncated JSON recovery: auto-close unclosed braces and strings
        if first_brace != -1 and (last_brace == -1 or last_brace < first_brace):
            candidate = normalized[first_brace:]
            open_braces = candidate.count("{") - candidate.count("}")
            open_brackets = candidate.count("[") - candidate.count("]")
            # Check if inside an unclosed string
            in_string = False
            escape = False
            for ch in candidate:
                if escape: escape = False; continue
                if ch == "\\": escape = True; continue
                if ch == '"': in_string = not in_string
            if in_string:
                candidate += '"'
            candidate += "]" * max(0, open_brackets)
            candidate += "}" * max(0, open_braces)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        raise ValueError("DeepSeek returned non-JSON content")

    async def _iter_sse_content(
        self,
        frames: Iterable[str],
        usage_sink: Callable[[dict], None] | None = None,
    ) -> AsyncIterator[str]:
        for frame in frames:
            for line in frame.splitlines():
                if not line.startswith("data: "):
                    continue

                payload = line.removeprefix("data: ").strip()
                if payload == "[DONE]":
                    return

                data = json.loads(payload)
                if usage_sink is not None and data.get("usage"):
                    usage_sink(data["usage"])
                chunk = data.get("choices", [{}])[0].get("delta", {}).get("content")
                if isinstance(chunk, str) and chunk:
                    yield chunk

    async def stream_text(
        self,
        messages: list[dict[str, str]],
        usage_sink: Callable[[dict], None] | None = None,
    ) -> AsyncIterator[str]:
        if self._recorder is not None and self._recorder.mode == "replay":
            self._recorder.bind_usage_sink(usage_sink)
            async for chunk in self._recorder.replay_stream(messages):
                yield chunk
            return

        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.deepseek_model,
            "messages": messages,
            "temperature": 0.1,
            "stream": True,
            "max_tokens": 8192,
            "stream_options": {"include_usage": True},
        }
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }

        recorded_chunks: list[str] = []
        recorded_usages: list[dict] = []

        def _record_usage(usage: dict) -> None:
            recorded_usages.append(usage)
            if usage_sink is not None:
                usage_sink(usage)

        try:
            async with self._client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code in {401, 403}:
                    raise ProviderAuthenticationError("deepseek_auth_error")
                if response.status_code in {400, 404, 422}:
                    raise ProviderResponseError("deepseek_request_rejected")
                if response.status_code in {408, 425, 429, 500, 502, 503, 504}:
                    raise RetryableStreamingError(f"deepseek_retryable_status: {response.status_code}")

                response.raise_for_status()
                async for line in response.aiter_lines():
                    async for chunk in self._iter_sse_content([line], usage_sink=_record_usage):
                        recorded_chunks.append(chunk)
                        yield chunk
            if self._recorder is not None and self._recorder.mode == "record":
                self._recorder.record_stream(messages, recorded_chunks, recorded_usages)
                self._recorder.save()
        except httpx.TimeoutException as exc:
            raise RetryableStreamingError("deepseek_timeout") from exc
        except httpx.RequestError as exc:
            raise RetryableStreamingError("deepseek_request_error") from exc

    async def complete(self, messages: list[dict[str, str]]) -> str:
        """非流式完整响应（内部走流式收集）。"""
        chunks: list[str] = []
        async for chunk in self.stream_text(messages):
            chunks.append(chunk)
        return "".join(chunks)
