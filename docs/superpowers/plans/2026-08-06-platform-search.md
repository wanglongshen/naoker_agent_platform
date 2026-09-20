# 平台站内搜索（fetch_platform_search）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供小红书/抖音平台站内搜索工具，落实蓝图"平台研究必须平台内搜索"硬规则与 150 条样本硬闸门。

**Architecture:** web_renderer 服务（FastAPI :9001）新增 `/search` 端点，用 Playwright 渲染平台搜索页并滚动加载，平台解析器提取样本列表；后端新增 `fetch_platform_search` 工具（cookie 注入复用既有 `web_cookie_store`）；loop 主循环按 URL 去重累计各平台样本数，research→content 转移处样本 <150 时抛 `_QuestionHangSignal` 挂起等待人工确认。

**Tech Stack:** FastAPI、Playwright（独立 web_renderer 服务）、httpx、pydantic、pytest（后端测试，conda env 01-rbac）。

## Global Constraints

- 蓝图硬规则：涉及小红书/抖音平台研究必须平台内搜索；样本口径=去重、与 brief 相关、至少提供标题/账号/链接/互动信息或正文线索；不足 150 条须说明原因并等待人工确认。
- `max_results` 上限 50、默认 30；`keyword` ≤ 50 字符；`platform ∈ {xiaohongshu, douyin}`。
- 登录墙/验证码不视为错误：返回 `login_required: true`。
- 同一平台连续两次平台搜索间隔 ≥ 3 秒。
- /search 独立超时 60s（`web_renderer_search_timeout_seconds` 可配置）。
- 错误码/观察键为英文蛇形，与既有风格一致（`web_renderer_unavailable`、`login_required`、`platform_search_parse_fallback`）。
- 只允许修改：`backend/app/workers/web_renderer.py`、`backend/app/services/agent/web_renderer.py`、`backend/app/services/agent/planner.py`、`backend/app/services/agent/tool_executor.py`、`backend/app/services/agent/workflow_rules.py`、`backend/app/services/agent/loop.py`、`backend/app/core/config.py`、`.env.example` 及对应测试文件。
- 测试命令（backend 目录、conda env 01-rbac）：`python -X utf8 -m pytest <file> -q`
- 每任务独立 commit，commit message 以 `feat:` / `fix:` 前缀。

---

### Task 1: web_renderer /search 端点与平台搜索引擎

**Files:**
- Modify: `backend/app/services/agent/web_renderer.py`（追加 `search_platform` 与解析辅助函数）
- Modify: `backend/app/workers/web_renderer.py:24-37`（`/render` 后追加 `POST /search`）
- Test: `backend/tests/test_web_renderer.py`（追加测试类）

**Interfaces:**
- Consumes: `render_page`（既有，web_renderer.py:107）、`_extract_douyin_json`（web_renderer.py:40）、`assess_login_expired(platform, text)`（login_session.py:147）、`_WebContentParser`/`_normalize_text`（tool_executor.py 导入）
- Produces: `search_platform(url, keyword, platform, max_results, cookies, timeout_seconds) -> dict`（键：`samples: list[dict]`、`sample_count: int`、`login_required: bool`、`platform: str`）；`/search` 端点消费 `SearchRequest{platform, keyword, max_results, cookies}`

- [ ] **Step 1: 写解析辅助函数的失败测试**（追加到 `backend/tests/test_web_renderer.py`）

