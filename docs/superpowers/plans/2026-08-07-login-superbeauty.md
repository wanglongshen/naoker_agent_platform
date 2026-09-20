# 登录页超级美化（科技神经）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 登录页左侧品牌区升级为"科技神经"主题（神经网络连线 + 脑形光晕徽章 + 橙焰 AI 胶囊 + 脉动光点），右侧表单区精致化（渐变条卡片 + 图标输入框 + 渐变按钮 + 底部行）。

**Architecture:** 全部改动在 `frontend/src/app/(auth)/login/page.tsx`（品牌区装饰元素）、`frontend/src/components/auth/login-form.tsx`（输入框 prefix 图标 + 底部行）、`frontend/src/app/globals.css`（全部新样式 + keyframes）。Task 1 改品牌区，Task 2 改表单区，两任务都动 globals.css 与测试文件——严格串行 1→2→3。

**Tech Stack:** Next.js 16 客户端组件、antd（Input/Input.Password prefix + UserOutlined/LockOutlined）、纯 CSS（keyframes、inline SVG）、vitest（jsdom）。

**Spec:** `docs/superpowers/specs/2026-08-07-login-superbeauty-design.md`（`34b1585`）

## Global Constraints

- 品牌区渐变：`linear-gradient(155deg,#cf5a10 0%,#b94f0c 55%,#9a3d0a 100%)`
- AI 胶囊（变体 2）：橙渐变 `linear-gradient(135deg,#f97316,#c2410c)` + 白字 "AI" + 绿点 `#4ade80`
- 不做"忘记密码"实际功能（纯视觉 span，无跳转）
- 不加第三方依赖（图标用 antd 内置）
- 测试断言必须与写入的 CSS/JSX 文本逐字符一致（readFileSync + toContain / querySelector）
- 前端测试基线：573 passed / 12 既有失败（已知失败文件与本改动零交集，不得新增失败）
- 并行会话可能在操作同一仓库：只 `git add` 自己任务的文件路径，提交前核对 `git diff --cached --name-only`

---

### Task 1: 品牌区 · 科技神经装饰

**Files:**
- Modify: `frontend/src/app/(auth)/login/page.tsx`（品牌区加 SVG/光点/脑形徽章/AI 胶囊）
- Modify: `frontend/src/app/globals.css`（.login-brand 渐变、::before 网格/光晕、新装饰类 + keyframes）
- Modify: `frontend/src/app/(auth)/login/page.test.tsx`（追加装饰断言）
- Modify: `frontend/src/app/globals.test.ts`（追加主题断言）

**Interfaces:**
- Consumes: 无
- Produces: 品牌区 DOM 结构（.login-net / .login-node ×8 / .login-brain / .login-ai-chip）与 CSS 类（Task 2 不依赖，仅同文件顺序）

- [ ] **Step 1: 追加失败测试**

`frontend/src/app/(auth)/login/page.test.tsx` 末尾追加：

```tsx
test("renders neural brain theme decorations", async () => {
  mockFetchCurrentUser.mockResolvedValue(null);
  const { container } = render(<LoginPage />);
  await screen.findByText("脑壳工作台");
  expect(container.querySelector(".login-brain")).toBeTruthy();
  expect(container.querySelectorAll(".login-node").length).toBe(8);
  expect(container.querySelector(".login-ai-chip")).toBeTruthy();
  expect(screen.getByText("AI")).toBeTruthy();
});
```

`frontend/src/app/globals.test.ts` 末尾追加：

```ts
test("login page neural brain theme css", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

  expect(css).toContain("background: linear-gradient(155deg,#cf5a10 0%,#b94f0c 55%,#9a3d0a 100%);");
  expect(css).toContain("@keyframes login-pulse");
  expect(css).toContain("@keyframes login-spin");
  expect(css).toContain(".login-ai-chip { position: absolute; right: -6px; top: -8px;");
});
```

- [ ] **Step 2: 运行确认失败**

Run（frontend/ 目录）: `npx vitest run "src/app/(auth)/login/page.test.tsx" src/app/globals.test.ts`
Expected: FAIL（2 个新测试均失败）

- [ ] **Step 3: 修改 page.tsx 品牌区**

`frontend/src/app/(auth)/login/page.tsx` 的 `<section className="login-brand">` 内容，原为 mark + copy + foot，改为（在 `<div className="login-brand-mark" />` 之后插入 SVG/光点/脑形，`login-brand-copy` 与 `login-brand-foot` 保留不动）：

