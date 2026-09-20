# 扫码登录修复（patchright 反爬）与弹窗美化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 patchright 替换 Playwright 绕过抖音/小红书反爬（当前 headless Chromium 被拦截、二维码不渲染），并增加二维码渲染检测与错误分级，同时美化扫码弹窗为简约现代风格。

**Architecture:** patchright 是 API 兼容 Playwright 的反检测 fork，替换两处导入（`web_renderer.py` 的 `render_page`、`login_session.py` 的 `_default_browser_factory`）即可。`login_session.py` 的 `_open_and_watch` 在 `goto` 后新增 `_wait_for_qr`：轮询检测二维码元素（候选 selector + 兜底 img），检测到才置 `waiting_scan`，验证页 → `platform_blocked`，超时 → `qr_timeout`，其余异常 → `browser_failed`（前端按 detail 分级显示文案）。前端 `platform-login-modal.tsx` 重写为简约现代卡片风格。

**Tech Stack:** Python 3.12, patchright (fork of Playwright), React 19, Ant Design

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-03-platform-login-scan-polish-design.md`
- patchright 跨平台（开发机 Windows 与生产 Linux 一致）；部署时须执行 `patchright install chromium`
- QR 等待超时 20 秒，轮询间隔 1 秒
- 错误 detail 契约（前端按此显示文案）：`platform_blocked`（验证页）、`qr_timeout`（超时）、`browser_failed`（其他异常）
- 二维码候选 selector：`img[src*='qrcode']`、`canvas`；兜底：非验证页 + 出现任一 `img`
- 前端文案映射：`platform_blocked` → "平台安全验证拦截，请稍后重试"；`qr_timeout` → "二维码加载超时，请点击刷新"；`browser_failed` → "浏览器启动失败，请稍后重试"；其他 → detail 原文或"登录失败，请重试"
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；后端测试工作目录 `C:\01_agent_loop_pro\backend`
- **git 纪律**：仓库有其他并行会话的未提交变更——只能 `git add` 本任务列出的精确路径，禁止 `git add -A`/`git reset`/rebase/全局操作；提交前用 `git status` 确认暂存内容
- **⚠️ 已实测修订（GATE 结论）**：headless 状态本身就是反爬检测点（patchright/完整 chromium/Edge 的 headless 全被拦；headed 真实窗口全通过）。方案定为：**`headless=False`（headed）+ channel 配置 + Linux 生产 xvfb-run**：
  - `Settings.web_renderer_headless: bool = False`、`Settings.web_renderer_channel: str | None = None`（未设置按平台推断：Windows → `msedge`，Linux → `None`=patchright chromium）——`get_browser_channel()` 助手放 `app/core/config.py`
  - 生产 Linux 启动：`xvfb-run -a python -m app.workers.web_renderer`（README 写明）
  - 登录 URL 保持既有 `LOGIN_URLS` 首页（`douyin.com/login` 实测空白，不用）
- 部署说明写入新建的 `backend/README.md`（不要动根 README.md，其他会话可能正在修改）

---

### Task 1: patchright 依赖、headed 启动与导入替换（含反爬探针验证）

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/agent/web_renderer.py`
- Modify: `backend/app/services/agent/login_session.py`
- Create: `backend/README.md`

**Interfaces:**
- Consumes: 无
- Produces: `Settings.web_renderer_headless: bool = False`、`Settings.web_renderer_channel: str | None = None`、`get_browser_channel(settings) -> str | None`（config.py）；`render_page` 与 `LoginSessionManager` 签名不变，仅底层驱动与启动参数变化

- [ ] **Step 1: Install patchright（已执行 ✅）**

```powershell
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pip install patchright -i https://pypi.tuna.tsinghua.edu.cn/simple
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"
& "X:\python\anaconda\envs\01-rbac\python.exe" -m patchright install chromium
& "X:\python\anaconda\envs\01-rbac\python.exe" -m patchright install chromium --no-shell
```
Workdir: `C:\01_agent_loop_pro\backend`
Expected: patchright 1.61.2 + chromium 完整版与 headless-shell 均下载完成。