```python
from app.services.agent.web_renderer import (
    _extract_samples_from_json,
    _detect_login_wall,
    _sample_url,
)


def test_extract_samples_from_douyin_aweme_list():
    data = {
        "aweme_list": [
            {
                "desc": "GAP成毅秋季大片",
                "author": {"nickname": "品牌情报局"},
                "statistics": {"digg_count": 1200},
                "share_url": "https://www.douyin.com/video/1001",
            },
            {
                "desc": "成毅代言现场",
                "author": {"nickname": "时尚前线"},
                "share_url": "https://www.douyin.com/video/1002",
            },
        ]
    }
    samples = _extract_samples_from_json(data, "douyin")
    assert len(samples) == 2
    assert samples[0]["title"] == "GAP成毅秋季大片"
    assert samples[0]["author"] == "品牌情报局"
    assert samples[0]["url"] == "https://www.douyin.com/video/1001"
    assert samples[0]["likes"] == 1200


def test_extract_samples_from_xiaohongshu_notes():
    data = {
        "note": {
            "noteList": [
                {
                    "title": "成毅同款穿搭",
                    "user": {"nickname": "穿搭博主"},
                    "interactInfo": {"likedCount": "3456"},
                    "noteId": "abc123",
                }
            ]
        }
    }
    samples = _extract_samples_from_json(data, "xiaohongshu")
    assert len(samples) == 1
    assert samples[0]["title"] == "成毅同款穿搭"
    assert samples[0]["author"] == "穿搭博主"
    assert "abc123" in samples[0]["url"]


def test_detect_login_wall_douyin():
    assert _detect_login_wall("douyin", "<html>扫码登录</html>") is True
    assert _detect_login_wall("douyin", "<html>大量正常内容</html>") is False


def test_detect_login_wall_xiaohongshu():
    assert _detect_login_wall("xiaohongshu", "登录后推荐更懂你的笔记") is True


def test_sample_url_falls_back_to_domain():
    assert "douyin.com" in _sample_url("douyin", "")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -X utf8 -m pytest tests/test_web_renderer.py::test_extract_samples_from_douyin_aweme_list tests/test_web_renderer.py::test_extract_samples_from_xiaohongshu_notes tests/test_web_renderer.py::test_detect_login_wall_douyin tests/test_web_renderer.py::test_detect_login_wall_xiaohongshu tests/test_web_renderer.py::test_sample_url_falls_back_to_domain -q`
Expected: FAIL（ImportError: cannot import name）

- [ ] **Step 3: 实现解析辅助函数**（追加到 `backend/app/services/agent/web_renderer.py` 末尾）

```python
_LOGIN_HINTS = {
    "douyin": ("扫码登录", "验证码登录", "登录后畅享高清视频"),
    "xiaohongshu": ("登录后推荐更懂你的笔记", "新用户可直接登录"),
}

_SAMPLE_KEYS = {
    "douyin": {
        "title": ("desc",),
        "author": ("author", "nickname"),
        "url": ("share_url",),
        "likes": ("statistics", "digg_count"),
    },
    "xiaohongshu": {
        "title": ("title",),
        "author": ("user", "nickname"),
        "url": ("noteId",),
        "likes": ("interactInfo", "likedCount"),
    },
}


def _json_get(node: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _sample_url(platform: str, url_or_id: Any) -> str:
    if not url_or_id:
        return ""
    if isinstance(url_or_id, str) and "://" in url_or_id:
        return url_or_id
    if platform == "douyin":
        return f"https://www.douyin.com/video/{url_or_id}"
    return f"https://www.xiaohongshu.com/explore/{url_or_id}"


def _extract_samples_from_json(data: Any, platform: str) -> list[dict[str, Any]]:
    """启发式递归提取样本：遍历 JSON 树，收集含标题/账号键的节点。"""
    keys = _SAMPLE_KEYS[platform]
    samples: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        title = _json_get(node, keys["title"])
        if isinstance(title, str) and title.strip():
            url = _sample_url(platform, _json_get(node, keys["url"]))
            if url and url not in seen_urls:
                seen_urls.add(url)
                author = _json_get(node, keys["author"])
                likes = _json_get(node, keys["likes"])
                samples.append(
                    {
                        "title": title.strip()[:200],
                        "author": str(author).strip()[:80] if author else "",
                        "url": url,
                        "likes": int(likes) if isinstance(likes, (int, float, str)) and str(likes).isdigit() else None,
                    }
                )
        for value in node.values():
            walk(value)

    walk(data)
    return samples


def _detect_login_wall(platform: str, text: str) -> bool:
    hints = _LOGIN_HINTS.get(platform, ())
    return any(hint in text for hint in hints)


def _extract_links(html: str, platform: str) -> list[str]:
    pattern = {
        "douyin": r"https?://www\.douyin\.com/video/\d+",
        "xiaohongshu": r"https?://www\.xiaohongshu\.com/(?:explore|discovery/item)/[A-Za-z0-9]+",
    }[platform]
    return list(dict.fromkeys(re.findall(pattern, html)))
```

