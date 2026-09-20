# Playwright Web Renderer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `fetch_web_content` tool using Playwright headless Chromium to render JS-heavy pages (抖音/小红书) with anti-detection.

**Architecture:** New standalone renderer process (FastAPI + Playwright) on port 9001. ToolExecutor's `fetch_web_content` action calls it via httpx. Planner gets `fetch_web_content` action type. Config adds renderer URL/timeout.

**Tech Stack:** Python 3.12, FastAPI, Playwright, httpx

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-playwright-web-renderer-design.md`
- Renderer process: standalone, crash-isolated, port 9001
- Reuse `_safe_http_url`, `_validate_resolved_target`, `_WebContentParser` from tool_executor.py
- Anti-detection: random UA, stealth JS, random viewport, random delay 1-3s
- Page timeout 30s, content cap 50KB
- `fetch_web_content` failures → `RetryableToolError`
- Windows compatible (`WindowsSelectorEventLoopPolicy` pattern in worker entry)

---

### Task 1: Dependencies and Config

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Add playwright to requirements.txt**

Append to `backend/requirements.txt`:

```
playwright>=1.45,<2
```

- [ ] **Step 2: Install playwright**

```powershell
python -X utf8 -m pip install "playwright>=1.45,<2"
python -X utf8 -m playwright install chromium
```

Expected: Chromium downloaded.

- [ ] **Step 3: Add renderer config**

In `backend/app/core/config.py`, after `agent_sync_persist_events` (line 55), add:

```python
    web_renderer_url: str = "http://127.0.0.1:9001"
    web_renderer_timeout_seconds: float = 40.0
```

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt backend/app/core/config.py
git commit -m "chore: add playwright dep and web renderer config"
```

---

### Task 2: Web Renderer Service

**Files:**
- Create: `backend/app/services/agent/web_renderer.py`
- Create: `backend/tests/test_web_renderer.py`

**Interfaces:**
- Produces:
  - `async def render_page(url: str, cookies: list[dict] | None = None, timeout_seconds: float = 30.0) -> dict`
  - Returns `{"title", "text", "url", "status_code", "error"}`

- [ ] **Step 1: Write the test file**

Create `backend/tests/test_web_renderer.py`:

```python
import asyncio
import pytest
from app.services.agent.web_renderer import _pick_user_agent, _stealth_js, _parse_rendered_html


class TestUserAgent:
    def test_returns_desktop_chrome_ua(self):
        ua = _pick_user_agent()
        assert "Chrome" in ua
        assert "Windows" in ua or "Macintosh" in ua

    def test_multiple_calls_vary(self):
        uas = {_pick_user_agent() for _ in range(5)}
        assert len(uas) > 1


class TestStealthJs:
    def test_contains_webdriver_override(self):
        js = _stealth_js()
        assert "navigator.webdriver" in js


class TestParseRenderedHtml:
    def test_extracts_title_and_text(self):
        html = "<html><head><title>测试标题</title></head><body><p>Hello 世界</p></body></html>"
        result = _parse_rendered_html(html, "https://example.com")
        assert result["title"] == "测试标题"
        assert "Hello 世界" in result["text"]
        assert result["url"] == "https://example.com"
        assert result["status_code"] == 200

    def test_truncates_long_text(self):
        html = f"<html><body><p>{'x' * 60000}</p></body></html>"
        result = _parse_rendered_html(html, "https://example.com")
        assert len(result["text"]) <= 50000
```

- [ ] **Step 2: Run tests to verify they FAIL**

```powershell
python -X utf8 -m pytest tests/test_web_renderer.py -v --no-header
```

Expected: FAIL — `web_renderer` module not found.

- [ ] **Step 3: Implement web_renderer.py**

Create `backend/app/services/agent/web_renderer.py`:

```python
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from app.services.agent.tool_executor import _WebContentParser, _normalize_text

logger = logging.getLogger("web_renderer")

MAX_RENDER_TEXT = 50_000

_DESKTOP_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_VIEWPORTS = [(1366, 768), (1440, 900), (1920, 1080)]


def _pick_user_agent() -> str:
    return random.choice(_DESKTOP_UAS)


def _stealth_js() -> str:
    return """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = window.chrome || { runtime: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    """


def _parse_rendered_html(html: str, url: str, status_code: int = 200) -> dict:
    parser = _WebContentParser(url)
    parser.feed(html[:100_000])
    return {
        "title": _normalize_text(" ".join(parser.title_parts))[:300],
        "text": _normalize_text(" ".join(parser.text_parts))[:MAX_RENDER_TEXT],
        "url": url,
        "status_code": status_code,
    }


async def render_page(
    url: str,
    cookies: list[dict] | None = None,
    timeout_seconds: float = 30.0,
) -> dict:
    """Render a JS-heavy page with Playwright. Returns parsed content dict.

    Raises RuntimeError on render failure (caller converts to RetryableToolError).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("playwright not installed") from exc

    await asyncio.sleep(random.uniform(1.0, 3.0))  # anti-bot delay

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
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
                response = await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_seconds * 1000))
                await page.wait_for_timeout(1500)  # let JS render
                status_code = response.status if response else 200
                html = await page.content()
                result = _parse_rendered_html(html, str(page.url), status_code)
                return result
            finally:
                await page.close()
        finally:
            await browser.close()
```

- [ ] **Step 4: Run tests to verify they PASS**

```powershell
python -X utf8 -m pytest tests/test_web_renderer.py -v --no-header
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/web_renderer.py backend/tests/test_web_renderer.py
git commit -m "feat: add Playwright web renderer service with anti-detection"
```

---

### Task 3: Renderer HTTP Process

**Files:**
- Create: `backend/app/workers/web_renderer.py`