- [ ] **Step 2: Update requirements.txt**

In `C:\01_agent_loop_pro\backend\requirements.txt`, replace line 19:
```
playwright>=1.45,<2
```
with:
```
patchright>=1.45,<2
```

- [ ] **Step 3: Add headed/channel settings in config.py**

In `C:\01_agent_loop_pro\backend\app\core\config.py`, add to `Settings` (after `web_renderer_timeout_seconds`):

```python
    web_renderer_headless: bool = False
    web_renderer_channel: str | None = None
```

And add module-level helper (after the `Settings` class):

```python
def get_browser_channel(settings: Settings | None = None) -> str | None:
    """Resolve browser channel: explicit setting wins; on Windows default to msedge, else None (bundled chromium)."""
    s = settings or Settings()
    if s.web_renderer_channel:
        return s.web_renderer_channel
    if sys.platform == "win32":
        return "msedge"
    return None
```

(需要 `import sys`。)

- [ ] **Step 4: Replace imports & switch to headed launch**

In `C:\01_agent_loop_pro\backend\app\services\agent\web_renderer.py`, find:
```python
        from playwright.async_api import async_playwright
```
Replace with:
```python
        from patchright.async_api import async_playwright
```

And replace the launch block (lines ~120-123):
```python
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
```
with:
```python
        from app.core.config import get_settings, get_browser_channel

        _settings = get_settings()
        browser = await p.chromium.launch(
            headless=_settings.web_renderer_headless,
            channel=get_browser_channel(_settings),
            args=["--disable-blink-features=AutomationControlled"],
        )
```

In `C:\01_agent_loop_pro\backend\app\services\agent\login_session.py`, find inside `_default_browser_factory`:
```python
    from playwright.async_api import async_playwright

    p = await async_playwright().start()
    return await p.chromium.launch(headless=True)
```
Replace with:
```python
    from patchright.async_api import async_playwright
    from app.core.config import get_settings, get_browser_channel

    p = await async_playwright().start()
    _settings = get_settings()
    return await p.chromium.launch(
        headless=_settings.web_renderer_headless,
        channel=get_browser_channel(_settings),
    )
```

- [ ] **Step 5: Write and run the anti-bot probe (GATE — decides if headed+channel works)**

Create `C:\Users\Lenovo\AppData\Local\Temp\opencode\probe_patchright.py`（最终形态——headed + channel 可配置，复现已通过实验）:

```python
import asyncio
from patchright.async_api import async_playwright

URLS = [
    "https://www.douyin.com/",
    "https://www.xiaohongshu.com/explore",
]


async def probe(url: str) -> bool:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="msedge")
        page = await browser.new_page(viewport={"width": 900, "height": 1200})
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(8000)
        title = (await page.title()) or ""
        qr_like = await page.evaluate(
            """() => {
                const imgs = Array.from(document.querySelectorAll('img'));
                const qr = imgs.filter(i => /qr|qrcode|code/i.test(i.src || '')).length;
                return { imgs: imgs.length, qr, canvases: document.querySelectorAll('canvas').length };
            }"""
        )
        blocked = any(k in title for k in ["验证", "安全", "captcha", "verify"])
        print(f"{url} | title={title[:40]!r} | imgs={qr_like['imgs']} qr={qr_like['qr']} canvases={qr_like['canvases']} | blocked={blocked}")
        await browser.close()
        return not blocked


async def main():
    results = [await probe(u) for u in URLS]
    print("ALL_PASS" if all(results) else "SOME_BLOCKED")
    if not all(results):
        raise SystemExit(1)


asyncio.run(main())
```

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" "C:\Users\Lenovo\AppData\Local\Temp\opencode\probe_patchright.py"`
Expected: prints `ALL_PASS`（两 URL 均 `blocked=False` 且 qr>0）。

**GATE RULE**: 如果输出 `SOME_BLOCKED`，**停止并上报**，不要继续后续任务——回到设计层评估下一纵深（真实登录态 Cookie / 代理 IP）。

- [ ] **Step 6: Create deployment note**

Create `C:\01_agent_loop_pro\backend\README.md`:

```markdown
# backend

FastAPI 服务（API / agent_worker / web_renderer 三进程）。

## 部署注意

- 扫码登录（平台登录中心）依赖 **patchright** 的浏览器二进制：
  - 安装：`pip install patchright`
  - 安装浏览器（首次部署必须执行）：`patchright install chromium`
  - Linux 服务器如需系统依赖（libnss3 等），参考 Playwright 官方依赖清单：
    `python -m patchright install-deps chromium`
- **真实窗口模式（必须）**：反爬实测确认 headless 模式会被抖音/小红书拦截，
  因此浏览器以 `headless=False` 启动（`.env` 可配 `WEB_RENDERER_HEADLESS`/`WEB_RENDERER_CHANNEL`）：
  - Windows 开发机：直接弹窗（channel 默认 `msedge`）
  - Linux 生产：用 xvfb 虚拟显示承载，启动命令：
    `xvfb-run -a python -m app.workers.web_renderer`
    （Debian/Ubuntu 安装：`apt install xvfb`；RHEL 系：`dnf install xorg-x11-server-Xvfb`）
- 登录态相关环境变量见 `.env`（web_renderer_url 等）。
```

- [ ] **Step 7: Verify imports still work**

```powershell
& "X:\python\anaconda\envs\01-rbac\python.exe" -c "import sys; sys.path.insert(0,'.'); from app.workers.web_renderer import app; from app.core.config import get_browser_channel, get_settings; print('worker OK', get_browser_channel(get_settings()))"
```
Workdir: `C:\01_agent_loop_pro\backend`
Expected: prints `worker OK msedge`

- [ ] **Step 8: Commit**

```bash
git add backend/requirements.txt backend/app/core/config.py backend/app/services/agent/web_renderer.py backend/app/services/agent/login_session.py backend/README.md
git commit -m "feat: switch renderer to patchright headed mode with channel config"
```
Workdir: `C:\01_agent_loop_pro`

---

### Task 2: 二维码渲染检测与错误分级状态机

**Files:**
- Modify: `backend/app/services/agent/login_session.py`（追加常量与 `_wait_for_qr`，修改 `_open_and_watch`）
- Modify: `backend/tests/test_login_session_manager.py`（FakePage 加 query_selector，更新一个既有测试语义，追加新测试类）

**Interfaces:**
- Consumes: 既有 `LoginSessionManager`、`LoginSessionError`、`assess_login_expired`、`LOGIN_URLS`；`app.services.agent.web_renderer._extract_platform_content(html, url) -> dict`
- Produces:
  - 常量：`QR_WAIT_TIMEOUT: float = 20.0`、`QR_POLL_INTERVAL: float = 1.0`、`QR_SELECTORS: dict[str, list[str]]` = `{"douyin": ["img[src*='qrcode']", "canvas"], "xiaohongshu": ["img[src*='qrcode']", "canvas"]}`、`QR_FALLBACK_SELECTOR: str = "img"`
  - `async _wait_for_qr(self, record, timeout: float = QR_WAIT_TIMEOUT) -> None` — 二维码出现即返回；验证页抛 `LoginSessionError("platform_blocked")`；超时抛 `LoginSessionError("qr_timeout")`
  - `_open_and_watch` 行为变更：`goto` 后先调 `_wait_for_qr` 再置 `waiting_scan`；`LoginSessionError` → `status="error", detail=str(exc)`；其他异常 → `status="error", detail="browser_failed"`

- [ ] **Step 1: Update the test fixtures**

In `C:\01_agent_loop_pro\backend\tests\test_login_session_manager.py`, replace the `FakePage`/`FakeContext`/`FakeBrowser`/`_manager` block (lines ~16-72) with:

```python
class FakePage:
    def __init__(
        self,
        content: str = "首页 热门视频 用户",
        qr_selectors: list[str] | None = None,
        has_fallback_img: bool = True,
    ):
        self._content = content
        self._qr_selectors = qr_selectors or []
        self._has_fallback_img = has_fallback_img
        self.url = "https://www.douyin.com/"

    async def goto(self, url, wait_until="domcontentloaded", timeout=30000):
        self.url = url
        return None

    async def wait_for_timeout(self, ms):
        await asyncio.sleep(0)

    async def content(self):
        return f"<html><body>{self._content}</body></html>"

    async def query_selector(self, selector):
        if selector in self._qr_selectors:
            return object()
        if selector == "img" and self._has_fallback_img:
            return object()
        return None

    async def screenshot(self, **kwargs):
        return b"\xff\xd8\xff\xe0" + bytes(20)  # minimal JPEG header

    async def close(self):
        pass


class FakeContext:
    def __init__(
        self,
        cookie_names=None,
        content: str = "首页 热门视频 用户",
        qr_selectors: list[str] | None = None,
        has_fallback_img: bool = True,
    ):
        self._cookie_names = cookie_names or []
        self._page = FakePage(content, qr_selectors, has_fallback_img)

    async def add_init_script(self, js):
        pass

    async def new_page(self):
        return self._page

    async def cookies(self):
        return [{"name": n, "value": f"v_{n}"} for n in self._cookie_names]

    async def close(self):
        pass


class FakeBrowser:
    def __init__(
        self,
        cookie_names=None,
        content: str = "首页 热门视频 用户",
        qr_selectors: list[str] | None = None,
        has_fallback_img: bool = True,
    ):
        self._cookie_names = cookie_names
        self._content = content
        self._qr_selectors = qr_selectors
        self._has_fallback_img = has_fallback_img

    async def new_context(self, **kwargs):
        return FakeContext(
            self._cookie_names, self._content, self._qr_selectors, self._has_fallback_img
        )

    async def close(self):
        pass


def _manager(
    tmp_path,
    cookie_names=None,
    content="首页 热门视频 用户",
    qr_selectors: list[str] | None = None,
    has_fallback_img: bool = True,
):
    async def factory():
        return FakeBrowser(cookie_names, content, qr_selectors, has_fallback_img)

    return LoginSessionManager(browser_factory=factory, data_root=Path(tmp_path))
```

- [ ] **Step 2: Update the changed-behavior existing test**

Replace the whole `test_verification_page_not_marked_logged_in` test in `C:\01_agent_loop_pro\backend\tests\test_login_session_manager.py` with:

```python
@pytest.mark.anyio
async def test_verification_page_blocked(tmp_path, monkeypatch):
    # verification page is intercepted at QR-wait stage: platform_blocked
    m = _manager(tmp_path, content="验证中间页 请稍候")
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    st = await _wait_for(m, record.session_id, uid, {"error"}, timeout=5)
    assert st["status"] == "error"
    assert st["detail"] == "platform_blocked"
    await m.close(record.session_id, uid)
```

- [ ] **Step 3: Append the new test class**

Append to `C:\01_agent_loop_pro\backend\tests\test_login_session_manager.py`:

```python
class TestQrWait:
    @pytest.mark.anyio
    async def test_qr_selector_hit_reaches_waiting_scan(self, tmp_path):
        m = _manager(tmp_path, qr_selectors=["img[src*='qrcode']"])
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
        assert st["status"] == "waiting_scan"
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_fallback_img_reaches_waiting_scan(self, tmp_path):
        m = _manager(tmp_path)  # default has_fallback_img=True
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
        assert st["status"] == "waiting_scan"
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_no_qr_times_out(self, tmp_path):
        m = _manager(tmp_path, has_fallback_img=False)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"error"}, timeout=5)
        assert st["status"] == "error"
        assert st["detail"] == "qr_timeout"
        await m.close(record.session_id, uid)
```

- [ ] **Step 4: Run tests — expect the new QR tests to FAIL**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_login_session_manager.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: `TestQrWait.test_no_qr_times_out` FAIL（当前无 QR 检测，直接进 `waiting_scan`）且 `test_verification_page_blocked` FAIL（当前验证页不拦截，最终 `timeout` 而非 `error/platform_blocked`）。`test_qr_selector_hit_reaches_waiting_scan` 与 `test_fallback_img_reaches_waiting_scan` 在实现前恰好通过（现状即直接 waiting_scan）——属预期，实现后它们依然成立。

