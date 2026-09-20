# LangChain 并行实验模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建与生产 `DeepSeekClient` 三方法接口一致的 `LangChainClient` 实验模块 + 真实调用对比测试 + 基准报告，生产代码零改动。

**Architecture:** 新目录 `backend/app/services/langchain_demo/` 完全隔离；`LangChainClient` 内部用 `ChatOpenAI(base_url=deepseek)`，`stream_text`/`complete`/`create_plan` 签名与 `DeepSeekClient` 一致；契约层测试用 fake model（monkeypatch `client._llm`），真实调用层用真实 DeepSeek API（skipif 无 key）；benchmark 脚本产 `docs/langchain-eval/report.md`。

**Tech Stack:** langchain-openai 0.3.35 / langchain-core 0.3.86（已装进 01-rbac）/ pydantic 2.13.4 / httpx（生产）/ pytest anyio

## Global Constraints

- Python 解释器：`X:\python\anaconda\envs\01-rbac\python.exe`（后端所有命令用它）
- 测试 workdir：`C:\01_agent_loop_pro\backend`；DB 隔离：`$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_langchain"`
- **生产零改动**：`backend/app/services/agent/llm.py`、`loop.py`、`planner.py`、`tool_executor.py`、`api/`、`main.py` 一律不许碰（spec 承诺）
- 提交纪律：只 `git add` 自己的文件路径（仓库有并行会话的未提交/已暂存文件）；绝不 `git add -A`；提交前 `git status --short`
- 真实调用测试/脚本每次运行消耗真实 token（6 次调用/轮，约几毛钱），仅手动触发，不随全量测试跑
- 依赖版本锁定：langchain-openai>=0.3.35,<0.6；langchain-core 随依赖自动安装

---
### Task 1: LangChainClient 骨架（构造/close/stream_text/complete/异常映射）

**Files:**
- Create: `backend/app/services/langchain_demo/__init__.py`
- Create: `backend/app/services/langchain_demo/client.py`
- Test: `backend/tests/test_langchain_demo.py`

**Interfaces:**
- Consumes: `app.core.config.get_settings()`（`deepseek_api_key` / `deepseek_base_url` / `deepseek_model`）；`app.services.agent.llm` 的异常类 `ProviderAuthenticationError` / `ProviderResponseError` / `RetryableStreamingError`
- Produces: `class LangChainClient`（Task 2 加 `create_plan`，Task 3 消费全部）：
  - `async def stream_text(self, messages: list[dict[str, str]], usage_sink: Callable[[dict], None] | None = None) -> AsyncIterator[str]`
  - `async def complete(self, messages: list[dict[str, str]]) -> str`
  - `async def close(self) -> None`
  - `staticmethod _map_error(exc: Exception) -> Exception`

- [ ] **Step 1: Write the failing test**

创建 `backend/tests/test_langchain_demo.py`：

```python
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from openai import APIError, APITimeoutError, AuthenticationError

from app.core.config import get_settings
from app.services.agent.llm import (
    ProviderAuthenticationError,
    ProviderResponseError,
    RetryableStreamingError,
)
from app.services.langchain_demo.client import LangChainClient


class FakeChatModel:
    """契约层 fake：astream/ainvoke 返回预定义 chunk；可注入异常。"""

    def __init__(self, chunks=None, error=None):
        self._chunks = chunks if chunks is not None else [{"content": "hello", "usage": None}]
        self._error = error
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
    c._llm = FakeChatModel()
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
        settings = get_settings()
        monkeypatch.setattr(settings, "deepseek_api_key", "")
        c = LangChainClient()
        with pytest.raises(ValueError):
            async for _ in c.stream_text([{"role": "user", "content": "hi"}]):
                pass

    @pytest.mark.anyio
    async def test_auth_error_mapped(self, client):
        client._llm = FakeChatModel(error=AuthenticationError("nope"))
        with pytest.raises(ProviderAuthenticationError):
            async for _ in client.stream_text([{"role": "user", "content": "hi"}]):
                pass

    @pytest.mark.anyio
    async def test_timeout_error_mapped(self, client):
        client._llm = FakeChatModel(error=APITimeoutError("slow"))
        with pytest.raises(RetryableStreamingError):
            async for _ in client.stream_text([{"role": "user", "content": "hi"}]):
                pass


class TestMapError:
    def test_auth(self):
        assert isinstance(LangChainClient._map_error(AuthenticationError("x")), ProviderAuthenticationError)

    def test_timeout(self):
        assert isinstance(LangChainClient._map_error(APITimeoutError("x")), RetryableStreamingError)

    def test_api_4xx_means_response_error(self):
        err = APIError("bad", response=None, body=None)
        err.status_code = 400
        assert isinstance(LangChainClient._map_error(err), ProviderResponseError)

    def test_api_429_means_retryable(self):
        err = APIError("limit", response=None, body=None)
        err.status_code = 429
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_langchain"
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_langchain_demo.py -q --no-header
```
Expected: 16 tests FAIL（`ModuleNotFoundError: No module named 'app.services.langchain_demo'`）