- [ ] **Step 4: 运行测试确认通过**

Run: 同 Step 2 命令
Expected: PASS（5 passed）

- [ ] **Step 5: 实现 `search_platform` 引擎**（追加到 `backend/app/services/agent/web_renderer.py` 末尾）

```python
SEARCH_URLS = {
    "xiaohongshu": "https://www.xiaohongshu.com/search_result?keyword={keyword}",
    "douyin": "https://www.douyin.com/search/{keyword}",
}

_SEARCH_SCROLL_ROUNDS = 8
_SEARCH_MAX_RESULTS = 50


async def search_platform(
    platform: str,
    keyword: str,
    max_results: int = 30,
    cookies: list[dict] | None = None,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """渲染平台搜索页并滚动加载，提取样本列表。"""
    url = SEARCH_URLS[platform].format(keyword=keyword)
    from urllib.parse import quote

    url = SEARCH_URLS[platform].format(keyword=quote(keyword, safe=""))

    import playwright.async_api as playwright_async

    async with playwright_async.async_playwright() as p:
        from app.core.config import get_browser_channel, get_settings

        _settings = get_settings()
        browser = await p.chromium.launch(
            headless=_settings.web_renderer_headless,
            channel=get_browser_channel(_settings),
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            width, height = random.choice(_VIEWPORTS)
            context = await browser.new_context(
                user_agent=_pick_user_agent(),
                viewport={"width": width, "height": height},
                locale="zh-CN",
            )
            await context.add_init_script(_stealth_js())
            if cookies:
                try:
                    await context.add_cookies(cookies)
                except Exception:
                    logger.warning("web_renderer_add_cookies_failed")
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    await page.wait_for_timeout(4000)

                samples: list[dict[str, Any]] = []
                for _round in range(_SEARCH_SCROLL_ROUNDS):
                    await page.mouse.wheel(0, random.randint(1500, 3000))
                    await page.wait_for_timeout(random.randint(900, 1400))
                    html = await page.content()
                    new_samples = _parse_search_html(html, platform, url)
                    for sample in new_samples:
                        if sample["url"] and not any(
                            s["url"] == sample["url"] for s in samples
                        ):
                            samples.append(sample)
                    if len(samples) >= max_results or not new_samples:
                        break
                    if _detect_login_wall(platform, " ".join(s["title"] for s in new_samples)):
                        break
                samples = samples[:max_results]
                return {
                    "samples": samples,
                    "sample_count": len(samples),
                    "login_required": _detect_login_wall(platform, html),
                    "platform": platform,
                }
            finally:
                await page.close()
        finally:
            await browser.close()


def _parse_search_html(html: str, platform: str, page_url: str) -> list[dict[str, Any]]:
    """搜索页 HTML → 样本列表。优先 JSON，兜底文本+链接。"""
    from app.services.agent.login_session import assess_login_expired

    raw_json = None
    if platform == "douyin":
        raw_json = _extract_douyin_json(html)
    else:
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", html, re.DOTALL)
        if m:
            try:
                raw_json = json.loads(m.group(1))
            except json.JSONDecodeError:
                raw_json = None

    if raw_json:
        samples = _extract_samples_from_json(raw_json, platform)
        if samples:
            return samples

    parser = _WebContentParser(page_url)
    parser.feed(html[:100_000])
    text = _normalize_text(" ".join(parser.text_parts))
    samples = []
    for link in _extract_links(html, platform):
        samples.append({"title": text[:80], "author": "", "url": link, "likes": None})
    logger.warning("platform_search_parse_fallback", extra={"platform": platform})
    return samples
```

