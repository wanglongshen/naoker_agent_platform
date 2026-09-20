# 平台扫码登录（抖音/小红书）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让非技术用户通过手机扫码（托管浏览器 + 截图流）完成抖音/小红书登录态配置，agent 抓取自动使用，登录态严格按用户隔离。

**Architecture:** 在现有 `web_renderer` 进程（端口 9001）内新增 `LoginSessionManager`：每个会话 = 独立 Playwright context + 临时用户数据目录，打开平台登录页后前端轮询截图帧（800ms），登录成功信号（凭证 cookie 出现 + 首页抓取非验证页双保险）后自动导出 cookies 写入现有 `user_web_cookies` 表（AES-GCM 加密，`web_cookie_store.py`）。API 层（8000）负责鉴权与归属校验后转发到 worker。抓取链路仅新增 `login_expired` 判定字段。

**Tech Stack:** Python 3.12, Playwright (async), FastAPI, httpx, SQLAlchemy 2.0

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-03-platform-login-scan-design.md`
- 平台映射（唯一真源，各任务必须一致）：
  - `douyin` → 登录页 `https://www.douyin.com/`，域名 `www.douyin.com`，凭证 cookie `pass_token`
  - `xiaohongshu` → 登录页 `https://www.xiaohongshu.com/explore`，域名 `www.xiaohongshu.com`，凭证 cookie `web_session`
- 会话超时：总时长 600 秒；截图轮询 800ms；登录检测间隔 1.5s；内容阈值 500 字符
- 验证页特征：`captcha`、`verify_data`、`验证中间页`、`安全验证`（小写匹配）
- 多租户铁律：所有会话 API 校验归属（非本人 403）；存储按 `owner_user_id` 过滤；无任何跨用户查看端点
- 每个用户同时最多 1 个活跃会话（409）
- 登录成功后：导出 cookies → `save_user_cookie(owner, DOMAIN_BY_PLATFORM[platform], cookie_string)`，Cookie 字符串格式 `name1=value1; name2=value2`
- Cookie 加密复用 `app/services/feishu/crypto.py`（经 `web_cookie_store.py`，勿直接改动）
- 不做：点击/键盘交互、多会话并发、手动粘贴入口
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；后端测试工作目录 `C:\01_agent_loop_pro\backend`
- 会话数据目录：`C:\01_agent_loop_pro\backend\var\login_sessions\<user_id>\<session_id>\`

---

### Task 1: 验证页识别 + 登录信号纯逻辑

**Files:**
- Create: `backend/app/services/agent/login_session.py`（本任务只写纯函数部分，Task 2 追加 manager）
- Test: `backend/tests/test_login_session.py`

**Interfaces:**
- Consumes: 无（纯函数，无依赖）
- Produces:
  - `PLATFORMS: tuple[str, ...]` = `("douyin", "xiaohongshu")`
  - `LOGIN_URLS: dict[str, str]`、`DOMAIN_BY_PLATFORM: dict[str, str]`、`SESSION_CREDENTIAL_COOKIES: dict[str, str]`、`SESSION_TTL_SECONDS: int` = 600、`LOGIN_CHECK_INTERVAL: float` = 1.5、`CONTENT_THRESHOLD: int` = 500
  - `is_verification_page(text: str) -> bool`
  - `assess_login_expired(platform: str, text: str) -> bool`
  - `detect_login_signal(platform: str, cookie_names: list[str]) -> bool`
  - `cookies_to_string(cookies: list[dict]) -> str`

- [ ] **Step 1: Write the failing test**

Create `C:\01_agent_loop_pro\backend\tests\test_login_session.py`:

```python
from app.services.agent.login_session import (
    assess_login_expired,
    cookies_to_string,
    detect_login_signal,
    is_verification_page,
)


class TestVerificationPage:
    def test_detects_captcha(self):
        assert is_verification_page("请完成 captcha 验证")

    def test_detects_verify_data(self):
        assert is_verification_page('const verify_data = {"code":"10000"}')

    def test_detects_chinese_verification(self):
        assert is_verification_page("<title>验证中间页</title>")

    def test_detects_security_verification(self):
        assert is_verification_page("正在进行安全验证，请稍候")

    def test_normal_content_false(self):
        assert not is_verification_page("热门视频 用户主页 直播 推荐")


class TestAssessLoginExpired:
    def test_douyin_short_verification_true(self):
        assert assess_login_expired("douyin", "验证中间页 请稍候") is True

    def test_xhs_short_verification_true(self):
        assert assess_login_expired("xiaohongshu", "captcha verify") is True

    def test_long_content_false(self):
        assert assess_login_expired("douyin", "x" * 600) is False

    def test_verification_but_long_text_false(self):
        assert assess_login_expired("douyin", "captcha" + "x" * 600) is False

    def test_generic_platform_false(self):
        assert assess_login_expired("generic", "验证中间页") is False


class TestDetectLoginSignal:
    def test_credential_cookie_hit(self):
        assert detect_login_signal("douyin", ["pass_token"]) is True

    def test_xhs_credential_cookie_hit(self):
        assert detect_login_signal("xiaohongshu", ["web_session"]) is True

    def test_no_credential_false(self):
        assert detect_login_signal("douyin", ["sessionid", "ttwid"]) is False

    def test_unknown_platform_false(self):
        assert detect_login_signal("weibo", ["pass_token"]) is False


