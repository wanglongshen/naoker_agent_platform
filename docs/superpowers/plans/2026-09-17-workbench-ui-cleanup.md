# 工作台界面整理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 6 项工作台界面整理：下线方案中心、侧栏排序、DSH 设置常显、清理测试对话并播种专业示例对话、统一顶栏、DSH 工作区占满内容区。

**Architecture:** 前端只做局部改动（侧栏菜单数组、统一顶栏组件、工作区深链）；DSH 会话清理与播种走一个后端脚本（直接操作 DSH home 的会话目录 + `dsh_sessions` 同步表，播种用 headless 真跑）；DSH 布局修正走 client 插件注入 CSS（与现有侧栏隐藏同一机制，先用探针测量再改）。

**Tech Stack:** Next.js + AntD + vitest；Python + SQLAlchemy async + pytest；TypeScript + tsdown + vitest（DSH connector 插件）。

**Spec:** `docs/superpowers/specs/2026-09-17-workbench-ui-cleanup-design.md`

## Global Constraints

- 前端命令在 `C:\01_agent_loop_pro\frontend` 下执行；后端命令在 `C:\01_agent_loop_pro\backend` 下执行，Python 一律用 `X:\python\anaconda\envs\01-rbac\python.exe`（PowerShell 语法，不要用 `&&`）。
- 插件命令在 `C:\01_agent_loop_pro\dsh-platform\packages\server-connector` 下执行（`pnpm test` / `pnpm build`）。
- 提交时**只 add 本任务列出的路径**；提交前用 `git diff --cached --name-only` 核对（仓库里有大量他人未跟踪/已暂存文件，绝不用 `git add -A`/`.`）。
- 顶栏统一方案 = spec 方案 A：单一顶栏（品牌区 + 右侧用户下拉），飞书连接与平台登录收进下拉，**功能不丢**。
- 后端任务链（`/api/task-chain`、worker、数据表）**不删**，只移除前台入口。
- 删除 DSH 会话的范围严格限定为 `admin` 自己的 home；不触碰其它用户目录。
- DSH 工作区布局修正**先测量后修改**，不改 DSH 本体。
- 前端测试基线：`npx vitest run <file>`；已知存在与本轮无关的历史失败用例，只看目标文件的结果。

---

### Task 1: 侧栏整理（顺序 / DSH 设置常显 / 移除方案中心入口）

**Files:**
- Modify: `frontend/src/components/layout/app-sidebar.tsx`
- Modify: `frontend/src/lib/copy.ts`（删除 `navigation.generations` 键）
- Delete: `frontend/src/app/(dashboard)/generations/page.tsx`、`frontend/src/components/generations/**`（确认无其它引用后）
- Test: `frontend/src/components/layout/app-sidebar.test.tsx`

**Interfaces:**
- Consumes: `dshBridgeStore.send`、`copy.navigation.*`、`hasPermission/isSuperAdmin`
- Produces: 侧栏菜单顺序 `我的文件 → 账户 → 对话审计 → 文件管理 → 知识库管理 → 用户管理 → 角色管理 → DSH 设置`；DSH 设置项在任何页面/实例状态都渲染，点击执行 `router.push("/agent?settings=1")`

- [ ] **Step 1: 先确认 `components/generations/**` 无其它引用**

Run: `Select-String -Path frontend\src -Include *.ts,*.tsx -Pattern "components/generations" -Recurse | ForEach-Object { "$($_.Filename):$($_.LineNumber)" }`
Expected: 只有 `(dashboard)/generations/page.tsx` 及其同目录测试引用；如有其它引用则保留被引用文件

- [ ] **Step 2: 写失败测试（追加到 `app-sidebar.test.tsx`）**

