import asyncio
import io as _io
import time
import uuid
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("patchright", reason="patchright 未安装（登录可见窗口测试）")

from app.services.agent.login_session import (
    LoginSessionError,
    LoginSessionManager,
    SessionConflictError,
    SessionNotOwnerError,
    cookies_to_string,
)

# Real JPEG bytes: frame() decodes screenshots with PIL when record.qr_box is set
_FAKE_JPEG_BUF = _io.BytesIO()
Image.new("RGB", (32, 32), "white").save(_FAKE_JPEG_BUF, "JPEG", quality=90)
_FAKE_JPEG = _FAKE_JPEG_BUF.getvalue()


class FakePage:
    def __init__(
        self,
        content: str = "首页 热门视频 用户",
        qr_selectors: list[str] | None = None,
        has_fallback_img: bool = True,
        dialog_marker: bool = True,
        qr_data_img: bool = False,
        qr_box: dict | None = None,
        has_canvas: bool = False,
        blocked_page: bool = False,
        verify_form: bool = False,
        verify_error_text: str | None = None,
    ):
        self._content = content
        self._qr_selectors = qr_selectors or []
        self._has_fallback_img = has_fallback_img
        self._dialog_marker = dialog_marker
        self._qr_data_img = qr_data_img
        self._qr_box = qr_box or {"x": 180, "y": 515, "width": 179, "height": 179}
        self._has_canvas = has_canvas
        self._blocked_page = blocked_page
        self._verify_form = verify_form
        self._verify_error_text = verify_error_text
        self._send_disabled = False
        self.url = "https://www.douyin.com/"
        self.clicked_login = False
        self.send_clicked = False
        self.filled = None

    async def fill(self, selector, value):
        self.filled = (selector, value)
        return None

    async def goto(self, url, wait_until="domcontentloaded", timeout=30000):
        self.url = url
        return None

    async def wait_for_timeout(self, ms):
        await asyncio.sleep(0)

    async def content(self):
        if self._blocked_page:
            return "<html><body>安全验证 问题反馈</body></html>"
        return f"<html><body>{self._content}</body></html>"

    async def evaluate(self, js, arg=None):
        # contract with the real implementation: one evaluate call per action,
        # each sending an arg dict with an "action" key
        if arg is not None and isinstance(arg, dict) and arg.get("action") == "click_login":
            self.clicked_login = True
            # the login-entry click only opens the dialog when the page really
            # renders a QR element (data-url img / canvas); a stray fallback
            # img (e.g. a video cover) must NOT make the dialog "appear"
            if self._qr_data_img or self._has_canvas:
                self._dialog_marker = True
        if arg is not None and isinstance(arg, dict) and arg.get("action") == "find_qr":
            if self._qr_data_img:
                return {"kind": "img", "x": self._qr_box["x"], "y": self._qr_box["y"],
                        "w": self._qr_box["width"], "h": self._qr_box["height"]}
            if self._has_canvas:
                return {"kind": "canvas", "x": self._qr_box["x"], "y": self._qr_box["y"],
                        "w": self._qr_box["width"], "h": self._qr_box["height"]}
            if self._has_fallback_img:
                return {"kind": "img", "x": self._qr_box["x"], "y": self._qr_box["y"],
                        "w": self._qr_box["width"], "h": self._qr_box["height"]}
            return None
        if arg is not None and isinstance(arg, dict) and arg.get("action") == "has_marker":
            return self._dialog_marker
        if arg is not None and isinstance(arg, dict) and arg.get("action") == "click_send":
            if self._send_disabled:
                return {"ok": False, "reason": "button_disabled"}
            self.send_clicked = True
            return {"ok": True, "clicked": True}
        # SMS verify-code channel: the real code calls evaluate() with no arg
        # (VERIFY_PHONE_INPUT_JS) or a plain dict without an "action" key
        # (VERIFY_SUBMIT_JS {"phase": ...}). All action-based calls are handled
        # above, so these branches never collide with the action contract.
        if arg is not None and isinstance(arg, dict) and arg.get("action") is None:
            if arg.get("phase") == "phone":
                self.submitted_phone = arg.get("phone")
                self.submitted_action = "phone"
                # form stays up after phone submit; only code submit clears it
                return {"ok": True}
            if arg.get("phase") == "code":
                self.submitted_code = arg.get("code")
                self.submitted_action = "code"
                # form disappears on successful login so the watch loop can
                # fall through to cookie detection
                self._verify_form = False
                return {"ok": True}
            return None
        if arg is not None and isinstance(arg, dict) and arg.get("action") == "read_verify_error":
            return self._verify_error_text or ""
        if arg is None:
            if self._verify_form:
                return {"exists": True}
            return {"exists": False}
        return None

    async def query_selector(self, selector):
        if selector in self._qr_selectors:
            return object()
        if selector == "img" and self._has_fallback_img:
            return object()
        return None

    async def screenshot(self, **kwargs):
        return _FAKE_JPEG

    def on(self, event, handler):
        pass

    def is_closed(self):
        return getattr(self, "closed", False)

    async def close(self):
        pass


