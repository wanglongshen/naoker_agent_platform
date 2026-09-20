from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentRunCreate
from app.services.agent import AgentLoopService, ResearchPlanner, RetryableToolError, ToolExecutor


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    ("action", "expected_type"),
    [
        ({"type": "web_search", "input": {"query": "python", "max_results": 3}}, "web_search"),
        ({"type": "http_request", "input": {"method": "GET", "url": "https://example.com"}}, "http_request"),
        ({"type": "extract_web_content", "input": {"url": "https://example.com/page"}}, "extract_web_content"),
        ({"type": "calculator", "input": {"expression": "2 + 3 * 4"}}, "calculator"),
        ({"type": "finish", "input": {}}, "finish"),
    ],
)
def test_planner_validates_supported_actions(action: dict, expected_type: str):
    parsed = ResearchPlanner()._validate_plan({"thought_summary": "next", "action": action})

    assert parsed.action.type == expected_type


@pytest.mark.parametrize(
    "action",
    [
        {"type": "web_search", "input": {"query": "", "max_results": 3}},
        {"type": "web_search", "input": {"query": "python", "max_results": 100}},
        {"type": "http_request", "input": {"method": "DELETE", "url": "https://example.com"}},
        {"type": "extract_web_content", "input": {"url": "file:///etc/passwd"}},
        {"type": "calculator", "input": {"expression": ""}},
    ],
)
def test_planner_rejects_invalid_action_inputs(action: dict):
    from app.services.agent.llm import RetryablePlannerError

    with pytest.raises(RetryablePlannerError):
        ResearchPlanner()._validate_plan({"thought_summary": "next", "action": action})


def test_planner_prompt_disables_network_actions():
    messages = ResearchPlanner()._build_messages("calculate", 0, None, web_enabled=False)
    prompt = "\n".join(message["content"] for message in messages)

    assert "calculator" in prompt
    assert "finish" in prompt
    assert "禁止" in prompt
    assert "web_search" in prompt


def test_planner_final_step_requires_finish_and_http_is_get_only():
    messages = ResearchPlanner()._build_messages(
        "research", 2, {"text": "facts"}, web_enabled=True, final_step=True
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "必须选择 finish" in prompt
    from app.services.agent.llm import RetryablePlannerError

    with pytest.raises(RetryablePlannerError):
        ResearchPlanner()._validate_plan(
            {
                "thought_summary": "post",
                "action": {
                    "type": "http_request",
                    "input": {"method": "POST", "url": "https://example.com", "body": {"token": "secret"}},
                },
            }
        )


def test_safe_search_url_strips_embedded_credentials_and_fragment():
    from app.services.agent.tool_executor import _safe_http_url

    assert _safe_http_url("https://user:password@example.com/path?q=1#secret") == (
        "https://example.com/path?q=1"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1/private",
        "http://10.0.0.8/private",
        "http://172.16.0.8/private",
        "http://192.168.1.8/private",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/private",
    ],
)
def test_safe_http_url_rejects_local_and_private_network_targets(url: str):
    from app.services.agent.tool_executor import _safe_http_url

    assert _safe_http_url(url) is None


@pytest.mark.anyio
async def test_dns_validation_accepts_only_when_every_address_is_global(monkeypatch: pytest.MonkeyPatch):
    from app.services.agent import tool_executor

    loop = asyncio.get_running_loop()
    resolve = AsyncMock(
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)),
        ]
    )
    monkeypatch.setattr(loop, "getaddrinfo", resolve)

    await tool_executor._validate_resolved_target("https://example.com/path")

    resolve.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1"])
async def test_dns_validation_rejects_any_non_global_address(
    monkeypatch: pytest.MonkeyPatch, address: str
):
    from app.services.agent import tool_executor

    loop = asyncio.get_running_loop()
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
    monkeypatch.setattr(
        loop,
        "getaddrinfo",
        AsyncMock(return_value=[(family, socket.SOCK_STREAM, 6, "", sockaddr)]),
    )

    with pytest.raises(RetryableToolError, match="unsafe_network_target"):
        await tool_executor._validate_resolved_target("https://attacker.example/path")