```tsx
  it("知识库管理紧跟在文件管理之后", async () => {
    renderSidebar({ roles: [{ code: "super_admin", name: "超级管理员" }], permissions: ["user:read", "role:read", "file:admin_view"] });
    await screen.findByText("文件管理");
    const items = Array.from(document.querySelectorAll(".sidebar-management .ant-menu-item"));
    const labels = items.map((item) => item.textContent ?? "");
    const filesIndex = labels.findIndex((text) => text.includes("文件管理"));
    const knowledgeIndex = labels.findIndex((text) => text.includes("知识库管理"));
    expect(knowledgeIndex).toBe(filesIndex + 1);
  });

  it("不再渲染方案中心菜单项", () => {
    renderSidebar({ roles: [{ code: "super_admin", name: "超级管理员" }], permissions: ["user:read", "role:read", "file:admin_view"] });
    expect(screen.queryByText("方案中心")).toBeNull();
  });

  it("实例未运行时也显示 DSH 设置，点击跳转 /agent?settings=1", async () => {
    const push = vi.fn();
    mockRouterPush(push);
    renderSidebar({ roles: [{ code: "super_admin", name: "超级管理员" }], permissions: [] });
    const button = await screen.findByRole("button", { name: "DSH 设置" });
    button.click();
    expect(push).toHaveBeenCalledWith("/agent?settings=1");
  });
```

（沿用文件内已有的渲染辅助函数与 mock 名；若没有 `mockRouterPush`，用文件里已有的 `next/navigation` mock 方式实现。）

- [ ] **Step 3: 运行测试确认失败**

Run: `npx vitest run src/components/layout/app-sidebar.test.tsx`
Expected: 3 个新用例 FAIL

- [ ] **Step 4: 实现侧栏改动**

`app-sidebar.tsx` 的 `systemItems` 数组改为（顺序即渲染顺序）：

```tsx
  const systemItems: MenuProps["items"] = [
    {
      key: "/agent/files",
      icon: <FolderOpenOutlined />,
      label: <Link href="/agent/files" onClick={onNavigate}>{copy.navigation.myFiles}</Link>,
    },
    {
      key: "/account/points",
      icon: <WalletOutlined />,
      label: <Link href="/account/points" onClick={onNavigate}>账户</Link>,
    },
    ...(isSuperAdmin(user)
      ? [{
          key: "/agent/audit",
          icon: <AuditOutlined />,
          label: <Link href="/agent/audit" onClick={onNavigate}>{copy.navigation.agentAudit}</Link>,
        }]
      : []),
    ...(hasPermission({ ...user, permissions: menuPerms }, FILE_ADMIN_VIEW)
      ? [{
          key: "/files",
          icon: <FolderOpenOutlined />,
          label: <Link href="/files" onClick={onNavigate}>{copy.navigation.files}</Link>,
        }]
      : []),
    ...(isSuperAdmin(user)
      ? [{
          key: "/knowledge",
          icon: <BookOutlined />,
          label: <Link href="/knowledge" onClick={onNavigate}>{copy.navigation.knowledge}</Link>,
        }]
      : []),
    ...(hasPermission({ ...user, permissions: menuPerms }, USER_READ)
      ? [{
          key: "/users",
          icon: <TeamOutlined />,
          label: <Link href="/users" onClick={onNavigate}>{copy.navigation.users}</Link>,
        }]
      : []),
    ...(hasPermission({ ...user, permissions: menuPerms }, ROLE_READ)
      ? [{
          key: "/roles",
          icon: <SafetyCertificateOutlined />,
          label: <Link href="/roles" onClick={onNavigate}>{copy.navigation.roles}</Link>,
        }]
      : []),
    {
      key: "dsh-settings",
      icon: <SettingOutlined />,
      label: (
        <button
          type="button"
          className="sidebar-settings-link"
          onClick={() => router.push("/agent?settings=1")}
        >
          DSH 设置
        </button>
      ),
    },
  ];
```

同时：删除 `RocketOutlined` 导入（不再使用）、删除 `selectedKey` 里的 `/generations` 分支（`app-sidebar.tsx:112-113`）、删除 `dshBridgeStore` 的 `send` 依赖（不再直接发命令；`bridge` 快照仍供会话列表使用）。

- [ ] **Step 5: 删除方案中心页面与组件**

```powershell
git rm -r "frontend/src/app/(dashboard)/generations" frontend/src/components/generations
```
并在 `frontend/src/lib/copy.ts` 删除 `navigation.generations` 键（先 grep 确认无其它引用）。

- [ ] **Step 6: 运行测试确认通过**