**Interfaces:**
- Produces: Standalone FastAPI app exposing `POST /render`, runnable via `python -m app.workers.web_renderer`
- Consumes: `render_page` from Task 2

- [ ] **Step 1: Implement the worker entry**

Create `backend/app/workers/web_renderer.py`:

```python
from __future__ import annotations

import sys
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from app.services.agent.web_renderer import render_page

app = FastAPI(title="Web Renderer")


class RenderRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    cookies: list[dict[str, Any]] | None = None
    timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)


@app.post("/render")
async def render(req: RenderRequest) -> dict:
    try:
        result = await render_page(req.url, req.cookies, req.timeout_seconds)
        result["error"] = None
        return result
    except Exception as exc:
        return {"title": "", "text": "", "url": req.url, "status_code": 0, "error": str(exc)[:500]}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    if sys.platform == "win32":
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(app, host="127.0.0.1", port=9001)
```

- [ ] **Step 2: Verify it imports**

```powershell
python -X utf8 -c "import sys; sys.path.insert(0,'.'); from app.workers.web_renderer import app; print('renderer app OK')"
```

Expected: prints `renderer app OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/workers/web_renderer.py
git commit -m "feat: add web renderer HTTP worker process"
```

---

### Task 4: ToolExecutor fetch_web_content Action

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`
- Modify: `backend/app/services/agent/planner.py`

**Interfaces:**
- Consumes: `render_page` from Task 2, config `web_renderer_url`
- Produces: `execute()` handles `action_type == "fetch_web_content"`

- [ ] **Step 1: Add action branch in execute()**

In `tool_executor.py`, find the `execute()` method. Add before the `finish` branch:

```python
        if action_type == "fetch_web_content":
            return await self._fetch_web_content(payload)
```

- [ ] **Step 2: Implement _fetch_web_content**

Add to `ToolExecutor` class (after `_http_request`):

```python
    async def _fetch_web_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = _safe_http_url(str(payload.get("url", "")))
        if url is None:
            raise ValueError("unsafe_network_target")
        if is_forbidden_utility_url(url):
            raise RetryableToolError(f"forbidden_utility_url: {url}")

        timeout = httpx.Timeout(settings.web_renderer_timeout_seconds)
        cookies = payload.get("cookies")
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{settings.web_renderer_url.rstrip('/')}/render",
                    json={"url": url, "cookies": cookies if isinstance(cookies, list) else None},
                )
                response.raise_for_status()
                data = response.json()
        except (TimeoutException, ConnectError, httpx.RequestError) as exc:
            raise RetryableToolError("web_renderer_unavailable") from exc
        except httpx.HTTPStatusError as exc:
            raise RetryableToolError(f"web_renderer_status: {exc.response.status_code}") from exc

        if data.get("error"):
            raise RetryableToolError(f"web_render_error: {data['error'][:200]}")
        return {
            "status_code": data.get("status_code", 0),
            "url": data.get("url", url),
            "title": data.get("title", ""),
            "text": data.get("text", ""),
            "source": "playwright",
        }
```

- [ ] **Step 3: Add planner schema**

In `planner.py`, add after `EditFileInput`:

```python
class FetchWebContentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
```

Update `PlanAction.type` Literal to include `"fetch_web_content"`.

Update `input_models` dict:

```python
        "fetch_web_content": FetchWebContentInput,
```

Update the `action_policy` string in `_build_messages` to mention:

```python
        "fetch_web_content（用浏览器渲染 JS 页面，适合抖音/小红书等动态网页，需 url）"
```

- [ ] **Step 4: Add test**

Append to `backend/tests/test_agent_tool_files.py`:

```python
class TestFetchWebContent:
    @pytest.mark.anyio
    async def test_execute_dispatches_fetch_web_content(self, monkeypatch):
        executor = ToolExecutor()

        async def fake_post(url, json, **kwargs):
            class FakeResp:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {"title": "抖音视频", "text": "内容", "url": "https://www.douyin.com/video/1", "status_code": 200, "error": None}
            return FakeResp()

        monkeypatch.setattr("app.services.agent.tool_executor.httpx.AsyncClient", lambda timeout=None: type("C", (), {"__aenter__": lambda self: type("S", (), {"post": fake_post})(), "__aexit__": lambda *a: None})())

        result = await executor.execute(
            {"type": "fetch_web_content", "input": {"url": "https://www.douyin.com/video/1"}},
        )
        assert result["title"] == "抖音视频"
        assert result["source"] == "playwright"

    @pytest.mark.anyio
    async def test_fetch_web_content_rejects_bad_url(self):
        executor = ToolExecutor()
        with pytest.raises(ValueError, match="unsafe_network_target"):
            await executor.execute(
                {"type": "fetch_web_content", "input": {"url": "file:///etc/passwd"}},
            )
```

- [ ] **Step 5: Run tests**

```powershell
python -X utf8 -m pytest tests/test_agent_tool_files.py tests/test_file_reader.py -v --no-header
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/app/services/agent/planner.py backend/tests/test_agent_tool_files.py
git commit -m "feat: add fetch_web_content tool action using Playwright renderer"
```

---

### Task 5: Manual E2E Verification

- [ ] **Step 1: Start the renderer**

```powershell
python -X utf8 -m app.workers.web_renderer
```

Expected: uvicorn running on port 9001.

- [ ] **Step 2: Test the render endpoint**

```powershell
python -X utf8 -c "import httpx; r=httpx.post('http://127.0.0.1:9001/render', json={'url':'https://example.com'}); print(r.status_code, r.json().get('title'))"
```

Expected: 200, title "Example Domain".

- [ ] **Step 3: Start worker + API, prompt the agent to fetch a Douyin page**

Verify agent can call `fetch_web_content` and returns content from rendered page.

- [ ] **Step 4: Commit any fixes**