```tsx
        <section className="login-brand" aria-hidden="true">
          <div className="login-brand-mark" />
          <svg className="login-net" viewBox="0 0 320 460" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
            <g stroke="rgba(255,255,255,.26)" strokeWidth="1">
              <line x1="46" y1="70" x2="140" y2="170" />
              <line x1="140" y1="170" x2="80" y2="270" />
              <line x1="140" y1="170" x2="230" y2="130" />
              <line x1="230" y1="130" x2="286" y2="220" />
              <line x1="286" y1="220" x2="200" y2="330" />
              <line x1="80" y1="270" x2="170" y2="380" />
              <line x1="230" y1="130" x2="170" y2="380" />
              <line x1="46" y1="70" x2="230" y2="130" />
              <line x1="80" y1="270" x2="40" y2="360" />
            </g>
          </svg>
          <span className="login-node" style={{ left: "42px", top: "66px" }} />
          <span className="login-node" style={{ left: "136px", top: "166px" }} />
          <span className="login-node" style={{ left: "76px", top: "266px" }} />
          <span className="login-node" style={{ left: "226px", top: "126px" }} />
          <span className="login-node login-node--slow" style={{ left: "282px", top: "216px" }} />
          <span className="login-node" style={{ left: "196px", top: "326px" }} />
          <span className="login-node login-node--slow" style={{ left: "36px", top: "356px" }} />
          <span className="login-node" style={{ left: "166px", top: "376px" }} />
          <div className="login-brain">
            <span className="login-ai-chip">AI</span>
          </div>
          <div className="login-brand-copy">
            <div className="login-brand-kicker">AI SOLUTION WORKSPACE</div>
            <h1 className="login-brand-title">{copy.app.title}</h1>
            <p className="login-brand-desc">{copy.app.description}</p>
          </div>
          <div className="login-brand-foot">BRAIN SHELL · AGENT PLATFORM</div>
        </section>
```

- [ ] **Step 4: 修改 globals.css 品牌区**

`frontend/src/app/globals.css`：

(4a) `.login-brand` 背景渐变改为（第 250 行）：

```css
.login-brand { display: none; flex: 1; background: linear-gradient(155deg,#cf5a10 0%,#b94f0c 55%,#9a3d0a 100%); position: relative; overflow: hidden; }
```

(4b) `.login-brand::before` 改为（网格 26px + 保留两个白色光晕 + 新增右侧聚焦光晕，background-size 五层）：

```css
.login-brand::before { content: ""; position: absolute; inset: 0; background: radial-gradient(ellipse at 20% 50%, rgba(255,255,255,.16) 0, transparent 50%), radial-gradient(circle at 70% 15%, rgba(255,255,255,.10) 0, transparent 35%), radial-gradient(ellipse at 78% 40%, rgba(255,255,255,.16), transparent 55%), linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px); background-size: auto, auto, auto, 26px 26px, 26px 26px; }
```

(4c) 在 `.login-brand-foot` 规则之后追加新装饰类与 keyframes：

```css
.login-net { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 1; }
.login-node { position: absolute; width: 7px; height: 7px; border-radius: 50%; background: rgba(255,255,255,.9); box-shadow: 0 0 12px 3px rgba(255,255,255,.4); animation: login-pulse 3.2s ease-in-out infinite; z-index: 3; }
.login-node--slow { animation-duration: 4.6s; }
.login-brain { position: absolute; right: 36px; top: 50%; transform: translateY(-50%); width: 150px; height: 150px; border-radius: 46% 54% 55% 45% / 50% 46% 54% 50%; background: linear-gradient(135deg, rgba(255,255,255,.30), rgba(255,255,255,.08)); border: 1.5px solid rgba(255,255,255,.5); display: flex; align-items: center; justify-content: center; z-index: 3; box-shadow: inset 0 0 34px rgba(255,255,255,.16), 0 0 40px rgba(255,190,110,.16); }
.login-brain::before { content: ""; position: absolute; inset: 22px; border-radius: 50%; border: 1px dashed rgba(255,255,255,.55); animation: login-spin 30s linear infinite; }
.login-brain::after { content: ""; position: absolute; width: 36px; height: 36px; border-radius: 50%; background: radial-gradient(circle at 35% 35%, #ffd9a8, #f97316); box-shadow: 0 0 26px 8px rgba(255,180,90,.55); }
.login-ai-chip { position: absolute; right: -6px; top: -8px; display: flex; align-items: center; gap: 5px; height: 22px; padding: 0 8px 0 9px; background: linear-gradient(135deg,#f97316,#c2410c); border-radius: 11px; box-shadow: 0 4px 12px rgba(0,0,0,.25); font-size: 9.5px; font-weight: 800; color: #fff; letter-spacing: .08em; border: 1px solid rgba(255,255,255,.35); }
.login-ai-chip::after { content: ""; width: 5px; height: 5px; border-radius: 50%; background: #4ade80; box-shadow: 0 0 6px 2px rgba(74,222,128,.7); }
@keyframes login-pulse { 0%,100% { opacity: .55; transform: scale(.9); } 50% { opacity: 1; transform: scale(1.15); } }
@keyframes login-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .login-node, .login-brain::before { animation: none; } }
```