Run: `npx vitest run src/components/layout/app-sidebar.test.tsx`
Expected: 全部 PASS（含 3 个新用例）

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/layout/app-sidebar.tsx frontend/src/components/layout/app-sidebar.test.tsx frontend/src/lib/copy.ts
git commit -m "feat(ui): 侧栏排序/DSH设置常显/下线方案中心入口"
```

---

### Task 2: `/agent?settings=1` 深链

**Files:**
- Modify: `frontend/src/components/dsh/dsh-workspace.tsx`
- Test: `frontend/src/components/dsh/dsh-workspace.test.tsx`

**Interfaces:**
- Consumes: `useDshBridge().send`、`ready`、桥命令 `open-settings`
- Produces: 进入 `/agent?settings=1` 时，在 `ready` 后发送 `{v:1,type:"cmd",action:"open-settings"}` 并清除 URL 参数

- [ ] **Step 1: 写失败测试（追加到 `dsh-workspace.test.tsx`）**

```tsx
  it("?settings=1 在桥就绪后发送 open-settings 并清掉参数", async () => {
    const send = vi.fn();
    mockBridge({ ready: true, send });
    window.history.replaceState(null, "", "/agent?settings=1");
    render(<DshWorkspace />);
    await waitFor(() => expect(send).toHaveBeenCalledWith({ v: 1, type: "cmd", action: "open-settings" }));
    expect(window.location.search).toBe("");
  });
```

（沿用文件内已有的 bridge mock 方式与渲染辅助。）

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/components/dsh/dsh-workspace.test.tsx`
Expected: 新用例 FAIL

- [ ] **Step 3: 实现**

在 `dsh-workspace.tsx` 处理 `new=1` 的同一段 `useEffect`（`dsh-workspace.tsx:116-121`）后追加：

```tsx
    if (params.get("settings") === "1") {
      send({ v: 1, type: "cmd", action: "open-settings" });
      const next = new URL(window.location.href);
      next.searchParams.delete("settings");
      window.history.replaceState(null, "", next);
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/components/dsh/dsh-workspace.test.tsx`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/dsh/dsh-workspace.tsx frontend/src/components/dsh/dsh-workspace.test.tsx
git commit -m "feat(ui): /agent?settings=1 深链打开 DSH 设置"
```

---

### Task 3: 统一顶栏（方案 A）

**Files:**
- Modify: `frontend/src/components/feishu/feishu-connect.tsx`（拆出受控弹窗 + 状态 hook）
- Modify: `frontend/src/components/layout/app-header.tsx`
- Modify: `frontend/src/app/(agent)/layout.tsx`
- Delete: `frontend/src/components/layout/conversation-top-bar.tsx`
- Test: `frontend/src/components/layout/app-header.test.tsx`（新建）、`frontend/src/components/feishu/feishu-connect.test.tsx`（改造）

**Interfaces:**
- Consumes: `/api/feishu/status`、`PlatformLoginModal`、`resolveAvatarUrl`
- Produces:
  - `useFeishuConnection(): { connected: boolean; refresh: () => Promise<void> }`
  - `FeishuConnectModal({ open, onClose, connected, onConnectedChange }: { open: boolean; onClose: () => void; connected: boolean; onConnectedChange: (v: boolean) => void })`
  - `AppHeader({ user, onMenuToggle? })`：渲染 `.app-header`（品牌区 + 右侧用户下拉），下拉含 `飞书：已连接/连接飞书`、`平台登录`、`个人资料`、`退出登录`

- [ ] **Step 1: 写失败测试（新建 `app-header.test.tsx`）**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AppHeader from "./app-header";

const USER = {
  id: "u-1",
  username: "admin",
  display_name: "超级管理员",
  avatar_url: null,
  roles: [],
  permissions: [],
} as never;

describe("AppHeader", () => {
  it("渲染品牌区与用户区", () => {
    render(<AppHeader user={USER} />);
    expect(screen.getByText("脑壳工作台")).toBeTruthy();
    expect(screen.getByText("超级管理员")).toBeTruthy();
  });

  it("用户下拉包含飞书与平台登录入口", async () => {
    render(<AppHeader user={USER} />);
    screen.getByRole("button", { name: /超级管理员/ }).click();
    expect(await screen.findByText(/飞书|连接飞书/)).toBeTruthy();
    expect(await screen.findByText("平台登录")).toBeTruthy();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/components/layout/app-header.test.tsx`
Expected: FAIL（当前 AppHeader 无品牌区、无飞书/平台登录项）

- [ ] **Step 3: 重构 `feishu-connect.tsx`**

把组件拆成受控弹窗 + 状态 hook（保留原有全部业务逻辑：配置列表、同步开关、断开、URL 参数提示）：

