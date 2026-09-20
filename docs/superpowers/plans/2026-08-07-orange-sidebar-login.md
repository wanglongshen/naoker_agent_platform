# 品牌橙导航栏与登录页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把左侧导航栏与登录页左侧从深棕黑渐变改为品牌橙渐变（#D96313 → #C74E0B → #B94F0C），导航栏选中态改为白底橙字，登录页加白色光晕与网格纹理。

**Architecture:** 全部改动集中在 `frontend/src/app/globals.css`（主题变量 + 选择器）与 `frontend/src/app/globals.test.ts`（颜色断言同步）。`--color-sidebar` / `--color-sidebar-elevated` 两个变量驱动 sidebar 渐变两端，改变量即带动 `.enterprise-sidebar`、drawer、legacy sider。登录页左侧是独立渐变块，单独改。不触碰布局结构与文案。

**Tech Stack:** CSS 变量、CSS 渐变、antd Menu dark 主题覆盖（cssinjs）、vitest（globals.test.ts 用 readFileSync 断言 CSS 文本）。

**Spec:** `docs/superpowers/specs/2026-08-07-orange-sidebar-login-design.md`（`b5301b3`）

## Global Constraints

- 主色保持 `--color-primary: #D96313` 不变（按钮/链接/焦点全站主色）
- 品牌橙渐变三色：`#D96313 → #C74E0B → #B94F0C`（spec 定稿，浏览器 mockup 确认）
- 导航栏选中态 = 白底橙字（`background:#fff; color:#a03c08` + 轻阴影）
- 不修改任何布局结构、文案、其他页面配色
- 测试断言必须与写入的 CSS 文本**逐字符一致**（globals.test.ts 是 readFileSync + toContain 精确匹配）
- 前端测试基线：539 passed / 11 既有失败（4 个已知失败文件与本改动零交集，不得新增失败）

---

### Task 1: 主题变量 + 导航栏（sidebar）橙色化

**Files:**
- Modify: `frontend/src/app/globals.css`（:root 变量 6-7 行、.sidebar-brand-mark 86 行、菜单选中态 111-113 行、.session-item-active 121 行）
- Modify: `frontend/src/app/globals.test.ts`（16 行断言 + 新增断言测试块）

**Interfaces:**
- Consumes: 无
- Produces: globals.css 中的橙色主题变量与导航栏选择器（Task 2 复用同文件不依赖接口）

- [ ] **Step 1: 更新 globals.test.ts 断言（先红）**

在 `globals.test.ts` 的 `"defines the shared warm-intelligence design tokens in :root"` 测试中，把第 16 行：

```ts
  expect(css).toContain("--color-sidebar: #2A1812");
```

改为：

```ts
  expect(css).toContain("--color-sidebar: #D96313");
  expect(css).toContain("--color-sidebar-elevated: #B94F0C");
```

并在文件末尾追加一个新测试块：

```ts
test("brand orange sidebar: white-background selected state and brand mark", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

  expect(css).toContain(".sidebar-brand-mark { flex-shrink: 0; width: 34px; height: 34px; background: #fff;");
  expect(css).toContain("background: #fff !important; color: #a03c08 !important;");
  expect(css).toContain(".sidebar-session-list-wrapper .session-item-active { background: rgba(255,255,255,.20) !important; border-left: 2px solid #fff; padding-left: 8px; }");
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/app/globals.test.ts`
Expected: FAIL（`--color-sidebar: #D96313` 与新增断言均不匹配当前 CSS）

- [ ] **Step 3: 修改 globals.css 变量（6-7 行）**

```css
  --color-sidebar: #D96313;
  --color-sidebar-elevated: #B94F0C;
```

（原值为 `#2A1812` / `#3B271F`）

- [ ] **Step 4: 修改 .sidebar-brand-mark（86 行）**

原：

```css
.sidebar-brand-mark { flex-shrink: 0; width: 34px; height: 34px; background: linear-gradient(140deg, #fba05a, var(--warm-primary)); border-radius: 9px; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 18px; }
```

