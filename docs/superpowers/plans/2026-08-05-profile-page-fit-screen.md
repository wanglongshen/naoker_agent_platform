# 个人资料页一屏居中实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 个人资料页内容一屏放下并整体水平居中（双卡并排）。

**Architecture:** 页面根容器改为全高 flex 居中（`min-height: 100%`，父级 `.warm-executive-content` 是 antd Layout.Content，`flex: auto` 有确定高度，百分比可生效）；新增 `.profile-cards` 双栏 grid 包裹两张卡片；压缩横幅/卡片间距与字号。纯前端 CSS + 少量 JSX 结构改动。

**Tech Stack:** React 19 + AntD 6 + Next.js 16；vitest

## Global Constraints

- 前端测试 jsdom 病理约束：禁止对完整页面做 byRole/getAllByRole 查询；用 `document.querySelectorAll` + textContent 匹配
- 颜色一律引用 design tokens（`var(--color-*)` / `var(--radius-*)` / `var(--shadow-*)`），不硬编码色值
- git 纪律：提交前 `git status --short` 核对只含本任务列出的文件；精确路径 `git add`，绝对禁止 `git add -A`
- 表单 label 与按钮文案不得改变（测试选择器依赖）：姓名/邮箱/手机号/旧密码/新密码/确认新密码、保存、修改密码、上传头像、移除头像

---

### Task 1: 页面根居中 + 双卡并排 + 紧凑化

**Files:**
- Modify: `frontend/src/components/profile/profile-page.tsx`
- Modify: `frontend/src/app/globals.css`（追加新类、修改既有 `.profile-*` 间距值）
- Test: `frontend/src/components/profile/profile-page.test.tsx`

**Interfaces:**
- Consumes: `CurrentUser`（不变）
- Produces: 无（纯布局调整，props 与行为不变）

- [ ] **Step 1: 写失败测试**（`profile-page.test.tsx` 末尾追加）

```tsx
  test("renders two cards side by side", () => {
    render(<ProfilePage currentUser={currentUser} />);
    expect(document.querySelectorAll(".profile-card").length).toBe(2);
    expect(document.querySelectorAll(".profile-cards").length).toBe(1);
    const titles = Array.from(document.querySelectorAll(".profile-card-title"));
    expect(titles.some((el) => el.textContent?.includes("基本信息"))).toBe(true);
    expect(titles.some((el) => el.textContent?.includes("安全设置"))).toBe(true);
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run（工作目录 `frontend`）: `npx vitest run src/components/profile/profile-page.test.tsx`
Expected: 新测试 FAIL（无 `.profile-cards`）

- [ ] **Step 3: 追加/修改 CSS**（`frontend/src/app/globals.css`）

**追加**到文件末尾（`.profile-form` 规则之后）：

```css
.profile-page-root {
  display: flex;
  min-height: 100%;
  justify-content: center;
  align-items: center;
  padding: 24px 0;
}
.profile-page-inner { width: 100%; max-width: 960px; }
.profile-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-top: 20px;
}
@media (max-width: 900px) {
  .profile-cards { grid-template-columns: 1fr; }
}
```

**修改**既有规则的间距值（用 edit 精确替换）：
- `.profile-hero`：`padding: 32px;` → `padding: 28px;`
- `.profile-card`：`padding: 28px;` 保持；`margin-top: 24px;` → `margin-top: 0;`（双卡间距由 `.profile-cards` 的 grid gap 控制）
- `.profile-card-title`：`padding-bottom: 16px;` → `padding-bottom: 12px;`、`margin-bottom: 20px;` → `margin-bottom: 16px;`
- `.profile-info`：`gap: 8px;` → `gap: 6px;`
- 头像：组件里 `size={88}` → `size={80}`（Step 4）
- 姓名：`.profile-name` 的 `font-size: 22px` → `20px`

- [ ] **Step 4: 组件结构改动**（`frontend/src/components/profile/profile-page.tsx`）

只改 return 的外层结构：根 `<div>` 加 `className="profile-page-root"`，内部包一层 `<div className="profile-page-inner">`（PageHeader + 横幅 + 双卡全在 inner 内）；两张 `<section className="profile-card">` 包进 `<div className="profile-cards">`。`<Avatar size={88}` → `<Avatar size={80}`。其余 JSX（handler、Form、label、按钮）**一字不改**。当前结构为：

```tsx
  return (
    <div>
      <div className="page-hero">...</div>
      <div className="content" style={{ maxWidth: 860 }}>
        <section className="profile-hero">...</section>
        <section className="profile-card">（基本信息）</section>
        <section className="profile-card">（安全设置）</section>
      </div>
    </div>
  );
```

改为：

```tsx
  return (
    <div className="profile-page-root">
      <div className="profile-page-inner">
        <div className="page-hero">...</div>
        <section className="profile-hero">...</section>
        <div className="profile-cards">
          <section className="profile-card">（基本信息）</section>
          <section className="profile-card">（安全设置）</section>
        </div>
      </div>
    </div>
  );
```

（原有 `.content` 包裹 div 删除，改由 `.profile-page-inner` 承担宽度约束；maxWidth 960 由 CSS 控制，不再用内联 style。）

- [ ] **Step 5: 跑测试确认通过**

Run: `npx vitest run src/components/profile/profile-page.test.tsx`
Expected: 6 个测试全部 PASS（5 既有 + 1 新增双卡断言）

- [ ] **Step 6: eslint**

Run: `npx eslint src/components/profile/profile-page.tsx src/components/profile/profile-page.test.tsx`
Expected: 0 errors（既有 warning 可忽略）

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/profile/profile-page.tsx frontend/src/components/profile/profile-page.test.tsx frontend/src/app/globals.css
git commit -m "style: fit profile page into one screen with centered dual cards"
```

---

### Task 2: 回归验证

**Files:** 无代码改动

- [ ] **Step 1: 前端受影响文件回归**

Run: `npx vitest run src/components/profile src/components/users src/components/layout/dashboard-shell.test.tsx`
Expected: 全部 PASS

- [ ] **Step 2: 汇报**

汇总提交 hash 与回归结果。