```tsx
export function useFeishuConnection(): { connected: boolean; refresh: () => Promise<void> } {
  const [connected, setConnected] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const data = await api<{ connected: boolean }>("/api/feishu/status");
      setConnected(data.connected);
    } catch {
      setConnected(false);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return { connected, refresh };
}

export default function FeishuConnectModal({
  open, onClose, connected, onConnectedChange,
}: {
  open: boolean;
  onClose: () => void;
  connected: boolean;
  onConnectedChange: (value: boolean) => void;
}) {
  // 原 Modal 内部实现不变，仅：
  // ① 移除外部触发按钮（connected ? 飞书已连接 : 连接飞书）
  // ② open / onCancel 改为 props
  // ③ 断开成功后调用 onConnectedChange(false)
  // ④ 原 useEffect 中的 ?feishu=connected 提示逻辑保留
}
```

- [ ] **Step 4: 扩展 `app-header.tsx`**

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Avatar, Button, Dropdown, Tooltip } from "antd";
import { LinkOutlined, CheckOutlined, LogoutOutlined, QrcodeOutlined, UserOutlined } from "@ant-design/icons";
import { api } from "@/lib/api";
import { resolveAvatarUrl } from "@/lib/avatar";
import { copy, PRODUCT_NAME } from "@/lib/copy";
import type { CurrentUser } from "@/types/auth";
import FeishuConnectModal, { useFeishuConnection } from "@/components/feishu/feishu-connect";
import PlatformLoginModal from "@/components/feishu/platform-login-modal";

export default function AppHeader({ user, onMenuToggle }: AppHeaderProps) {
  const router = useRouter();
  const { connected, refresh } = useFeishuConnection();
  const [feishuOpen, setFeishuOpen] = useState(false);
  const [cookieModalOpen, setCookieModalOpen] = useState(false);

  async function handleLogout() {
    try { await api("/api/auth/logout", { method: "POST" }); } catch { /* proceed */ }
    router.push("/login");
  }

  return (
    <header className="app-header">
      <div className="header-context">
        <Button type="text" icon={<MenuOutlined />} onClick={onMenuToggle} aria-label="Open navigation" className="mobile-only" />
        <span className="top-bar-logo" aria-hidden="true">脑</span>
        <span className="header-product-name">{PRODUCT_NAME}</span>
      </div>
      <div className="header-account">
        <Dropdown
          menu={{
            items: [
              {
                key: "feishu",
                icon: connected ? <CheckOutlined /> : <LinkOutlined />,
                label: connected ? "飞书已连接" : "连接飞书",
                onClick: () => setFeishuOpen(true),
              },
              {
                key: "platform-login",
                icon: <QrcodeOutlined />,
                label: "平台登录",
                onClick: () => setCookieModalOpen(true),
              },
              { type: "divider" },
              { key: "profile", icon: <UserOutlined />, label: "个人资料", onClick: () => router.push("/settings/profile") },
              { key: "logout", icon: <LogoutOutlined />, label: copy.navigation.logout, onClick: handleLogout },
            ],
          }}
          trigger={["click"]}
        >
          <button type="button" className="top-bar-user-btn" aria-label={`${user.display_name} 账户菜单`}>
            <Avatar size={28} src={resolveAvatarUrl(user.avatar_url)} icon={user.avatar_url ? undefined : <UserOutlined />} className="header-avatar">
              {user.display_name?.[0]}
            </Avatar>
            <span className="header-user-name">{user.display_name}</span>
          </button>
        </Dropdown>
      </div>
      <FeishuConnectModal open={feishuOpen} onClose={() => setFeishuOpen(false)} connected={connected} onConnectedChange={(v) => { void refresh(); }} />
      <PlatformLoginModal open={cookieModalOpen} onClose={() => setCookieModalOpen(false)} />
    </header>
  );
}
```

- [ ] **Step 5: `(agent)` 组改用统一顶栏并删除旧顶栏**

`frontend/src/app/(agent)/layout.tsx` 改为：

```tsx
"use client";

import AuthenticatedPage from "@/components/auth/authenticated-page";
import AppShell from "@/components/layout/app-shell";
import AppHeader from "@/components/layout/app-header";

