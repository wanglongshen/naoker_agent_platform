# 个人资料页美化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按系统 Warm Intelligence 设计语言将个人资料页重构为"通栏横幅 + 双卡"结构并精致美化。

**Architecture:** 单一前端任务：`profile-page.tsx` JSX 重构为三段（横幅 + 基本信息卡 + 安全设置卡），新增 `.profile-*` CSS 类到 `globals.css`（复用既有 design tokens：`--color-bg-subtle`/`--color-primary`/`--radius-lg`/`--shadow-sm` 等），所有 handler 与 API 调用零改动。

**Tech Stack:** React 19 + AntD 6 + Next.js 16；vitest

## Global Constraints

- 前端测试 jsdom 病理约束：禁止对完整页面做 byRole/getAllByRole 查询；用 `document.querySelectorAll` + textContent 匹配（`pageButtons`/`findPageButton` helper 模式）
- 颜色一律引用 design tokens（`var(--color-*)` / `var(--radius-*)` / `var(--shadow-*)`），不硬编码色值；唯一例外：光环渐变可含 `#fba05a`（与 `.sidebar-brand-mark` 既有用法一致）
- git 纪律：提交前 `git status --short` 核对只含 3 个文件（profile-page.tsx、profile-page.test.tsx、globals.css）；精确路径 `git add`，绝对禁止 `git add -A`
- 表单 label 与按钮文案不得改变：姓名/邮箱/手机号/旧密码/新密码/确认新密码、保存、修改密码、上传头像、移除头像（测试选择器依赖）

---

### Task 1: 资料页重构与美化

**Files:**
- Modify: `frontend/src/components/profile/profile-page.tsx`
- Modify: `frontend/src/app/globals.css`（追加 `.profile-*` 类，文件末尾）
- Test: `frontend/src/components/profile/profile-page.test.tsx`

**Interfaces:**
- Consumes: `CurrentUser`（roles: RoleReference[] 必填，avatar_url?/email? 可选）
- Produces: 无（纯视觉重构，props 与行为不变）

- [ ] **Step 1: 写失败测试**（`profile-page.test.tsx` 末尾追加横幅断言测试）