@pytest.mark.anyio
async def test_dns_validation_rejects_mixed_public_and_private_answers(monkeypatch: pytest.MonkeyPatch):
    from app.services.agent import tool_executor

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop,
        "getaddrinfo",
        AsyncMock(
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
            ]
        ),
    )

    with pytest.raises(RetryableToolError, match="unsafe_network_target"):
        await tool_executor._validate_resolved_target("https://mixed.example/path")


@pytest.mark.anyio
async def test_dns_validation_allows_non_global_when_override_enabled(monkeypatch: pytest.MonkeyPatch):
    """web_tool_allow_non_global_targets=true（默认关闭，仅录制/本地环境）时放行非公网解析。"""
    from app.services.agent import tool_executor

    monkeypatch.setattr(tool_executor.settings, "web_tool_allow_non_global_targets", True)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop,
        "getaddrinfo",
        AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.5", 443))]),
    )

    await tool_executor._validate_resolved_target("https://api.tavily.com/search")


@pytest.mark.anyio
async def test_dns_validation_override_defaults_off(monkeypatch: pytest.MonkeyPatch):
    from app.services.agent import tool_executor

    monkeypatch.setattr(tool_executor.settings, "web_tool_allow_non_global_targets", False)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop,
        "getaddrinfo",
        AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.5", 443))]),
    )

    with pytest.raises(RetryableToolError, match="unsafe_network_target"):
        await tool_executor._validate_resolved_target("https://api.tavily.com/search")


@pytest.mark.anyio
async def test_redirect_target_is_dns_validated_before_second_request(monkeypatch: pytest.MonkeyPatch):
    from app.services.agent import tool_executor

    first = httpx.Response(
        302,
        headers={"location": "http://private.example/admin"},
        request=httpx.Request("GET", "https://public.example/start"),
    )
    client = SimpleNamespace(request=AsyncMock(return_value=first))
    validate = AsyncMock(side_effect=[None, RetryableToolError("unsafe_network_target")])
    monkeypatch.setattr(tool_executor, "_validate_resolved_target", validate)

    with pytest.raises(RetryableToolError, match="unsafe_network_target"):
        await tool_executor._request_without_forbidden_redirects(client, "GET", "https://public.example/start", None)

    assert client.request.await_count == 1
    assert validate.await_args_list[1].args[0] == "http://private.example/admin"


@pytest.mark.anyio
@pytest.mark.parametrize("action_type", ["web_search", "http_request", "extract_web_content"])
async def test_networking_policy_rejects_before_http_client_creation(
    monkeypatch: pytest.MonkeyPatch, action_type: str
):
    def fail_client(*args, **kwargs):
        raise AssertionError("HTTP client must not be created")

    monkeypatch.setattr(httpx, "AsyncClient", fail_client)
    action_input = {"query": "python"} if action_type == "web_search" else {"url": "https://example.com"}

    with pytest.raises(ValueError, match="networking_disabled"):
        await ToolExecutor().execute({"type": action_type, "input": action_input}, web_enabled=False)


@pytest.mark.anyio
async def test_web_search_reports_missing_key_without_secret(monkeypatch: pytest.MonkeyPatch):
    from app.services.agent import tool_executor

    monkeypatch.setattr(tool_executor.settings, "tavily_api_key", None)

    with pytest.raises(ValueError, match="tavily_api_key_not_configured") as exc_info:
        await ToolExecutor().execute({"type": "web_search", "input": {"query": "python"}})

    assert "api_key" not in str(exc_info.value).replace("tavily_api_key", "")