export default function AgentLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthenticatedPage>
      {(user) => (
        <AppShell currentUser={user}>
          <AppHeader user={user} />
          <div className="agent-route-content">{children}</div>
        </AppShell>
      )}
    </AuthenticatedPage>
  );
}
```

```powershell
git rm frontend/src/components/layout/conversation-top-bar.tsx
```

在 `agent-globals.css` 中把 `.conversation-top-bar` 相关样式（`:3004-3047`）迁移为 `.app-header .header-product-name` / `.app-header .top-bar-user-btn` 等（`.app-header` 的橙色渐变已存在于 `agent-globals.css:3048-3053`，无需改动），并删除 `.conversation-top-bar` 选择器。

- [ ] **Step 6: 更新飞书组件测试并运行**

把 `feishu-connect.test.tsx` 改为渲染 `FeishuConnectModal`（传 `open`、`onClose`、`connected`、`onConnectedChange`），断言不变（连接状态显示、点击登录跳转）。

Run: `npx vitest run src/components/layout/app-header.test.tsx src/components/feishu/feishu-connect.test.tsx src/components/layout/dashboard-shell.test.tsx`
Expected: 全部 PASS

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/feishu/feishu-connect.tsx frontend/src/components/feishu/feishu-connect.test.tsx frontend/src/components/layout/app-header.tsx frontend/src/components/layout/app-header.test.tsx "frontend/src/app/(agent)/layout.tsx" frontend/src/app/agent-globals.css
git commit -m "feat(ui): 统一顶栏（飞书与平台登录收入用户下拉）"
```

---

### Task 4: DSH 会话清理与专业示例对话

**Files:**
- Create: `backend/scripts/dsh_sessions_reset.py`
- Test: `backend/tests/test_dsh_sessions_reset.py`

**Interfaces:**
- Consumes: `iter_sessions(home)`（`app/services/dsh/session_sync.py:98`）、`DshSession` 模型、`Settings.dsh_home_root_path`、`DshHeadlessExecutor`（`app/services/dsh/executor.py`）
- Produces: `clear_sessions(home: Path) -> int`（删除会话目录数）、`clear_sync_rows(db, user_id) -> int`、`seed_sessions(home, user_id, prompts) -> list[str]`

- [ ] **Step 1: 先做删除路径与标题行为的小验证（spike，不改代码）**

1. 确认会话落盘结构：`Get-ChildItem backend\var\dsh\<admin-uid>\sessions -Directory | Select-Object -First 5`
2. 确认 DSH 是否会缓存会话索引（决定删除目录后是否需要重启实例才生效）：在 `deepseek-harness/packages/session/**` 与 `apps/web/**` 里检索会话列表的数据来源；若列表直接扫描 `sessions/**` 目录，则删除目录即可。
3. 用一条 headless 会话验证标题行为：
   `X:\python\anaconda\envs\01-rbac\python.exe -m app.services.dsh.executor`（或用现有 executor 的 `run_task`）跑一句测试问题 → 检查生成的会话文件里是否有 `session/title` 事件。
   - 有标题 → 播种直接用 headless。
   - 无标题 → 改用 `--profile web` 重试；仍无标题则在播种后用「注入 `session/title` 事件」的方式补标题（事件格式见 `session_sync.py:27-29` 注释）。

把三条结论写进 `dsh-platform/NOTES.md` 的新小节（供后续维护）。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_dsh_sessions_reset.py
import json
from pathlib import Path

from scripts.dsh_sessions_reset import clear_sessions


def _write_session(home: Path, session_id: str) -> Path:
    session_dir = home / "sessions" / session_id
    session_dir.mkdir(parents=True)
    payload = "\n".join(
        [
            json.dumps({"type": "session", "version": 1, "id": session_id, "createdAt": 1700000000000}),
            json.dumps({"type": "turn/start", "time": 1700000001000, "data": {"turn": 1}}),
        ]
    )
    (session_dir / "session.jsonl").write_text(payload, encoding="utf-8")
    return session_dir


def test_clear_sessions_removes_all_session_dirs(tmp_path):
    home = tmp_path / "home"
    _write_session(home, "s-1")
    _write_session(home, "s-2")
    assert clear_sessions(home) == 2
    assert list((home / "sessions").iterdir()) == []


def test_clear_sessions_is_idempotent_on_missing_root(tmp_path):
    assert clear_sessions(tmp_path / "nope") == 0
```

- [ ] **Step 3: 运行测试确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_dsh_sessions_reset.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.dsh_sessions_reset'`

- [ ] **Step 4: 实现脚本**