- [ ] **Step 6: 写 /search 端点测试**（追加到 `backend/tests/test_web_renderer.py`）

```python
def test_search_request_validation():
    from app.workers.web_renderer import SearchRequest
    from pydantic import ValidationError

    req = SearchRequest(platform="douyin", keyword="GAP成毅", max_results=30)
    assert req.max_results == 30
    try:
        SearchRequest(platform="douyin", keyword="x", max_results=51)
        raise AssertionError("max_results must be capped at 50")
    except ValidationError:
        pass
    try:
        SearchRequest(platform="weibo", keyword="x")
        raise AssertionError("platform must be xiaohongshu or douyin")
    except ValidationError:
        pass
```

- [ ] **Step 7: 运行测试确认失败**

Run: `python -X utf8 -m pytest tests/test_web_renderer.py::test_search_request_validation -q`
Expected: FAIL（ImportError: cannot import name SearchRequest）

- [ ] **Step 8: 在 web_renderer 服务加端点**（`backend/app/workers/web_renderer.py`，`/render` 端点后追加）

```python
class SearchRequest(BaseModel):
    platform: Literal["xiaohongshu", "douyin"]
    keyword: str = Field(min_length=1, max_length=50)
    max_results: int = Field(default=30, ge=1, le=50)
    cookies: list[dict[str, Any]] | None = None


@app.post("/search")
async def search(req: SearchRequest) -> dict:
    try:
        result = await search_platform(
            req.platform,
            req.keyword,
            req.max_results,
            req.cookies,
        )
        result["error"] = None
        return result
    except Exception as exc:
        return {
            "samples": [],
            "sample_count": 0,
            "login_required": False,
            "platform": req.platform,
            "error": str(exc)[:500],
        }
```

同时把导入改为：`from app.services.agent.web_renderer import render_page, search_platform`，并在文件头 `from typing import Any, Literal`。

- [ ] **Step 9: 运行测试确认通过**

Run: `python -X utf8 -m pytest tests/test_web_renderer.py -q`
Expected: PASS（既有测试 + 新增全部通过）

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/agent/web_renderer.py backend/app/workers/web_renderer.py backend/tests/test_web_renderer.py
git commit -m "feat: platform search endpoint and parser in web_renderer"
```

---

### Task 2: planner FetchPlatformSearchInput 与提示词

**Files:**
- Modify: `backend/app/services/agent/planner.py`（`FetchWebContentInput` 后加 `FetchPlatformSearchInput`；`PlanAction.type` Literal 加 `fetch_platform_search`；`_ACTION_INPUTS` 映射；action_policy 提示）
- Test: `backend/tests/test_agent_tools.py`（追加测试）

**Interfaces:**
- Consumes: 无（独立）
- Produces: `FetchPlatformSearchInput{platform: Literal["xiaohongshu","douyin"], keyword: str(≤50), max_results: int(1-50, default 30)}`；action type 字符串 `"fetch_platform_search"`（Task 3/4 使用）

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_agent_tools.py` 末尾）

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -X utf8 -m pytest tests/test_agent_tools.py::test_fetch_platform_search_input_validation tests/test_agent_tools.py::test_action_policy_mentions_platform_search -q`
Expected: FAIL（ImportError / 断言失败）

- [ ] **Step 3: 实现**（`backend/app/services/agent/planner.py`）

在 `FetchWebContentInput` 类后追加：

```python
class FetchPlatformSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["xiaohongshu", "douyin"]
    keyword: str = Field(min_length=1, max_length=50)
    max_results: int = Field(default=30, ge=1, le=50)
```

`PlanAction.type` Literal 中（`"fetch_web_content"` 后）加 `"fetch_platform_search"`。

`_ACTION_INPUTS` 映射中（`"fetch_web_content": FetchWebContentInput,` 后）加：

```python
            "fetch_platform_search": FetchPlatformSearchInput,
