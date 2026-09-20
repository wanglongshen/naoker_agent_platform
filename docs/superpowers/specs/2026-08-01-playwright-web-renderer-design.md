# Playwright 渲染服务 — 抖音/小红书/普通网页爬取

## Goal

为 Agent 增加 `fetch_web_content` 工具，使用 Playwright 无头浏览器渲染 JavaScript 页面，抓取抖音、小红书和普通网页的公开信息。支持反检测伪装和登录态 Cookie。

## Current State

`ToolExecutor._http_request` 用 httpx GET 抓取静态 HTML。抖音/小红书是 JS 渲染 SPA，直接 GET 拿不到内容。无浏览器基础设施，无 Cookie 存储。

## Architecture

```
Worker 进程                          Renderer 进程 (新增)
──────────                          ─────────────────
ToolExecutor                         web_renderer.py
  └─ fetch_web_content ──HTTP──▶    FastAPI + Playwright
      action 分支                     ├─ /render {url, cookies?}
                                     └─ Chromium 无头实例
                                          └─ 反检测伪装
```

独立进程（仿照 `agent_worker`），崩溃隔离，Worker 不阻塞。

## Components

### 1. web_renderer.py — 渲染服务（独立进程）
- FastAPI app，端口 `9001`
- `POST /render`：接收 `{url, cookies: list[dict]?}`，返回 `{title, text, url, status_code}`
- Playwright `chromium.launch(headless=True)`，`new_context(user_agent=随机UA, locale="zh-CN")`
- 反检测：注入 stealth JS（隐藏 `navigator.webdriver`），随机 viewport，随机延迟
- 页面超时 30s，`wait_until="networkidle"`，最大内容 50KB

### 2. tool_executor.py — fetch_web_content action
- 复用 `_safe_http_url` / `_validate_resolved_target` 校验
- 调渲染服务 HTTP API（httpx）
- 渲染失败 → `RetryableToolError`（重试）
- 返回 `{title, text, url, status_code, source: "playwright"}`

### 3. planner.py — 新 action schema
```python
class FetchWebContentInput(BaseModel):
    url: HttpUrl
```
- `PlanAction.type` 加 `"fetch_web_content"`
- system prompt 告知 LLM：复杂 JS 页面（抖音/小红书）用此工具

### 4. Config
```python
web_renderer_url: str = "http://127.0.0.1:9001"
web_renderer_timeout_seconds: float = 40.0
```

### 5. Cookie 支持（Phase 2，本期不做完整 UI）
- 渲染服务支持 `cookies` 参数透传
- 本期：fetch_web_content 接受 `cookies: list[dict]?` 字段（可选），LLM 不主动使用
- 完整 Cookie 管理 UI 后续迭代

## Anti-Detection（反检测伪装）

| 技术 | 实现 |
|------|------|
| UA 伪装 | 随机桌面 Chrome UA 池 |
| webdriver 隐藏 | `navigator.webdriver` 覆写 |
| Viewport | 随机 1366x768 / 1440x900 / 1920x1080 |
| 语言 | `zh-CN` |
| 请求延迟 | 每次渲染前随机 1-3s |
| Chrome flags | `--disable-blink-features=AutomationControlled` |

## 抖音/小红书字段提取

| 平台 | 提取 |
|------|------|
| 抖音视频页 | 页面 title（含视频标题/作者）、meta description、JSON-LD 结构化数据 |
| 小红书笔记页 | title、meta description、JSON-LD、og:title/og:description |

用 Playwright 的 `page.content()` 拿渲染后 HTML，复用现有 `_WebContentParser` 提取正文/标题/链接。

## Files

| File | Change |
|------|--------|
| `backend/app/services/agent/web_renderer.py` | **New.** 渲染服务 |
| `backend/app/workers/web_renderer.py` | **New.** 独立进程入口 |
| `backend/app/services/agent/tool_executor.py` | `fetch_web_content` action |
| `backend/app/services/agent/planner.py` | `FetchWebContentInput` + prompt |
| `backend/app/core/config.py` | 渲染服务 URL/超时 |
| `backend/requirements.txt` | `playwright` |
| `backend/tests/test_web_renderer.py` | 单元测试 |

## Non-Goals（本期）

- Cookie 管理 UI（后续迭代）
- 完整登录态抓取（需用户 Cookie，Phase 3）
- 视频下载/音频提取
- 分布式渲染集群