改为：

```css
.sidebar-brand-mark { flex-shrink: 0; width: 34px; height: 34px; background: #fff; border-radius: 9px; display: flex; align-items: center; justify-content: center; color: #c74e0b; font-size: 18px; box-shadow: 0 3px 10px rgba(0,0,0,.18); }
```

- [ ] **Step 5: 修改菜单选中态（111-113 行）**

原：

```css
.sidebar-management .ant-menu-dark .ant-menu-item-selected { background: rgba(232,117,22,.18) !important; border-left: 3px solid var(--warm-primary) !important; padding-left: 13px !important; }
.sidebar-management .ant-menu-dark .ant-menu-item-selected .anticon { color: var(--warm-primary) !important; opacity: 1; }
```

改为（删除左边条与 padding 覆盖，白底橙字 + 阴影）：

```css
.sidebar-management .ant-menu-dark .ant-menu-item-selected { background: #fff !important; color: #a03c08 !important; font-weight: 700 !important; box-shadow: 0 3px 10px rgba(0,0,0,.18) !important; }
.sidebar-management .ant-menu-dark .ant-menu-item-selected .anticon { color: #a03c08 !important; opacity: 1; }
```

- [ ] **Step 6: 修改会话列表选中态（121 行）**

原：

```css
.sidebar-session-list-wrapper .session-item-active { background: rgba(232,117,22,.14) !important; border-left: 2px solid var(--warm-primary); padding-left: 8px; }
```

改为：

```css
.sidebar-session-list-wrapper .session-item-active { background: rgba(255,255,255,.20) !important; border-left: 2px solid #fff; padding-left: 8px; }
```

- [ ] **Step 7: 运行确认通过**

Run: `npx vitest run src/app/globals.test.ts`
Expected: PASS（3 个测试全过）

- [ ] **Step 8: 提交**

```bash
git add src/app/globals.css src/app/globals.test.ts
git commit -m "feat: brand orange sidebar with white selected state"
```

---

### Task 2: 登录页左侧（.login-brand）橙色化

**Files:**
- Modify: `frontend/src/app/globals.css`（.login-brand 250 行、::before 251 行、.login-brand-mark 252-253 行）
- Modify: `frontend/src/app/globals.test.ts`（追加断言）

**Interfaces:**
- Consumes: Task 1 已提交的 globals.css（无接口依赖，仅同文件顺序执行）
- Produces: 登录页左侧橙色渐变 + 白色光晕 + 网格纹理

- [ ] **Step 1: 追加测试断言（先红）**

在 `globals.test.ts` 末尾追加：

```ts
test("brand orange login panel: orange gradient with white glow and white mark", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

  expect(css).toContain("background: linear-gradient(160deg, #d96313 0%, #c74e0b 55%, #b94f0c 100%);");
  expect(css).toContain("radial-gradient(ellipse at 20% 50%, rgba(255,255,255,.16) 0, transparent 50%)");
  expect(css).toContain("background: #fff; border-radius: 11px;");
  expect(css).toContain("border: 2px solid #c74e0b; border-radius: 5px;");
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/app/globals.test.ts`
Expected: FAIL（新断言不匹配当前深棕渐变）

- [ ] **Step 3: 修改 .login-brand 背景（250 行）**

原：

```css
.login-brand { display: none; flex: 1; background: linear-gradient(160deg, #170d09 0%, #2b1b15 55%, #1f1211 100%); position: relative; overflow: hidden; }
```

改为：

```css
.login-brand { display: none; flex: 1; background: linear-gradient(160deg, #d96313 0%, #c74e0b 55%, #b94f0c 100%); position: relative; overflow: hidden; }
```

- [ ] **Step 4: 修改 ::before 光晕 + 网格（251 行）**

原：

```css
.login-brand::before { content: ""; position: absolute; inset: 0; background: radial-gradient(ellipse at 20% 50%, rgba(224,107,18,.15) 0, transparent 50%), radial-gradient(circle at 70% 15%, rgba(224,107,18,.06) 0, transparent 35%); }
```

