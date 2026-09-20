# 抖音验证码登录通道（生产环境可用的短信验证码输入） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 抖音登录遇到短信验证码界面时，把手机号/验证码输入暴露到系统前端：用户在系统弹窗输入手机号与短信验证码，worker 自动填入抖音页面完成登录——生产环境（无图形服务器）可用。

**Architecture:** 抖音验证码登录表单（已实测 DOM）：`input[name="normal-input"]`（手机号，placeholder=请输入手机号）、`input[name="button-input"]`（验证码，placeholder=请输入验证码）、文本"获取验证码"按钮、"登录"按钮（弹窗内）。LoginSessionManager watch 循环检测该表单出现 → `status="verify_required"` → 前端弹窗切换为手机号输入 → `POST /login-sessions/{id}/phone` fill 手机号并点击"获取验证码"（抖音发短信）→ `status="verify_code_required"` → 前端验证码输入 → `POST /login-sessions/{id}/verify` fill 验证码并点击"登录" → watch 恢复 UIFID 检测 → cookie 自动导出。watch 循环在 verify 状态跳过 cookies 检测（无 UIFID），其余逻辑不变。

**Tech Stack:** Python 3.12 + patchright (web_renderer 端口 9001), React + AntD (frontend)

## Global Constraints

- 修复/新增文件：
  - `backend/app/services/agent/login_session.py`（状态机 + phone/verify 方法）
  - `backend/app/workers/web_renderer.py`（2 个新端点）
  - `frontend/src/components/platform-login/platform-login-modal.tsx`（verify 两阶段 UI）
  - `frontend/src/api/api.ts`（2 个新 API 函数）
  - `backend/tests/test_login_session_manager.py`（新测试）
- 状态语义：`verify_required`（等手机号）→ `verify_code_required`（等验证码）→ `waiting_scan`（提交后恢复检测）→ `logged_in`
- watch 循环在 `verify_required`/`verify_code_required` 状态：跳过 cookie 检测与验证页判定，只检查验证码表单是否仍在；TTL 超时照常
- phone 端点：fill `input[name="normal-input"]` + click 文本"获取验证码"元素（JS 定位）；verify 端点：fill `input[name="button-input"]` + click 文本"登录"元素（JS 定位，弹窗内最后一个"登录"按钮——用 `textContent.trim()==='登录'` 且位于视口中部）
- 前端 modal：verify 状态显示手机号/验证码输入框 + 提交/重发按钮；手机号默认区号 +86（表单已有区号输入框 `web-login-area-code-input`，只填号码）
- 平台适用：douyin 专用检测；xiaohongshu 若出现同构表单（input[name=normal-input]）同样可用（泛化：检测 `input[name="normal-input"]` + `input[name="button-input"]` 存在即可）
- **git 纪律**：只 add 上列 5 个路径，禁止 `git add -A`；提交前 `git status --short`
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；后端测试 workdir `C:\01_agent_loop_pro\backend`；前端 `npx tsc --noEmit` + `npx vitest run src/components/platform-login/`
- 日志纪律：worker 日志（renderer-err.log）级别 warning——新增关键日志用 `logger.warning` 保证可见

---

### Task 1: 后端状态机 + phone/verify 方法 + 端点

**Files:**
- Modify: `backend/app/services/agent/login_session.py`
- Modify: `backend/app/workers/web_renderer.py`
- Test: `backend/tests/test_login_session_manager.py`

**Interfaces:**
- Consumes: `LoginSessionRecord`（追加 `verify_state: str | None = None`）、`_watch_login` 循环、`_get_owned`
- Produces:
  - `LoginSessionRecord.verify_state: str | None`
  - `async submit_phone(session_id, owner_user_id, phone: str) -> dict`（填手机号+点获取验证码，置 `verify_state="code"` + `status="verify_code_required"`；表单不在时抛 `LoginSessionError("verify_form_gone")`）
  - `async submit_code(session_id, owner_user_id, code: str) -> dict`（填验证码+点登录，置 `status="waiting_scan"`、`verify_state=None`，返回后 watch 恢复检测）
  - 端点：`POST /login-sessions/{id}/phone`（body `{phone}`）、`POST /login-sessions/{id}/verify`（body `{code}`），均带 `x_owner_user_id` header + 403 校验

- [ ] **Step 1: 常量与检测辅助（login_session.py）**

模块级常量（放在 `_VERIFY_UI_MARKERS` 附近）：

