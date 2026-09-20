# 账号退出/换号功能实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 飞书/小红书/抖音账号支持退出登录与换号。

**Architecture:** 后端新增 `DELETE /api/feishu/connection`（尽力调飞书 revoke + 删除本地 token）；前端飞书已连接按钮变"退出飞书"（Popconfirm）；平台登录弹窗已登录行加"退出登录"（复用已有 `DELETE /api/agent/cookies/{domain}`）。

**Tech Stack:** FastAPI + pytest；React 19 + AntD 6 + vitest

## Global Constraints

- 后端 Python：conda `01-rbac`（X:\python\anaconda\envs\01-rbac\python.exe）；测试前设置独立 `TEST_DATABASE_URL`（各任务指定库名）
- revoke 是尽力而为：失败仅日志，绝不阻塞本地删除
- 前端测试 jsdom 病理约束：禁止对完整页面做 byRole/getAllByRole 查询；用 `document.querySelectorAll` + textContent 匹配；antd Popconfirm/Modal 确认按钮经 portal 渲染，用 `document.querySelector(".ant-popconfirm-buttons .ant-btn-primary")`（或实际类名，先跑通再定）点击
- git 纪律：提交前 `git status --short` 核对暂存区只含本任务列出的文件；精确路径 `git add`，绝对禁止 `git add -A`
- 中文文案：退出飞书 / 退出登录 / 已退出飞书 / 已退出登录 / 退出失败，请重试

---

### Task 1: 后端飞书断开端点

**Files:**
- Modify: `backend/app/services/feishu/client.py`（加 revoke_token）
- Modify: `backend/app/api/feishu.py`（加 DELETE /connection）
- Test: `backend/tests/test_feishu_disconnect.py`（新建）

**Interfaces:**
- Produces: `DELETE /api/feishu/connection` → `{"connected": False}`（Task 2 前端依赖）

- [ ] **Step 1: 写失败测试**（创建 `backend/tests/test_feishu_disconnect.py`，参考 `tests/test_files_preview.py` 的 fixture 模式：`anyio_backend`、`admin_client`、`test_engine`；插入 FeishuToken 用 `encrypt_token`/`derive_token_key`）

```python
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.feishu_token import FeishuToken
from app.services.feishu.crypto import derive_token_key, encrypt_token

_FEISHU_APP_ID = "cli_test123"
_FEISHU_APP_SECRET = "test_secret"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _insert_token(test_engine, owner: uuid.UUID) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    key = derive_token_key(settings.feishu_token_encryption_key or settings.jwt_secret)
    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        s.add(
            FeishuToken(
                owner_user_id=owner,
                access_token=encrypt_token("fake_access_token", key),
                refresh_token=encrypt_token("fake_refresh_token", key),
                expires_at=datetime.now(UTC) + timedelta(hours=2),
                open_id="ou_fake123",
            )
        )
        await s.commit()


async def _first_user(test_engine) -> uuid.UUID:
    from app.models.rbac import User
    from sqlalchemy import select

    async with async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)() as s:
        owner = (await s.scalars(select(User).limit(1))).one()
        return owner.id


@pytest.mark.asyncio
async def test_disconnect_removes_token_and_updates_status(admin_client, test_engine, monkeypatch) -> None:
    from app.services.feishu import client as feishu_client

    owner_id = await _first_user(test_engine)
    await _insert_token(test_engine, owner_id)

    monkeypatch.setattr(feishu_client.FeishuClient, "revoke_token", lambda self, token: None)

    resp = await admin_client.delete("/api/feishu/connection")
    assert resp.status_code == 200
    assert resp.json()["data"]["connected"] is False

    status = await admin_client.get("/api/feishu/status")
    assert status.json()["data"]["connected"] is False


@pytest.mark.asyncio
async def test_disconnect_without_token_is_idempotent(admin_client, test_engine) -> None:
    resp = await admin_client.delete("/api/feishu/connection")
    assert resp.status_code == 200
    assert resp.json()["data"]["connected"] is False


@pytest.mark.asyncio
async def test_disconnect_removes_local_token_when_revoke_fails(admin_client, test_engine, monkeypatch) -> None:
    from app.services.feishu import client as feishu_client

    owner_id = await _first_user(test_engine)
    await _insert_token(test_engine, owner_id)

    def _boom(self, token):
        raise RuntimeError("feishu down")

    monkeypatch.setattr(feishu_client.FeishuClient, "revoke_token", _boom)

    resp = await admin_client.delete("/api/feishu/connection")
    assert resp.status_code == 200
    status = await admin_client.get("/api/feishu/status")
    assert status.json()["data"]["connected"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run（工作目录 `backend`）:
```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_disc_t1"; python -X utf8 -m pytest tests/test_feishu_disconnect.py -q
```
Expected: FAILED（路由 405/404）

- [ ] **Step 3: 实现 revoke_token**（`backend/app/services/feishu/client.py`，OAuth 小节内、`refresh_access_token` 之后）

```python
    async def revoke_token(self, access_token: str) -> dict:
        """尽力吊销 user_access_token；失败由调用方吞掉（本地删除不依赖飞书侧成功）。"""
        return await self._post(
            "/authen/v1/revoke",
            json={
                "app_id": self.settings.feishu_app_id,
                "app_secret": self.settings.feishu_app_secret,
                "token": access_token,
            },
        )