- [ ] **Step 5: Implement in login_session.py**

In `C:\01_agent_loop_pro\backend\app\services\agent\login_session.py`:

1. Add constants after `CONTENT_THRESHOLD: int = 500`:

```python
QR_WAIT_TIMEOUT: float = 20.0
QR_POLL_INTERVAL: float = 1.0

QR_SELECTORS: dict[str, list[str]] = {
    "douyin": ["img[src*='qrcode']", "canvas"],
    "xiaohongshu": ["img[src*='qrcode']", "canvas"],
}

QR_FALLBACK_SELECTOR: str = "img"
```

2. Add method `_wait_for_qr` to `LoginSessionManager` (place it right after `_open_and_watch`, before `_watch_login`):

```python
    async def _wait_for_qr(
        self, record: LoginSessionRecord, timeout: float = QR_WAIT_TIMEOUT
    ) -> None:
        """Wait until a QR code element renders; raise graded errors."""
        from app.services.agent.web_renderer import _extract_platform_content

        # initial verification-page guard
        html = await record.page.content()
        text = _extract_platform_content(html, LOGIN_URLS[record.platform])["text"]
        if assess_login_expired(record.platform, text):
            raise LoginSessionError("platform_blocked")

        deadline = time.monotonic() + timeout
        selectors = QR_SELECTORS.get(record.platform, [])
        while time.monotonic() < deadline:
            for sel in selectors:
                try:
                    el = await record.page.query_selector(sel)
                except Exception:
                    el = None
                if el is not None:
                    return
            # fallback: any img on a non-verification page counts as QR
            try:
                el = await record.page.query_selector(QR_FALLBACK_SELECTOR)
                if el is not None:
                    html = await record.page.content()
                    text = _extract_platform_content(html, LOGIN_URLS[record.platform])["text"]
                    if not assess_login_expired(record.platform, text):
                        return
            except Exception:
                pass
            await asyncio.sleep(QR_POLL_INTERVAL)
        raise LoginSessionError("qr_timeout")
```

3. In `_open_and_watch`, replace:

```python
            await page.goto(LOGIN_URLS[record.platform], wait_until="domcontentloaded", timeout=30000)
            record.status = "waiting_scan"
            await self._watch_login(record)
```

with:

```python
            await page.goto(LOGIN_URLS[record.platform], wait_until="domcontentloaded", timeout=30000)
            await self._wait_for_qr(record)
            record.status = "waiting_scan"
            await self._watch_login(record)
```

4. In `_open_and_watch`, replace the exception handler:

```python
        except Exception as exc:
            record.status = "error"
            record.detail = str(exc)[:300]
            logger.error("login_session_open_failed: %s", exc)
```

with:

```python
        except LoginSessionError as exc:
            record.status = "error"
            record.detail = str(exc)
            logger.warning("login_session_qr_failed: %s", exc)
        except Exception as exc:
            record.status = "error"
            record.detail = "browser_failed"
            logger.error("login_session_open_failed: %s", exc)
```