```python
VERIFY_PHONE_INPUT_JS = """() => {
    const el = document.querySelector('input[name="normal-input"]');
    if (el) { const r = el.getBoundingClientRect(); return { exists: true, x: r.x, y: r.y, w: r.width, h: r.height }; }
    return { exists: false };
}"""

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
    if (arg.phase === 'phone') return fillAndSubmit('normal-input', arg.phone, '获取验证码');
    return fillAndSubmit('button-input', arg.code, '登录');
}"""
```

- [ ] **Step 2: watch 循环集成（login_session.py）**

`_watch_login` 循环开头（cookie 检测之前）插入：

```python
            try:
                verify_ui = await record.page.evaluate(VERIFY_PHONE_INPUT_JS)
            except Exception:
                verify_ui = {"exists": False}
            if verify_ui.get("exists"):
                if record.status != "verify_required" and record.status != "verify_code_required":
                    record.status = "verify_required"
                    record.verify_state = "phone"
                    logger.warning("login_session_verify_required")
                await asyncio.sleep(check_interval)
                continue
```

（表单消失——登录成功或跳转——watch 恢复原逻辑；`record.status` 已由 submit_code 置回 `waiting_scan`。）

- [ ] **Step 3: submit_phone / submit_code 方法（login_session.py）**

加在 `_watch_login` 之后：

```python
    async def submit_phone(self, session_id: str, owner_user_id: uuid.UUID, phone: str) -> dict:
        record = await self._get_owned(session_id, owner_user_id)
        if record.status not in ("verify_required", "verify_code_required"):
            raise LoginSessionError("not_verify_state")
        try:
            result = await record.page.evaluate(
                VERIFY_SUBMIT_JS, {"phase": "phone", "phone": phone}
            )
        except Exception:
            raise LoginSessionError("verify_form_gone")
        if not result.get("ok"):
            raise LoginSessionError(result.get("reason", "verify_submit_failed"))
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
        record.verify_state = None
        record.status = "waiting_scan"
        logger.warning("login_session_verify_code_submitted")
        return {"status": "waiting_scan"}
```

`LoginSessionRecord` 加字段：`verify_state: str | None = None`。

- [ ] **Step 4: 端点（web_renderer.py）**

仿照现有 `/login-sessions/{session_id}/status` 端点添加（模块内已有 `_owner_id`/`LoginSessionManager` 单例）：

```python
@router.post("/login-sessions/{session_id}/phone")
async def login_session_phone(
    session_id: str,
    payload: dict,
    x_owner_user_id: str = Header(...),
) -> dict:
    phone = str(payload.get("phone", "")).strip()
    if not phone:
        raise HTTPException(status_code=422, detail="phone_required")
    try:
        return await manager.submit_phone(session_id, _owner_id(x_owner_user_id), phone)
    except LoginSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/login-sessions/{session_id}/verify")
async def login_session_verify(
    session_id: str,
    payload: dict,
    x_owner_user_id: str = Header(...),
) -> dict:
    code = str(payload.get("code", "")).strip()
    if not code:
        raise HTTPException(status_code=422, detail="code_required")
    try:
        return await manager.submit_code(session_id, _owner_id(x_owner_user_id), code)
    except LoginSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
```

（`LoginSessionError`/`HTTPException`/`Header`/`router` 均已在 web_renderer.py import——核实，缺失则补。）

- [ ] **Step 5: 测试（test_login_session_manager.py）**

FakePage 加支持：`verify_form: bool = False` 参数；`evaluate` 增加 action 分支：

```python
        if arg is not None and isinstance(arg, dict) and arg.get("action") is None:
            # real VERIFY_PHONE_INPUT_JS / VERIFY_SUBMIT_JS calls use plain dicts
            if "exists" in str(arg) or arg.get("phase") is not None:
                if arg.get("phase") == "phone":
                    self.submitted_phone = arg.get("phone")
                    self.submitted_action = "phone"
                if arg.get("phase") == "code":
                    self.submitted_code = arg.get("code")
                    self.submitted_action = "code"
                return {"ok": True}
```

注意：真实代码的 `VERIFY_PHONE_INPUT_JS` 是无参 evaluate（`arg` 为 None）——fake 需要区分：无 arg 的 evaluate 若 `self._verify_form` 为 True 返回 `{"exists": True}`。设计 fake 的 evaluate 入口统一按 arg 形态分发（保持既有 action 契约不变，新增裸 JS 调用兼容分支——在报告里说明你选择的形态）。