- [ ] **Step 5: 运行确认通过**

Run: `npx vitest run "src/app/(auth)/login/page.test.tsx" src/app/globals.test.ts`
Expected: PASS（page.test.tsx 6 个 + globals.test.ts 5 个全过）

- [ ] **Step 6: 提交**

```bash
git add "src/app/(auth)/login/page.tsx" "src/app/(auth)/login/page.test.tsx" src/app/globals.css src/app/globals.test.ts
git diff --cached --name-only
git commit -m "feat: login brand panel neural brain theme"
```

（提交前核对暂存区只含这 4 个文件）

---

### Task 2: 表单区 · 精致化

**Files:**
- Modify: `frontend/src/components/auth/login-form.tsx`（prefix 图标 + 底部行）
- Modify: `frontend/src/app/globals.css`（.login-panel/.login-card/输入框/按钮/底部行样式）
- Modify: `frontend/src/app/(auth)/login/page.test.tsx`（追加表单断言）

**Interfaces:**
- Consumes: Task 1 已就位（同文件顺序，无接口依赖）
- Produces: `.login-card-foot` / `.login-forgot` / `.login-version` 类与 antd prefix 渲染

- [ ] **Step 1: 追加失败测试**

`frontend/src/app/(auth)/login/page.test.tsx` 末尾追加：

```tsx
test("renders enhanced form card with icons and footer", async () => {
  mockFetchCurrentUser.mockResolvedValue(null);
  const { container } = render(<LoginPage />);
  await screen.findByText("脑壳工作台");
  expect(container.querySelector(".ant-input-prefix")).toBeTruthy();
  expect(screen.getByText("忘记密码？")).toBeTruthy();
  expect(screen.getByText("V1.0")).toBeTruthy();
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run "src/app/(auth)/login/page.test.tsx"`
Expected: FAIL（新测试：无 .ant-input-prefix、无"忘记密码？"）

- [ ] **Step 3: 修改 login-form.tsx**

(3a) 第 5 行 import 增加图标：

```tsx
import { Alert, Button, Form, Input } from "antd";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
```

(3b) 用户名 Input 增加 prefix（第 63-70 行）：

```tsx
        <Input
          id="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          disabled={loading}
          placeholder={copy.auth.usernamePlaceholder}
          autoComplete="username"
          prefix={<UserOutlined />}
        />
```

(3c) 密码 Input.Password 增加 prefix（第 73-80 行）：

```tsx
        <Input.Password
          id="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={loading}
          placeholder={copy.auth.passwordPlaceholder}
          autoComplete="current-password"
          prefix={<LockOutlined />}
        />
```

(3d) `</Form>` 之后、`);` 之前追加底部行（第 85 行）：

```tsx
      <div className="login-card-foot">
        <span className="login-forgot">忘记密码？</span>
        <span className="login-version">V1.0</span>
      </div>
    </Form>
  );
```

- [ ] **Step 4: 修改 globals.css 表单区**

(4a) `.login-panel`（第 257 行）改为米色渐变 + 定位，并追加光晕：

```css
.login-panel { flex: 1; display: flex; align-items: center; justify-content: center; background: linear-gradient(180deg,#fdfaf6 0%,#f6efe8 100%); padding: 48px; position: relative; }
.login-panel::before { content: ""; position: absolute; inset: 0; background: radial-gradient(circle at 100% 0%, rgba(217,99,19,.07), transparent 45%); }
```

(4b) `.login-card`（第 258 行）改为（圆角 18、双层阴影、渐变条、overflow hidden）：