```python
# backend/scripts/dsh_sessions_reset.py
"""清理某用户 DSH home 的全部会话，并可播种专业示例对话。

用法（在 backend 目录下运行）：
    python -m scripts.dsh_sessions_reset --user-id <uuid> --dry-run
    python -m scripts.dsh_sessions_reset --user-id <uuid> --clear
    python -m scripts.dsh_sessions_reset --user-id <uuid> --seed
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import uuid
from pathlib import Path

from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models.dsh import DshSession
from app.services.dsh.session_sync import iter_sessions

SEED_PROMPTS = [
    "为新品制定一份抖音千川投放策略，包含出价与预算分配",
    "短视频内容选题与脚本框架怎么设计？",
    "直播间转化率提升的关键动作有哪些？",
    "广告投放中哪些表述属于平台规则与广告法风险？",
    "拆解一个生鲜类目的经营案例，提炼可复用打法",
]


def clear_sessions(home: Path) -> int:
    sessions_root = home / "sessions"
    if not sessions_root.is_dir():
        return 0
    removed = 0
    for child in sessions_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        else:
            child.unlink(missing_ok=True)
    return removed


async def clear_sync_rows(user_id: uuid.UUID) -> int:
    async with async_session_factory() as session:
        result = await session.execute(delete(DshSession).where(DshSession.user_id == user_id))
        await session.commit()
        return result.rowcount or 0


async def seed_sessions(user_id: uuid.UUID, prompts: list[str]) -> list[str]:
    from app.services.dsh.executor import DshHeadlessExecutor

    executor = DshHeadlessExecutor()
    created: list[str] = []
    for prompt in prompts:
        result = await executor.run_task(user_id=user_id, task=prompt, timeout=900)
        created.append(result.session_id or prompt[:40])
        print(f"[播种] {prompt[:32]}… → {created[-1]}")
    return created


def main() -> int:
    from app.core.config import get_settings

    parser = argparse.ArgumentParser(description="清理/播种 DSH 会话")
    parser.add_argument("--user-id", required=True, help="平台用户 UUID")
    parser.add_argument("--home", default=None, help="DSH home（默认按 settings 推导）")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不删除")
    parser.add_argument("--clear", action="store_true", help="删除该用户全部 DSH 会话与同步表记录")
    parser.add_argument("--seed", action="store_true", help="播种专业示例对话")
    args = parser.parse_args()

    user_id = uuid.UUID(args.user_id)
    home = Path(args.home) if args.home else get_settings().dsh_home_root_path / str(user_id)
    if not home.is_dir():
        print(f"[错误] home 不存在：{home}")
        return 1

    records = list(iter_sessions(home))
    print(f"[统计] 会话 {len(records)} 条（home={home}）")
    if args.dry_run:
        return 0
    if args.clear:
        removed = clear_sessions(home)
        rows = asyncio.run(clear_sync_rows(user_id))
        print(f"[清理] 删除会话目录 {removed} 个、同步表记录 {rows} 条")
    if args.seed:
        created = asyncio.run(seed_sessions(user_id, SEED_PROMPTS))
        print(f"[播种] 完成 {len(created)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

（`DshHeadlessExecutor.run_task` 的实际签名以 `backend/app/services/dsh/executor.py` 为准；若返回对象没有 `session_id`，用返回的 stdout 首行或跳过该字段。）

- [ ] **Step 5: 运行测试确认通过**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_dsh_sessions_reset.py -v`
Expected: 2 passed

- [ ] **Step 6: 真实执行清理 + 播种**

先停 DSH 实例（避免文件占用），再执行（`<admin-uid>` 从 `dsh_instances` 表取，本机为 `4c40bada-b2e6-45ea-b1b2-a2e43e663072`）：

```powershell
$dshPid = (Get-NetTCPConnection -LocalPort 3163 -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($dshPid) { Stop-Process -Id $dshPid -Force }
X:\python\anaconda\envs\01-rbac\python.exe -m scripts.dsh_sessions_reset --user-id 4c40bada-b2e6-45ea-b1b2-a2e43e663072 --clear
X:\python\anaconda\envs\01-rbac\python.exe -m scripts.dsh_sessions_reset --user-id 4c40bada-b2e6-45ea-b1b2-a2e43e663072 --seed
```

（播种 5 条真实 LLM 调用，约 3-6 分钟，有 token 消耗。）