@pytest.mark.anyio
async def test_web_search_returns_bounded_safe_results(monkeypatch: pytest.MonkeyPatch):
    from app.services.agent import tool_executor

    created_clients = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"title": " Python ", "url": "https://example.com/a#fragment", "content": "x" * 2000},
                    {"title": "Unsafe", "url": "javascript:alert(1)", "content": "bad"},
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.request_body = None
            self.request_headers = None
            created_clients.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json, headers):
            self.request_body = json
            self.request_headers = headers
            return FakeResponse()

    monkeypatch.setattr(tool_executor.settings, "tavily_api_key", "super-secret")
    monkeypatch.setattr(tool_executor.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(tool_executor, "_validate_resolved_target", AsyncMock())

    result = await ToolExecutor().execute(
        {"type": "web_search", "input": {"query": "python", "max_results": 2}}
    )

    assert result == {
        "results": [{"title": "Python", "url": "https://example.com/a", "content": "x" * 1000}]
    }
    assert "super-secret" not in str(result)
    assert created_clients[0].request_headers == {"Authorization": "Bearer super-secret"}


@pytest.mark.anyio
@pytest.mark.parametrize("action_type", ["http_request", "extract_web_content"])
async def test_web_content_is_extracted_without_headers_or_active_content(
    monkeypatch: pytest.MonkeyPatch, action_type: str
):
    from app.services.agent import tool_executor

    html = """
    <html><head><title> Example title </title><style>.hidden{}</style></head>
    <body><script>stealCookie()</script><h1>Hello</h1><p>Useful text</p>
    <a href="/next">Next page</a><a href="javascript:bad()">Bad</a></body></html>
    """
    response = httpx.Response(
        200,
        text=html,
        headers={"set-cookie": "secret=1"},
        request=httpx.Request("GET", "https://example.com/start"),
    )
    monkeypatch.setattr(tool_executor, "_request_without_forbidden_redirects", AsyncMock(return_value=response))

    result = await ToolExecutor().execute(
        {"type": action_type, "input": {"url": "https://example.com/start"}}
    )

    assert result["status_code"] == 200
    assert result["url"] == "https://example.com/start"
    assert result["title"] == "Example title"
    assert "Hello" in result["text"] and "Useful text" in result["text"]
    assert "stealCookie" not in result["text"] and "hidden" not in result["text"]
    assert result["links"] == [{"title": "Next page", "url": "https://example.com/next"}]
    assert "headers" not in result and "set-cookie" not in str(result)


@pytest.mark.anyio
async def test_generic_calculator_tool_preserves_thought_tool_thought_event_order():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def stream_text(self, messages, **kwargs):
            self.calls += 1
            yield "先计算。" if self.calls == 1 else "计算结果可用于回答。"

    service = AgentLoopService()
    service.llm_client = FakeClient()
    service.tool_executor = SimpleNamespace(execute=AsyncMock(return_value={"result": 4}))

    event_log: list[str] = []
    service._persist_and_notify = AsyncMock(
        side_effect=lambda repo, ctx, event_type, payload: event_log.append(event_type)
    )

    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")

    ctx = _AttemptContext(run=run, attempt=attempt)
    repo = SimpleNamespace(is_cancel_requested=AsyncMock(return_value=False))
    action = {"type": "calculator", "input": {"expression": "2+2"}}

    _text, observation = await service._stream_visible_thought_with_tool_interleave(
        repo,
        ctx,
        0,
        "calculator",
        [{"role": "user", "content": "目标：计算"}],
        action,
        None,
        web_enabled=False,
    )

    assert event_log == [
        "visible_thought_started",
        "visible_thought_delta",
        "visible_thought_paused",
        "tool_started",
        "tool_completed",
        "visible_thought_started",
        "visible_thought_delta",
        "visible_thought_completed",
    ]
    assert observation == {"result": 4}
    service.tool_executor.execute.assert_awaited_once_with(
        action, web_enabled=False, owner_user_id=None, is_super_admin=False, goal="test"
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 3 * 4", 14),
        ("-5 + +2", -3),
        ("7 / 2", 3.5),
        ("7 // 2", 3),
        ("7 % 2", 1),
        ("2 ** 8", 256),
        ("2 ^ 3", 8),
        ("(3247 * 1.035^5) + (15680 / 12.5)", (3247 * 1.035**5) + (15680 / 12.5)),
    ],
)
async def test_calculator_allows_restricted_arithmetic(expression: str, expected: int | float):
    result = await ToolExecutor().execute({"type": "calculator", "input": {"expression": expression}})

    assert result == {"result": expected}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "expression",
    [
        "open('x')",
        "value + 1",
        "(1).__class__",
        "[1][0]",
        "[1, 2]",
        "True + 1",
        "1j + 1",
        "1 / 0",
        "2 ** 1000",
        "9" * 300,
    ],
)
async def test_calculator_rejects_unsafe_or_unbounded_expressions(expression: str):
    with pytest.raises(ValueError, match="calculator_"):
        await ToolExecutor().execute({"type": "calculator", "input": {"expression": expression}})