新增测试（TestQrWait 后）：

```python
    @pytest.mark.anyio
    async def test_verify_form_detected_and_phone_submitted(self, tmp_path):
        m = _manager(tmp_path, verify_form=True)
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"verify_required"}, timeout=10)
        assert st["status"] == "verify_required"
        r1 = await m.submit_phone(record.session_id, uid, "13800138000")
        assert r1["status"] == "verify_code_required"
        st2 = (await m.status(record.session_id, uid))
        assert st2["status"] == "verify_code_required"
        await m.close(record.session_id, uid)

    @pytest.mark.anyio
    async def test_verify_code_submitted_then_login_signal(self, tmp_path):
        m = _manager(tmp_path, verify_form=True, cookie_names=["UIFID"])
        uid = uuid.uuid4()
        record = await m.start(uid, "douyin")
        st = await _wait_for(m, record.session_id, uid, {"verify_required"}, timeout=10)
        await m.submit_phone(record.session_id, uid, "13800138000")
        await m.submit_code(record.session_id, uid, "123456")
        st2 = await _wait_for(m, record.session_id, uid, {"logged_in"}, timeout=10)
        assert st2["status"] == "logged_in"
        await m.close(record.session_id, uid)
```

`test_verify_code_submitted_then_login_signal` 需 fake 语义：submit_code 后 `verify_form` 变 False（表单消失模拟登录）+ cookie 含 UIFID → logged_in。fake 里 submit_code 置 `self._verify_form = False`。

- [ ] **Step 6: RED → GREEN**

RED: `pytest tests/test_login_session_manager.py -k verify -v --no-header` 应失败（方法不存在）。
GREEN: 实现后同命令全过；再跑 `pytest tests/test_login_session_manager.py tests/test_login_session.py -q --no-header`（37+ 全过，含 2 个 20s 超时测试）。

- [ ] **Step 7: 提交**

```bash
git add backend/app/services/agent/login_session.py backend/app/workers/web_renderer.py backend/tests/test_login_session_manager.py
git commit -m "feat: SMS verify-code login channel for douyin via frontend input"
```
Workdir `C:\01_agent_loop_pro`（先 `git status --short` 核实暂存内容）。

---

### Task 2: 前端两阶段验证码 UI

**Files:**
- Modify: `frontend/src/api/api.ts`
- Modify: `frontend/src/components/platform-login/platform-login-modal.tsx`
- Test: `frontend/src/components/platform-login/platform-login-modal.test.tsx`（如存在则扩展，否则跳过——检查现有测试文件）

**Interfaces:**
- Consumes: 既有 `startLoginSession`/`getLoginSessionStatus` 模式；`verify_required`/`verify_code_required` 状态来自 status 接口
- Produces:
  - `api.ts`: `submitLoginPhone(sessionId, phone)`、`submitLoginCode(sessionId, code)`（POST，带 `X-Owner-User-Id` header，同 startLoginSession）
  - modal：verify 两阶段表单（手机号 → 验证码），提交中 loading，成功后回到扫码视图（已登录由轮询状态驱动）

- [ ] **Step 1: api.ts 加函数**

```ts
export async function submitLoginPhone(sessionId: string, phone: string) {
  const res = await fetch(`http://127.0.0.1:9001/login-sessions/${sessionId}/phone`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Owner-User-Id": getOwnerUserId(),
    },
    body: JSON.stringify({ phone }),
  });
  if (!res.ok) throw new Error("phone_submit_failed");
  return res.json();
}