```tsx
  test("renders hero banner with account and role tags", () => {
    const user: CurrentUser = {
      ...currentUser,
      roles: [{ id: "r1", code: "super_admin", name: "超级管理员" }],
    };
    render(<ProfilePage currentUser={user} />);
    expect(screen.getByText("@admin")).toBeTruthy();
    expect(screen.getByText("超级管理员")).toBeTruthy();
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run（工作目录 `frontend`）: `npx vitest run src/components/profile/profile-page.test.tsx`
Expected: 新测试 FAIL（无 @admin 文本）

- [ ] **Step 3: 追加 CSS 类**（`frontend/src/app/globals.css` 文件末尾）

```css
/* ====== PROFILE PAGE ====== */
.profile-hero {
  position: relative;
  overflow: hidden;
  background: var(--color-bg-subtle);
  border-radius: var(--radius-lg);
  padding: 32px;
  display: flex;
  align-items: center;
  gap: 24px;
  box-shadow: inset 0 -1px 0 color-mix(in srgb, var(--color-primary) 18%, transparent);
}
.profile-decor-circle {
  position: absolute;
  border: 1px solid color-mix(in srgb, var(--color-primary) 22%, transparent);
  border-radius: 50%;
  pointer-events: none;
}
.profile-decor-circle.big { width: 180px; height: 180px; top: -60px; right: -40px; }
.profile-decor-circle.small { width: 120px; height: 120px; bottom: -48px; right: 96px; }
.profile-avatar-ring {
  flex-shrink: 0;
  padding: 4px;
  background: linear-gradient(140deg, var(--color-primary), #fba05a);
  border-radius: 50%;
}
.profile-info { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.profile-name { font-size: 22px; font-weight: 700; color: var(--color-text-primary); }
.profile-account { font-size: 14px; color: var(--color-text-muted); }
.profile-roles { display: flex; gap: 6px; flex-wrap: wrap; }
.profile-role-tag {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 600;
  width: fit-content;
}
.profile-email { font-size: 13px; color: var(--color-text-secondary); display: flex; align-items: center; gap: 6px; }
.profile-hero-actions { margin-left: auto; display: flex; flex-direction: column; align-items: flex-end; gap: 8px; }
.profile-hint { font-size: 12px; color: var(--color-text-muted); }
.profile-card {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 28px;
  margin-top: 24px;
}
.profile-card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 17px;
  font-weight: 600;
  color: var(--color-text-primary);
  padding-bottom: 16px;
  margin-bottom: 20px;
  border-bottom: 1px solid var(--color-border);
}
.profile-card-title .anticon { font-size: 18px; color: var(--color-primary); }
.profile-form { max-width: 460px; }
@media (max-width: 768px) {
  .profile-hero { flex-direction: column; text-align: center; }
  .profile-hero-actions { margin-left: 0; align-items: center; }
  .profile-email { justify-content: center; }
}
```

- [ ] **Step 4: 重构组件**（`frontend/src/components/profile/profile-page.tsx` 整体重写为以下内容；handler 逻辑与 Step 原实现完全一致，仅 JSX 与 import 变化）

```tsx
"use client";

import { useRef, useState } from "react";
import { Avatar, Button, Form, Input, message, Space } from "antd";
import {
  DeleteOutlined,
  LockOutlined,
  MailOutlined,
  PhoneOutlined,
  SafetyOutlined,
  SaveOutlined,
  UploadOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { api } from "@/lib/api";
import PageHeader from "@/components/layout/page-header";
import type { CurrentUser } from "@/types/auth";

interface ProfilePageProps {
  currentUser: CurrentUser;
}

export default function ProfilePage({ currentUser }: ProfilePageProps) {
  const [avatarUrl, setAvatarUrl] = useState<string | null>(currentUser.avatar_url ?? null);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    if (file.size > 2 * 1024 * 1024) {
      message.error("头像文件不能超过 2MB");
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    setUploading(true);
    try {
      const data = await api<{ avatar_url: string }>("/api/avatars/me", {
        method: "POST",
        body: formData,
        csrf: true,
      });
      setAvatarUrl(data.avatar_url);
      message.success("头像已更新");
    } catch {
      message.error("头像上传失败");
    } finally {
      setUploading(false);
    }
  }

  async function handleClearAvatar() {
    setUploading(true);
    try {
      const data = await api<{ avatar_url: string | null }>("/api/avatars/me", {
        method: "DELETE",
        csrf: true,
      });
      setAvatarUrl(data.avatar_url);
      message.success("头像已移除");
    } catch {
      message.error("移除头像失败");
    } finally {
      setUploading(false);
    }
  }

  async function handleSaveProfile(values: { display_name: string; email?: string; phone?: string }) {
    setSaving(true);
    try {
      await api("/api/users/me/profile", {
        method: "PUT",
        body: JSON.stringify(values),
        csrf: true,
      });
      message.success("资料已保存");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败，请检查输入");
    } finally {
      setSaving(false);
    }
  }

  async function handleChangePassword(values: { old_password: string; new_password: string; confirm: string }) {
    if (values.new_password !== values.confirm) {
      message.error("两次输入的新密码不一致");
      return;
    }
    setSaving(true);
    try {
      await api("/api/users/me/password", {
        method: "POST",
        body: JSON.stringify({ old_password: values.old_password, new_password: values.new_password }),
        csrf: true,
      });
      message.success("密码已更新");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "修改密码失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="page-hero">
        <PageHeader title="个人资料" description="管理你的头像、基本信息和密码" />
      </div>
      <div className="content" style={{ maxWidth: 860 }}>
        <section className="profile-hero">
          <span className="profile-decor-circle big" aria-hidden />
          <span className="profile-decor-circle small" aria-hidden />
          <div className="profile-avatar-ring">
            <Avatar size={88} src={avatarUrl ?? undefined} icon={avatarUrl ? undefined : <UserOutlined />} />
          </div>
          <div className="profile-info">
            <div className="profile-name">{currentUser.display_name}</div>
            <div className="profile-account">@{currentUser.username}</div>
            {currentUser.roles.length > 0 && (
              <div className="profile-roles">
                {currentUser.roles.map((role) => (
                  <span key={role.id} className="profile-role-tag">
                    {role.name}
                  </span>
                ))}
              </div>
            )}
            {currentUser.email && (
              <div className="profile-email">
                <MailOutlined />
                <span>{currentUser.email}</span>
              </div>
            )}
          </div>
          <div className="profile-hero-actions">
            <Space>
              <Button icon={<UploadOutlined />} loading={uploading} onClick={() => fileRef.current?.click()}>
                上传头像
              </Button>
              {avatarUrl && (
                <Button icon={<DeleteOutlined />} danger onClick={handleClearAvatar} disabled={uploading}>
                  移除头像
                </Button>
              )}
            </Space>
            <span className="profile-hint">支持 PNG/JPG/GIF/WebP，不超过 2MB</span>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleUpload(file);
              e.target.value = "";
            }}
          />
        </section>

        <section className="profile-card">
          <div className="profile-card-title">
            <UserOutlined />
            <span>基本信息</span>
          </div>
          <Form
            layout="vertical"
            className="profile-form"
            initialValues={{
              display_name: currentUser.display_name,
              email: currentUser.email ?? undefined,
              phone: currentUser.phone ?? undefined,
            }}
            onFinish={handleSaveProfile}
          >
            <Form.Item name="display_name" label="姓名" rules={[{ required: true, message: "请输入姓名" }]}>
              <Input prefix={<UserOutlined />} />
            </Form.Item>
            <Form.Item name="email" label="邮箱" rules={[{ type: "email", message: "邮箱格式不正确" }]}>
              <Input prefix={<MailOutlined />} />
            </Form.Item>
            <Form.Item name="phone" label="手机号">
              <Input prefix={<PhoneOutlined />} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={saving} icon={<SaveOutlined />}>
              保存
            </Button>
          </Form>
        </section>

        <section className="profile-card">
          <div className="profile-card-title">
            <LockOutlined />
            <span>安全设置</span>
          </div>
          <Form layout="vertical" className="profile-form" onFinish={handleChangePassword}>
            <Form.Item name="old_password" label="旧密码" rules={[{ required: true, message: "请输入旧密码" }]}>
              <Input.Password prefix={<LockOutlined />} />
            </Form.Item>
            <Form.Item name="new_password" label="新密码" rules={[{ required: true, message: "请输入新密码" }]}>
              <Input.Password prefix={<LockOutlined />} />
            </Form.Item>
            <Form.Item name="confirm" label="确认新密码" rules={[{ required: true, message: "请确认新密码" }]}>
              <Input.Password prefix={<LockOutlined />} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={saving} icon={<SafetyOutlined />}>
              修改密码
            </Button>
            <div className="profile-hint" style={{ marginTop: 12 }}>
              新密码需至少 8 位，且同时包含字母和数字
            </div>
          </Form>
        </section>
      </div>
    </div>
  );
}
```

注意：`DataSurface` 不再使用（JSX 中已无引用），import 已一并删除。

- [ ] **Step 5: 适配既有测试断言**（`profile-page.test.tsx`）

`test("renders profile info form and password block")` 中"修改密码"标题从 `<h3>` 改为 `.profile-card-title` div，断言改为：

```tsx
    expect(
      Array.from(document.querySelectorAll(".profile-card-title")).some(
        (el) => el.textContent?.includes("修改密码")
      )
    ).toBe(true);
```

- [ ] **Step 6: 跑测试确认通过**

Run: `npx vitest run src/components/profile/profile-page.test.tsx`
Expected: 5 个测试全部 PASS（4 既有 + 1 新增横幅断言）

- [ ] **Step 7: eslint**

Run: `npx eslint src/components/profile/profile-page.tsx src/components/profile/profile-page.test.tsx`
Expected: 0 errors（既有 warning 可忽略）

- [ ] **Step 8: 提交**

```bash
git add frontend/src/components/profile/profile-page.tsx frontend/src/components/profile/profile-page.test.tsx frontend/src/app/globals.css
git commit -m "style: redesign profile page with hero banner and dual cards"
```

---

### Task 2: 回归验证

**Files:** 无代码改动

- [ ] **Step 1: 前端受影响文件回归**

Run: `npx vitest run src/components/profile src/components/users src/components/layout/dashboard-shell.test.tsx`
Expected: 全部 PASS（资料页/用户管理/导航相关不受影响）

- [ ] **Step 2: 汇报**

汇总提交 hash 与回归结果。