- [ ] **Step 7: 验证**

- 会话目录只剩 5 个：`Get-ChildItem backend\var\dsh\4c40bada-b2e6-45ea-b1b2-a2e43e663072\sessions -Directory | Measure-Object`
- 每条都有可读标题（读一个会话文件确认 `session/title` 事件）
- 浏览器打开 `/agent` → 侧栏会话列表恰好 5 条、标题为问题本身
- `dsh_sessions` 表同步后只有这 5 条

- [ ] **Step 8: 提交**

```bash
git add backend/scripts/dsh_sessions_reset.py backend/tests/test_dsh_sessions_reset.py dsh-platform/NOTES.md
git commit -m "feat(dsh): 会话清理与专业示例对话播种脚本"
```

---

### Task 5: DSH 工作区占满内容区

**Files:**
- Modify: `dsh-platform/packages/server-connector/src/client/selectors.ts`
- Modify: `dsh-platform/packages/server-connector/src/client/sidebar-hide.ts`（或新增 `layout-fix.ts` 并在 `client/index.ts` 挂载）
- Test: `dsh-platform/packages/server-connector/tests/client-hide.test.ts`（或新增 `client-layout.test.ts`）

**Interfaces:**
- Consumes: 桥协议（`src/client/protocol.ts`）、`SIDEBAR_COLUMN_SELECTOR`
- Produces: 新增导出 `APP_FRAME_SELECTOR`；布局修正函数 `installLayoutFix(): () => void`

- [ ] **Step 1: 加临时探针命令，实测 DOM（先测后改）**

在 `src/client/bridge.ts` 的命令分发里临时加一个 `probe-layout` 动作，回传：

```ts
const frame = document.querySelector(APP_FRAME_SELECTOR) as HTMLElement | null
const column = document.querySelector(SIDEBAR_COLUMN_SELECTOR) as HTMLElement | null
return {
  frameTracks: frame ? getComputedStyle(frame).gridTemplateColumns : null,
  frameRect: frame?.getBoundingClientRect().toJSON() ?? null,
  frameClass: frame?.className ?? null,
  frameData: frame ? { ...frame.dataset } : null,
  columnRect: column?.getBoundingClientRect().toJSON() ?? null,
  bodyWidth: document.body.getBoundingClientRect().width,
}
```

（此时 `APP_FRAME_SELECTOR` 尚未确定，先用临时的宽匹配 `[class*='frame']` 找出候选元素，把候选的 `className`/`data-*` 打印出来再定稿。）

构建插件（`pnpm build`）→ 杀掉实例 → 重启 → 在平台侧调用该命令（临时在 `dsh-workspace.tsx` 里 `send` 一次并把回包 `console.log` 出来，或直接看浏览器控制台）。

记录实测结论到 `dsh-platform/NOTES.md`：
- 若 `frameTracks` 有 ≥2 轨且非内容轨宽度 > 0 → **右轨残留**；
- 若 `frameRect.width` < `bodyWidth` → **内容列自身宽度限制**。

- [ ] **Step 2: 写失败测试**

```ts
// tests/client-layout.test.ts
import { describe, expect, it } from "vitest";
import { buildLayoutCss } from "../src/client/layout-fix.ts";

describe("layout-fix", () => {
  it("右轨残留时把所有非内容轨归零", () => {
    const css = buildLayoutCss("tracks", "0px 320px 1fr");
    expect(css).toContain("grid-template-columns: 0px 0px 1fr");
  });

  it("内容列受限时解除宽度限制", () => {
    const css = buildLayoutCss("width", "");
    expect(css).toContain("max-width: none");
    expect(css).toContain("width: 100%");
  });
});
```

- [ ] **Step 3: 运行测试确认失败**

Run（workdir=`dsh-platform/packages/server-connector`）: `pnpm test -- tests/client-layout.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现（按 Step 1 的实测结论二选一或都做）**

```ts
// src/client/layout-fix.ts
/// <reference lib="dom" />
import { APP_FRAME_SELECTOR, CONVERSATION_COLUMN_SELECTOR } from './selectors.ts'

const STYLE_ID = 'naoker-layout-fix'

