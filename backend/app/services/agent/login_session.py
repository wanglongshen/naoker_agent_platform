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
    "douyin": "UIFID",
    "xiaohongshu": "id_token",
}

SESSION_TTL_SECONDS: int = 900
LOGIN_CHECK_INTERVAL: float = 1.5
CONTENT_THRESHOLD: int = 500

QR_WAIT_TIMEOUT: float = 20.0
QR_POLL_INTERVAL: float = 1.0

OPEN_RETRY_ATTEMPTS: int = 3
OPEN_RETRY_BACKOFF: float = 2.0

# Text markers that only appear when the platform login dialog is open
DIALOG_MARKERS: dict[str, tuple[str, ...]] = {
    "douyin": ("登录后免费畅享高清视频", "扫码登录", "验证码登录"),
    "xiaohongshu": ("新用户可直接登录", "登录后推荐更懂你的笔记"),
}

# Login-entry text matched to open the login dialog when it is not open
LOGIN_ENTRY_TEXTS: dict[str, tuple[str, ...]] = {
    "douyin": ("登录",),
    "xiaohongshu": ("新用户可直接登录",),
}

_VERIFICATION_MARKERS: tuple[str, ...] = ("captcha", "verify_data", "验证中间页", "安全验证")

_CONFIRM_MARKERS: tuple[str, ...] = ("保存登录状态", "保持登录", "记住登录", "保存登录")

_VERIFY_UI_MARKERS: tuple[str, ...] = ("短信验证码", "请输入验证码", "获取验证码", "验证码已发送")

_SMS_SEND_ERROR_MARKERS: tuple[str, ...] = (
    "错误次数过多",
    "操作频繁",
    "请稍后重试",
    "已失效",
    "发送过于频繁",
)

_VERIFY_ERROR_MARKERS: tuple[str, ...] = (
    "错误次数过多",
    "验证码错误",
    "验证码已过期",
    "验证码过期",
    "操作频繁",
    "请稍后重试",
    "已失效",
    "不正确",
)

# Detects the douyin SMS verify-code form (verified real DOM: input[name="normal-input"])
VERIFY_PHONE_INPUT_JS = """() => {
    const el = document.querySelector('input[name="normal-input"]');
    if (el) {
        const r = el.getBoundingClientRect();
        return { exists: true, x: r.x, y: r.y, w: r.width, h: r.height };
    }
    return { exists: false };
}"""

# Fills and submits the SMS verify-code form (arg.phase == 'phone' | 'code')
VERIFY_SUBMIT_JS = """(arg) => {
    const find = (label) => {
        const els = Array.from(document.querySelectorAll('button, div, span, a'));
        const visible = els.filter(el => {
            const t = (el.textContent || '').trim();
            const r = el.getBoundingClientRect();
            return t === label && r.width > 0 && r.height > 0;
        });
        return visible[visible.length - 1] || null;
    };
    const fillAndSubmit = (inputName, value, submitLabel) => {
        const input = document.querySelector(`input[name="${inputName}"]`);
        if (!input) return { ok: false, reason: 'input_missing', name: inputName };
        input.focus();
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        if (submitLabel) {
            const btn = find(submitLabel);
            if (btn) { btn.click(); return { ok: true, clicked: submitLabel }; }
            return { ok: false, reason: 'button_missing', label: submitLabel };
        }
        return { ok: true };
    };
    if arg.phase === 'code') return fillAndSubmit('button-input', arg.code, '登录');
}"""

VERIFY_SEND_JS = """(arg) => {
    const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    const clickable = (el) => {
        // 文本元素往往无处理器；向上找可点击祖先（button/role=button/类含 btn）
        for (let i = 0; i < 4 && el; i++) {
            const tag = el.tagName;
            const role = el.getAttribute && el.getAttribute('role');
            const cls = (el.className || '').toString().toLowerCase();
            if (tag === 'BUTTON' || role === 'button' || /btn|button/.test(cls)) return el;
            el = el.parentElement;
        }
        return null;
    };
    const byText = (label) => {
        const els = Array.from(document.querySelectorAll('button, div, span, a'));
        return els.filter(el => {
            const t = (el.textContent || '').trim();
            return t === label && visible(el);
        });
    };
    const disabledState = (btn) => {
        const cls = (btn.className || '').toString().toLowerCase();
        const aria = btn.getAttribute && btn.getAttribute('aria-disabled');
        return btn.disabled === true || aria === 'true' || /disabled|loading/.test(cls);
    };
    const matches = byText('获取验证码');
    if (!matches.length) return { ok: false, reason: 'button_missing' };
    for (const m of matches) {
        const target = clickable(m) || m;
        if (disabledState(target)) continue;
        target.click();
        return {
            ok: true,
            clicked: true,
            target: { tag: target.tagName, cls: (target.className || '').toString().slice(0, 60) },
        };
    }
    return { ok: false, reason: 'button_disabled' };
}"""