class FakeContext:
    def __init__(
        self,
        cookie_names=None,
        content: str = "首页 热门视频 用户",
        qr_selectors: list[str] | None = None,
        has_fallback_img: bool = True,
        dialog_marker: bool = True,
        qr_data_img: bool = False,
        qr_box: dict | None = None,
        has_canvas: bool = False,
        blocked_page: bool = False,
        verify_form: bool = False,
        verify_error_text: str | None = None,
    ):
        self._cookie_names = cookie_names or []
        self._page = FakePage(
            content, qr_selectors, has_fallback_img,
            dialog_marker, qr_data_img, qr_box, has_canvas,
            blocked_page, verify_form, verify_error_text,
        )

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
        dialog_marker: bool = True,
        qr_data_img: bool = False,
        qr_box: dict | None = None,
        has_canvas: bool = False,
        blocked: dict | None = None,
        verify_form: bool = False,
        verify_error_text: str | None = None,
    ):
        self._cookie_names = cookie_names
        self._content = content
        self._qr_selectors = qr_selectors
        self._has_fallback_img = has_fallback_img
        self._dialog_marker = dialog_marker
        self._qr_data_img = qr_data_img
        self._qr_box = qr_box
        self._has_canvas = has_canvas
        self._blocked = blocked
        self._verify_form = verify_form
        self._verify_error_text = verify_error_text

    async def new_context(self, **kwargs):
        blocked_page = False
        if self._blocked is not None and self._blocked["remaining"] > 0:
            self._blocked["remaining"] -= 1
            blocked_page = True
        return FakeContext(
            self._cookie_names, self._content, self._qr_selectors,
            self._has_fallback_img, self._dialog_marker, self._qr_data_img,
            self._qr_box, self._has_canvas, blocked_page, self._verify_form,
            self._verify_error_text,
        )

    async def close(self):
        pass


def _manager(
    tmp_path,
    cookie_names=None,
    content="首页 热门视频 用户",
    qr_selectors: list[str] | None = None,
    has_fallback_img: bool = True,
    dialog_marker: bool = True,
    qr_data_img: bool = False,
    qr_box: dict | None = None,
    has_canvas: bool = False,
    blocked_rounds: int = 0,
    verify_form: bool = False,
    verify_error_text: str | None = None,
):
    blocked = {"remaining": blocked_rounds}

    async def factory():
        return FakeBrowser(
            cookie_names, content, qr_selectors, has_fallback_img,
            dialog_marker, qr_data_img, qr_box, has_canvas, blocked,
            verify_form, verify_error_text,
        )

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
    m = _manager(tmp_path, cookie_names=["UIFID", "sessionid"])
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    st = await _wait_for(m, record.session_id, uid, {"logged_in"}, timeout=5)
    assert st["status"] == "logged_in"
    assert saved["owner"] == str(uid)
    assert saved["domain"] == "www.douyin.com"
    assert "UIFID=v_UIFID" in saved["cookie_string"]
    await m.close(record.session_id, uid)


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
async def test_per_user_supersedes_previous(tmp_path):
    m = _manager(tmp_path)
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
    # 再次 start：不再抛 conflict，旧会话被作废（superseded），新会话可用
    record2 = await m.start(uid, "xiaohongshu")
    st2 = await m.status(record2.session_id, uid)
    assert st2["status"] == "waiting_scan" or st2["status"] == "starting"
    st_old = await m.status(record.session_id, uid)
    assert st_old["status"] == "error"
    assert st_old["detail"] == "superseded"
    await m.close(record2.session_id, uid)


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