export function buildLayoutCss(mode: 'tracks' | 'width', tracks: string): string {
  if (mode === 'tracks') {
    const parts = tracks.trim().split(/\s+/)
    const last = parts.length - 1
    const zeroed = parts.map((part, index) => (index === last ? part : '0px')).join(' ')
    return `${APP_FRAME_SELECTOR} { grid-template-columns: ${zeroed} !important; }`
  }
  return `${CONVERSATION_COLUMN_SELECTOR} { max-width: none !important; width: 100% !important; }`
}

export function installLayoutFix(mode: 'tracks' | 'width'): () => void {
  const style = document.createElement('style')
  style.id = STYLE_ID
  const frame = document.querySelector(APP_FRAME_SELECTOR)
  const tracks = frame instanceof HTMLElement ? getComputedStyle(frame).gridTemplateColumns : ''
  style.textContent = buildLayoutCss(mode, tracks)
  document.head.appendChild(style)
  return () => style.remove()
}
```

在 `client/index.ts` 挂载 `installLayoutFix(<实测 mode>)`，并在 `selectors.ts` 增加两个常量（**值一律来自 Step 1 的实测**，与现有 `SIDEBAR_COLUMN_SELECTOR` 同风格：锚定 `data-slot` / `aria-label` / 官方稳定 class 子串，并写成 `:is(a, b)` 的前向兼容双臂）：

```ts
/** DSH 应用框架容器（承载侧栏列与内容列的网格容器）。 */
export const APP_FRAME_SELECTOR = <Step 1 实测得到的稳定选择器>

/** 会话内容列（右轨/宽度修正目标）。 */
export const CONVERSATION_COLUMN_SELECTOR = <Step 1 实测得到的稳定选择器>
```

Step 1 的探针必须同时回传这两个元素的 `className` 与全部 `data-*` 属性，便于挑选最稳定的锚点；把最终选择器与选择理由一并写入 `NOTES.md`。

- [ ] **Step 5: 运行测试 + 构建**

Run: `pnpm test` → 全部 PASS
Run: `pnpm build` → 无错误（提交 `lib/` 产物）

- [ ] **Step 6: 真实验证**

杀掉实例 → 重启（加载新插件）→ 浏览器打开 `/agent`：DSH 内容区左右无空白，横向占满；再点开设置面板/切换会话确认无副作用。

- [ ] **Step 7: 移除临时探针并提交**

```bash
git add dsh-platform/packages/server-connector/src/client dsh-platform/packages/server-connector/tests dsh-platform/packages/server-connector/lib dsh-platform/NOTES.md
git commit -m "fix(dsh): 工作区布局修正（内容区占满）"
```

---

### Task 6: 端到端验收

**Files:**
- Create: `docs/verification/workbench-ui-cleanup-checklist.md`

- [ ] **Step 1: 全量回归**

Run（workdir=`frontend`）: `npx vitest run src/components/layout src/components/dsh src/components/feishu`
Expected: 目标文件全绿（与基线对比，无新增失败）

Run（workdir=`dsh-platform/packages/server-connector`）: `pnpm test`
Expected: 全绿

Run（workdir=`backend`）: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_dsh_sessions_reset.py -q`
Expected: 2 passed

- [ ] **Step 2: 浏览器验收（6 条）**

1. 侧栏无「方案中心」；`/generations` 404
2. 侧栏顺序：我的文件 → 账户 → 对话审计 → 文件管理 → 知识库管理 → 用户管理 → 角色管理 → DSH 设置
3. 任意页面（含 `/knowledge`、`/files`）都显示「DSH 设置」；点击 → 进 `/agent` 并打开 DSH 设置面板
4. 侧栏会话列表只有 5 条专业示例对话（标题为问题本身）
5. 全站顶栏一致（`/agent` 与 `/knowledge` 同一套）；用户下拉里有「飞书已连接/连接飞书」「平台登录」，都能打开各自弹窗
6. DSH 工作区内容占满，右侧无空白

- [ ] **Step 3: 落盘验收清单并提交**

```bash
git add docs/verification/workbench-ui-cleanup-checklist.md
git commit -m "docs(ui): 工作台界面整理验收清单与实测结果"
```

---

## 附：任务依赖与并行建议

- Task 1、2、3、5 互不共享文件，可并发（Task 5 需要先杀实例、跑真实测量）。
- Task 4 需要停 DSH 实例并执行真实清理/播种（会真实消耗 token），建议在 Task 5 的实例操作之后串行执行，避免两边同时重启实例。
- Task 6 依赖全部任务。