VERIFY_SENT_JS = """() => {
    const els = Array.from(document.querySelectorAll('button, div, span, a'));
    const texts = [];
    els.forEach(el => {
        const t = (el.textContent || '').trim();
        const r = el.getBoundingClientRect();
        if (t && t.length <= 20 && r.width > 0 && r.height > 0) texts.push(t);
    });
    const hit = texts.find(t => /重新获取|已发送|重新发送|秒后重试|已发送至/.test(t));
    return hit ? hit : null;
}"""

_VERIFY_UI_DUMP_JS = """() => {
    const inputs = [];
    document.querySelectorAll('input').forEach((el, i) => {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            inputs.push({
                i,
                type: el.type || '',
                placeholder: el.placeholder || '',
                name: el.name || '',
                value: (el.value || '').slice(0, 20),
                cls: (el.className || '').toString().slice(0, 50),
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height),
            });
        }
    });
    const buttons = [];
    document.querySelectorAll('button, div, span, a').forEach((el, i) => {
        const t = (el.textContent || '').trim();
        const r = el.getBoundingClientRect();
        if (t && t.length <= 12 && r.width > 0 && r.height > 0 &&
            /验证|登录|提交|确定|同意|获取/.test(t)) {
            buttons.push({
                tag: el.tagName, text: t,
                disabled: el.disabled === true,
                cls: (el.className || '').toString().slice(0, 40),
                x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height),
            });
        }
    });
    return { inputs: inputs.slice(0, 12), buttons: buttons.slice(0, 15) };
}"""

_SMS_SENT_MARKERS: tuple[str, ...] = (
    "已发送",
    "重新获取",
    "重新发送",
    "秒后重试",
)


def _has_verify_ui(text: str) -> bool:
    return any(m in text for m in _VERIFY_UI_MARKERS)


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
    status: str = "starting"  # starting|waiting_scan|verify_required|verify_code_required|logged_in|timeout|error|closed
    detail: str = ""
    verify_state: str | None = None  # phone|code while the SMS form is being filled
    context: object | None = None
    browser: object | None = None
    page: object | None = None
    user_data_dir: Path | None = None
    started_at: float = field(default_factory=time.monotonic)
    qr_box: dict | None = None


def _page_is_closed(page) -> bool:
    try:
        return page.is_closed()
    except Exception:
        return True