```

- [ ] **Step 4: 实现断开端点**（`backend/app/api/feishu.py`，`/status` 之后追加；文件头补 `import logging` 与 `logger = logging.getLogger("app.feishu")`，补 `from app.services.feishu.crypto import decrypt_token`——先确认 crypto.py 有 decrypt_token，没有则用 decrypt 对应函数名）

```python
@router.delete("/connection")
async def feishu_disconnect(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    token = await db.scalar(
        select(FeishuToken).where(FeishuToken.owner_user_id == current_user.id)
    )
    if token is not None:
        settings = get_settings()
        key = derive_token_key(settings.feishu_token_encryption_key or settings.jwt_secret)
        client = FeishuClient()
        try:
            await client.revoke_token(decrypt_token(token.access_token, key))
        except Exception:
            logger.warning("feishu_revoke_failed", exc_info=True)
        await db.delete(token)
        await db.commit()
    return success(request, {"connected": False})
```

- [ ] **Step 5: 跑测试确认通过**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_disc_t1"; python -X utf8 -m pytest tests/test_feishu_disconnect.py -q
```
Expected: 全部 PASS（3 个）

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/feishu/client.py backend/app/api/feishu.py backend/tests/test_feishu_disconnect.py
git commit -m "feat: add feishu account disconnect endpoint"
```

---

### Task 2: 前端飞书退出按钮

**Files:**
- Modify: `frontend/src/components/feishu/feishu-connect.tsx`
- Test: `frontend/src/components/feishu/feishu-connect.test.tsx`（新建）

**Interfaces:**
- Consumes: `DELETE /api/feishu/connection`（Task 1）
- Produces: 无

- [ ] **Step 1: 写失败测试**（创建 `frontend/src/components/feishu/feishu-connect.test.tsx`）

```tsx
import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: mockApi };
});

import FeishuConnect from "@/components/feishu/feishu-connect";

function pageButtons() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
}

function findPageButton(label: RegExp) {
  return pageButtons().find((b) => label.test(b.textContent || ""));
}

describe("FeishuConnect", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  test("shows connect button when disconnected", async () => {
    mockApi.mockResolvedValue({ connected: false });
    render(<FeishuConnect />);
    expect(await screen.findByText("连接飞书")).toBeTruthy();
  });

  test("shows disconnect button when connected", async () => {
    mockApi.mockResolvedValue({ connected: true });
    render(<FeishuConnect />);
    expect(await screen.findByText("退出飞书")).toBeTruthy();
  });

  test("disconnect calls DELETE and flips back to connect", async () => {
    const user = userEvent.setup();
    mockApi
      .mockResolvedValueOnce({ connected: true })
      .mockResolvedValueOnce({ connected: false });
    render(<FeishuConnect />);
    await screen.findByText("退出飞书");

    await user.click(findPageButton(/退出飞书/)!);
    const confirmBtn = document.querySelector(".ant-popconfirm-buttons .ant-btn-primary") as HTMLButtonElement;
    expect(confirmBtn).not.toBeNull();
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/feishu/connection",
        expect.objectContaining({ method: "DELETE" })
      );
    });
    expect(await screen.findByText("连接飞书")).toBeTruthy();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run（工作目录 `frontend`）: `npx vitest run src/components/feishu/feishu-connect.test.tsx`
Expected: FAIL（组件无"退出飞书"）

- [ ] **Step 3: 实现**（`frontend/src/components/feishu/feishu-connect.tsx`）

import 区补：`import { DisconnectOutlined } from "@ant-design/icons";`、`import { Button, Popconfirm, message } from "antd";`（原为 `Button, message`）

补 handler 与 connected 分支（`handleConnect` 之后；connected 渲染替换为）：

```tsx
  async function handleDisconnect() {
    setLoading(true);
    try {
      await api("/api/feishu/connection", { method: "DELETE", csrf: true });
      setConnected(false);
      message.success("已退出飞书");
    } catch {
      message.error("退出失败，请重试");
    } finally {
      setLoading(false);
    }
  }

  return connected ? (
    <Popconfirm title="退出飞书账号？" description="退出后可连接其他飞书账号" onConfirm={handleDisconnect}>
      <Button icon={<DisconnectOutlined />} loading={loading}>
        退出飞书
      </Button>
    </Popconfirm>
  ) : (
    <Button icon={<LinkOutlined />} onClick={handleConnect} loading={loading}>
      连接飞书
    </Button>
  );
```