class TestCookiesToString:
    def test_basic(self):
        cookies = [{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]
        assert cookies_to_string(cookies) == "a=1; b=2"

    def test_skips_empty_pairs(self):
        cookies = [{"name": "", "value": "1"}, {"name": "b", "value": ""}, {"name": "c", "value": "3"}]
        assert cookies_to_string(cookies) == "c=3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_login_session.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.agent.login_session'`

- [ ] **Step 3: Write minimal implementation**

Create `C:\01_agent_loop_pro\backend\app\services\agent\login_session.py`:

```python
"""Platform login session management (pure logic + LoginSessionManager).

Pure functions in this file are unit-tested without a browser.
The manager (Task 2) accepts an injected browser_factory for testability.
"""

from __future__ import annotations

PLATFORMS: tuple[str, ...] = ("douyin", "xiaohongshu")

LOGIN_URLS: dict[str, str] = {
    "douyin": "https://www.douyin.com/",
    "xiaohongshu": "https://www.xiaohongshu.com/explore",
}

DOMAIN_BY_PLATFORM: dict[str, str] = {
    "douyin": "www.douyin.com",
    "xiaohongshu": "www.xiaohongshu.com",
}

SESSION_CREDENTIAL_COOKIES: dict[str, str] = {
    "douyin": "pass_token",
    "xiaohongshu": "web_session",
}

SESSION_TTL_SECONDS: int = 600
LOGIN_CHECK_INTERVAL: float = 1.5
CONTENT_THRESHOLD: int = 500

_VERIFICATION_MARKERS: tuple[str, ...] = ("captcha", "verify_data", "验证中间页", "安全验证")


def is_verification_page(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _VERIFICATION_MARKERS)


def assess_login_expired(platform: str, text: str) -> bool:
    if platform not in PLATFORMS:
        return False
    if len(text.strip()) >= CONTENT_THRESHOLD:
        return False
    return is_verification_page(text)


def detect_login_signal(platform: str, cookie_names: list[str]) -> bool:
    if platform not in PLATFORMS:
        return False
    return SESSION_CREDENTIAL_COOKIES[platform] in cookie_names


def cookies_to_string(cookies: list[dict]) -> str:
    pairs = [
        f"{c['name']}={c['value']}"
        for c in cookies
        if c.get("name") and c.get("value")
    ]
    return "; ".join(pairs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_login_session.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/login_session.py backend/tests/test_login_session.py
git commit -m "feat: verification page detection and login signal pure logic"
```

---

### Task 2: LoginSessionManager（生命周期 + 截图 + 导出 + 清理）

**Files:**
- Modify: `backend/app/services/agent/login_session.py`（追加 manager，保留 Task 1 全部内容）
- Test: `backend/tests/test_login_session_manager.py`

**Interfaces:**
- Consumes: Task 1 全部常量/函数；`web_cookie_store.save_user_cookie(owner_user_id: uuid.UUID, domain: str, cookie_string: str) -> None`；`web_renderer._extract_platform_content(html: str, url: str) -> dict`
- Produces:
  - `class LoginSessionError(Exception)`、`class SessionConflictError(LoginSessionError)`、`class SessionNotFoundError(LoginSessionError)`、`class SessionNotOwnerError(LoginSessionError)`
  - `class LoginSessionManager`:
    - `__init__(self, browser_factory=None, data_root: Path | None = None)` — `browser_factory` 为可调用，返回 Playwright Browser 对象
    - `async start(self, owner_user_id: uuid.UUID, platform: str) -> LoginSessionRecord` — 返回记录（含 `session_id: str`、`status: str`）
    - `async frame(self, session_id: str, owner_user_id: uuid.UUID) -> str | None` — JPEG base64 或 None
    - `async status(self, session_id: str, owner_user_id: uuid.UUID) -> dict` — `{"session_id", "status", "detail"}`
    - `async refresh(self, session_id: str, owner_user_id: uuid.UUID) -> None`
    - `async close(self, session_id: str, owner_user_id: uuid.UUID) -> bool`
    - `@staticmethod cleanup_orphans(data_root: Path) -> int` — 同步删除 mtime 超过 `SESSION_TTL_SECONDS` 的目录

- [ ] **Step 1: Write the failing test**

Create `C:\01_agent_loop_pro\backend\tests\test_login_session_manager.py`:

```python
import asyncio
import time
import uuid
from pathlib import Path

import pytest

from app.services.agent.login_session import (
    LoginSessionManager,
    SessionConflictError,
    SessionNotOwnerError,
    cookies_to_string,
)


class FakePage:
    def __init__(self, content: str = "首页 热门视频 用户"):
        self._content = content
        self.url = "https://www.douyin.com/"

    async def goto(self, url, wait_until="domcontentloaded", timeout=30000):
        self.url = url
        return None

    async def wait_for_timeout(self, ms):
        await asyncio.sleep(0)

    async def content(self):
        return f"<html><body>{self._content}</body></html>"

    async def screenshot(self, **kwargs):
        return b"\xff\xd8\xff\xe0" + bytes(20)  # minimal JPEG header

    async def close(self):
        pass


class FakeContext:
    def __init__(self, cookie_names=None, content: str = "首页 热门视频 用户"):
        self._cookie_names = cookie_names or []
        self._page = FakePage(content)

    async def add_init_script(self, js):
        pass

    async def new_page(self):
        return self._page

    async def cookies(self):
        return [{"name": n, "value": f"v_{n}"} for n in self._cookie_names]

    async def close(self):
        pass


class FakeBrowser:
    def __init__(self, cookie_names=None, content: str = "首页 热门视频 用户"):
        self._cookie_names = cookie_names
        self._content = content

    async def new_context(self, **kwargs):
        return FakeContext(self._cookie_names, self._content)

    async def close(self):
        pass


def _manager(tmp_path, cookie_names=None, content="首页 热门视频 用户"):
    async def factory():
        return FakeBrowser(cookie_names, content)

    return LoginSessionManager(browser_factory=factory, data_root=Path(tmp_path))


async def _wait_for(m, session_id, uid, target, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = await m.status(session_id, uid)
        if st["status"] in target:
            return st
        await asyncio.sleep(0.01)
    return await m.status(session_id, uid)


@pytest.mark.anyio
async def test_start_then_waiting_scan(tmp_path, monkeypatch):
    m = _manager(tmp_path)
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
    assert st["status"] == "waiting_scan"
    await m.close(record.session_id, uid)


@pytest.mark.anyio
async def test_login_success_exports_cookie(tmp_path, monkeypatch):
    saved = {}

    async def fake_save(owner_user_id, domain, cookie_string):
        saved["owner"] = str(owner_user_id)
        saved["domain"] = domain
        saved["cookie_string"] = cookie_string

    monkeypatch.setattr(
        "app.services.agent.login_session.save_user_cookie", fake_save
    )
    m = _manager(tmp_path, cookie_names=["pass_token", "sessionid"])
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    st = await _wait_for(m, record.session_id, uid, {"logged_in"}, timeout=5)
    assert st["status"] == "logged_in"
    assert saved["owner"] == str(uid)
    assert saved["domain"] == "www.douyin.com"
    assert "pass_token=v_pass_token" in saved["cookie_string"]
    await m.close(record.session_id, uid)


@pytest.mark.anyio
async def test_verification_page_not_marked_logged_in(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(
        "app.services.agent.login_session.save_user_cookie", fake_save
    )

    async def fake_save(owner_user_id, domain, cookie_string):
        saved["cookie_string"] = cookie_string

    # credential cookie appears but home page still verification -> keep waiting
    m = _manager(
        tmp_path, cookie_names=["pass_token"], content="验证中间页 请稍候"
    )
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    # run watch loop with short ttl; it should time out, NOT log in
    await m._watch_login(record, ttl_seconds=0.1, check_interval=0.01)
    assert record.status == "timeout"
    assert "cookie_string" not in saved


@pytest.mark.anyio
async def test_ttl_timeout(tmp_path):
    m = _manager(tmp_path)
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
    record.started_at = time.monotonic() - 1000
    await m._watch_login(record, ttl_seconds=0.05, check_interval=0.01)
    st = await m.status(record.session_id, uid)
    assert st["status"] == "timeout"
    await m.close(record.session_id, uid)


@pytest.mark.anyio
async def test_per_user_conflict(tmp_path):
    m = _manager(tmp_path)
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
    with pytest.raises(SessionConflictError):
        await m.start(uid, "xiaohongshu")
    await m.close(record.session_id, uid)


@pytest.mark.anyio
async def test_other_user_forbidden(tmp_path):
    m = _manager(tmp_path)
    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()
    record = await m.start(uid_a, "douyin")
    st = await _wait_for(m, record.session_id, uid_a, {"waiting_scan"})
    with pytest.raises(SessionNotOwnerError):
        await m.status(record.session_id, uid_b)
    with pytest.raises(SessionNotOwnerError):
        await m.frame(record.session_id, uid_b)
    with pytest.raises(SessionNotOwnerError):
        await m.close(record.session_id, uid_b)
    await m.close(record.session_id, uid_a)


@pytest.mark.anyio
async def test_frame_returns_image(tmp_path):
    m = _manager(tmp_path)
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
    img = await m.frame(record.session_id, uid)
    assert img is not None
    assert img.startswith("/9j/")  # JPEG base64 magic
    await m.close(record.session_id, uid)


class TestCleanupOrphans:
    def test_deletes_old_dirs(self, tmp_path):
        root = Path(tmp_path) / "sessions"
        old = root / "u1" / "s1"
        new = root / "u2" / "s2"
        old.mkdir(parents=True)
        new.mkdir(parents=True)
        (old / "f").write_text("x")
        (new / "f").write_text("x")
        # fake old mtime
        import os

        os.utime(old, (time.time() - 10000, time.time() - 10000))
        deleted = LoginSessionManager.cleanup_orphans(root)
        assert deleted == 1
        assert not old.exists()
        assert new.exists()


class TestCookiesToStr:
    def test_used_by_export(self):
        assert cookies_to_string([{"name": "a", "value": "1"}]) == "a=1"
```

NOTE: `test_verification_page_not_marked_logged_in` and `test_ttl_timeout` call `m._watch_login(...)` directly with fast timing — this is intentional for test speed.

- [ ] **Step 2: Run test to verify it fails**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_login_session_manager.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: FAIL with `ImportError` / `AttributeError: module 'app.services.agent.login_session' has no attribute 'LoginSessionManager'`

- [ ] **Step 3: Append the manager to login_session.py**

Append to `C:\01_agent_loop_pro\backend\app\services\agent\login_session.py`:

```python
import asyncio
import base64
import logging
import random
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.services.agent.web_cookie_store import save_user_cookie

logger = logging.getLogger("login_session")

RETENTION_SECONDS: int = 300  # keep finished records queryable


class LoginSessionError(Exception):
    pass


class SessionConflictError(LoginSessionError):
    pass


class SessionNotFoundError(LoginSessionError):
    pass


class SessionNotOwnerError(LoginSessionError):
    pass


@dataclass
class LoginSessionRecord:
    session_id: str
    owner_user_id: uuid.UUID
    platform: str
    status: str = "starting"  # starting|waiting_scan|logged_in|timeout|error
    detail: str = ""
    context: object | None = None
    browser: object | None = None
    page: object | None = None
    user_data_dir: Path | None = None
    started_at: float = field(default_factory=time.monotonic)


async def _default_browser_factory():
    from playwright.async_api import async_playwright

    p = await async_playwright().start()
    return await p.chromium.launch(headless=True)


class LoginSessionManager:
    def __init__(
        self,
        browser_factory=None,
        data_root: Path | None = None,
    ) -> None:
        self._sessions: dict[str, LoginSessionRecord] = {}
        self._lock = asyncio.Lock()
        self._browser_factory = browser_factory or _default_browser_factory
        self._data_root = data_root or Path(__file__).resolve().parents[2] / "var" / "login_sessions"

    async def start(self, owner_user_id: uuid.UUID, platform: str) -> LoginSessionRecord:
        platform = platform.strip().lower()
        if platform not in PLATFORMS:
            raise LoginSessionError(f"unsupported_platform: {platform}")
        await self._purge_stale()
        async with self._lock:
            for rec in self._sessions.values():
                if rec.owner_user_id == owner_user_id and rec.status in ("starting", "waiting_scan"):
                    raise SessionConflictError("active_session_exists")
            record = LoginSessionRecord(
                session_id=uuid.uuid4().hex[:16],
                owner_user_id=owner_user_id,
                platform=platform,
            )
            self._sessions[record.session_id] = record
        asyncio.create_task(self._open_and_watch(record))
        return record

    async def _purge_stale(self) -> None:
        async with self._lock:
            now = time.monotonic()
            for sid in [
                s
                for s, r in self._sessions.items()
                if now - r.started_at > RETENTION_SECONDS
            ]:
                self._sessions.pop(sid, None)

    async def _get_owned(
        self, session_id: str, owner_user_id: uuid.UUID
    ) -> LoginSessionRecord:
        record = self._sessions.get(session_id)
        if record is None:
            raise SessionNotFoundError("session_not_found")
        if str(record.owner_user_id) != str(owner_user_id):
            raise SessionNotOwnerError("session_not_owned")
        return record

    async def frame(self, session_id: str, owner_user_id: uuid.UUID) -> str | None:
        record = await self._get_owned(session_id, owner_user_id)
        if record.page is None:
            return None
        try:
            shot = await record.page.screenshot(type="jpeg", quality=60)
            return base64.b64encode(shot).decode("ascii")
        except Exception:
            return None

    async def status(self, session_id: str, owner_user_id: uuid.UUID) -> dict:
        record = await self._get_owned(session_id, owner_user_id)
        return {
            "session_id": record.session_id,
            "status": record.status,
            "detail": record.detail,
        }

    async def refresh(self, session_id: str, owner_user_id: uuid.UUID) -> None:
        record = await self._get_owned(session_id, owner_user_id)
        if record.page is not None and record.status == "waiting_scan":
            try:
                await record.page.goto(LOGIN_URLS[record.platform], wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass

    async def close(self, session_id: str, owner_user_id: uuid.UUID) -> bool:
        record = await self._get_owned(session_id, owner_user_id)
        async with self._lock:
            self._sessions.pop(session_id, None)
        await self._release_browser(record)
        return True

    async def _open_and_watch(self, record: LoginSessionRecord) -> None:
        try:
            browser = await self._browser_factory()
            record.browser = browser
            context = await browser.new_context(
                viewport={"width": 900, "height": 1200},
                user_agent=_random_ua(),
                locale="zh-CN",
            )
            await context.add_init_script(_stealth_js())
            record.context = context
            page = await context.new_page()
            record.page = page
            user_dir = self._data_root / str(record.owner_user_id) / record.session_id
            user_dir.mkdir(parents=True, exist_ok=True)
            record.user_data_dir = user_dir
            await page.goto(LOGIN_URLS[record.platform], wait_until="domcontentloaded", timeout=30000)
            record.status = "waiting_scan"
            await self._watch_login(record)
        except Exception as exc:
            record.status = "error"
            record.detail = str(exc)[:300]
            logger.error("login_session_open_failed: %s", exc)
        finally:
            await self._release_browser(record)

    async def _watch_login(
        self,
        record: LoginSessionRecord,
        ttl_seconds: float = SESSION_TTL_SECONDS,
        check_interval: float = LOGIN_CHECK_INTERVAL,
    ) -> None:
        while record.status == "waiting_scan":
            if time.monotonic() - record.started_at > ttl_seconds:
                record.status = "timeout"
                return
            try:
                cookies = await record.context.cookies()
                names = [c["name"] for c in cookies]
                if detect_login_signal(record.platform, names):
                    content = await self._fetch_home_content(record)
                    if assess_login_expired(record.platform, content):
                        await asyncio.sleep(check_interval)
                        continue
                    record.status = "logged_in"
                    await self._export_cookie(record, cookies)
                    return
            except Exception as exc:
                logger.warning("login_session_watch_error: %s", exc)
            await asyncio.sleep(check_interval)

    async def _fetch_home_content(self, record: LoginSessionRecord) -> str:
        try:
            await record.page.goto(LOGIN_URLS[record.platform], wait_until="domcontentloaded", timeout=30000)
            await record.page.wait_for_timeout(3000)
            html = await record.page.content()
            from app.services.agent.web_renderer import _extract_platform_content

            result = _extract_platform_content(html, LOGIN_URLS[record.platform])
            return result["text"]
        except Exception:
            return ""

    async def _export_cookie(self, record: LoginSessionRecord, cookies: list[dict]) -> None:
        cookie_str = cookies_to_string(cookies)
        if cookie_str:
            await save_user_cookie(
                record.owner_user_id,
                DOMAIN_BY_PLATFORM[record.platform],
                cookie_str,
            )
            logger.info("login_session_cookie_exported platform=%s", record.platform)

    async def _release_browser(self, record: LoginSessionRecord) -> None:
        for obj in (record.page, record.context, record.browser):
            if obj is not None:
                try:
                    await obj.close()
                except Exception:
                    pass
        if record.user_data_dir is not None and record.user_data_dir.exists():
            try:
                shutil.rmtree(record.user_data_dir, ignore_errors=True)
            except Exception:
                pass
        record.page = None
        record.context = None
        record.browser = None

    @staticmethod
    def cleanup_orphans(data_root: Path) -> int:
        if not data_root.exists():
            return 0
        deleted = 0
        cutoff = time.time() - SESSION_TTL_SECONDS
        for user_dir in data_root.iterdir():
            if not user_dir.is_dir():
                continue
            for session_dir in user_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                try:
                    if session_dir.stat().st_mtime < cutoff:
                        shutil.rmtree(session_dir, ignore_errors=True)
                        deleted += 1
                except OSError:
                    continue
        return deleted


def _random_ua() -> str:
    return random.choice(
        [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        ]
    )


def _stealth_js() -> str:
    return """
    delete navigator.webdriver;
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = window.chrome || { runtime: {} };
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_login_session_manager.py tests/test_login_session.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: all pass (12 manager + 13 pure)

If `test_frame_returns_image` fails because screenshot bytes aren't valid JPEG base64 (`/9j/` magic): adjust the FakePage screenshot to return real minimal JPEG bytes `b"\xff\xd8\xff\xe0..."` — update the test fixture so `base64` of it starts with `/9j/`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/login_session.py backend/tests/test_login_session_manager.py
git commit -m "feat: login session manager with lifecycle, screenshot and cookie export"
```

---

### Task 3: 登录会话端点（worker 9001 + API 8000 转发 + 鉴权）

**Files:**
- Modify: `backend/app/workers/web_renderer.py`
- Create: `backend/app/api/agent_login_sessions.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_agent_login_sessions_api.py`

**Interfaces:**
- Consumes: Task 2 `LoginSessionManager`（单例）、`SessionConflictError/SessionNotFoundError/SessionNotOwnerError`、`PLATFORMS`
- Produces:
  - worker 端点（9001，头 `X-Owner-User-Id` 必填）:
    - `POST /login-sessions` body `{"platform": str, "owner_user_id": str}` → `{"session_id", "status"}`
    - `GET /login-sessions/{id}/frame` → `{"image": str|null}`
    - `GET /login-sessions/{id}/status` → `{"session_id", "status", "detail"}`
    - `POST /login-sessions/{id}/refresh` → `{"refreshed": true}`
    - `DELETE /login-sessions/{id}` → `{"deleted": true}`
    - 错误：409 conflict / 403 not_owned / 404 not_found / 422 unsupported_platform
  - API 端点（8000，前缀 `/api/agent`，鉴权 + CSRF）同结构，内部转发 9001；worker 不可达 → 503

- [ ] **Step 1: Extend the worker app**

Modify `C:\01_agent_loop_pro\backend\app\workers\web_renderer.py` — replace the whole file with:

```python
from __future__ import annotations

import sys
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.agent.login_session import (
    LoginSessionManager,
    SessionConflictError,
    LoginSessionError,
    SessionNotFoundError,
    SessionNotOwnerError,
)
from app.services.agent.web_renderer import render_page

app = FastAPI(title="Web Renderer")
manager = LoginSessionManager()


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


class LoginSessionStartRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=50)
    owner_user_id: str = Field(min_length=1, max_length=64)


def _owner_id(x_owner_user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(x_owner_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_owner") from exc


@app.post("/login-sessions")
async def start_login_session(req: LoginSessionStartRequest) -> dict:
    try:
        record = await manager.start(_owner_id(req.owner_user_id), req.platform)
    except SessionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LoginSessionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"session_id": record.session_id, "status": record.status}


@app.get("/login-sessions/{session_id}/frame")
async def login_session_frame(session_id: str, x_owner_user_id: str = Header(...)) -> dict:
    try:
        image = await manager.frame(session_id, _owner_id(x_owner_user_id))
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotOwnerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"image": image}


@app.get("/login-sessions/{session_id}/status")
async def login_session_status(session_id: str, x_owner_user_id: str = Header(...)) -> dict:
    try:
        return await manager.status(session_id, _owner_id(x_owner_user_id))
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotOwnerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/login-sessions/{session_id}/refresh")
async def login_session_refresh(session_id: str, x_owner_user_id: str = Header(...)) -> dict:
    try:
        await manager.refresh(session_id, _owner_id(x_owner_user_id))
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotOwnerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"refreshed": True}


@app.delete("/login-sessions/{session_id}")
async def login_session_delete(session_id: str, x_owner_user_id: str = Header(...)) -> dict:
    try:
        await manager.close(session_id, _owner_id(x_owner_user_id))
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionNotOwnerError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"deleted": True}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    if sys.platform == "win32":
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(app, host="127.0.0.1", port=9001)
```

- [ ] **Step 2: Create the API router**

Create `C:\01_agent_loop_pro\backend\app\api\agent_login_sessions.py`:

```python
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user
from app.core.errors import ApiError
from app.models.rbac import User
from app.schemas.common import success

router = APIRouter(tags=["Agent Login Sessions"])


class LoginSessionStartRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=50)


def _worker_url() -> str:
    return get_settings().web_renderer_url.rstrip("/")


def _map_status(status_code: int, detail: str) -> ApiError:
    if status_code == 409:
        return ApiError(status_code=409, code="ACTIVE_SESSION", message="已有进行中的登录，请先完成或取消")
    if status_code == 403:
        return ApiError(status_code=403, code="FORBIDDEN", message="无权访问该登录会话")
    if status_code == 404:
        return ApiError(status_code=404, code="SESSION_NOT_FOUND", message="登录会话不存在或已结束")
    return ApiError(status_code=422, code="INVALID_REQUEST", message=detail or "请求参数错误")


@router.post("/login-sessions")
async def start_login_session(
    request: Request,
    data: LoginSessionStartRequest,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{_worker_url()}/login-sessions",
                json={"platform": data.platform, "owner_user_id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())


@router.get("/login-sessions/{session_id}/frame")
async def get_login_frame(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{_worker_url()}/login-sessions/{session_id}/frame",
                headers={"X-Owner-User-Id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())


@router.get("/login-sessions/{session_id}/status")
async def get_login_status(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                f"{_worker_url()}/login-sessions/{session_id}/status",
                headers={"X-Owner-User-Id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())


@router.post("/login-sessions/{session_id}/refresh")
async def refresh_login_session(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{_worker_url()}/login-sessions/{session_id}/refresh",
                headers={"X-Owner-User-Id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())


@router.delete("/login-sessions/{session_id}")
async def delete_login_session(
    request: Request,
    session_id: str,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.delete(
                f"{_worker_url()}/login-sessions/{session_id}",
                headers={"X-Owner-User-Id": str(current_user.id)},
            )
    except httpx.RequestError as exc:
        raise ApiError(status_code=503, code="RENDERER_DOWN", message="登录服务不可用，请稍后重试") from exc
    if r.status_code != 200:
        raise _map_status(r.status_code, r.json().get("detail", ""))
    return success(request, r.json())
```

NOTE: 此文件完全照抄现有 `app/api/agent_cookies.py` 的模式（`success` from `app.schemas.common`、`ApiError` from `app.core.errors`、`require_csrf` from `app.core.csrf`）。如果 `ApiError` 或 `success` 的导入路径不同，以 `agent_cookies.py` 为准。

- [ ] **Step 3: Register the router**

In `C:\01_agent_loop_pro\backend\app\main.py`:

```python
from app.api.agent_login_sessions import router as agent_login_sessions_router
```

and register:

```python
app.include_router(agent_login_sessions_router, prefix="/api/agent")
```

- [ ] **Step 4: Write API tests (mock httpx)**

Create `C:\01_agent_loop_pro\backend\tests\test_agent_login_sessions_api.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.main import app


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture
def client(monkeypatch):
    import httpx

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, **kw):
            return FakeResponse(200, {"session_id": "abc", "status": "waiting_scan"})

        async def get(self, url, **kw):
            return FakeResponse(200, {"image": "abc"})

        async def delete(self, url, **kw):
            return FakeResponse(200, {"deleted": True})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    return TestClient(app)
```

NOTE: This test requires auth — `get_current_user` will reject anonymous requests, so these tests only assert 401/403 unauthenticated behavior, plus route existence. The real auth flow is covered by manual E2E (Task 6). Adjust `FakeResponse` usage if the app's auth middleware short-circuits differently. At minimum assert:

```python
def test_routes_exist(client):
    r = client.get("/api/agent/login-sessions/abc/status")
    assert r.status_code in (401, 403)  # unauthenticated -> rejected
```

- [ ] **Step 5: Run tests**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_login_sessions_api.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: PASS.

Also verify app imports: `& "X:\python\anaconda\envs\01-rbac\python.exe" -c "import sys; sys.path.insert(0,'.'); from app.main import app; print('app OK')"` (workdir `C:\01_agent_loop_pro\backend`) → prints `app OK`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/workers/web_renderer.py backend/app/api/agent_login_sessions.py backend/app/main.py backend/tests/test_agent_login_sessions_api.py
git commit -m "feat: login session endpoints with ownership checks and API proxy"
```

---

### Task 4: fetch_web_content 集成 login_expired

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py`（`_fetch_web_content`，约 712-753 行）
- Modify: `backend/app/services/agent/planner.py`（action_policy 文本，约 161 行）
- Test: `backend/tests/test_agent_tool_files.py`（追加）

**Interfaces:**
- Consumes: Task 1 `assess_login_expired(platform: str, text: str) -> bool`
- Produces: `_build_fetch_result(data: dict, url: str) -> dict`（返回含 `login_expired: bool`）

- [ ] **Step 1: Write the failing test**

Append to `C:\01_agent_loop_pro\backend\tests\test_agent_tool_files.py`:

```python
class TestFetchWebContentLoginExpired:
    def test_marks_douyin_verification_expired(self):
        from app.services.agent.tool_executor import _build_fetch_result

        data = {"platform": "douyin", "text": "验证中间页 请稍候", "title": "验证中间页", "url": "https://www.douyin.com/", "status_code": 200}
        result = _build_fetch_result(data, "https://www.douyin.com/")
        assert result["login_expired"] is True

    def test_normal_content_not_expired(self):
        from app.services.agent.tool_executor import _build_fetch_result

        data = {"platform": "douyin", "text": "热门视频" * 100, "title": "抖音", "url": "https://www.douyin.com/", "status_code": 200}
        result = _build_fetch_result(data, "https://www.douyin.com/")
        assert result["login_expired"] is False

    def test_generic_platform_not_expired(self):
        from app.services.agent.tool_executor import _build_fetch_result

        data = {"platform": "generic", "text": "captcha 验证", "title": "x", "url": "https://example.com", "status_code": 200}
        result = _build_fetch_result(data, "https://example.com")
        assert result["login_expired"] is False

    def test_result_keeps_all_fields(self):
        from app.services.agent.tool_executor import _build_fetch_result

        data = {"platform": "douyin", "text": "x" * 600, "title": "T", "url": "https://www.douyin.com/", "status_code": 200}
        result = _build_fetch_result(data, "https://www.douyin.com/")
        assert result["status_code"] == 200
        assert result["title"] == "T"
        assert result["source"] == "playwright"
        assert result["login_expired"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_tool_files.py::TestFetchWebContentLoginExpired -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: FAIL with `AttributeError: module ... has no attribute '_build_fetch_result'`

- [ ] **Step 3: Refactor _fetch_web_content**

In `C:\01_agent_loop_pro\backend\app\services\agent\tool_executor.py`:

1. Add import near top with other imports:
```python
from app.services.agent.login_session import assess_login_expired
```

2. Add module-level function before the ToolExecutor class:
```python
def _build_fetch_result(data: dict, url: str) -> dict:
    platform = data.get("platform", "generic")
    text = data.get("text", "")
    return {
        "status_code": data.get("status_code", 0),
        "url": data.get("url", url),
        "title": data.get("title", ""),
        "text": text,
        "platform": platform,
        "source": "playwright",
        "login_expired": assess_login_expired(platform, text),
    }
```

3. In `_fetch_web_content` (约 746-753 行), replace the return dict:
```python
        if data.get("error"):
            raise RetryableToolError(f"web_render_error: {data['error'][:200]}")
        return _build_fetch_result(data, url)
```

- [ ] **Step 4: Update planner prompt**

In `C:\01_agent_loop_pro\backend\app\services\agent\planner.py`, find the `fetch_web_content` mention in `action_policy` (约 161 行). Add a sentence:

```text
fetch_web_content（用浏览器渲染 JS 页面，适合抖音/小红书等动态网页，需 url；如需登录数据可设置 requires_login=true。若返回 login_expired=true，说明平台登录态已过期，告知用户"登录态已过期，请打开平台登录中心重新扫码"，不要反复重试）
```

- [ ] **Step 5: Run tests**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_agent_tool_files.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: all pass (36 existing + 4 new)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent/tool_executor.py backend/app/services/agent/planner.py backend/tests/test_agent_tool_files.py
git commit -m "feat: detect login expired in fetch_web_content"
```

---

### Task 5: 前端平台登录中心

**Files:**
- Create: `frontend/src/components/feishu/platform-login-modal.tsx`
- Modify: `frontend/src/components/layout/conversation-top-bar.tsx`
- Delete: `frontend/src/components/feishu/web-cookie-modal.tsx`

**Interfaces:**
- Consumes: Task 3 API `POST/GET/DELETE /api/agent/login-sessions...`（经 `@/lib/api`，csrf 用法同现有组件）、`GET /api/agent/cookies`
- Produces: `PlatformLoginModal({ open: boolean; onClose: () => void })`（平台卡片列表 + 扫码弹窗，截图轮询 800ms）

- [ ] **Step 1: Create the modal component**

Create `C:\01_agent_loop_pro\frontend\src\components\feishu\platform-login-modal.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { Modal, Button, List, Tag, Space, Spin, message } from "antd";
import { QrcodeOutlined, ReloadOutlined, CloseOutlined } from "@ant-design/icons";
import { api } from "@/lib/api";

interface CookieItem {
  domain: string;
  cookie_string: string;
}

const PLATFORMS = [
  { key: "douyin", name: "抖音", domain: "www.douyin.com" },
  { key: "xiaohongshu", name: "小红书", domain: "www.xiaohongshu.com" },
];

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
        setScanError(st.detail || "登录失败，请重试");
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

  useEffect(() => {
    return () => stopPolling();
  }, []);

  return (
    <Modal title="平台登录" open={open} onCancel={onClose} footer={null} width={560}>
      {!scanning ? (
        <List
          loading={loading}
          dataSource={PLATFORMS}
          locale={{ emptyText: "暂无平台" }}
          renderItem={(p) => (
            <List.Item
              actions={[
                <Button
                  key="scan"
                  type="primary"
                  icon={<QrcodeOutlined />}
                  onClick={() => startScan(p.key)}
                >
                  扫码登录
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={p.name}
                description={
                  loggedDomains.has(p.domain) ? (
                    <Tag color="success">已登录</Tag>
                  ) : (
                    <Tag>未登录</Tag>
                  )
                }
              />
            </List.Item>
          )}
        />
      ) : (
        <div style={{ textAlign: "center" }}>
          <p>
            请用手机 {PLATFORMS.find((p) => p.key === scanPlatform)?.name} App
            扫码登录
          </p>
          {image ? (
            <img
              src={`data:image/jpeg;base64,${image}`}
              alt="登录二维码"
              style={{ maxWidth: 300, border: "1px solid #eee", borderRadius: 8 }}
            />
          ) : (
            <Spin />
          )}
          {scanError && <p style={{ color: "#ff4d4f" }}>{scanError}</p>}
          <Space style={{ marginTop: 12 }}>
            <Button icon={<ReloadOutlined />} onClick={handleRefresh} disabled={!sessionId}>
              二维码失效？刷新
            </Button>
            <Button icon={<CloseOutlined />} onClick={handleCloseScan}>
              取消登录
            </Button>
          </Space>
        </div>
      )}
    </Modal>
  );
}
```

- [ ] **Step 2: Update the top bar**

Modify `C:\01_agent_loop_pro\frontend\src\components\layout\conversation-top-bar.tsx`:

- Replace `import WebCookieModal from "@/components/feishu/web-cookie-modal";` with `import PlatformLoginModal from "@/components/feishu/platform-login-modal";`
- Replace `import { UserOutlined, LogoutOutlined, ChromeOutlined } from "@ant-design/icons";` with `import { UserOutlined, LogoutOutlined, QrcodeOutlined } from "@ant-design/icons";`
- Replace the button:
```tsx
      <Button icon={<QrcodeOutlined />} onClick={() => setCookieModalOpen(true)}>平台登录</Button>
```
- Replace `<WebCookieModal open={cookieModalOpen} onClose={() => setCookieModalOpen(false)} />` with `<PlatformLoginModal open={cookieModalOpen} onClose={() => setCookieModalOpen(false)} />`

- [ ] **Step 3: Delete the old modal**

```powershell
Remove-Item "C:\01_agent_loop_pro\frontend\src\components\feishu\web-cookie-modal.tsx"
```

- [ ] **Step 4: TypeScript check**

Run: `npx tsc --noEmit` (workdir `C:\01_agent_loop_pro\frontend`)
Expected: no NEW errors from your files. (Pre-existing errors in `*.test.*` files are OK.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feishu/platform-login-modal.tsx frontend/src/components/layout/conversation-top-bar.tsx
git add -A frontend/src/components/feishu/web-cookie-modal.tsx
git commit -m "feat: platform login center with scan QR modal"
```

---

### Task 6: E2E 验证与收尾

**Files:**
- No new files (verification only)

- [ ] **Step 1: Restart the web_renderer process**

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'web_renderer' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
Start-Process -FilePath "X:\python\anaconda\envs\01-rbac\python.exe" -ArgumentList "-m","app.workers.web_renderer" -WorkingDirectory "C:\01_agent_loop_pro\backend" -WindowStyle Hidden
Start-Sleep -Seconds 5
```
Expected: process running (check with the Get-CimInstance query again).

- [ ] **Step 2: Smoke-test worker endpoints**

```powershell
$body = '{"platform":"douyin","owner_user_id":"00000000-0000-0000-0000-000000000001"}'
$r = Invoke-RestMethod -Uri "http://127.0.0.1:9001/login-sessions" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 20
$r.session_id
$sid = $r.session_id
$st = Invoke-RestMethod -Uri "http://127.0.0.1:9001/login-sessions/$sid/status" -Headers @{"X-Owner-User-Id"="00000000-0000-0000-0000-000000000001"} -TimeoutSec 20
$st.status
Invoke-RestMethod -Uri "http://127.0.0.1:9001/login-sessions/$sid" -Method DELETE -Headers @{"X-Owner-User-Id"="00000000-0000-0000-0000-000000000001"} -TimeoutSec 20
```
Expected: `session_id` printed; `status` is `waiting_scan` (或 `starting` → 等 3 秒再查)；DELETE 返回 `deleted=True`。

- [ ] **Step 3: Run full backend test suite**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: 4 known failures only (test_file_reader.py pypdf 缺失, 既有), everything else passes.

- [ ] **Step 4: Manual scan verification (user)**

1. 前端刷新页面，打开顶栏"平台登录"
2. 抖音卡片 → 扫码登录 → 用手机抖音 App 扫码 → 等待几秒 → 自动提示"登录成功"，卡片变"已登录"
3. 关闭 Modal，让 agent"看看抖音首页有什么热门内容"
4. 预期：agent 返回真实视频流内容（不再只有标题/验证页）

- [ ] **Step 5: Commit any fixes made during verification**

```bash
git add -A
git commit -m "fix: adjustments from platform login E2E verification"
```
(仅当有修复时执行；无改动则跳过)