async def _default_browser_factory():
    from patchright.async_api import async_playwright
    from app.core.config import get_browser_channel, get_settings

    p = await async_playwright().start()
    _settings = get_settings()
    return await p.chromium.launch(
        headless=False,  # 登录会话需真人操作（可见窗口）；/search /detail 走 render_page 不受影响
        channel=get_browser_channel(_settings),
    )


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
            for rec in list(self._sessions.values()):
                if rec.owner_user_id == owner_user_id and rec.status in (
                    "starting",
                    "waiting_scan",
                    "verify_required",
                    "verify_code_required",
                ):
                    # 用户发起新的登录意图：作废旧活动会话（watch 循环检测到
                    # 状态变化后自动退出并释放浏览器），不再抛 409 冲突
                    rec.status = "error"
                    rec.detail = "superseded"
                    logger.info(
                        "login_session_superseded session_id=%s",
                        rec.session_id,
                    )
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
            kwargs: dict = {"type": "jpeg", "quality": 90}
            if record.qr_box:
                box = record.qr_box
                kwargs["clip"] = {
                    "x": max(0, box["x"] - 20),
                    "y": max(0, box["y"] - 20),
                    "width": box["width"] + 40,
                    "height": box["height"] + 40,
                }
                kwargs["scale"] = "css"
                raw = await record.page.screenshot(**kwargs)
                from PIL import Image
                import io as _io

                im = Image.open(_io.BytesIO(raw))
                im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
                buf = _io.BytesIO()
                im.save(buf, "JPEG", quality=90)
                raw = buf.getvalue()
            else:
                raw = await record.page.screenshot(**kwargs)
            return base64.b64encode(raw).decode("ascii")
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
        record.status = "closed"
        async with self._lock:
            self._sessions.pop(session_id, None)
        await self._release_browser(record)
        return True

    async def _open_and_watch(self, record: LoginSessionRecord) -> None:
        for attempt in range(OPEN_RETRY_ATTEMPTS):
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

                async def _auto_accept_dialog(dialog) -> None:
                    logger.info(
                        "login_session_dialog type=%s message=%s",
                        dialog.type,
                        dialog.message[:120],
                    )
                    try:
                        await dialog.accept()
                    except Exception:
                        pass

                page.on("dialog", _auto_accept_dialog)
                user_dir = self._data_root / str(record.owner_user_id) / record.session_id
                user_dir.mkdir(parents=True, exist_ok=True)
                record.user_data_dir = user_dir
                await page.goto(LOGIN_URLS[record.platform], wait_until="domcontentloaded", timeout=30000)
                await self._wait_for_qr(record)
                record.status = "waiting_scan"
                await self._watch_login(record)
                return
            except LoginSessionError as exc:
                if str(exc) != "platform_blocked" or attempt == OPEN_RETRY_ATTEMPTS - 1:
                    record.status = "error"
                    record.detail = str(exc)
                    logger.warning("login_session_qr_failed: %s", exc)
                    return
                logger.warning("login_session_retry_platform_blocked (attempt %d)", attempt + 1)
                await asyncio.sleep(OPEN_RETRY_BACKOFF)
            except Exception as exc:
                record.status = "error"
                record.detail = "browser_failed"
                logger.error("login_session_open_failed: %s", exc)
                return
            finally:
                await self._release_browser(record)
        record.status = "error"
        record.detail = "platform_blocked"
        logger.warning("login_session_qr_failed: platform_blocked (all %d attempts)", OPEN_RETRY_ATTEMPTS)

    async def _ensure_login_dialog(self, record: LoginSessionRecord) -> bool:
        """Click the platform login entry if the login dialog is not open yet."""
        if await self._has_login_dialog(record):
            return True
        entries = LOGIN_ENTRY_TEXTS.get(record.platform, ())
        if not entries:
            return False
        try:
            await record.page.evaluate(
                """(arg) => {
                    for (const el of Array.from(document.querySelectorAll('button, div, span, a'))) {
                        const t = (el.textContent || '').trim();
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && arg.entries.some(e => e === t || t.includes(e))) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""",
                {"action": "click_login", "entries": list(entries)},
            )
            await record.page.wait_for_timeout(2000)
            return True
        except Exception:
            return False

    async def _has_login_dialog(self, record: LoginSessionRecord) -> bool:
        """True when the login dialog is open (marker text visible in the page)."""
        try:
            markers = list(DIALOG_MARKERS.get(record.platform, ()))
            return bool(
                await record.page.evaluate(
                    """(arg) => arg.markers.some(m => (document.body.innerText || '').includes(m))""",
                    {"action": "has_marker", "markers": markers},
                )
            )
        except Exception:
            from app.services.agent.web_renderer import _extract_platform_content

            try:
                html = await record.page.content()
                text = _extract_platform_content(html, LOGIN_URLS[record.platform])["text"]
            except Exception:
                text = ""
            return any(m in text for m in DIALOG_MARKERS.get(record.platform, ()))

    async def _wait_for_qr(
        self, record: LoginSessionRecord, timeout: float = QR_WAIT_TIMEOUT
    ) -> None:
        """Wait until the login dialog shows a QR code element; raise graded errors."""
        from app.services.agent.web_renderer import _extract_platform_content

        # initial verification-page guard
        html = await record.page.content()
        text = _extract_platform_content(html, LOGIN_URLS[record.platform])["text"]
        if assess_login_expired(record.platform, text):
            raise LoginSessionError("platform_blocked")

        await self._ensure_login_dialog(record)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self._has_login_dialog(record):
                qr = await record.page.evaluate(
                    """() => {
                        for (const im of Array.from(document.querySelectorAll('img'))) {
                            const r = im.getBoundingClientRect();
                            if ((im.src || '').startsWith('data:') && r.width >= 100 && r.width <= 400) {
                                return { kind: 'img', x: Math.round(r.x), y: Math.round(r.y),
                                         w: Math.round(r.width), h: Math.round(r.height) };
                            }
                        }
                        for (const c of Array.from(document.querySelectorAll('canvas'))) {
                            const r = c.getBoundingClientRect();
                            if (r.width >= 100 && r.width <= 500 && r.height >= 100 && r.height <= 500) {
                                return { kind: 'canvas', x: Math.round(r.x), y: Math.round(r.y),
                                         w: Math.round(r.width), h: Math.round(r.height) };
                            }
                        }
                        for (const im of Array.from(document.querySelectorAll('img[src*="qrcode"]'))) {
                            const r = im.getBoundingClientRect();
                            if (r.width >= 100 && r.width <= 400) {
                                return { kind: 'img', x: Math.round(r.x), y: Math.round(r.y),
                                         w: Math.round(r.width), h: Math.round(r.height) };
                            }
                        }
                        return null;
                    }""",
                    {"action": "find_qr"},
                )
                if qr is not None:
                    record.qr_box = {
                        "x": qr["x"], "y": qr["y"],
                        "width": qr["w"], "height": qr["h"],
                    }
                    return
            else:
                await self._ensure_login_dialog(record)
            await asyncio.sleep(QR_POLL_INTERVAL)
        raise LoginSessionError("qr_timeout")

    async def _watch_login(
        self,
        record: LoginSessionRecord,
        ttl_seconds: float = SESSION_TTL_SECONDS,
        check_interval: float = LOGIN_CHECK_INTERVAL,
    ) -> None:
        while record.status in ("waiting_scan", "verify_required", "verify_code_required"):
            if time.monotonic() - record.started_at > ttl_seconds:
                record.status = "timeout"
                return
            try:
                verify_ui = await record.page.evaluate(VERIFY_PHONE_INPUT_JS)
            except Exception:
                verify_ui = {"exists": False}
                if _page_is_closed(record.page):
                    record.status = "error"
                    record.detail = "window_closed"
                    return
            if verify_ui.get("exists"):
                if record.status != "verify_required" and record.status != "verify_code_required":
                    record.status = "verify_required"
                    record.verify_state = "phone"
                    logger.warning("login_session_verify_required")
                await asyncio.sleep(check_interval)
                continue
            try:
                cookies = await record.context.cookies()
                names = [c["name"] for c in cookies]
                key = tuple(sorted(n for n in names if n))
                if key != getattr(self, "_last_cookie_log", None):
                    self._last_cookie_log = key
                    logger.warning(
                        "login_session_cookies n=%d names=%s",
                        len(key),
                        ",".join(key)[:400],
                    )
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
                if _page_is_closed(record.page):
                    record.status = "error"
                    record.detail = "window_closed"
                    return
            if record.context is not None:
                try:
                    t = await record.page.evaluate(
                        "() => (document.body.innerText || '').slice(0, 2000)"
                    )
                    if any(m in t for m in _CONFIRM_MARKERS):
                        logger.warning(
                            "login_session_confirm_dialog_seen text=%s", t[:300]
                        )
                    if _has_verify_ui(t):
                        info = await record.page.evaluate(
                            _VERIFY_UI_DUMP_JS
                        )
                        logger.warning(
                            "login_session_verify_ui_dump %s", info
                        )
                    else:
                        has_input = await record.page.evaluate(
                            """() => {
                                for (const el of document.querySelectorAll('input')) {
                                    const r = el.getBoundingClientRect();
                                    if (r.width > 0 && r.height > 0) return true;
                                }
                                return false;
                            }"""
                        )
                        if has_input:
                            info = await record.page.evaluate(_VERIFY_UI_DUMP_JS)
                            logger.warning("login_session_input_ui_dump %s", info)
                except Exception:
                    pass
            await asyncio.sleep(check_interval)

    async def submit_phone(self, session_id: str, owner_user_id: uuid.UUID, phone: str) -> dict:
        record = await self._get_owned(session_id, owner_user_id)
        if record.status not in ("verify_required", "verify_code_required"):
            raise LoginSessionError("not_verify_state")
        try:
            # Playwright 原生 fill：对 React 受控输入触发完整事件链，比 JS setter 注入可靠
            await record.page.fill('input[name="normal-input"]', phone)
            await record.page.wait_for_timeout(600)
            try:
                ui_before = await record.page.evaluate(
                    _VERIFY_UI_DUMP_JS, {"action": "phone_dump_before"}
                )
                logger.warning("login_session_phone_dump_before %s", str(ui_before)[:500])
            except Exception:
                pass
            # 等待"获取验证码"按钮从 disabled 变为可用（React 状态更新需要时间）
            for _ in range(4):
                result = await record.page.evaluate(
                    VERIFY_SEND_JS, {"action": "click_send"}
                )
                if result.get("ok"):
                    logger.warning(
                        "login_session_click_send target=%s",
                        str(result.get("target"))[:200],
                    )
                    break
                logger.warning(
                    "login_session_click_send_failed reason=%s target=%s",
                    result.get("reason"),
                    str(result.get("target"))[:200],
                )
                if result.get("reason") != "button_disabled":
                    break
                await record.page.wait_for_timeout(800)
        except Exception as exc:
            raise LoginSessionError("verify_form_gone") from exc
        if not result.get("ok"):
            raise LoginSessionError(result.get("reason", "verify_submit_failed"))
        # 点击后轮询发送结果：按钮文本变"重新获取/已发送" = 发送成功（最多 6s）
        sent_marker = None
        for _ in range(4):
            await record.page.wait_for_timeout(1500)
            try:
                sent_marker = await record.page.evaluate(
                    VERIFY_SENT_JS, {"action": "verify_sent_marker"}
                )
            except Exception:
                sent_marker = None
            if sent_marker:
                break
        logger.warning(
            "login_session_verify_send_marker %s",
            sent_marker or "none",
        )
        # 弹窗关闭检测：点击后若验证码表单消失（抖音风控静默关闭），明确报错
        try:
            form_still = await record.page.evaluate(VERIFY_PHONE_INPUT_JS, None)
        except Exception:
            form_still = {"exists": False}
        if not form_still.get("exists"):
            raise LoginSessionError(
                "verify_dialog_closed: 登录弹窗已关闭（可能被平台风控拦截），请重试"
            )
        try:
            ui_after = await record.page.evaluate(
                _VERIFY_UI_DUMP_JS, {"action": "phone_dump_after"}
            )
            logger.warning(
                "login_session_phone_dump_after_inputs %s",
                str(ui_after.get("inputs"))[:300],
            )
            logger.warning(
                "login_session_phone_dump_after_buttons %s",
                str(ui_after.get("buttons"))[:500],
            )
        except Exception:
            pass
        verify_error = await self._read_verify_error(record, _SMS_SEND_ERROR_MARKERS)
        if verify_error:
            raise LoginSessionError(f"verify_rejected:{verify_error}")
        record.verify_state = "code"
        record.status = "verify_code_required"
        logger.warning("login_session_verify_phone_submitted")
        return {"status": "verify_code_required"}

    async def submit_code(self, session_id: str, owner_user_id: uuid.UUID, code: str) -> dict:
        record = await self._get_owned(session_id, owner_user_id)
        if record.status != "verify_code_required":
            raise LoginSessionError("not_verify_state")
        try:
            result = await record.page.evaluate(
                VERIFY_SUBMIT_JS, {"phase": "code", "code": code}
            )
        except Exception:
            raise LoginSessionError("verify_form_gone")
        if not result.get("ok"):
            raise LoginSessionError(result.get("reason", "verify_submit_failed"))
        await record.page.wait_for_timeout(2500)
        verify_error = await self._read_verify_error(record)
        if verify_error:
            raise LoginSessionError(f"verify_rejected:{verify_error}")
        record.verify_state = None
        record.status = "waiting_scan"
        logger.warning("login_session_verify_code_submitted")
        return {"status": "waiting_scan"}

    async def _read_verify_error(
        self,
        record: LoginSessionRecord,
        markers: tuple[str, ...] = _VERIFY_ERROR_MARKERS,
    ) -> str | None:
        try:
            text = await record.page.evaluate(
                "() => (document.body.innerText || '')",
                {"action": "read_verify_error"},
            )
        except Exception:
            return None
        if not isinstance(text, str):
            return None
        for marker in markers:
            idx = text.find(marker)
            if idx >= 0:
                line = text[max(0, idx - 30) : idx + 80].strip()
                return line[:120] or marker
        return None

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
