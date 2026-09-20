# 平台登录获取（手动 Cookie 导入 + 可见窗口）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 抖音/小红书登录态双路径：A 手动 Cookie 导入（无桌面远端可用）+ B 可见窗口登录（本机）；登录态统一存 `user_web_cookies`，搜索/详情无头 + cookie 注入不变。

**Architecture:** 后端 `agent_cookies.py` 新增 `/cookies/import`（Cookie-Editor JSON → 平台分组 → `cookies_to_string` → `save_user_cookie`）；`login_session.py` 登录浏览器改可见（headless=False）+ TTL 900 + 窗口关闭/无桌面检测；前端登录中心移除二维码改为状态提示 + 新增手动导入表单。

**Tech Stack:** FastAPI / Playwright(patchright) / React(antd) / vitest

## Global Constraints

- 存储格式：cookie_string = `name=value; name2=value2; ...`（`cookies_to_string`，login_session.py）
- 注入链路不变：tool_executor `_parse_cookie_string`（`k1=v1; k2=v2` → Playwright list）
- 平台域名：douyin → `www.douyin.com`，xiaohongshu → `www.xiaohongshu.com`（`DOMAIN_BY_PLATFORM`）
- import 校验：cookies ≤500 条；name/value 非空；domain 匹配 `douyin.com`/`xiaohongshu.com` 或其子域（含 `.douyin.com` 前缀点号形式）
- 可见窗口仅登录会话；`/search` `/detail` 的 `render_page` 保持 `web_renderer_headless` 配置
- `SESSION_TTL_SECONDS` = 900；`_watch_login` 异常区分 window_closed（error）与瞬时错误（继续轮询）
- 后端测试命令（从 `C:\01_agent_loop_pro\backend`）：`X:\python\anaconda\envs\01-rbac\python.exe -X utf8 -m pytest <file> -q`（conda run 崩溃，直接用 python.exe）
- 前端测试命令（从 `C:\01_agent_loop_pro\frontend`）：`npm test -- <file>`；构建：`npm run build`
- 前端 jsdom 约束（AGENTS.md/项目记忆）：页面级 byRole 超时（antd 样式表），用 `document.querySelectorAll` + textContent 匹配
- 提交时只 `git add` 自己的文件（工作区常有另一会话文件）；登录中心组件是另一会话常改文件，改动前先 `git status` 核对

---

### Task 1: 后端 Cookie 导入端点

**Files:**
- Modify: `backend/app/api/agent_cookies.py`（新增 `POST /cookies/import`）
- Modify: `backend/tests/test_agent_cookies.py`（追加导入测试）
- Test: `backend/tests/test_agent_cookies.py`