export async function submitLoginCode(sessionId: string, code: string) {
  const res = await fetch(`http://127.0.0.1:9001/login-sessions/${sessionId}/verify`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Owner-User-Id": getOwnerUserId(),
    },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw new Error("code_submit_failed");
  return res.json();
}
```

（`getOwnerUserId` 与 `startLoginSession` 同源——先读 api.ts 现有实现，保持一致。）

- [ ] **Step 2: modal 状态扩展（platform-login-modal.tsx）**

读现有文件。当前有 `scanning`/`waiting`/`loggedIn` 等状态与轮询。扩展：

```tsx
const [verifyPhase, setVerifyPhase] = useState<"phone" | "code" | null>(null);
const [phone, setPhone] = useState("");
const [code, setCode] = useState("");
const [submitting, setSubmitting] = useState(false);
const [verifyError, setVerifyError] = useState("");
```

轮询回调中当 status 为 `verify_required` → `setVerifyPhase("phone")`；`verify_code_required` → `setVerifyPhase("code")`。

渲染（verifyPhase 非空时替换二维码区域）：

```tsx
{verifyPhase && (
  <div className="verify-form">
    {verifyPhase === "phone" ? (
      <>
        <Input placeholder="请输入手机号" value={phone}
          onChange={(e) => setPhone(e.target.value)} maxLength={11} />
        <Button type="primary" block loading={submitting}
          onClick={handleSendCode}>获取验证码</Button>
      </>
    ) : (
      <>
        <p className="verify-tip">验证码已发送至 {phone}</p>
        <Input placeholder="请输入验证码" value={code}
          onChange={(e) => setCode(e.target.value)} maxLength={6} />
        <Button type="primary" block loading={submitting}
          onClick={handleVerifyCode}>提交验证</Button>
        <Button type="link" block disabled={submitting} onClick={handleResend}>重新获取验证码</Button>
      </>
    )}
    {verifyError && <p className="verify-error">{verifyError}</p>}
  </div>
)}
```

handler：

```tsx
const handleSendCode = async () => {
  if (!/^1\d{10}$/.test(phone)) { setVerifyError("请输入正确的手机号"); return; }
  setSubmitting(true); setVerifyError("");
  try {
    await submitLoginPhone(sessionId, phone);
    setVerifyPhase("code");
  } catch { setVerifyError("提交失败，请重试"); }
  setSubmitting(false);
};

const handleVerifyCode = async () => {
  if (!/^\d{4,6}$/.test(code)) { setVerifyError("请输入验证码"); return; }
  setSubmitting(true); setVerifyError("");
  try {
    await submitLoginCode(sessionId, code);
    setVerifyPhase(null);
  } catch { setVerifyError("验证失败，请重试"); }
  setSubmitting(false);
};

const handleResend = async () => {
  setSubmitting(true); setVerifyError("");
  try {
    await submitLoginPhone(sessionId, phone);
  } catch { setVerifyError("重新发送失败"); }
  setSubmitting(false);
};
```

（AntD 组件风格/布局跟随现有文件；`sessionId` 从现有 state 取。）

- [ ] **Step 3: 前端验证**

Run: `npx tsc --noEmit`（workdir `C:\01_agent_loop_pro\frontend`）——零新错误（注意仓库存在并行会话的 pre-existing tsc 错误——只保证本文件无新增错误）。
Run: `npx vitest run src/components/platform-login/`——若已有测试文件需保持通过（新增状态不破坏现有断言；如现有测试断言固定渲染结构，需同步更新——在报告中说明）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/api.ts frontend/src/components/platform-login/platform-login-modal.tsx
git commit -m "feat: verify-code two-phase input UI in platform login modal"
```

---

### Task 3: E2E 验证与收尾

- [ ] **Step 1: 重启 web_renderer**

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'web_renderer' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 3
Start-Process -FilePath "X:\python\anaconda\envs\01-rbac\python.exe" -ArgumentList "-m","app.workers.web_renderer" -WorkingDirectory "C:\01_agent_loop_pro\backend" -WindowStyle Hidden -RedirectStandardOutput "C:\Users\Lenovo\AppData\Local\Temp\opencode\renderer.log" -RedirectStandardError "C:\Users\Lenovo\AppData\Local\Temp\opencode\renderer-err.log"
Start-Sleep -Seconds 10
```
Expected: /health ok。

- [ ] **Step 2: 用户实测（关键验收）**

1. 前端 → 平台登录 → 抖音 → 扫码 → 手机确认 → **弹窗变为"手机号输入"**
2. 输入抖音绑定手机号 → 获取验证码 → 手机收到短信
3. 输入验证码 → 提交 → **前端变"已登录"** + 卡片绿色"已登录"
4. 查日志：`login_session_verify_phone_submitted` + `login_session_verify_code_submitted` + `login_session_cookie_exported` 全出现
5. Agent 测试：让 agent 抓抖音首页 → 返回真实内容

- [ ] **Step 3: 全量回归**

后端：`pytest tests/ -q --no-header`（隔离 DB：`$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_qrfix3"`；预期 725+ 通过、仅 4 个已知 pypdf 失败）
前端：`npx vitest run src/components/platform-login/ src/components/files/`

- [ ] **Step 4: 提交校准修复（如有）**

```bash
git add <精确路径>
git commit -m "fix: QR login E2E calibration"
```
（仅当有修复；无则跳过。）