（原有 CheckCircleOutlined import 若不再使用则删除。）

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/feishu/feishu-connect.test.tsx`
Expected: 全部 PASS（3 个）。若 Popconfirm 确认按钮类名不对（antd 6 差异），先运行看真实 DOM 类名再调整测试。

- [ ] **Step 5: eslint**

Run: `npx eslint src/components/feishu/feishu-connect.tsx src/components/feishu/feishu-connect.test.tsx`
Expected: 0 errors（既有基线问题除外）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/feishu/feishu-connect.tsx frontend/src/components/feishu/feishu-connect.test.tsx
git commit -m "feat: add feishu disconnect button"
```

---

### Task 3: 前端平台退出按钮

**Files:**
- Modify: `frontend/src/components/feishu/platform-login-modal.tsx`
- Test: `frontend/src/components/feishu/platform-login-modal.test.tsx`（新建）

**Interfaces:**
- Consumes: `DELETE /api/agent/cookies/{domain}`（已有）
- Produces: 无

- [ ] **Step 1: 写失败测试**（创建 `frontend/src/components/feishu/platform-login-modal.test.tsx`）

```tsx
import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: mockApi };
});

import PlatformLoginModal from "@/components/feishu/platform-login-modal";

function pageButtons() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
}

function findPageButton(label: RegExp) {
  return pageButtons().find((b) => label.test(b.textContent || ""));
}

describe("PlatformLoginModal", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  test("shows logout button for logged-in platform", async () => {
    mockApi.mockResolvedValue({
      items: [{ domain: "www.douyin.com", cookie_string: "x" }],
    });
    render(<PlatformLoginModal open onClose={() => {}} />);
    expect(await screen.findByText("已登录")).toBeTruthy();
    expect(findPageButton(/退出登录/)).toBeTruthy();
  });

  test("logout calls DELETE cookie endpoint and refreshes state", async () => {
    const user = userEvent.setup();
    mockApi
      .mockResolvedValueOnce({
        items: [{ domain: "www.douyin.com", cookie_string: "x" }],
      })
      .mockResolvedValueOnce({ deleted: true })
      .mockResolvedValueOnce({ items: [] });

    render(<PlatformLoginModal open onClose={() => {}} />);
    await screen.findByText("已登录");

    await user.click(findPageButton(/退出登录/)!);
    const confirmBtn = document.querySelector(".ant-popconfirm-buttons .ant-btn-primary") as HTMLButtonElement;
    expect(confirmBtn).not.toBeNull();
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/agent/cookies/www.douyin.com",
        expect.objectContaining({ method: "DELETE" })
      );
    });
    expect(await screen.findByText("未登录")).toBeTruthy();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/feishu/platform-login-modal.test.tsx`
Expected: FAIL（无"退出登录"按钮）

- [ ] **Step 3: 实现**（`frontend/src/components/feishu/platform-login-modal.tsx`）

import 区补：`import { Popconfirm } from "antd";`（Modal 行）、`import { LogoutOutlined } from "@ant-design/icons";`

补 handler（`handleRetry` 之后）：

```tsx
  async function handleLogout(domain: string) {
    try {
      await api(`/api/agent/cookies/${domain}`, { method: "DELETE", csrf: true });
      message.success("已退出登录");
      load();
    } catch {
      message.error("退出失败，请重试");
    }
  }
```

PLATFORMS 行内按钮组（现有"重新扫码" Button 前加，`logged` 为 true 时渲染）：

```tsx
                  {logged && (
                    <Popconfirm title="退出登录？" description="退出后可扫码登录其他账号" onConfirm={() => handleLogout(p.domain)}>
                      <Button icon={<LogoutOutlined />}>退出登录</Button>
                    </Popconfirm>
                  )}
                  <Button
                    type={logged ? "default" : "primary"}
                    icon={<QrcodeOutlined />}
                    onClick={() => startScan(p.key)}
                  >
                    {logged ? "重新扫码" : "扫码登录"}
                  </Button>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/components/feishu/platform-login-modal.test.tsx`
Expected: 全部 PASS（2 个）。若 Popconfirm 确认按钮类名不对，先运行看真实 DOM 类名再调整。

- [ ] **Step 5: eslint**

Run: `npx eslint src/components/feishu/platform-login-modal.tsx src/components/feishu/platform-login-modal.test.tsx`
Expected: 0 errors（既有基线问题除外）

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/feishu/platform-login-modal.tsx frontend/src/components/feishu/platform-login-modal.test.tsx
git commit -m "feat: add platform account logout buttons"
```

---

### Task 4: 回归验证

**Files:** 无代码改动

- [ ] **Step 1: 后端相关测试**

```
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_disc_final"; python -X utf8 -m pytest tests/test_feishu_disconnect.py tests/test_feishu_oauth.py tests/test_feishu_crypto.py tests/test_feishu_service.py tests/test_agent_cookies.py -q
```
Expected: 全部 PASS

- [ ] **Step 2: 前端相关测试**

Run（`frontend`）: `npx vitest run src/components/feishu`
Expected: 全部 PASS

- [ ] **Step 3: 汇报**

汇总提交 hash 与回归结果。