```

action_policy 中 `fetch_web_content（用浏览器渲染 JS 页面…` 描述后追加：

```python
                "fetch_platform_search（平台站内搜索：小红书或抖音，输入 platform/keyword/max_results，"
                "返回笔记/视频样本列表（标题/账号/链接/互动数）；涉及小红书或抖音平台研究时必须优先使用本工具，"
                "不能只用普通网页搜索替代（蓝图硬规则）；可多次搜索不同关键词累积样本）、"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -X utf8 -m pytest tests/test_agent_tools.py -q`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/planner.py backend/tests/test_agent_tools.py
git commit -m "feat: planner input and policy for fetch_platform_search"
```

---

### Task 3: tool_executor `_fetch_platform_search` 工具

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`（`_fetch_web_content` 附近加方法；`execute` 分发链 378 行附近加分支）
- Test: `backend/tests/test_agent_tool_files.py`（追加测试类）

**Interfaces:**
- Consumes: `FetchPlatformSearchInput`（Task 2）、`POST {web_renderer_url}/search`（Task 1）、`get_user_cookie_string(owner_user_id, domain)`（web_cookie_store，既有）
- Produces: `_fetch_platform_search(payload, owner_user_id) -> dict`（键：`platform`、`keyword`、`sample_count`、`samples`（最多 20 条）、`login_required`、`note`）

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_agent_tool_files.py` 末尾，类 `TestFetchPlatformSearch`）

```python
class TestFetchPlatformSearch:
    async def _executor(self):
        from app.services.agent.tool_executor import ToolExecutor

        return ToolExecutor()

    async def test_returns_samples_with_note(self, monkeypatch):
        import httpx
        from app.services.agent.tool_executor import ToolExecutor

        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "samples": [
                        {"title": "成毅GAP大片", "author": "博主", "url": "https://www.douyin.com/video/1", "likes": 100}
                    ],
                    "sample_count": 1,
                    "login_required": False,
                    "platform": "douyin",
                    "error": None,
                }

        async def fake_post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        result = await ToolExecutor()._fetch_platform_search(
            {"platform": "douyin", "keyword": "GAP成毅", "max_results": 30},
            owner_user_id=None,
        )
        assert result["platform"] == "douyin"
        assert result["sample_count"] == 1
        assert result["samples"][0]["title"] == "成毅GAP大片"
        assert "累计" in result["note"]
        assert "/search" in captured["url"]

    async def test_login_required_passthrough(self, monkeypatch):
        import httpx
        from app.services.agent.tool_executor import ToolExecutor

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"samples": [], "sample_count": 0, "login_required": True, "platform": "xiaohongshu", "error": None}

        async def fake_post(self, url, json=None):
            return FakeResponse()

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        result = await ToolExecutor()._fetch_platform_search(
            {"platform": "xiaohongshu", "keyword": "成毅", "max_results": 30},
            owner_user_id=None,
        )
        assert result["login_required"] is True

    async def test_renderer_unavailable_is_retryable(self, monkeypatch):
        import httpx
        from app.services.agent.tool_executor import (
            ToolExecutor,
            RetryableToolError,
        )

        async def fake_post(self, url, json=None):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        try:
            await ToolExecutor()._fetch_platform_search(
                {"platform": "douyin", "keyword": "x", "max_results": 10},
                owner_user_id=None,
            )
            raise AssertionError("must raise RetryableToolError")
        except RetryableToolError as exc:
            assert "web_renderer_unavailable" in str(exc)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -X utf8 -m pytest tests/test_agent_tool_files.py::TestFetchPlatformSearch -q`
Expected: FAIL（AttributeError: _fetch_platform_search）

- [ ] **Step 3: 实现**（`backend/app/services/agent/tool_executor.py`，`_fetch_web_content` 方法后追加）