def test_run_policy_returns_full_steps_for_all_modes():
    from app.models.agent import AgentRun

    run1 = AgentRun(mode="quick", network_enabled=True)
    run2 = AgentRun(mode="expert", network_enabled=True)
    run3 = AgentRun(mode="quick", network_enabled=False)
    run4 = AgentRun(mode="expert", network_enabled=False)
    assert AgentLoopService()._run_policy(run1, 12) == (True, 12)
    assert AgentLoopService()._run_policy(run2, 20) == (True, 20)
    assert AgentLoopService()._run_policy(run3, 2) == (False, 2)
    assert AgentLoopService()._run_policy(run4, 12) == (False, 12)


@pytest.mark.parametrize("value", ["true", 1, [], {}, None])
def test_agent_loop_policy_fails_closed_for_malformed_web_enabled(value):
    from app.models.agent import AgentRun

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test",
                   mode="quick", network_enabled=value, max_steps=3)
    assert AgentLoopService()._run_policy(run, 3)[0] is False


def test_sanitized_action_removes_url_secrets_body_and_sensitive_fields():
    service = AgentLoopService()
    action = {
        "type": "http_request",
        "input": {
            "method": "GET",
            "url": "https://user:password@example.com/path?token=secret#private",
            "body": {"password": "secret"},
            "authorization": "Bearer secret",
        },
    }

    sanitized = service._sanitize_action(action)

    assert sanitized == {
        "type": "http_request",
        "input": {"method": "GET", "url": "https://example.com/path"},
    }
    assert "secret" not in str(sanitized)


def test_plan_and_step_persistence_projections_do_not_contain_action_secrets():
    service = AgentLoopService()
    action = {
        "type": "http_request",
        "input": {
            "method": "GET",
            "url": "https://example.com/path?access_token=secret#private",
            "body": {"token": "secret"},
        },
    }

    plan_event = {"step_index": 0, "thought_summary": "visit", "action": service._sanitize_action(action)}
    step_payload = service._sanitize_action(action)["input"]
    tool_event = service._tool_event_payload(0, action)

    assert plan_event["action"]["input"] == {"method": "GET", "url": "https://example.com/path"}
    assert step_payload == {"method": "GET", "url": "https://example.com/path"}
    assert tool_event["tool_call"] == {"method": "GET", "url": "https://example.com/path"}
    assert "secret" not in str((plan_event, step_payload, tool_event))


@pytest.mark.anyio
@pytest.mark.parametrize("error", [RetryableToolError("temporary"), asyncio.TimeoutError()])
async def test_retryable_tool_failure_uses_existing_retry_flow(error: Exception, monkeypatch: pytest.MonkeyPatch):
    service = AgentLoopService()
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt
    from app.services.agent.event_bus import event_bus as bus

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)

    fake_event = SimpleNamespace(id="evt-1", created_at=datetime.now(UTC), seq=7)
    monkeypatch.setattr("app.services.agent.loop.inspect", lambda obj: SimpleNamespace(identity=[7]))
    publish_mock = AsyncMock()
    monkeypatch.setattr(bus, "publish", publish_mock)

    repo = SimpleNamespace(
        transition_attempt_status=AsyncMock(return_value=True),
        schedule_retry_attempt=AsyncMock(return_value=AgentRunAttempt(
            id=None, run_id=None, attempt_number=2, status="queued",
            retry_of_attempt_id=attempt.id
        )),
        append_event=AsyncMock(return_value=fake_event),
    )
    service._persist_and_notify = AsyncMock()

    handled = await service._schedule_retryable_failure(repo, ctx, error)

    assert handled is True
    repo.transition_attempt_status.assert_awaited_once()
    repo.schedule_retry_attempt.assert_awaited_once_with(run, attempt, str(error))
    repo.append_event.assert_awaited_once()
    assert repo.append_event.await_args.args[2] == "run_retry_scheduled"
    publish_mock.assert_awaited_once()