改为（白色光晕 + 34px 极淡网格，四层背景）：

```css
.login-brand::before { content: ""; position: absolute; inset: 0; background: radial-gradient(ellipse at 20% 50%, rgba(255,255,255,.16) 0, transparent 50%), radial-gradient(circle at 70% 15%, rgba(255,255,255,.10) 0, transparent 35%), linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px); background-size: auto, auto, 34px 34px, 34px 34px; }
```

- [ ] **Step 5: 修改 .login-brand-mark（252-253 行）**

原：

```css
.login-brand-mark { position: absolute; top: 48px; left: 56px; width: 42px; height: 42px; background: linear-gradient(140deg, #fba05a, var(--warm-primary)); border-radius: 11px; }
.login-brand-mark::after { content: ""; position: absolute; inset: 9px; border: 2px solid rgba(255,255,255,.8); border-radius: 5px; }
```

改为：

```css
.login-brand-mark { position: absolute; top: 48px; left: 56px; width: 42px; height: 42px; background: #fff; border-radius: 11px; box-shadow: 0 6px 18px rgba(0,0,0,.18); }
.login-brand-mark::after { content: ""; position: absolute; inset: 9px; border: 2px solid #c74e0b; border-radius: 5px; }
```

- [ ] **Step 6: 运行确认通过**

Run: `npx vitest run src/app/globals.test.ts`
Expected: PASS（4 个测试全过）

- [ ] **Step 7: 提交**

```bash
git add src/app/globals.css src/app/globals.test.ts
git commit -m "feat: brand orange login panel with white glow and grid texture"
```

---

### Task 3: 集成验证

**Files:** 无代码改动

**Interfaces:**
- Consumes: Task 1 + Task 2 的 globals.css 改动

- [ ] **Step 1: 前端全量测试**

Run: `npx vitest run`
Expected: 539 passed / 11 failed（11 个失败必须与基线一致——文件为 run-diagnostics / use-run-event-stream / run-stream-reducer / thought-narrative 相关；若失败数量或文件超出基线，立即停下报告，不得掩盖）

- [ ] **Step 2: 类型检查**

Run: `npx tsc --noEmit`
Expected: 无本改动文件的新错误（若报错需先确认是否为既有测试文件错误，与本改动无关则记录并继续）

- [ ] **Step 3: 手动视觉清单（dev 环境核对）**

Run: `npm run dev` 后浏览器逐项核对：

1. 登录页 `http://localhost:3000/login`（宽屏 ≥961px）：左侧为品牌橙渐变（#D96313→#B94F0C）、右上/左下白色光晕、极淡网格纹理、白字标题描述、左上 logo 白底橙框
2. 登录（admin / 密码）进入工作台：左侧导航栏整体橙色渐变
3. 导航栏：品牌 logo 白底橙字、当前菜单项白底橙字高亮、hover 项半透明白、会话列表选中项半透明白 + 白左边条、底部账户区可读
4. 缩放窗口 ≤960px：登录页左侧隐藏、drawer 导航正常

- [ ] **Step 4: 提交验证结果**

无需提交（无代码改动）；在交付说明中记录视觉清单核对结果。

---

## Self-Review

- **Spec 覆盖**：① 主题变量 ✅ Task 1；② 导航栏选中态白底橙字 ✅ Task 1；③ 会话选中态 ✅ Task 1；④ 登录页渐变/光晕/网格/mark ✅ Task 2；⑤ globals.test.ts 断言 ✅ Task 1+2；⑥ 不做的事（布局/文案/主色/其他页面）——计划未涉及 ✅。
- **占位符扫描**：全部步骤含完整 CSS 代码与测试代码，无 TBD。
- **类型一致性**：断言字符串与写入 CSS 逐字符一致（两任务各自红→绿闭环）；`--color-sidebar` 断言替换在 Task 1 Step 1，变量修改在 Step 3，顺序正确。