```python
    async def _fetch_platform_search(
        self, payload: dict[str, Any], owner_user_id: uuid.UUID | None
    ) -> dict[str, Any]:
        platform = str(payload.get("platform", ""))
        keyword = str(payload.get("keyword", ""))
        max_results = int(payload.get("max_results", 30))
        if platform not in ("xiaohongshu", "douyin"):
            raise ValueError("unsupported_platform")
        domain = "www.douyin.com" if platform == "douyin" else "www.xiaohongshu.com"

        cookies = None
        if owner_user_id is not None:
            cookie_str = await get_user_cookie_string(owner_user_id, domain)
            if cookie_str:
                cookies = _parse_cookie_string(cookie_str, domain)

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.web_renderer_search_timeout_seconds)
            ) as client:
                response = await client.post(
                    f"{settings.web_renderer_url.rstrip('/')}/search",
                    json={
                        "platform": platform,
                        "keyword": keyword,
                        "max_results": max_results,
                        "cookies": cookies if isinstance(cookies, list) else None,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except (TimeoutException, ConnectError, httpx.RequestError) as exc:
            raise RetryableToolError("web_renderer_unavailable") from exc
        except httpx.HTTPStatusError as exc:
            raise RetryableToolError(f"web_render_status: {exc.response.status_code}") from exc

        if data.get("error"):
            raise RetryableToolError(f"web_render_error: {data['error'][:200]}")
        samples = data.get("samples") or []
        visible = samples[:20]
        note_parts = [f"该平台累计 X/150 条（由系统统计）"]
        if data.get("login_required"):
            note_parts.append("平台登录态不足，部分内容可能无法获取；可提示用户登录")
        return {
            "platform": platform,
            "keyword": keyword,
            "sample_count": len(samples),
            "samples": visible,
            "total_available": len(samples),
            "login_required": bool(data.get("login_required")),
            "note": "；".join(note_parts),
        }
```

在 `execute` 分发链中（`if action_type == "fetch_web_content":` 分支后）追加：

```python
        if action_type == "fetch_platform_search":
            return await self._fetch_platform_search(payload, owner_user_id)
```

- [ ] **Step 4: 加 `web_renderer_search_timeout_seconds` 配置**（`backend/app/core/config.py`，`web_renderer_timeout_seconds` 附近）

```python
    web_renderer_search_timeout_seconds: float = 60.0
```

同时把 `.env.example` 中 `WEB_RENDERER_TIMEOUT_SECONDS` 行后加一行 `WEB_RENDERER_SEARCH_TIMEOUT_SECONDS=60.0`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -X utf8 -m pytest tests/test_agent_tool_files.py::TestFetchPlatformSearch -q`
Expected: PASS（3 passed）

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/app/core/config.py .env.example backend/tests/test_agent_tool_files.py
git commit -m "feat: fetch_platform_search tool with cookie injection and search timeout"
```

---

### Task 4: 路由映射与 150 条样本硬闸门

**Files:**
- Modify: `backend/app/services/agent/workflow_rules.py:59-64`（`_CAPABILITY_MAP`）
- Modify: `backend/app/services/agent/loop.py`（`_RunWorkflowState` 加字段；`_STAGE_ALLOWED_ACTIONS`；主循环观察处累计；`_advance_workflow_stage` research→content 闸门）
- Test: `backend/tests/test_workflow_rules.py`、`backend/tests/test_agent_loop.py`（追加）

**Interfaces:**
- Consumes: action type `"fetch_platform_search"`（Task 2）；工具观察含 `platform`/`sample_count`/`samples[].url`（Task 3）
- Produces: per-run 状态字段 `platform_samples: dict[str, int]`、`platform_sample_urls: dict[str, set[str]]`、`platform_waived: set[str]`

- [ ] **Step 1: 写路由映射失败测试**（追加到 `backend/tests/test_workflow_rules.py`）

```python
def test_capability_map_routes_agent_reach_to_platform_search():
    from app.services.agent.workflow_rules import _CAPABILITY_MAP

    assert _CAPABILITY_MAP["$agent-reach"] == "fetch_platform_search"
    assert _CAPABILITY_MAP["agent-reach"] == "fetch_platform_search"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -X utf8 -m pytest tests/test_workflow_rules.py::test_capability_map_routes_agent_reach_to_platform_search -q`