@pytest.mark.anyio
async def test_permanent_tool_failure_is_not_scheduled_for_retry():
    service = AgentLoopService()
    from app.services.agent.loop import _AttemptContext
    from app.models.agent import AgentRun, AgentRunAttempt

    run = AgentRun(id=None, session_id=None, owner_user_id=None, goal="test", status="running")
    attempt = AgentRunAttempt(id=None, run_id=None, attempt_number=1, status="running")
    ctx = _AttemptContext(run=run, attempt=attempt)
    repo = SimpleNamespace(transition_attempt_status=AsyncMock(), create_retry_attempt=AsyncMock())

    with pytest.raises(ValueError, match="networking_disabled"):
        await service._schedule_retryable_failure(repo, ctx, ValueError("networking_disabled"))

    repo.transition_attempt_status.assert_not_awaited()


def test_final_step_replaces_provider_tool_action_with_finish():
    service = AgentLoopService()
    plan = {
        "thought_summary": "继续访问",
        "action": {"type": "http_request", "input": {"url": "https://example.com"}},
    }

    guarded = service._enforce_final_step(plan, final_step=True)

    assert guarded["action"] == {"type": "finish", "input": {}}


@pytest.mark.parametrize(
    "action_type", ["web_search", "http_request", "extract_web_content", "calculator", "finish", "unknown"]
)
def test_agent_loop_visible_fallback_is_safe_for_every_action(action_type: str):
    text = AgentLoopService()._visible_thought_fallback(action_type)

    assert isinstance(text, str) and text


def test_pre_tool_visible_thought_rewrites_claimed_results_as_future_intent():
    service = AgentLoopService()

    text = service._finalize_pre_tool_visible_thought(
        "已从Next.js官网获取到最新教程，建议直接访问官方文档开始学习。",
        "http_request",
    )

    assert text == "我将访问相关公开网页，获取资料后再继续整理。"


def test_pre_tool_visible_thought_keeps_future_intent():
    service = AgentLoopService()

    text = service._finalize_pre_tool_visible_thought(
        "我将访问 Next.js 官方文档，确认最新教程内容。",
        "http_request",
    )

    assert text == "我将访问 Next.js 官方文档，确认最新教程内容。"


def test_agent_loop_generic_tool_payload_has_action_type_without_secrets():
    service = AgentLoopService()

    search = service._tool_event_payload(1, {"type": "web_search", "input": {"query": "python"}})
    calculator = service._tool_event_payload(2, {"type": "calculator", "input": {"expression": "2+2"}})

    assert search == {"step_index": 1, "action_type": "web_search", "tool_call": {"query": "python"}}
    assert calculator == {
        "step_index": 2,
        "action_type": "calculator",
        "tool_call": {"expression": "2+2"},
    }


def test_agent_run_create_defaults_with_networking():
    request = AgentRunCreate(goal="research")

    assert request.network_enabled is True


def test_agent_loop_policy_persists_network_and_steps_from_run():
    from app.models.agent import AgentRun

    run = AgentRun(
        id=None, session_id=None, owner_user_id=None,
        goal="research", mode="expert", network_enabled=False,
        max_steps=8, status="running"
    )
    service = AgentLoopService()

    web_enabled, effective_steps = service._run_policy(run, 8)

    assert web_enabled is False
    assert effective_steps == 8


def test_step_timeout_value_is_configured():
    from app.core.config import get_settings

    settings = get_settings()
    assert settings.step_timeout_seconds == 30.0


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ("请把总结保存到 reports/a.md", True),
        ("将内容写入我的文件", True),
        ("生成一份文档存为模板", True),
        ("把结果保存到文件", True),
        ("写出报告并保存", True),
        ("帮我分析这份数据", False),
        ("解释一下这个方案", False),
        ("搜索相关资料", False),
        ("继续完善刚才的答案", False),
    ],
)
def test_save_intent_detection(goal: str, expected: bool):
    assert AgentLoopService()._has_save_intent(goal) is expected