```css
.login-card { width: 100%; max-width: 390px; background: #fff; border-radius: 18px; padding: 40px 36px; box-shadow: 0 16px 40px rgba(90,50,20,.12), 0 2px 6px rgba(90,50,20,.04); border: 1px solid var(--warm-border); position: relative; overflow: hidden; }
.login-card::before { content: ""; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg,#d96313,#b94f0c,#e8963e); }
```

(4c) `.login-card .ant-input, .login-card .ant-input-password`（第 261 行）改为：

```css
.login-card .ant-input, .login-card .ant-input-password { height: 44px; border-radius: 10px; border-color: #e4d6c9; background: #fdfbf9; }
```

(4d) `.login-card .ant-btn-primary`（第 263 行）改为：

```css
.login-card .ant-btn-primary { height: 46px; font-weight: 700; font-size: 15px; border-radius: 11px !important; box-shadow: 0 10px 22px rgba(201,84,12,.30); letter-spacing: .2em; }
```

(4e) `.login-submit`（第 265 行）之后追加 prefix 与底部行样式：

```css
.login-card .ant-input-prefix { background: #fbeee1; border-radius: 7px; padding: 5px; color: #c97b3d; margin-right: 8px; }
.login-card-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; font-size: 10px; color: #b3947c; }
.login-forgot { color: #c9691e; font-weight: 600; }
```

- [ ] **Step 5: 运行确认通过**

Run: `npx vitest run "src/app/(auth)/login/page.test.tsx" src/app/globals.test.ts`
Expected: PASS（page.test.tsx 7 个 + globals.test.ts 5 个全过）

- [ ] **Step 6: 提交**

```bash
git add "src/components/auth/login-form.tsx" "src/app/(auth)/login/page.test.tsx" src/app/globals.css
git diff --cached --name-only
git commit -m "feat: polished login form card with icons and footer"
```

（提交前核对暂存区只含这 3 个文件）

---

### Task 3: 集成验证

**Files:** 无代码改动

**Interfaces:**
- Consumes: Task 1 + Task 2

- [ ] **Step 1: 前端全量测试**

Run: `npx vitest run`
Expected: 573 passed / 12 failed 基线（失败文件必须仍为已知 5 个文件：use-run-event-stream / run-stream-reducer / thought-narrative / run-diagnostics / user-management，与本改动零交集；若超出立即停下报告）

- [ ] **Step 2: 类型检查**

Run: `npx tsc --noEmit`
Expected: 无本改动文件的新错误（既有测试文件错误记录并继续）

- [ ] **Step 3: 手动视觉清单（dev 核对）**

`npm run dev` 后浏览器打开 `http://localhost:3000/login`（宽屏 ≥961px）逐项核对：

1. 品牌区：深橙渐变（#cf5a10 起）、26px 网格、9 条神经连线、8 个脉动光点（2 个慢速）、脑形徽章（旋转虚线环 + 发光橙核）、橙焰 AI 胶囊（白字 + 绿点）
2. 表单区：米色渐变面板 + 左上角橙色光晕、卡片顶部橙渐变细条、用户名/密码输入框带圆角图标、聚焦橙色描边、渐变登录按钮（字距拉开）、底部"忘记密码？"橙字 + "V1.0"
3. 系统开启"减少动态效果"（Windows 设置 → 辅助功能 → 动画效果）时：光点与虚线环动画静止
4. 缩放窗口 ≤960px：品牌区隐藏、表单正常

- [ ] **Step 4: 记录验证结果**

无需提交；在交付说明中记录视觉清单核对结果。

---

## Self-Review

- **Spec 覆盖**：① 渐变/网格/聚焦光晕 ✅ Task 1(4a/4b)；② SVG/光点/脑形/胶囊 ✅ Task 1(3/4c)；③ keyframes + reduced-motion ✅ Task 1(4c)；④ 面板/卡片/输入框/按钮/底部行 ✅ Task 2(4a-4e, 3d)；⑤ 测试 ✅ Task 1(1)/Task 2(1)；⑥ 不做的事（忘记密码纯视觉、无新依赖）✅ Task 2 只用 span + antd 图标。
- **占位符扫描**：全部步骤含完整代码与命令，无 TBD。
- **类型一致性**：类名（.login-brain/.login-node/.login-ai-chip/.login-card-foot/.login-forgot）在测试与实现中逐字符一致；SVG 坐标与 mockup 一致；断言字符串与写入 CSS 逐字符一致（每任务红→绿闭环）。