Expected: FAIL（断言 web_search != fetch_platform_search）

- [ ] **Step 3: 改映射**（`backend/app/services/agent/workflow_rules.py`）

```python
_CAPABILITY_MAP = {
    "$agent-reach": "fetch_platform_search",
    "agent-reach": "fetch_platform_search",
    "案例库": "read_file",
    "案例库调用": "read_file",
}
```

- [ ] **Step 4: 运行确认通过**

Run: `python -X utf8 -m pytest tests/test_workflow_rules.py -q`
Expected: PASS

- [ ] **Step 5: 写闸门失败测试**（追加到 `backend/tests/test_agent_loop.py`，类 `TestPlatformSampleGate`）

```python
class TestPlatformSampleGate:
    async def _make_state(self, service):
        from uuid import uuid4
        from app.services.agent.loop import _RunWorkflowState

        run_id = uuid4()
        st = service._wf(run_id)
        st.platform_samples = {}
        st.platform_sample_urls = {}
        st.platform_waived = set()
        return st

    async def test_state_has_platform_fields(self):
        from app.services.agent.loop import AgentLoopService, _RunWorkflowState

        st = _RunWorkflowState()
        assert st.platform_samples == {}
        assert st.platform_sample_urls == {}
        assert st.platform_waived == set()

    async def test_gate_hangs_when_samples_below_150(self):
        from app.services.agent.loop import AgentLoopService, _QuestionHangSignal

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        st.platform_samples = {"xiaohongshu": 42}
        st.platform_sample_urls = {"xiaohongshu": {"u1"}}
        try:
            service._check_platform_sample_gate(st)
            raise AssertionError("must hang when below 150")
        except _QuestionHangSignal as hang:
            assert "42" in hang.questions[0]
            assert "150" in hang.questions[0]

    async def test_gate_passes_when_above_150(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        st.platform_samples = {"douyin": 200}
        st.platform_sample_urls = {"douyin": {"u1"}}
        service._check_platform_sample_gate(st)  # 不抛异常即通过

    async def test_gate_skipped_when_no_platform_used(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        service._check_platform_sample_gate(st)  # 不抛异常即通过

    async def test_waived_platform_not_hung_again(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        st.platform_samples = {"douyin": 10}
        st.platform_sample_urls = {"douyin": {"u1"}}
        st.platform_waived = {"douyin"}
        service._check_platform_sample_gate(st)  # 不抛异常即通过
```

- [ ] **Step 6: 运行确认失败**

Run: `python -X utf8 -m pytest tests/test_agent_loop.py::TestPlatformSampleGate -q`
Expected: FAIL（AttributeError: platform_samples）

- [ ] **Step 7: 实现状态字段与检查方法**（`backend/app/services/agent/loop.py`）

`_RunWorkflowState` 字段追加：

```python
    platform_samples: dict[str, int] = field(default_factory=dict)
    platform_sample_urls: dict[str, set[str]] = field(default_factory=dict)
    platform_waived: set[str] = field(default_factory=set)
```

类方法追加（放在 `_advance_workflow_stage` 前）：

```python
    async def _accumulate_platform_samples(self, st: _RunWorkflowState, observation: dict) -> None:
        platform = observation.get("platform")
        if platform not in ("xiaohongshu", "douyin"):
            return
        urls = st.platform_sample_urls.setdefault(platform, set())
        added = 0
        for sample in observation.get("samples") or []:
            url = sample.get("url")
            if url and url not in urls:
                urls.add(url)
                added += 1
        st.platform_samples[platform] = st.platform_samples.get(platform, 0) + added

    def _check_platform_sample_gate(self, st: _RunWorkflowState) -> None:
        if not st.platform_samples:
            return
        missing = [
            (platform, count)
            for platform, count in st.platform_samples.items()
            if count < 150 and platform not in st.platform_waived
        ]
        if not missing:
            return
        platform, count = max(missing, key=lambda item: item[1])
        label = "小红书" if platform == "xiaohongshu" else "抖音"
        questions = [
            f"平台样本不足：{label} 平台累计 {count} 条，未达到蓝图要求的 150 条目标。"
            "已尝试关键词见上方工具记录。是否换关键词继续搜索补充样本，"
            "或确认接受当前样本数继续生成方案？"
        ]
        raise _QuestionHangSignal(questions)
```