- [ ] **Step 6: Run tests — must PASS**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_login_session_manager.py tests/test_login_session.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: all pass (manager + 16 pure). Verify the three `TestQrWait` tests pass and `test_verification_page_blocked` passes.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/agent/login_session.py backend/tests/test_login_session_manager.py
git commit -m "feat: QR render detection with graded errors in login sessions"
```
Workdir: `C:\01_agent_loop_pro`

---

### Task 3: 前端扫码弹窗美化（简约现代）

**Files:**
- Modify: `frontend/src/components/feishu/platform-login-modal.tsx`（整体重写）

**Interfaces:**
- Consumes: Task 2 的错误 detail 契约（`platform_blocked` / `qr_timeout` / `browser_failed`）；既有 API 端点不变
- Produces: 同名的 `PlatformLoginModal` 组件（props 不变），视觉与错误处理升级

- [ ] **Step 1: Rewrite the modal component**

Replace the ENTIRE content of `C:\01_agent_loop_pro\frontend\src\components\feishu\platform-login-modal.tsx` with:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { Modal, Button, Tag, Spin, message } from "antd";
import { QrcodeOutlined, ReloadOutlined, CloseOutlined, SafetyOutlined } from "@ant-design/icons";
import { api } from "@/lib/api";

interface CookieItem {
  domain: string;
  cookie_string: string;
}

const PLATFORMS = [
  { key: "douyin", name: "抖音", domain: "www.douyin.com", iconBg: "#141414", iconChar: "♪" },
  { key: "xiaohongshu", name: "小红书", domain: "www.xiaohongshu.com", iconBg: "#ff2442", iconChar: "红" },
];

const ERROR_TEXT: Record<string, string> = {
  platform_blocked: "平台安全验证拦截，请稍后重试",
  qr_timeout: "二维码加载超时，请点击刷新",
  browser_failed: "浏览器启动失败，请稍后重试",
};

interface PlatformLoginModalProps {
  open: boolean;
  onClose: () => void;
}

export default function PlatformLoginModal({ open, onClose }: PlatformLoginModalProps) {
  const [items, setItems] = useState<CookieItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanPlatform, setScanPlatform] = useState<string>("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [scanStatus, setScanStatus] = useState<string>("");
  const [image, setImage] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string>("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionRef = useRef<string | null>(null);

  const loggedDomains = new Set(items.map((i) => i.domain));

  async function load() {
    setLoading(true);
    try {
      const data = await api<{ items: CookieItem[] }>("/api/agent/cookies");
      setItems(data.items);
    } catch {
      message.error("加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) load();
  }, [open]);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  useEffect(() => {
    return () => stopPolling();
  }, []);

  async function startScan(platformKey: string) {
    stopPolling();
    setScanning(true);
    setScanPlatform(platformKey);
    setScanStatus("starting");
    setImage(null);
    setScanError("");
    try {
      const data = await api<{ session_id: string; status: string }>(
        "/api/agent/login-sessions",
        { method: "POST", body: JSON.stringify({ platform: platformKey }), csrf: true }
      );
      sessionRef.current = data.session_id;
      setSessionId(data.session_id);
      setScanStatus(data.status);
      pollRef.current = setInterval(() => {
        void pollSession();
      }, 800);
    } catch {
      setScanError("无法启动登录，请稍后重试");
      setScanning(false);
    }
  }

  async function pollSession() {
    const sid = sessionRef.current;
    if (!sid) return;
    try {
      const frameData = await api<{ image: string | null }>(
        `/api/agent/login-sessions/${sid}/frame`
      );
      if (frameData.image) setImage(frameData.image);
    } catch {
      /* frame errors are non-fatal, keep polling */
    }
    try {
      const st = await api<{ status: string; detail: string }>(
        `/api/agent/login-sessions/${sid}/status`
      );
      setScanStatus(st.status);
      if (st.status === "logged_in") {
        stopPolling();
        message.success("登录成功");
        setScanning(false);
        sessionRef.current = null;
        load();
      } else if (st.status === "timeout") {
        stopPolling();
        setScanError("登录超时，请重新扫码");
        setScanning(false);
      } else if (st.status === "error") {
        stopPolling();
        setScanError(ERROR_TEXT[st.detail] ?? st.detail || "登录失败，请重试");
        setScanning(false);
      }
    } catch {
      /* status errors are non-fatal */
    }
  }

  async function handleRefresh() {
    const sid = sessionRef.current;
    if (!sid) return;
    try {
      await api(`/api/agent/login-sessions/${sid}/refresh`, {
        method: "POST",
        csrf: true,
      });
      message.info("已刷新，请重新扫码");
    } catch {
      message.error("刷新失败");
    }
  }

  async function handleCloseScan() {
    const sid = sessionRef.current;
    if (sid) {
      try {
        await api(`/api/agent/login-sessions/${sid}`, { method: "DELETE", csrf: true });
      } catch {
        /* ignore */
      }
    }
    sessionRef.current = null;
    stopPolling();
    setScanning(false);
    load();
  }

  function handleRetry() {
    if (scanPlatform) startScan(scanPlatform);
  }

  const platform = PLATFORMS.find((p) => p.key === scanPlatform);

  return (
    <Modal title="平台登录" open={open} onCancel={onClose} footer={null} width={560} destroyOnClose>
      {!scanning ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ fontSize: 13, color: "#8c8c8c", padding: "2px 4px" }}>
            连接抖音 / 小红书登录态，Agent 抓取内容时自动使用你的账号
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {PLATFORMS.map((p) => {
              const logged = loggedDomains.has(p.domain);
              return (
                <div
                  key={p.key}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "14px 16px",
                    borderRadius: 10,
                    background: "#fafafa",
                    border: "1px solid #f0f0f0",
                    transition: "box-shadow 0.2s ease",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLElement).style.boxShadow = "0 2px 8px rgba(0,0,0,0.08)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.boxShadow = "none";
                  }}
                >
                  <div
                    style={{
                      width: 40,
                      height: 40,
                      borderRadius: "50%",
                      background: p.iconBg,
                      color: "#fff",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 18,
                      flexShrink: 0,
                    }}
                  >
                    {p.iconChar}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600 }}>{p.name}</div>
                    <div style={{ fontSize: 12, color: "#8c8c8c", marginTop: 2 }}>
                      {p.domain}
                    </div>
                  </div>
                  <Tag color={logged ? "success" : "default"} style={{ borderRadius: 12, marginRight: 0 }}>
                    {logged ? "已登录" : "未登录"}
                  </Tag>
                  <Button
                    type={logged ? "default" : "primary"}
                    icon={<QrcodeOutlined />}
                    onClick={() => startScan(p.key)}
                  >
                    {logged ? "重新扫码" : "扫码登录"}
                  </Button>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 24,
                height: 24,
                borderRadius: "50%",
                background: platform?.iconBg ?? "#141414",
                color: "#fff",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 12,
              }}
            >
              {platform?.iconChar ?? "♪"}
            </div>
            <span style={{ fontWeight: 600 }}>{platform?.name ?? ""}</span>
            {scanStatus === "waiting_scan" && (
              <Tag color="processing" style={{ borderRadius: 12 }}>
                <span
                  style={{
                    display: "inline-block",
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: "#1677ff",
                    marginRight: 6,
                    animation: "plm-blink 1.2s infinite",
                  }}
                />
                等待扫码
              </Tag>
            )}
          </div>

          <p style={{ fontSize: 13, color: "#595959", margin: 0 }}>
            打开{platform?.name ?? ""}App 扫一扫，确认登录
          </p>

          <div
            style={{
              width: 320,
              padding: 16,
              borderRadius: 12,
              background: "#fff",
              border: "1px solid #f0f0f0",
              boxShadow: "0 4px 16px rgba(0,0,0,0.06)",
              textAlign: "center",
            }}
          >
            {image ? (
              <img
                src={`data:image/jpeg;base64,${image}`}
                alt="登录二维码"
                style={{ maxWidth: 288, width: "100%", borderRadius: 8, display: "block" }}
              />
            ) : (
              <div style={{ height: 288, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Spin size="large" />
              </div>
            )}
          </div>

          {scanError && (
            <div
              style={{
                width: "100%",
                background: "#fff1f0",
                border: "1px solid #ffa39e",
                color: "#cf1322",
                borderRadius: 8,
                padding: "8px 12px",
                fontSize: 13,
                textAlign: "center",
              }}
            >
              {scanError}
            </div>
          )}

          <div style={{ display: "flex", gap: 10 }}>
            {scanError ? (
              <Button type="primary" icon={<ReloadOutlined />} onClick={handleRetry}>
                重试
              </Button>
            ) : (
              <Button icon={<ReloadOutlined />} onClick={handleRefresh} disabled={!sessionId}>
                二维码失效？刷新
              </Button>
            )}
            <Button icon={<CloseOutlined />} onClick={handleCloseScan}>
              取消登录
            </Button>
          </div>

          {!scanError && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#bfbfbf" }}>
              <SafetyOutlined />
              登录态仅用于为你抓取内容，加密保存
            </div>
          )}

          <style>{`
            @keyframes plm-blink {
              0%, 100% { opacity: 1; }
              50% { opacity: 0.25; }
            }
          `}</style>
        </div>
      )}
    </Modal>
  );
}
```