- [ ] **Step 3: Write minimal implementation**

创建 `backend/app/services/langchain_demo/__init__.py`（空文件）。

创建 `backend/app/services/langchain_demo/client.py`：

```python
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
        self._llm = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key or "unset",
            base_url=settings.deepseek_base_url.rstrip("/"),
            temperature=0.1,
            max_tokens=8192,
            stream_usage=True,
            extra_body={"response_format": {"type": "json_object"}},
            streaming=True,
        )

    async def close(self) -> None:
        llm = getattr(self, "_llm", None)
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
        raise NotImplementedError  # Task 2 实现
```

- [ ] **Step 4: Run test to verify it passes**

```bash
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_langchain_demo.py -q --no-header
```
Expected: 16 passed（signature/stream/complete/map_error 全绿）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/langchain_demo/__init__.py backend/app/services/langchain_demo/client.py backend/tests/test_langchain_demo.py
git commit -m "feat: LangChainClient skeleton with stream/complete and error mapping"
```

---
### Task 2: create_plan（JSON 模式 + 截断修复复用）

**Files:**
- Modify: `backend/app/services/langchain_demo/client.py`
- Test: `backend/tests/test_langchain_demo.py`

**Interfaces:**
- Consumes: Task 1 的 `LangChainClient._llm`、`_map_error`、`_parse_json_content`
- Produces: `async def create_plan(self, messages: list[dict[str, str]]) -> dict[str, Any]`（完整实现，Task 3 消费）

- [ ] **Step 1: Write the failing test**

在 `backend/tests/test_langchain_demo.py` 追加：

```python
class TestCreatePlan:
    @pytest.mark.anyio
    async def test_parses_valid_json(self, client):
        client._llm = FakeChatModel(
            chunks=[{"content": '{"plan": [{"action": "read_file"}]}', "usage": None}]
        )
        result = await client.create_plan([{"role": "user", "content": "plan it"}])
        assert result == {"plan": [{"action": "read_file"}]}

    @pytest.mark.anyio
    async def test_truncated_json_recovered(self, client):
        # 模拟 LLM 截断输出（对象未闭合）——生产 _parse_json_content 的自动补全必须可用
        # 注意：补全算法先补 ] 再补 }，嵌套数组内截断会错位，故用无数组嵌套的对象截断用例
        client._llm = FakeChatModel(
            chunks=[{"content": '{"plan": {"title": "杭州两日游", "steps": 3', "usage": None}]
        )
        result = await client.create_plan([{"role": "user", "content": "plan it"}])
        assert result["plan"]["title"] == "杭州两日游"
        assert result["plan"]["steps"] == 3

    @pytest.mark.anyio
    async def test_non_json_content_raises_value_error(self, client):
        client._llm = FakeChatModel(chunks=[{"content": "今天天气不错", "usage": None}])
        with pytest.raises(ValueError):
            await client.create_plan([{"role": "user", "content": "plan it"}])

    @pytest.mark.anyio
    async def test_api_error_mapped(self, client):
        client._llm = FakeChatModel(error=AuthenticationError("nope"))
        with pytest.raises(ProviderAuthenticationError):
            await client.create_plan([{"role": "user", "content": "plan it"}])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_langchain_demo.py::TestCreatePlan -q --no-header