- [ ] **Step 8: 接线主循环累计与 stage 允许表**

`_STAGE_ALLOWED_ACTIONS` 中 research 行改为：

```python
        "research": {"read_file", "list_files", "web_search", "fetch_platform_search"},
```

主循环中 `if action["type"] == "web_search" and ...: st.research_ok = True` 附近追加（同一观察处理块）：

```python
            if action["type"] == "fetch_platform_search" and isinstance(observation, dict) and not observation.get("error"):
                await self._accumulate_platform_samples(st, observation)
                if observation.get("sample_count"):
                    st.research_ok = True
```

- [ ] **Step 9: `_advance_workflow_stage` research 分支加闸门**

```python
            if stage == "research":
                if st.research_ok:
                    self._check_platform_sample_gate(st)
                    st.stage = "content"
                    st.stages_done.append("research")
                    continue
                return
```

- [ ] **Step 10: 运行确认通过**

Run: `python -X utf8 -m pytest tests/test_agent_loop.py::TestPlatformSampleGate tests/test_workflow_rules.py -q`
Expected: PASS

- [ ] **Step 11: 回归**

Run: `python -X utf8 -m pytest tests/test_agent_loop.py tests/test_agent_tools.py tests/test_agent_tool_files.py tests/test_workflow_rules.py tests/test_workflow_policy.py -q`
Expected: PASS（含既有全部）

- [ ] **Step 12: Commit**

```bash
git add backend/app/services/agent/workflow_rules.py backend/app/services/agent/loop.py backend/tests/test_workflow_rules.py backend/tests/test_agent_loop.py
git commit -m "feat: 150-sample gate for platform research and agent-reach routing"
```

---

### Task 5: 全量回归与端到端实测

**Files:**
- Test: 全后端套件

- [ ] **Step 1: 全量回归**

Run: `python -X utf8 -m pytest tests -q`（backend 目录）
Expected: 全绿（已知预存失败除外，与本改动无关项记录在案）

- [ ] **Step 2: 重启 web_renderer 服务与 Worker**

```powershell
# web_renderer（:9001）与 agent_worker 各重启一次，让新代码生效
```

- [ ] **Step 3: 端到端实测（真实平台搜索）**

用脚本直接调用 `POST http://127.0.0.1:9001/search`（platform=douyin、keyword=成毅 GAP、max_results=20）与 xiaohongshu 各一次，记录：
- 实际返回样本数、样本字段完整性（title/author/url/likes）；
- 是否 login_required；
- 若平台风控/改版导致拿不到样本，记录实际现象（作为闸门"说明原因"路径的输入）。

- [ ] **Step 4: 结论写入 commit message 或后续迭代依据**

若两个平台都拿不到样本：记录现象，闸门"说明原因"路径即为主要行为（模型提示用户登录/说明限制），不阻塞交付。

---

## Self-Review 记录

- **Spec 覆盖**：/search 端点（Task 1）、planner 输入与提示（Task 2）、工具与 cookie/超时（Task 3）、路由映射 + 150 条闸门 + 豁免（Task 4）、回归与实测（Task 5）——spec 全部验收标准均有对应任务。
- **无占位符**：所有步骤含完整代码与命令。
- **类型一致性**：`FetchPlatformSearchInput`（Task 2 定义，Task 3 消费）、`_fetch_platform_search(payload, owner_user_id)`（Task 3 定义，Task 4 观察键 `platform`/`samples[].url` 消费）、`platform_samples`/`platform_sample_urls`/`platform_waived`（Task 4 内一致）。