class TestLoginDetection:
    @pytest.mark.anyio
    async def test_xiaohongshu_anonymous_web_session_not_logged_in(
        self, tmp_path, monkeypatch
    ):
        async def fake_save(owner_user_id, domain, cookie_string):
            raise AssertionError("must not export cookie for anonymous session")

        monkeypatch.setattr(
            "app.services.agent.login_session.save_user_cookie", fake_save
        )
        m = _manager(tmp_path, cookie_names=["web_session"])
        uid = uuid.uuid4()
        record = await m.start(uid, "xiaohongshu")
        st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
        assert st["status"] == "waiting_scan"
        await m._watch_login(record, ttl_seconds=0.2, check_interval=0.01)
        assert record.status == "timeout"
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_xiaohongshu_id_token_logs_in(self, tmp_path, monkeypatch):
        saved = {}

        async def fake_save(owner_user_id, domain, cookie_string):
            saved["owner"] = str(owner_user_id)
            saved["domain"] = domain
            saved["cookie_string"] = cookie_string

        monkeypatch.setattr(
            "app.services.agent.login_session.save_user_cookie", fake_save
        )
        m = _manager(tmp_path, cookie_names=["id_token", "web_session"])
        uid = uuid.uuid4()
        record = await m.start(uid, "xiaohongshu")
        st = await _wait_for(
            m, record.session_id, uid, {"waiting_scan", "logged_in"}
        )
        await m._watch_login(record, ttl_seconds=5, check_interval=0.01)
        assert record.status == "logged_in"
        assert saved["domain"] == "www.xiaohongshu.com"
        assert "id_token=v_id_token" in saved["cookie_string"]
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


class TestCloseStopsWatch:
    @pytest.mark.anyio
    async def test_close_marks_closed_and_stops_watch_loop(self, tmp_path):
        m = _manager(tmp_path)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
        assert st["status"] == "waiting_scan"

        assert await m.close(record.session_id, uid) is True
        assert record.status == "closed"

        # watch loop must terminate immediately for a closed record:
        # it must NOT keep looping (or set logged_in/timeout)
        await m._watch_login(record, ttl_seconds=5, check_interval=0.01)
        assert record.status == "closed"


class TestQrWait:
    @pytest.mark.anyio
    async def test_marker_and_data_img_reaches_waiting_scan(self, tmp_path):
        m = _manager(tmp_path, dialog_marker=True, qr_data_img=True)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
        assert st["status"] == "waiting_scan"
        assert record.qr_box is not None
        assert record.qr_box["width"] > 0
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_marker_and_canvas_reaches_waiting_scan(self, tmp_path):
        m = _manager(tmp_path, dialog_marker=True, has_canvas=True, has_fallback_img=False)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"waiting_scan"})
        assert st["status"] == "waiting_scan"
        assert record.qr_box is not None
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_no_dialog_no_qr_times_out(self, tmp_path):
        m = _manager(tmp_path, dialog_marker=False, has_fallback_img=True)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"error"}, timeout=25)
        assert st["status"] == "error"
        assert st["detail"] == "qr_timeout"
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_dialog_without_qr_times_out(self, tmp_path):
        m = _manager(tmp_path, dialog_marker=True, has_fallback_img=False, qr_data_img=False)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"error"}, timeout=25)
        assert st["status"] == "error"
        assert st["detail"] == "qr_timeout"
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_login_entry_clicked_when_no_dialog(self, tmp_path):
        m = _manager(tmp_path, dialog_marker=False, qr_data_img=True)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"waiting_scan"}, timeout=5)
        assert st["status"] == "waiting_scan"
        assert record.page.clicked_login is True
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_platform_blocked_retries_then_succeeds(self, tmp_path):
        m = _manager(tmp_path, blocked_rounds=1, qr_data_img=True)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"waiting_scan"}, timeout=15)
        assert st["status"] == "waiting_scan"
        await m.close(record.session_id, uid)