NOTE: `destroyOnClose` on Modal — verify this prop is still valid in this Next.js/AntD version (`modal` props); if deprecated, remove it.

- [ ] **Step 2: TypeScript check**

Run: `npx tsc --noEmit` (workdir `C:\01_agent_loop_pro\frontend`)
Expected: no NEW errors from your file. (Pre-existing errors in other files — including other parallel work — are not yours to fix; only ensure `platform-login-modal.tsx` compiles.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/feishu/platform-login-modal.tsx
git commit -m "feat: polish platform login modal UI with error grading"
```
Workdir: `C:\01_agent_loop_pro`

---

### Task 4: E2E 验证与收尾

**Files:**
- No new files (verification only)

- [ ] **Step 1: Restart the web_renderer process**

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'web_renderer' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
Start-Process -FilePath "X:\python\anaconda\envs\01-rbac\python.exe" -ArgumentList "-m","app.workers.web_renderer" -WorkingDirectory "C:\01_agent_loop_pro\backend" -WindowStyle Hidden
Start-Sleep -Seconds 6
```
Expected: process running (re-check with the Get-CimInstance query).

- [ ] **Step 2: Smoke-test QR detection via worker endpoints**

```powershell
$body = '{"platform":"douyin","owner_user_id":"00000000-0000-0000-0000-000000000001"}'
$r = Invoke-RestMethod -Uri "http://127.0.0.1:9001/login-sessions" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 20
$sid = $r.session_id
Start-Sleep -Seconds 8
$st = Invoke-RestMethod -Uri "http://127.0.0.1:9001/login-sessions/$sid/status" -Headers @{"X-Owner-User-Id"="00000000-0000-0000-0000-000000000001"} -TimeoutSec 20
$st.status
$st.detail
Invoke-RestMethod -Uri "http://127.0.0.1:9001/login-sessions/$sid" -Method DELETE -Headers @{"X-Owner-User-Id"="00000000-0000-0000-0000-000000000001"} -TimeoutSec 20
```
Expected: `status` = `waiting_scan`（patchright 已绕过反爬且 QR 检测通过）。若 `status=error`：检查 `detail` —— `platform_blocked`/`qr_timeout` 说明 selector 需校准（按 detail 上报），`browser_failed` 说明异常。

再测小红书：
```powershell
$body = '{"platform":"xiaohongshu","owner_user_id":"00000000-0000-0000-0000-000000000001"}'
$r = Invoke-RestMethod -Uri "http://127.0.0.1:9001/login-sessions" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 20
$sid = $r.session_id
Start-Sleep -Seconds 8
$st = Invoke-RestMethod -Uri "http://127.0.0.1:9001/login-sessions/$sid/status" -Headers @{"X-Owner-User-Id"="00000000-0000-0000-0000-000000000001"} -TimeoutSec 20
$st.status
$st.detail
Invoke-RestMethod -Uri "http://127.0.0.1:9001/login-sessions/$sid" -Method DELETE -Headers @{"X-Owner-User-Id"="00000000-0000-0000-0000-000000000001"} -TimeoutSec 20
```
Expected: `waiting_scan`。

- [ ] **Step 3: Full backend test suite**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: 4 known failures only (`test_file_reader.py` pypdf 缺失，既有），其余全部通过。

- [ ] **Step 4: Manual scan verification (user)**

1. 前端刷新页面，打开顶栏"平台登录"
2. 抖音卡片 → 扫码登录 → 应出现二维码画面（不再是验证页/空白）
3. 用手机抖音 App 扫码 → 自动提示"登录成功"，卡片变"已登录"
4. 关闭 Modal，让 agent"看看抖音首页有什么热门内容"
5. 预期：agent 返回真实视频流内容（非验证页）

- [ ] **Step 5: Commit any fixes**

```bash
git add <precise paths of changed files>
git commit -m "fix: adjustments from QR login E2E verification"
```
(仅当有修复时执行；无改动则跳过。遵守 Global Constraints 的 git 纪律——只 add 精确路径。)