**Interfaces:**
- Consumes: `save_user_cookie`（web_cookie_store，已有）；`cookies_to_string` + `DOMAIN_BY_PLATFORM`（login_session.py，已有）
- Produces: `POST /api/agent/cookies/import` body `{cookies: [{name, value, domain, path?, expires?, secure?, httpOnly?}]}` → `{saved: {douyin: n, xiaohongshu: m}}`；无效/无匹配 → 422 `INVALID_COOKIES`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_agent_cookies.py` 追加（先读该文件现有 fixture/模式——跟随其 admin_client/csrf 用法）：

```python
class TestCookieImport:
    async def test_import_groups_by_platform_and_saves(
        self, admin_client, csrf_headers
    ):
        resp = await admin_client.post(
            "/api/agent/cookies/import",
            json={
                "cookies": [
                    {"name": "sessionid", "value": "abc", "domain": ".douyin.com"},
                    {"name": "UIFID", "value": "xyz", "domain": "www.douyin.com"},
                    {"name": "id_token", "value": "tkn", "domain": ".xiaohongshu.com"},
                ]
            },
            **csrf_headers,
        )
        assert resp.status_code == 200
        saved = resp.json()["data"]["saved"]
        assert saved == {"douyin": 2, "xiaohongshu": 1}

    async def test_import_rejects_foreign_domain(self, admin_client, csrf_headers):
        resp = await admin_client.post(
            "/api/agent/cookies/import",
            json={
                "cookies": [
                    {"name": "x", "value": "y", "domain": "https://evil.com"}
                ]
            },
            **csrf_headers,
        )
        assert resp.status_code == 422

    async def test_import_filters_invalid_items(self, admin_client, csrf_headers):
        resp = await admin_client.post(
            "/api/agent/cookies/import",
            json={
                "cookies": [
                    {"name": "", "value": "v", "domain": ".douyin.com"},
                    {"name": "ok", "value": "", "domain": ".douyin.com"},
                    {"name": "good", "value": "v2", "domain": ".douyin.com"},
                ]
            },
            **csrf_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["saved"] == {"douyin": 1}

    async def test_import_requires_csrf(self, admin_client):
        resp = await admin_client.post(
            "/api/agent/cookies/import",
            json={"cookies": [{"name": "x", "value": "y", "domain": ".douyin.com"}]},
        )
        assert resp.status_code in (401, 403)
```

- [ ] **Step 2: 运行确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -X utf8 -m pytest tests/test_agent_cookies.py::TestCookieImport -q`
Expected: FAIL（404 端点不存在）

- [ ] **Step 3: 实现端点**

`backend/app/api/agent_cookies.py` 追加：

```python
class CookieImportItem(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=8192)
    domain: str = Field(min_length=1, max_length=256)


class CookieImportRequest(BaseModel):
    cookies: list[CookieImportItem] = Field(min_length=1, max_length=500)


_ALLOWED_COOKIE_HOSTS = ("douyin.com", "xiaohongshu.com")


def _platform_for_domain(domain: str) -> str | None:
    d = domain.strip().lower().lstrip(".")
    if d == "douyin.com" or d.endswith(".douyin.com"):
        return "douyin"
    if d == "xiaohongshu.com" or d.endswith(".xiaohongshu.com"):
        return "xiaohongshu"
    return None


@router.post("/cookies/import")
async def import_cookies(
    request: Request,
    data: CookieImportRequest,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    from app.services.agent.login_session import DOMAIN_BY_PLATFORM, cookies_to_string

    grouped: dict[str, list[dict]] = {}
    for c in data.cookies:
        platform = _platform_for_domain(c.domain)
        if platform is None:
            continue
        grouped.setdefault(platform, []).append({"name": c.name, "value": c.value})
    if not grouped:
        raise ApiError(
            status_code=422,
            code="INVALID_COOKIES",
            message="未找到有效的抖音/小红书 Cookie（检查 domain 是否包含 douyin.com 或 xiaohongshu.com）",
        )
    saved: dict[str, int] = {}
    for platform, pairs in grouped.items():
        cookie_str = cookies_to_string(pairs)
        await save_user_cookie(current_user.id, DOMAIN_BY_PLATFORM[platform], cookie_str)
        saved[platform] = len(pairs)
    return success(request, {"saved": saved})
```

注意：`cookies_to_string` 只取 name/value（`c['name']`/`c['value']`），导入 dict 键名必须为 `name`/`value`——`CookieImportItem` 已保证。

- [ ] **Step 4: 运行确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -X utf8 -m pytest tests/test_agent_cookies.py -q`
Expected: PASS（含既有测试）

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/agent_cookies.py backend/tests/test_agent_cookies.py
git commit -m "feat: import platform cookies from Cookie-Editor JSON"
```

---

### Task 2: 登录会话可见窗口（login_session.py）

**Files:**
- Modify: `backend/app/services/agent/login_session.py`（`_default_browser_factory` headless=False；`_watch_login` 窗口关闭检测；`SESSION_TTL_SECONDS`=900）
- Modify: `backend/tests/test_login_session_manager.py`（FakePage is_closed + window_closed/launch 失败测试 + TTL 断言）
- Test: `backend/tests/test_login_session_manager.py`

**Interfaces:**
- Consumes: 现有 `_watch_login` / `_open_and_watch` 结构
- Produces: 无（行为变更：登录浏览器可见；错误 detail 新增 `window_closed`）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_login_session_manager.py` 追加：

```python
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

    monkeypatch.setattr(ls, "async_playwright", lambda: FakePlaywright())
    monkeypatch.setattr(ls, "get_browser_channel", lambda s=None: "chrome")
    monkeypatch.setattr(ls, "get_settings", lambda: type("S", (), {"web_renderer_headless": True})())

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
```

（FakePage 需要 `closed` 属性 + `is_closed()` 方法——见 Step 3。`async_playwright`/`get_browser_channel`/`get_settings` 是 login_session 模块内 import 的名字——先确认 `_default_browser_factory` 内实际 import 方式，若为函数内 `from patchright.async_api import async_playwright` 则 monkeypatch 目标为 `ls.async_playwright` 需先确认模块级是否存在该名字；若不存在，monkeypatch `ls._default_browser_factory` 内部用的模块路径——读代码后按实际调整。）

- [ ] **Step 2: 运行确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -X utf8 -m pytest tests/test_login_session_manager.py -q`
Expected: FAIL（headless 断言失败 / window_closed 未实现 / TTL 非 900）

- [ ] **Step 3: 实现**

`backend/app/services/agent/login_session.py` 三处修改：

1. `_default_browser_factory`：

```python
    return await p.chromium.launch(
        headless=False,  # 登录会话需真人操作（可见窗口）；/search /detail 走 render_page 不受影响
        channel=get_browser_channel(_settings),
    )
```

2. `_watch_login` 的 `except Exception` 分支（现有 `login_session_watch_error` 日志处）改为：

```python
            except Exception as exc:
                logger.warning("login_session_watch_error: %s", exc)
                try:
                    closed = record.page.is_closed()
                except Exception:
                    closed = True
                if closed:
                    record.status = "error"
                    record.detail = "window_closed"
                    return
```

3. `SESSION_TTL_SECONDS: int = 900`

`backend/tests/test_login_session_manager.py` 的 FakePage 追加：

```python
    def is_closed(self):
        return getattr(self, "closed", False)
```

- [ ] **Step 4: 运行确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -X utf8 -m pytest tests/test_login_session_manager.py tests/test_login_session.py -q`
Expected: PASS（既有 23+17 测试全过——`test_ttl_timeout` 用 `ttl_seconds` 参数不受常量影响）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/login_session.py backend/tests/test_login_session_manager.py
git commit -m "fix: visible login window with window-closed detection and 900s TTL"
```

---

### Task 3: 前端登录中心（状态提示 + 手动导入）

**Files:**
- Modify: `frontend/src/components/feishu/platform-login-modal.tsx`（移除 /frame 轮询与二维码；状态提示文案；ERROR_TEXT 扩展；手动导入表单）
- Modify: `frontend/src/components/feishu/platform-login-modal.test.tsx`（更新/新增测试）
- Test: `frontend/src/components/feishu/platform-login-modal.test.tsx`

**Interfaces:**
- Consumes: `api`（@/lib/api，已有）；`POST /api/agent/cookies/import`（Task 1）；`POST /api/agent/login-sessions` + `/status`（已有）
- Produces: 无（组件行为变更）

- [ ] **Step 1: 写失败测试**

在 `frontend/src/components/feishu/platform-login-modal.test.tsx` 追加：

```tsx
test("import cookie posts JSON to import endpoint", async () => {
  const user = userEvent.setup();
  mockApi
    .mockResolvedValueOnce({ items: [] })
    .mockResolvedValueOnce({ saved: { douyin: 2 } });
  render(<PlatformLoginModal open onClose={() => {}} />);
  await screen.findByText("未登录");
  await user.click(findPageButton(/导入 Cookie/)!);
  const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
  expect(textarea).not.toBeNull();
  await user.type(
    textarea,
    JSON.stringify([{ name: "sessionid", value: "abc", domain: ".douyin.com" }])
  );
  await user.click(findPageButton(/保存/)!);
  await waitFor(() => {
    expect(mockApi).toHaveBeenCalledWith(
      "/api/agent/cookies/import",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          cookies: [{ name: "sessionid", value: "abc", domain: ".douyin.com" }],
        }),
      })
    );
  });
});

test("scan mode shows window-open hint instead of QR image", async () => {
  mockApi
    .mockResolvedValueOnce({ items: [] })
    .mockResolvedValueOnce({ session_id: "s1", status: "waiting_scan" })
    .mockResolvedValue({ status: "waiting_scan", detail: "" });
  render(<PlatformLoginModal open onClose={() => {}} />);
  await screen.findByText("未登录");
  const loginBtn = pageButtons().find((b) => /登录/.test(b.textContent || ""));
  await userEvent.setup().click(loginBtn!);
  expect(await screen.findByText(/浏览器窗口已弹出/)).toBeTruthy();
});
```

（若现有登录按钮文本与结构不符，读组件 JSX 后按实际文本调整；jsdom 约束：用 `findPageButton`/`querySelectorAll` 模式，不用页面级 byRole。）

- [ ] **Step 2: 运行确认失败**

Run（从 `C:\01_agent_loop_pro\frontend`）：`npm test -- src/components/feishu/platform-login-modal.test.tsx`
Expected: FAIL（无导入按钮 / 无窗口提示）

- [ ] **Step 3: 实现组件**

`frontend/src/components/feishu/platform-login-modal.tsx`：

1. `pollSession` 中删除 `/frame` 请求与 `setImage`；保留 `/status` 轮询
2. `ERROR_TEXT` 扩展：

```ts
const ERROR_TEXT: Record<string, string> = {
  platform_blocked: "平台安全验证拦截，请稍后重试",
  qr_timeout: "二维码加载超时，请点击刷新",
  browser_failed: "浏览器启动失败（无桌面环境请改用手动导入 Cookie）",
  window_closed: "登录窗口已关闭，请重新发起",
  environment_no_display: "当前环境无桌面，请使用手动导入 Cookie 登录",
};
```

3. `startScan` 后等待状态 UI：`scanStatus === "waiting_scan"` 时渲染提示卡片：

```tsx
{scanStatus === "waiting_scan" && (
  <div style={{ ... }}>
    浏览器窗口已弹出，请在弹出的窗口中扫码或完成登录
    （无桌面环境请改用手动导入 Cookie）
  </div>
)}
```

（`scanning` 区块内原二维码 `<img>` 展示删除；`image` state 及相关 set 可保留但不再使用——删干净则连同 `setImage(null)` 调用一起移除。）

4. 非扫描列表每平台行加"导入 Cookie"按钮（`importOpen` state：`"douyin" | "xiaohongshu" | null`）；展开后显示 Textarea + 平台名 + 保存按钮：

```tsx
{importOpen && (
  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
    <div style={{ fontSize: 12, color: "#8c8c8c" }}>
      在浏览器登录{platformName}后，用 Cookie-Editor 扩展导出 JSON 粘贴到这里
    </div>
    <Input.TextArea
      rows={6}
      value={importText}
      onChange={(e) => setImportText(e.target.value)}
      placeholder={'[{"name":"sessionid","value":"...","domain":".douyin.com"}]'}
    />
    <div style={{ display: "flex", gap: 8 }}>
      <Button type="primary" loading={importing} onClick={handleImport}>
        保存
      </Button>
      <Button onClick={() => setImportOpen(null)}>取消</Button>
    </div>
  </div>
)}
```

`handleImport`：

```tsx
async function handleImport() {
  if (!importOpen) return;
  setImporting(true);
  try {
    let parsed: unknown;
    try {
      parsed = JSON.parse(importText);
    } catch {
      setImportError("JSON 格式不正确，请粘贴 Cookie-Editor 导出的 JSON");
      return;
    }
    if (!Array.isArray(parsed) || parsed.length === 0) {
      setImportError("请粘贴至少一条 cookie");
      return;
    }
    const data = await api<{ saved: Record<string, number> }>(
      "/api/agent/cookies/import",
      { method: "POST", body: JSON.stringify({ cookies: parsed }), csrf: true }
    );
    const total = Object.values(data.saved).reduce((a, b) => a + b, 0);
    message.success(`已保存 ${total} 条 Cookie`);
    setImportOpen(null);
    setImportText("");
    load();
  } catch (err) {
    setImportError(err instanceof Error ? err.message : "导入失败，请重试");
  } finally {
    setImporting(false);
  }
}
```

（需要的 import：antd `Input`、`Button`——按组件现有 import 风格补齐；state：`importOpen/importText/importError/importing`。）

- [ ] **Step 4: 运行确认通过**

Run（从 `C:\01_agent_loop_pro\frontend`）：`npm test -- src/components/feishu/platform-login-modal.test.tsx`
Expected: PASS（既有 2 个 + 新增 2 个）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feishu/platform-login-modal.tsx frontend/src/components/feishu/platform-login-modal.test.tsx
git commit -m "feat: platform login - visible-window hints and manual cookie import UI"
```

---

### Task 4: 全量回归 + 重启 + 端到端

**Files:** 无新增

- [ ] **Step 1: 后端全量回归**

Run（`C:\01_agent_loop_pro\backend`）：`X:\python\anaconda\envs\01-rbac\python.exe -X utf8 -m pytest tests -q`
Expected: 全部通过或仅有已知预存失败（test_agent_blueprint_closure 等未改动模块；若涉及本计划文件必须修复）

- [ ] **Step 2: 前端全量 + 构建**

Run（`C:\01_agent_loop_pro\frontend`）：`npm test` 后 `npm run build`
Expected: 全过 + build 成功

- [ ] **Step 3: 重启服务**

```powershell
$all = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "web_renderer|agent_worker" }
foreach ($p in $all) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
Start-Process -FilePath "X:\python\anaconda\envs\01-rbac\python.exe" -ArgumentList "-m","app.workers.web_renderer" -WorkingDirectory "C:\01_agent_loop_pro\backend" -RedirectStandardOutput "$env:TEMP\opencode\renderer_out.log" -RedirectStandardError "$env:TEMP\opencode\renderer_err.log" -WindowStyle Hidden
Start-Process -FilePath "X:\python\anaconda\envs\01-rbac\python.exe" -ArgumentList "-m","app.workers.agent_worker" -WorkingDirectory "C:\01_agent_loop_pro\backend" -RedirectStandardOutput "$env:TEMP\opencode\worker_out.log" -RedirectStandardError "$env:TEMP\opencode\worker_err.log" -WindowStyle Hidden
```

验证：renderer health 200（`http://127.0.0.1:9001/health`）；两个 worker 进程存活。