class TestVerifyForm:
    @pytest.mark.anyio
    async def test_verify_form_detected_and_phone_submitted(self, tmp_path):
        m = _manager(tmp_path, verify_form=True)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"verify_required"}, timeout=10)
        assert st["status"] == "verify_required"
        assert record.verify_state == "phone"
        r1 = await m.submit_phone(record.session_id, uid, "13800138000")
        assert r1["status"] == "verify_code_required"
        assert record.verify_state == "code"
        st2 = await m.status(record.session_id, uid)
        assert st2["status"] == "verify_code_required"
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_send_button_disabled_surfaces_error(self, tmp_path):
        m = _manager(tmp_path, verify_form=True)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"verify_required"}, timeout=10)
        record.page._send_disabled = True
        with pytest.raises(LoginSessionError) as ei:
            await m.submit_phone(record.session_id, uid, "13800138000")
        assert "button_disabled" in str(ei.value)
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_dialog_closed_after_send_surfaces_error(self, tmp_path):
        m = _manager(tmp_path, verify_form=True)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"verify_required"}, timeout=10)
        # 模拟抖音风控：点击发送后弹窗被关闭（表单消失）
        async def closing_evaluate(js, arg=None):
            return {"exists": False}

        original_evaluate = record.page.evaluate

        async def wrapped_evaluate(js, arg=None):
            if arg is not None and isinstance(arg, dict) and arg.get("action") == "verify_sent_marker":
                return None
            if arg is not None and isinstance(arg, dict) and arg.get("action") == "phone_dump_before":
                return {"inputs": [], "buttons": []}
            if arg is None:
                return {"exists": False}
            return await original_evaluate(js, arg)

        record.page.evaluate = wrapped_evaluate
        with pytest.raises(LoginSessionError) as ei:
            await m.submit_phone(record.session_id, uid, "13800138000")
        assert "verify_dialog_closed" in str(ei.value)
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_verify_code_submitted_then_login_signal(self, tmp_path, monkeypatch):
        saved = {}

        async def fake_save(owner_user_id, domain, cookie_string):
            saved["owner"] = str(owner_user_id)
            saved["domain"] = domain
            saved["cookie_string"] = cookie_string

        monkeypatch.setattr(
            "app.services.agent.login_session.save_user_cookie", fake_save
        )
        m = _manager(tmp_path, verify_form=True, cookie_names=["UIFID"])
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"verify_required"}, timeout=10)
        await m.submit_phone(record.session_id, uid, "13800138000")
        await m.submit_code(record.session_id, uid, "123456")
        st2 = await _wait_for(m, record.session_id, uid, {"logged_in"}, timeout=10)
        assert st2["status"] == "logged_in"
        assert saved["domain"] == "www.douyin.com"
        assert "UIFID=v_UIFID" in saved["cookie_string"]
        await m.close(record.session_id, uid)

@pytest.mark.anyio
async def test_default_browser_factory_is_visible(monkeypatch):
    from app.services.agent import login_session as ls

    launched = {}

    class FakePlaywright:
        class chromium:
            @staticmethod
            async def launch(**kwargs):
                launched.update(kwargs)
                return object()

        @staticmethod
        async def start():
            return FakePlaywright()

    # _default_browser_factory imports these inside the function body, so
    # patch the real module attributes, not ls.<name>
    monkeypatch.setattr(
        "patchright.async_api.async_playwright", lambda: FakePlaywright()
    )
    monkeypatch.setattr(
        "app.core.config.get_browser_channel", lambda s=None: "chrome"
    )
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("S", (), {"web_renderer_headless": True})(),
    )

    await ls._default_browser_factory()
    assert launched.get("headless") is False


@pytest.mark.anyio
async def test_window_closed_sets_error(tmp_path):
    m = _manager(tmp_path, verify_form=True)
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    st = await _wait_for(m, record.session_id, uid, {"verify_required"}, timeout=10)
    record.page.closed = True

    async def closed_evaluate(js, arg=None):
        raise Exception("Target page, context or browser has been closed")

    record.page.evaluate = closed_evaluate
    await m._watch_login(record, ttl_seconds=5, check_interval=0.01)
    st2 = await m.status(record.session_id, uid)
    assert st2["status"] == "error"
    assert st2["detail"] == "window_closed"
    await m.close(record.session_id, uid)


@pytest.mark.anyio
async def test_ttl_constant_is_900():
    from app.services.agent.login_session import SESSION_TTL_SECONDS

    assert SESSION_TTL_SECONDS == 900


@pytest.mark.anyio
async def test_verify_code_rejected_error_surfaced(tmp_path):
    m = _manager(
        tmp_path,
        verify_form=True,
        verify_error_text="验证码错误，请重新输入",
    )
    uid = uuid.uuid4()
    record = await m.start(uid, "douyin")
    st = await _wait_for(m, record.session_id, uid, {"verify_required"}, timeout=10)
    assert st["status"] == "verify_required"
    await m.submit_phone(record.session_id, uid, "13800138000")
    with pytest.raises(LoginSessionError) as ei:
        await m.submit_code(record.session_id, uid, "123456")
    assert "验证码错误" in str(ei.value)
    st2 = await m.status(record.session_id, uid)
    assert st2["status"] == "verify_code_required"
    await m.close(record.session_id, uid)