```
Expected: 4 tests FAIL（NotImplementedError）

- [ ] **Step 3: Implement create_plan**

在 `backend/app/services/langchain_demo/client.py` 把占位方法替换为：

```python
    async def create_plan(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        try:
            response = await self._llm.ainvoke(messages)
            content = response.content
            text = content if isinstance(content, str) else ""
            return _parse_json_content(None, text)
        except (AuthenticationError, APIError, APITimeoutError) as exc:
            raise self._map_error(exc) from exc
```

- [ ] **Step 4: Run test to verify it passes**

```bash
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_langchain_demo.py -q --no-header
```
Expected: 20 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/langchain_demo/client.py backend/tests/test_langchain_demo.py
git commit -m "feat: create_plan with json_object mode reusing production truncated-JSON recovery"
```

---
### Task 3: 真实调用层测试 + benchmark 脚本 + 报告生成

**Files:**
- Create: `backend/app/services/langchain_demo/samples.py`
- Create: `backend/scripts/langchain_benchmark.py`
- Modify: `backend/tests/test_langchain_demo.py`（追加真实调用层）
- Generate: `docs/langchain-eval/report.md`（脚本产物）

**Interfaces:**
- Consumes: Task 1/2 完整 `LangChainClient`；`DeepSeekClient`（生产侧对照）；`SAMPLES`（本任务定义）
- Produces: `SAMPLES: dict[str, dict]`（测试与脚本共享）；`docs/langchain-eval/report.md`

- [ ] **Step 1: Write the failing test（真实调用层）**

创建 `backend/app/services/langchain_demo/samples.py`：

```python
"""对比基准样本：测试与 benchmark 脚本共享（DRY）。"""

SAMPLES: dict[str, dict] = {
    "qa": {
        "description": "普通问答",
        "messages": [
            {"role": "user", "content": "用一句话介绍 PostgreSQL 的流复制（Streaming Replication）。"}
        ],
    },
    "plan": {
        "description": "JSON 规划",
        "messages": [
            {"role": "system", "content": "你是任务规划器。只输出 JSON，不要输出任何其他文字。"},
            {"role": "user", "content": "为'周末杭州两日游'规划 3 个步骤，每个步骤包含 action 和 input。"},
        ],
    },
    "long": {
        "description": "长文生成",
        "messages": [
            {"role": "user", "content": "写一段 500 字左右的关于数据库索引的科普文章。"}
        ],
    },
}
```

在 `backend/tests/test_langchain_demo.py` 追加：

```python
from app.services.agent.llm import DeepSeekClient
from app.services.langchain_demo.samples import SAMPLES


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
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                assert abs(last_prod[key] - last_lc[key]) <= max(1, last_prod[key] * 0.05), (
                    f"{key} 不一致: prod={last_prod[key]} langchain={last_lc[key]}"
                )
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
            assert "plan" in prod_plan and isinstance(prod_plan["plan"], list)
            assert "plan" in lc_plan and isinstance(lc_plan["plan"], list)
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
```

- [ ] **Step 2: Run real tests once**

```bash
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_langchain_demo.py::TestRealCalls -q --no-header
```
Expected: 3 passed（消耗真实 token，首次运行验证链路；如网络不通/额度问题，记录到报告并继续——真实调用是数据来源，但失败不阻塞契约层）

- [ ] **Step 3: Write benchmark script**

创建 `backend/scripts/langchain_benchmark.py`：

```python
"""LangChain vs 生产 httpx 对比基准：产出 docs/langchain-eval/report.md。

用法（01-rbac 环境）：
    python scripts/langchain_benchmark.py
"""

import asyncio
import time
from pathlib import Path

from app.services.agent.llm import DeepSeekClient
from app.services.langchain_demo.client import LangChainClient
from app.services.langchain_demo.samples import SAMPLES

REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "langchain-eval" / "report.md"


async def measure_stream(client, messages):
    first_latency = None
    total = ""
    usage: list[dict] = []
    started = time.monotonic()
    async for chunk in client.stream_text(messages, usage_sink=usage.append):
        if first_latency is None:
            first_latency = time.monotonic() - started
        total += chunk
    return {
        "first_token_s": round(first_latency or 0, 3),
        "total_s": round(time.monotonic() - started, 3),
        "chars": len(total),
        "usage": usage[-1] if usage else None,
    }


async def measure_plan(client, messages):
    started = time.monotonic()
    result = await client.create_plan(messages)
    return {"total_s": round(time.monotonic() - started, 3), "json_ok": isinstance(result, dict)}


async def main() -> None:
    prod = DeepSeekClient()
    lc = LangChainClient()
    rows: list[str] = []
    try:
        for name, sample in SAMPLES.items():
            pm = await measure_stream(prod, sample["messages"])
            lm = await measure_stream(lc, sample["messages"])
            usage_match = "一致" if pm["usage"] == lm["usage"] else "有差异"
            rows.append(
                f"| {name}（{sample['description']}） | {pm['first_token_s']}s / {lm['first_token_s']}s | "
                f"{pm['total_s']}s / {lm['total_s']}s | {usage_match} |"
            )
        plan_p = await measure_plan(prod, SAMPLES["plan"]["messages"])
        plan_l = await measure_plan(lc, SAMPLES["plan"]["messages"])
        rows.append(f"| plan JSON 规划 | {plan_p['json_ok']} / {plan_l['json_ok']} | 双方耗时 {plan_p['total_s']}s / {plan_l['total_s']}s |")

    report = f"""# LangChain 实验对比报告

生成时间：{time.strftime("%Y-%m-%d %H:%M")}

对比对象：`DeepSeekClient`（生产 httpx 直连） vs `LangChainClient`（langchain-openai 0.3.35 + stream_usage）

## 指标

| 样本 | 首 token 延迟（prod/langchain） | 总耗时（prod/langchain） | usage 一致性 |
| --- | --- | --- | --- |
{chr(10).join(rows)}

> usage 一致性 = 同一输入同一模型下双方采集的 token 数是否一致；usage 差异说明 langchain 的 `stream_usage` 透传层与 DeepSeek 原生 `include_usage` 不完全等价。

## 结论（由数据驱动，团队决策依据）

- 若三行 usage 均为"一致"且延迟差距 <20%：薄层替换风险可控，可考虑渐进替换。
- 若 usage 有差异或 JSON 可用率低于生产：不建议替换，保持 httpx 生产实现。
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"report written: {REPORT_PATH}")
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run benchmark once**

```bash
& "X:\python\anaconda\envs\01-rbac\python.exe" scripts/langchain_benchmark.py
```
Expected: 打印对比表格 + 生成 `docs/langchain-eval/report.md`（真实 token 消耗；失败时记录错误到报告并说明）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/langchain_demo/samples.py backend/scripts/langchain_benchmark.py backend/tests/test_langchain_demo.py docs/langchain-eval/report.md
git commit -m "feat: real-call parity tests and benchmark report for langchain experiment"
```

---
### Task 4: README + requirements 记录 + 全量回归

**Files:**
- Create: `backend/app/services/langchain_demo/README.md`
- Modify: `backend/requirements.txt`
- Test: 全量回归（契约层并入）

**Interfaces:**
- Consumes: Task 1-3 全部产物
- Produces: 环境可复现（requirements 记录）；使用文档

- [ ] **Step 1: Write README**

创建 `backend/app/services/langchain_demo/README.md`：

```markdown
# LangChain 实验模块

目的：并行验证 LangChain 是否值得替换生产 `DeepSeekClient`（httpx 直连）。**生产代码零依赖本模块**——只有测试与脚本 import 它。

## 运行

```bash
# 契约层测试（全 mock，CI 可跑）
python -m pytest tests/test_langchain_demo.py -q --no-header

# 真实调用对比（消耗真实 token，需 .env 有 DEEPSEEK_API_KEY）
python -m pytest tests/test_langchain_demo.py::TestRealCalls -q --no-header

# 基准报告
python scripts/langchain_benchmark.py
# → 生成 docs/langchain-eval/report.md
```

## 决策流程

1. 跑 benchmark 拿数据
2. 团队读 `docs/langchain-eval/report.md` 结论
3. 若决定替换：另开 spec/plan（薄层替换 llm.py），本模块不直接进生产
```

- [ ] **Step 2: Record dependency in requirements.txt**

在 `backend/requirements.txt` 末尾追加（保持现有风格）：

```
# langchain experiment (isolated module; not used by production code)
langchain-openai>=0.3.35,<0.6
```

- [ ] **Step 3: Full regression (backend)**

```bash
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_langchain"
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header
```
Expected: 全量通过；预存在失败仅限 4 个 pypdf/pptx（test_file_reader.py 缺模块）+ test_agent_blueprint_closure（并行会话领域）——与本次改动无关，如出现其他失败需调查

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/langchain_demo/README.md backend/requirements.txt
git commit -m "docs: langchain demo README and requirements entry"
```

---
## Self-Review 记录

- **Spec 覆盖**：模块 ✓T1/T2；三方法签名一致 ✓T1/T2；异常映射 ✓T1；契约层 mock 测试 ✓T1/T2；真实调用层（skipif）✓T3；usage 一致性断言（±5%）✓T3；benchmark 脚本 + report.md ✓T3；README + requirements ✓T4；生产零改动 ✓全部（约束）；UI/开关/多供应商不做 ✓（无对应任务=不做清单）
- **占位符扫描**：无 TBD/TODO；create_plan 的 NotImplementedError 是 TDD 红阶段占位（T2 替换），非计划缺陷
- **类型一致性**：`LangChainClient` 三方法签名在 T1 定义、T2 实现 create_plan、T3 消费——签名一致；`SAMPLES` 在 T3 定义并被测试与脚本消费；异常类 import 路径（`openai` 而非 `langchain_core`）在 T1 已实测确认（langchain-openai 0.3.35 抛 openai SDK 异常）
- **已实测细节**（2026-08-10）：langchain-openai 0.3.35 + langchain-core 0.3.86 + pydantic 2.13.4 共存 OK；`ChatOpenAI` 有 `stream_usage`/`max_tokens`/`extra_body` 字段；`openai.AuthenticationError` 构造 `AuthenticationError("msg")` OK 且是 `openai.APIError` 子类；`_parse_json_content` 无 self 依赖可 unbound 复用