- [ ] **Step 4: 端到端冒烟**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -X utf8 "$env:TEMP\opencode\e2e_note.py"`
Expected: 不再崩溃（无 cookie 时 login_required 降级；导入 cookie 后 platform_total 随入库增长）

- [ ] **Step 5: Commit（如无代码改动则跳过）**

---

## Self-Review

**Spec 覆盖**：
- A 后端 import 端点（校验/白名单/分组/加密存储）→ Task 1 ✓
- A 前端导入表单（JSON 粘贴/指引/保存）→ Task 3 ✓
- B 可见窗口（headless=False）→ Task 2 ✓
- B window_closed 检测 → Task 2 ✓
- B TTL 900 → Task 2 ✓
- B 无桌面提示（browser_failed 文案含手动导入指引）→ Task 3（前端文案——后端保持 browser_failed，spec §3.2 的 environment_no_display 收敛为前端文案方案，实现一致）✓
- 前端移除 /frame + 状态提示 → Task 3 ✓
- 回归 + 重启 + 端到端 → Task 4 ✓

**占位符扫描**：无 TBD/TODO；Task 2 Step 1 的 monkeypatch 目标有明确指引（读代码后按实际调整——因 `_default_browser_factory` 的函数内 import 需确认模块级名字）；Task 3 测试的按钮文本有指引（读组件 JSX 后按实际调整）。

**类型一致性**：`cookies_to_string`（Task 1 消费）与 Task 2 的 `_export_cookie` 同一函数；`DOMAIN_BY_PLATFORM` 键 douyin/xiaohongshu 在 Task 1 分组与存储一致；前端 `{saved: Record<string, number>}` 与 Task 1 响应 `{saved: {platform: count}}` 一致。
