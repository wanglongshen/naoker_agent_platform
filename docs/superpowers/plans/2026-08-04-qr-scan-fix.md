# 扫码登录二维码修复（主动弹窗 + 真码检测 + 裁剪高清截图） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复抖音/小红书扫码登录"二维码扫不了"：worker 主动打开登录弹窗、检测真正的二维码元素、截图裁剪放大二维码区域输出高清帧。

**Architecture:** 根因已实测定位（诊断证据在 2026-08-04 会话记录）——① `_wait_for_qr` 用"任意 img 出现"当 QR 信号（假阳性：视频封面也算），且 worker 从不主动打开登录弹窗，waiting_scan 时截图里根本没有码；② 整页截图 JPEG60 + 码仅 ~180px + 前端 288px 显示 → 手机扫不出（OpenCV 实测整页 JPEG60→288px 解码失败）。修复：`_open_and_watch` goto 后若登录弹窗未出现（文本 marker 判定）则点击平台登录入口；`_wait_for_qr` 改为"弹窗 marker 出现 + 码元素（data-url img/canvas/100-400px img）"双重判定并记录码坐标；`frame()` 改为 clip 码区域 + 2x 放大 + JPEG90（实测 clip 2x→288px 显示仍可解码 ✓）。

**Tech Stack:** Python 3.12, patchright async API, FastAPI

## Global Constraints

- 修复目标文件：`backend/app/services/agent/login_session.py` + `backend/tests/test_login_session_manager.py`（+`test_login_session.py` 若其纯函数测试受影响）
- 判定语义：**waiting_scan 必须意味着"登录弹窗已出现且检测到二维码元素"**——不再有任何"任意 img 即算"的假阳性路径
- 弹窗 marker（文本信号，页面 innerText 包含即认为弹窗已开）：douyin = `("登录后免费畅享高清视频", "扫码登录", "验证码登录")`；xiaohongshu = `("扫码登录", "手机号登录", "验证码登录")`
- 登录入口点击（弹窗未开时）：douyin = 页面文本精确为"登录"的 button/div/span/a；xiaohongshu = 文本含"新用户直接登录"或精确为"登录"的元素；点击用 `page.evaluate` JS 实现，失败静默
- 码元素判定（弹窗已开时）：`img` 且 `src` 以 `data:` 开头且 CSS 尺寸 100-400px；或 `canvas` 尺寸 100-500px；或 `img[src*='qrcode']`；兜底：弹窗已开时任意 100-400px 的 `img`（弹窗是 gate，img 是 signal）
- 截图：`frame()` 有码坐标时 `clip={x-20, y-20, w+40, h+40}` + `scale=2` + JPEG quality=90；无码坐标时整页 JPEG90 兜底
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；测试工作目录 `C:\01_agent_loop_pro\backend`
- **git 纪律**：仓库有其他并行会话的未提交变更——只能 `git add` 本任务列出的精确路径，禁止 `git add -A`/`git reset`/rebase/全局操作；提交前 `git status` 确认暂存内容
- 本次**不动前端**（`platform-login-modal.tsx` 图片容器 288px 已够，clip 2x 帧实测可扫）

---

### Task 1: login_session.py 弹窗主动打开 + 真码检测 + 裁剪截图（含测试适配）

**Files:**
- Modify: `backend/app/services/agent/login_session.py`
- Modify: `backend/tests/test_login_session_manager.py`
- Modify: `backend/tests/test_login_session.py`（仅当纯函数测试受影响；先跑确认）

**Interfaces:**
- Consumes: 既有 `LoginSessionRecord`（dataclass，追加 `qr_box` 字段）、`PLATFORMS`、`LOGIN_URLS`、`is_verification_page`、`assess_login_expired`、`CONTENT_THRESHOLD`、`QR_WAIT_TIMEOUT`、`QR_POLL_INTERVAL`
- Produces:
  - 常量：`DIALOG_MARKERS: dict[str, tuple[str, ...]]`、`LOGIN_ENTRY_TEXTS: dict[str, tuple[str, ...]]`（登录入口文本匹配）
  - `LoginSessionRecord.qr_box: dict | None = None`（`{"x","y","width","height"}`，CSS 像素）
  - `async _ensure_login_dialog(record) -> None`（弹窗未开则点击登录入口，静默失败）
  - `_wait_for_qr` 语义变更（见上"判定语义"）；`frame()` 变更（见上"截图"）

- [ ] **Step 1: Read current test file state**

Read `C:\01_agent_loop_pro\backend\tests\test_login_session_manager.py` and `C:\01_agent_loop_pro\backend\app\services\agent\login_session.py` fully. Note: `TestQrWait` currently has 3 tests with fallback-img semantics that this task replaces.

- [ ] **Step 2: Update the Fake fixtures (test file)**

In `C:\01_agent_loop_pro\backend\tests\test_login_session_manager.py`, extend `FakePage`:

```python
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
    ):
        self._content = content
        self._qr_selectors = qr_selectors or []
        self._has_fallback_img = has_fallback_img
        self._dialog_marker = dialog_marker
        self._qr_data_img = qr_data_img
        self._qr_box = qr_box or {"x": 180, "y": 515, "width": 179, "height": 179}
        self._has_canvas = has_canvas
        self.url = "https://www.douyin.com/"
        self.clicked_login = False

    async def goto(self, url, wait_until="domcontentloaded", timeout=30000):
        self.url = url
        return None

    async def wait_for_timeout(self, ms):
        await asyncio.sleep(0)

    async def content(self):
        return f"<html><body>{self._content}</body></html>"

    async def evaluate(self, js, arg=None):
        # simulate login-entry click: opening the dialog sets the marker
        if arg is not None and isinstance(arg, dict) and arg.get("action") == "click_login":
            self.clicked_login = True
            self._dialog_marker = True
        if arg is not None and isinstance(arg, dict) and arg.get("action") == "find_qr":
            if self._qr_data_img:
                return {"kind": "img", "x": self._qr_box["x"], "y": self._qr_box["y"],
                        "w": self._qr_box["width"], "h": self._qr_box["height"]}
            if self._has_canvas:
                return {"kind": "canvas", "x": self._qr_box["x"], "y": self._qr_box["y"],
                        "w": self._qr_box["width"], "h": self._qr_box["height"]}
            return None
        if arg is not None and isinstance(arg, dict) and arg.get("action") == "has_marker":
            return self._dialog_marker
        return None

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
```

（`FakeContext`/`FakeBrowser`/`_manager` 相应透传新参数：`dialog_marker`、`qr_data_img`、`qr_box`、`has_canvas`。默认值设计：`dialog_marker=True` + `qr_data_img=False` + `has_fallback_img=True`——**保证既有测试默认行为不变**（弹窗开着 + 兜底 img 命中 → waiting_scan）。失败路径测试显式设置 `dialog_marker=False` 或 `qr_data_img=False & has_fallback_img=False`。）

- [ ] **Step 3: Rewrite TestQrWait (test file)**

Replace the whole `TestQrWait` class with:

```python
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
```

（`test_login_entry_clicked_when_no_dialog` 模拟：初始无 marker → 实现点击登录入口（fake evaluate 置 marker）→ 下一轮 marker 出现 + qr_data_img 命中 → waiting_scan。注意：`_wait_for_qr` 必须调用 `_ensure_login_dialog`。）

- [ ] **Step 4: Run tests to verify RED**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_login_session_manager.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: 新语义测试 FAIL（`test_marker_and_data_img_reaches_waiting_scan` 可能过——因兜底 img 仍在；`test_no_dialog_no_qr_times_out`、`test_dialog_without_qr_times_out`、`test_login_entry_clicked_when_no_dialog` FAIL——当前实现无 marker 判定/无登录入口点击）。记录具体失败集。

- [ ] **Step 5: Implement in login_session.py**

In `C:\01_agent_loop_pro\backend\app\services\agent\login_session.py`:

1. **Record field** — add to `LoginSessionRecord`:

```python
    qr_box: dict | None = None
```

2. **Constants** — replace `QR_SELECTORS`/`QR_FALLBACK_SELECTOR` usage with marker/entry constants (keep `QR_SELECTORS` for canvas/img[src*=qrcode] static selectors):

```python
DIALOG_MARKERS: dict[str, tuple[str, ...]] = {
    "douyin": ("登录后免费畅享高清视频", "扫码登录", "验证码登录"),
    "xiaohongshu": ("扫码登录", "手机号登录", "验证码登录"),
}

LOGIN_ENTRY_TEXTS: dict[str, tuple[str, ...]] = {
    "douyin": ("登录",),
    "xiaohongshu": ("新用户直接登录", "登录"),
}
```

3. **`_ensure_login_dialog`** — add after `_wait_for_qr`'s callers (place before `_wait_for_qr`):

```python
    async def _ensure_login_dialog(self, record: LoginSessionRecord) -> bool:
        """Click the platform login entry if the login dialog is not open yet."""
        try:
            html = await record.page.content()
            text = _extract_platform_content(html, LOGIN_URLS[record.platform])["text"]
        except Exception:
            text = ""
        if any(m in text for m in DIALOG_MARKERS.get(record.platform, ())):
            return True
        entries = LOGIN_ENTRY_TEXTS.get(record.platform, ())
        if not entries:
            return False
        try:
            await record.page.evaluate(
                """([entries]) => {
                    for (const el of Array.from(document.querySelectorAll('button, div, span, a'))) {
                        const t = (el.textContent || '').trim();
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && entries.some(e => e === t || t.includes(e))) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""",
                list(entries),
            )
            await record.page.wait_for_timeout(2000)
            return True
        except Exception:
            return False
```

注意：`_extract_platform_content` 已在 `_wait_for_qr` 中 import——把该 import 上移到模块级或保持局部 import 两处（既有模式即局部 import，两处均可局部 import）。

4. **Rewrite `_wait_for_qr`** — replace the whole method:

```python
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
        selectors = QR_SELECTORS.get(record.platform, [])
        while time.monotonic() < deadline:
            try:
                html = await record.page.content()
                text = _extract_platform_content(html, LOGIN_URLS[record.platform])["text"]
            except Exception:
                text = ""
            dialog_open = any(m in text for m in DIALOG_MARKERS.get(record.platform, ()))
            if dialog_open:
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
                        for (const im of Array.from(document.querySelectorAll('img[src*="qrcode"], img'))) {
                            const r = im.getBoundingClientRect();
                            if (r.width >= 100 && r.width <= 400) {
                                return { kind: 'img', x: Math.round(r.x), y: Math.round(r.y),
                                         w: Math.round(r.width), h: Math.round(r.height) };
                            }
                        }
                        return null;
                    }"""
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
```

（`QR_SELECTORS` 保留常量定义但不再作为主判定——或删除；删除更干净，`selectors` 变量不再需要。若删除，同步删除 `QR_SELECTORS` 常量定义及其在 fake/测试中的引用。**决策：删除 `QR_SELECTORS` 与 `QR_FALLBACK_SELECTOR`，全部判定走 evaluate JS。** 测试里 `qr_selectors` 参数保留但不再被实现使用——测试改用 `qr_data_img`/`has_canvas`。）

5. **`frame()` quality upgrade** — replace:

```python
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
```

注意：PIL 放大 2x 需要在 `requirements.txt` 已有 pillow（T4 诊断时为本地安装，**需确认已加入 requirements.txt；若没有，本任务在 requirements.txt 加 `pillow>=10,<12` 并安装**——检查 `backend/requirements.txt` 是否含 pillow，不含则 add+install 并纳入 commit）。

6. **`_open_and_watch`** — 无需改动（`_wait_for_qr` 内部已含 `_ensure_login_dialog`）。

- [ ] **Step 6: Run tests to verify GREEN**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_login_session_manager.py tests/test_login_session.py -v --no-header` (workdir `C:\01_agent_loop_pro\backend`)
Expected: all pass（manager + 16 纯函数；`test_no_qr_times_out` 旧名已删，新 4+1 测试全绿；注意测试集总时长 ~20-25s 因两个 20s 超时测试）。

- [ ] **Step 7: Run focused regression + commit**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_login_session_manager.py tests/test_agent_authorization.py -q --no-header` — 无回归（共享 DB 被并行会话占用时用 `TEST_DATABASE_URL` 隔离库）。

```bash
git add backend/app/services/agent/login_session.py backend/tests/test_login_session_manager.py backend/requirements.txt
git commit -m "fix: open login dialog, detect real QR element, crop-zoom screenshot"
```
Workdir: `C:\01_agent_loop_pro`
（requirements.txt 仅当 pillow 缺失需新增时才纳入；已存在则不加。）

---

### Task 2: E2E 验证与收尾

**Files:**
- No new files (verification only)

- [ ] **Step 1: Restart web_renderer**

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'web_renderer' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
& "X:\python\anaconda\envs\01-rbac\python.exe" "C:\Users\Lenovo\AppData\Local\Temp\opencode\launch_worker.py"
Start-Sleep -Seconds 8
```
Expected: 9001 health OK。

- [ ] **Step 2: Smoke both platforms + decode verification**

对 douyin 与 xiaohongshu 各执行：POST /login-sessions → 等 15s → status 应 `waiting_scan` → GET frame → 保存 base64 为 jpg → OpenCV `QRCodeDetector.detectAndDecode` 解码 → **必须解出内容**（douyin 应为 `https://v.douyin.com/...` 登录短链格式；xiaohongshu 应解出 `https://www.xiaohongshu.com/...` 或类似登录链接格式）→ DELETE。

解码脚本（`C:\Users\Lenovo\AppData\Local\Temp\opencode\decode_frame.py` 已存在，直接复用）。

判定：
- `status=waiting_scan` 且 frame 解码成功 → PASS
- `status=error` → 按 detail 分级处理（platform_blocked/qr_timeout/browser_failed）
- `status=waiting_scan` 但解码失败 → 码元素检测/坐标有误，上报校准（marker 或坐标）

- [ ] **Step 3: Full backend suite**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header` (workdir `C:\01_agent_loop_pro\backend`，共享 DB 冲突时用隔离 `TEST_DATABASE_URL`；上次全量 725 passed + 4 已知 pypdf 失败)
Expected: 无新增失败。

- [ ] **Step 4: Manual scan verification (user)**

1. 前端顶栏"平台登录"→ 抖音扫码登录 → 应显示**高清二维码**（不再是整页缩略）
2. 手机抖音 App 扫码 → 手机确认 → 前端"登录成功" + 卡片"已登录"
3. 小红书同样流程
4. Agent 抓取测试：让 agent 看抖音首页热门内容 → 返回真实内容（非验证页）

- [ ] **Step 5: Commit any calibration fixes**

```bash
git add <precise paths>
git commit -m "fix: QR login calibration from E2E verification"
```
(仅当有修复时执行；无改动则跳过。)