def test_finish_without_write_on_save_intent_raises_retryable():
    from app.services.agent.llm import RetryablePlannerError

    service = AgentLoopService()
    plan = {"thought_summary": "直接回答", "action": {"type": "finish", "input": {}}}

    with pytest.raises(RetryablePlannerError, match="save_intent_requires_write_tool"):
        service._enforce_save_intent("请把总结保存到文件", plan, wrote_file=False, final_step=False)


def test_finish_allowed_after_write_on_save_intent():
    service = AgentLoopService()
    plan = {"thought_summary": "已保存", "action": {"type": "finish", "input": {}}}

    assert service._enforce_save_intent("请把总结保存到文件", plan, wrote_file=True, final_step=False) == plan


def test_finish_allowed_on_non_save_goal():
    service = AgentLoopService()
    plan = {"thought_summary": "回答", "action": {"type": "finish", "input": {}}}

    assert service._enforce_save_intent("帮我分析这份数据", plan, wrote_file=False, final_step=False) == plan


def test_finish_blocked_on_final_step_when_save_intent_unfulfilled():
    from app.services.agent.llm import RetryablePlannerError

    service = AgentLoopService()
    plan = {"thought_summary": "收尾", "action": {"type": "finish", "input": {}}}

    with pytest.raises(RetryablePlannerError, match="save_intent_unfulfilled"):
        service._enforce_save_intent("请把总结保存到文件", plan, wrote_file=False, final_step=True)


def test_plan_prompt_requires_write_tool_on_save_intent():
    planner = ResearchPlanner()
    messages = planner._build_messages(
        goal="保存文件", step_index=0, previous_observation=None,
        session_history=None, web_enabled=True, final_step=False,
    )
    system_content = messages[0]["content"]
    assert "必须先调用" in system_content
    assert "write_file" in system_content
    assert "edit_file" in system_content


def test_build_messages_renders_step_journal():
    messages = ResearchPlanner()._build_messages(
        "读取 brief_test.md 并写方案保存到 brief/",
        2,
        {"type": "read_file", "observation": "..."},
        session_history=None,
        web_enabled=True,
        final_step=False,
        step_journal=[
            "步骤1: read_file(brief_test.md) → 成功",
            "步骤2: web_search(GAP成毅营销) → 5条结果",
        ],
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "本任务已执行步骤" in prompt
    assert "步骤1: read_file(brief_test.md)" in prompt
    assert "步骤2: web_search(GAP成毅营销)" in prompt


def test_build_messages_step_journal_has_no_repeat_guidance():
    messages = ResearchPlanner()._build_messages(
        "简单问题", 0, None, web_enabled=True, step_journal=None
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "不要重复读取" in prompt


def test_build_messages_discourages_repeat_web_search():
    messages = ResearchPlanner()._build_messages(
        "简单问题", 0, None, web_enabled=True, step_journal=None
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "不要反复搜索" in prompt
    assert "整个任务搜索合计不宜超过 6 次" in prompt
    assert "不要再声明" in prompt


def test_fetch_platform_search_input_validation():
    from app.services.agent.planner import FetchPlatformSearchInput
    from pydantic import ValidationError

    parsed = FetchPlatformSearchInput(platform="xiaohongshu", keyword="GAP成毅", max_results=40)
    assert parsed.max_results == 40
    try:
        FetchPlatformSearchInput(platform="weibo", keyword="x")
        raise AssertionError("platform must be xiaohongshu or douyin")
    except ValidationError:
        pass
    try:
        FetchPlatformSearchInput(platform="douyin", keyword="x", max_results=51)
        raise AssertionError("max_results must be <= 50")
    except ValidationError:
        pass
    try:
        FetchPlatformSearchInput(platform="douyin", keyword="x" * 51)
        raise AssertionError("keyword must be <= 50")
    except ValidationError:
        pass


def test_action_policy_mentions_platform_search():
    from app.services.agent.planner import ResearchPlanner

    messages = ResearchPlanner()._build_messages(
        "调研小红书GAP成毅口碑", 0, None, web_enabled=True, step_journal=None
    )
    prompt = "\n".join(message["content"] for message in messages)
    assert "fetch_platform_search" in prompt
    assert "平台站内搜索" in prompt
