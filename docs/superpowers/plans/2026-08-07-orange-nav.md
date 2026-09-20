# 顶栏橙色化 + 侧栏点缀 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 顶部导航栏（会话页 + 管理页）改为品牌橙渐变一体样式，左侧导航栏加点缀装饰（网格/光晕/圆环/眉标/白胶囊按钮/选中橙点）。

**Architecture:** Task 1 侧栏：globals.css 样式 + app-sidebar.tsx JSX（脑字 logo、眉标、+号方块、装饰层）+ globals.test.ts 断言；Task 2 顶栏：agent-globals.css 样式 + conversation-top-bar.tsx JSX（小徽标、平台登录按钮类名）。两任务都改 globals.test.ts——严格串行 1→2→3。

**Tech Stack:** CSS 渐变/伪元素、Next.js 客户端组件、antd（Button/Avatar/Menu dark 覆盖）、vitest（readFileSync 断言 CSS 文本）。

**Spec:** `docs/superpowers/specs/2026-08-07-orange-nav-design.md`（`eaf932b`）

## Global Constraints

- 品牌橙渐变：`linear-gradient(160deg,#e8751d 0%,#d96313 50%,#b94f0c 100%)`（侧栏与顶栏同款）
- 状态色一律暖橙（`#ffd9a8` / `#f97316`），**不得出现绿色**
- 不动布局结构与菜单项、不加动画
- 测试断言与写入 CSS 文本逐字符一致；`--color-sidebar` 断言同步更新
- 前端测试基线：576 passed / 12 既有失败（已知文件，不得新增）
- 并行会话可能在操作同一仓库：提交前 `git diff --cached --name-only` 核对，只精确 add 自己的文件

---

### Task 1: 侧栏点缀美化

**Files:**
- Modify: `frontend/src/components/layout/app-sidebar.tsx`（品牌 mark 脑字、眉标、+号方块、装饰层）
- Modify: `frontend/src/app/globals.css`（变量、渐变、装饰、品牌区、新对话按钮、选中橙点、分组尾线）
- Modify: `frontend/src/app/globals.test.ts`（--color-sidebar 断言 + 追加侧栏断言）

**Interfaces:**
- Consumes: 无
- Produces: `.sidebar-decor*` / `.new-chat-plus` / `.sidebar-descriptor` 类（Task 2 不依赖）

- [ ] **Step 1: 追加失败测试**

`frontend/src/app/globals.test.ts`：

(1a) 在 `"defines the shared warm-intelligence design tokens in :root"` 测试中：

```ts
  expect(css).toContain("--color-sidebar: #D96313");
```
改为：
```ts
  expect(css).toContain("--color-sidebar: #e8751d");
```

(1b) 文件末尾追加：

```ts
test("sidebar embellishment: gradient, decor, brand and new-chat styles", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

  expect(css).toContain("background: linear-gradient(160deg,#e8751d 0%,#d96313 50%,#b94f0c 100%);");
  expect(css).toContain(".sidebar-decor-ring { position: absolute; right: -34px; top: 96px; width: 110px; height: 110px;");
  expect(css).toContain(".new-chat-plus { width: 17px; height: 17px; border-radius: 5px;");
  expect(css).toContain(".sidebar-brand::after { content: \"\"; position: absolute; left: 18px; right: 18px; bottom: -1px; height: 1px;");
  expect(css).toContain(".sidebar-management .ant-menu-dark .ant-menu-item-selected::after");
});
```

- [ ] **Step 2: 运行确认失败**

Run（frontend/ 目录）: `npx vitest run src/app/globals.test.ts`
Expected: FAIL

- [ ] **Step 3: 修改 app-sidebar.tsx**

(3a) 品牌区（约 176-181 行），原：

```tsx
          <div className="sidebar-brand-mark">
            <DatabaseOutlined />
          </div>
          <div className="sidebar-brand-copy">
            <span className="sidebar-title">{PRODUCT_NAME}</span>
          </div>
```

改为：

```tsx
          <div className="sidebar-brand-mark">脑</div>
          <div className="sidebar-brand-copy">
            <span className="sidebar-title">{PRODUCT_NAME}</span>
            <span className="sidebar-descriptor">AGENT WORKSPACE</span>
          </div>
```

(3b) 在 `<nav aria-label="主导航" className="app-sidebar">` 之后（`.sidebar-brand` div 之前）插入装饰层：

```tsx
      <div className="sidebar-decor" aria-hidden="true">
        <span className="sidebar-decor-ring" />
        <span className="sidebar-decor-ring sidebar-decor-ring--dashed" />
        <span className="sidebar-decor-spark" />
        <span className="sidebar-decor-spark sidebar-decor-spark--slow" />
      </div>
```

(3c) 开始新对话按钮（约 184-189 行），原：

```tsx
        <Link href="/agent" className="new-chat-link" onClick={onNavigate}>
          <RobotOutlined aria-hidden="true" style={{ marginRight: 8 }} />
          开始新对话
        </Link>
```

改为：

```tsx
        <Link href="/agent" className="new-chat-link" onClick={onNavigate}>
          <span className="new-chat-plus" aria-hidden="true">+</span>
          开始新对话
        </Link>
```

- [ ] **Step 4: 修改 globals.css**

(4a) 第 6-7 行变量：

```css
  --color-sidebar: #e8751d;
```

(4b) `.enterprise-sidebar`（第 66 行）改为：

```css
.enterprise-sidebar { flex-shrink: 0; width: 248px; background: linear-gradient(160deg,#e8751d 0%,#d96313 50%,#b94f0c 100%); display: flex; flex-direction: column; min-height: 0; transition: width 0.25s ease, margin-left 0.25s ease; position: relative; z-index: 50; overflow: hidden; }
```

(4c) `.app-sidebar`（第 83 行）改为（加 ::before 网格 + 光晕）：

```css
.app-sidebar { display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; height: 100%; min-height: 0; overflow: hidden; position: relative; }
.app-sidebar::before { content: ""; position: absolute; inset: 0; background-image: linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px), radial-gradient(ellipse at 50% 120%, rgba(255,255,255,.16), transparent 60%); background-size: 30px 30px, 30px 30px, auto; pointer-events: none; z-index: 1; }
```

(4d) `.sidebar-brand`（第 84 行）改为（去 border-bottom，加 ::after 光带）：

```css
.sidebar-brand { display: flex; align-items: center; padding: 26px 20px 22px; flex: 0 0 auto; position: relative; z-index: 2; }
.sidebar-brand::after { content: ""; position: absolute; left: 18px; right: 18px; bottom: -1px; height: 1px; background: linear-gradient(90deg, rgba(255,255,255,.28), rgba(255,255,255,.02)); }
```

(4e) `.sidebar-brand-mark`（第 86 行）改为：

```css
.sidebar-brand-mark { flex-shrink: 0; width: 34px; height: 34px; background: #fff; border-radius: 9px; display: flex; align-items: center; justify-content: center; color: #c74e0b; font-size: 16px; font-weight: 800; box-shadow: 0 4px 12px rgba(0,0,0,.20), 0 0 14px rgba(255,255,255,.25); }
```

(4f) `.sidebar-descriptor`（第 89 行）改为：

```css
.sidebar-descriptor { font-size: 8px; font-weight: 700; color: rgba(255,255,255,.48); letter-spacing: .2em; text-transform: uppercase; display: flex; align-items: center; gap: 5px; }
.sidebar-descriptor::before { content: ""; width: 4px; height: 4px; border-radius: 50%; background: #ffd9a8; box-shadow: 0 0 5px 1px rgba(255,217,168,.7); }
```

(4g) `.sidebar-new-chat .new-chat-link`（第 102 行）改为：

```css
.sidebar-new-chat .new-chat-link { background: rgba(255,255,255,.94); color: #a03c08; border-color: transparent; font-size: 13px; height: 40px; font-weight: 700; box-shadow: 0 4px 12px rgba(0,0,0,.16); display: flex; align-items: center; justify-content: center; gap: 8px; }
.new-chat-plus { width: 17px; height: 17px; border-radius: 5px; background: linear-gradient(135deg,#d96313,#b94f0c); color: #fff; font-size: 11px; display: flex; align-items: center; justify-content: center; line-height: 1; flex-shrink: 0; }
```

(4h) 菜单选中橙点（`.sidebar-management .ant-menu-dark .ant-menu-item-selected .anticon` 规则后追加）：

```css
.sidebar-management .ant-menu-dark .ant-menu-item-selected::after { content: ""; position: absolute; right: 12px; top: 50%; transform: translateY(-50%); width: 5px; height: 5px; border-radius: 50%; background: #f97316; box-shadow: 0 0 6px 2px rgba(249,115,22,.5); }
```

(4i) `.sidebar-group-label`（`.sidebar-session-list-wrapper .sidebar-group-label`）改为 + 追加尾线：

```css
.sidebar-session-list-wrapper .sidebar-group-label { color: rgba(255,255,255,.45); display: flex; align-items: center; gap: 6px; }
.sidebar-session-list-wrapper .sidebar-group-label::after { content: ""; flex: 1; height: 1px; background: linear-gradient(90deg, rgba(255,255,255,.14), transparent); }
```

(4j) `.sidebar-decor` 装饰系列（文件末尾追加）：

```css
.sidebar-decor { position: absolute; inset: 0; overflow: hidden; pointer-events: none; z-index: 1; }
.sidebar-decor-ring { position: absolute; right: -34px; top: 96px; width: 110px; height: 110px; border: 1px solid rgba(255,255,255,.14); border-radius: 50%; }
.sidebar-decor-ring--dashed { right: -20px; top: 110px; width: 82px; height: 82px; border: 1px dashed rgba(255,255,255,.12); }
.sidebar-decor-spark { position: absolute; right: 26px; top: 34px; width: 6px; height: 6px; border-radius: 50%; background: rgba(255,255,255,.8); box-shadow: 0 0 8px 3px rgba(255,255,255,.35); }
.sidebar-decor-spark--slow { right: 64px; top: 170px; width: 4px; height: 4px; }
```

注意：`.app-sidebar` 是 grid 容器，装饰层 z-index 1、grid 子元素在文档流中默认 z-index auto——`.sidebar-brand` 等关键区块已设 z-index 2（4d 改了 brand；menu/sessions/foot 若被遮挡需同样加 position relative + z-index 2，检查后补充，保持内容可点）。

- [ ] **Step 5: 运行确认通过**

Run: `npx vitest run src/app/globals.test.ts`
Expected: PASS（全过）

- [ ] **Step 6: 提交**

```bash
git add src/components/layout/app-sidebar.tsx src/app/globals.css src/app/globals.test.ts
git diff --cached --name-only
git commit -m "feat: sidebar embellishments - gradient, decor, brand mark, new-chat button"
```

（核对暂存区只含 3 个文件）

---

### Task 2: 顶栏橙色化

**Files:**
- Modify: `frontend/src/app/agent-globals.css`（.conversation-top-bar / .app-header 橙色化 + 按钮胶囊 + logo）
- Modify: `frontend/src/components/layout/conversation-top-bar.tsx`（小徽标 + 平台登录按钮类名）
- Modify: `frontend/src/app/globals.test.ts`（追加 agent-globals.css 断言）

**Interfaces:**
- Consumes: Task 1 已完成（无接口依赖）
- Produces: `.top-bar-logo` / `.top-bar-login` 类

- [ ] **Step 1: 追加失败测试**

`frontend/src/app/globals.test.ts` 末尾追加：

```ts
test("orange top bars: gradient, white text, pill buttons and logo", () => {
  const css = readFileSync(resolve(process.cwd(), "src/app/agent-globals.css"), "utf8");

  expect(css).toContain(".conversation-top-bar {");
  expect(css).toContain("background: linear-gradient(160deg,#e8751d 0%,#d96313 50%,#b94f0c 100%);");
  expect(css).toContain(".top-bar-logo { width: 26px; height: 26px;");
  expect(css).toContain(".conversation-top-bar .ant-btn { background: rgba(255,255,255,.16); color: #fff; border: 1px solid rgba(255,255,255,.38); border-radius: 14px;");
  expect(css).toContain(".top-bar-login { background: rgba(255,255,255,.94); color: #a03c08;");
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run src/app/globals.test.ts`
Expected: FAIL（新测试找不到对应规则）

- [ ] **Step 3: 修改 conversation-top-bar.tsx**

(3a) 小徽标——`<h1>{PRODUCT_NAME}</h1>` 改为：

```tsx
      <span className="top-bar-logo" aria-hidden="true">脑</span>
      <h1>{PRODUCT_NAME}</h1>
```

(3b) 平台登录按钮加类名：

```tsx
      <Button className="top-bar-login" icon={<QrcodeOutlined />} onClick={() => setCookieModalOpen(true)}>平台登录</Button>
```

- [ ] **Step 4: 修改 agent-globals.css**

(4a) `.conversation-top-bar`（约 3004 行）改为：

```css
.conversation-top-bar {
  flex: 0 0 56px;
  min-height: 56px;
  display: flex;
  align-items: center;
  padding: 0 28px;
  background: linear-gradient(160deg,#e8751d 0%,#d96313 50%,#b94f0c 100%);
  border-bottom: 1px solid rgba(255,255,255,.16);
  position: relative;
  gap: 10px;
}
.conversation-top-bar::after { content: ""; position: absolute; left: 0; right: 0; bottom: -1px; height: 1px; background: linear-gradient(90deg, rgba(255,255,255,.4), rgba(255,255,255,.05)); }
```

(4b) `.conversation-top-bar h1`（约 3023 行）改为：

```css
.conversation-top-bar h1 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: #fff;
  flex: 1;
  letter-spacing: -.01em;
}
```

(4c) 在 `.conversation-top-bar h1` 规则后追加：

```css
.top-bar-logo { width: 26px; height: 26px; border-radius: 8px; background: rgba(255,255,255,.94); display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 800; color: #c74e0b; box-shadow: 0 3px 8px rgba(0,0,0,.14); flex-shrink: 0; }
.conversation-top-bar .ant-btn { background: rgba(255,255,255,.16); color: #fff; border: 1px solid rgba(255,255,255,.38); border-radius: 14px; height: 28px; padding: 0 12px; font-size: 11px; display: inline-flex; align-items: center; gap: 6px; }
.conversation-top-bar .ant-btn::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: #ffd9a8; box-shadow: 0 0 6px 2px rgba(255,217,168,.6); }
.conversation-top-bar .ant-btn:hover { background: rgba(255,255,255,.26); color: #fff; }
.top-bar-login { background: rgba(255,255,255,.94) !important; color: #a03c08 !important; box-shadow: 0 3px 8px rgba(0,0,0,.15); }
.top-bar-login::before { display: none !important; }
.top-bar-login:hover { background: #fff !important; color: #a03c08 !important; }
.conversation-top-bar .top-bar-user-btn { color: #fff; display: flex; align-items: center; gap: 8px; background: transparent; border: none; cursor: pointer; }
.conversation-top-bar .top-bar-user-name { color: rgba(255,255,255,.85); font-size: 12px; font-weight: 600; }
.conversation-top-bar .top-bar-avatar { box-shadow: inset 0 0 0 2px rgba(255,255,255,.45); }
```

(4d) `.app-header`（约 169 行）改为：

```css
.app-header { display: flex; align-items: center; justify-content: space-between; height: 56px; padding: 0 28px; background: linear-gradient(160deg,#e8751d 0%,#d96313 50%,#b94f0c 100%); border-bottom: 1px solid rgba(255,255,255,.16); position: relative; }
.app-header::after { content: ""; position: absolute; left: 0; right: 0; bottom: -1px; height: 1px; background: linear-gradient(90deg, rgba(255,255,255,.4), rgba(255,255,255,.05)); }
.app-header .ant-btn { color: #fff; }
.app-header .ant-btn:hover { color: rgba(255,255,255,.8); }
.app-header .header-avatar { background: #fff !important; box-shadow: inset 0 0 0 2px rgba(255,255,255,.45); }
```

（`.app-header` 原规则若含其他属性，保留其余部分只替换背景/边框；`.header-avatar` 原是 `background: var(--warm-primary)`，改为白底白描边，头像内 UserOutlined 图标为橙字 `color:#c74e0b` 追加一条 `.app-header .header-avatar .anticon { color: #c74e0b; }`）

- [ ] **Step 5: 运行确认通过**

Run: `npx vitest run src/app/globals.test.ts`
Expected: PASS（全过）

- [ ] **Step 6: 提交**

```bash
git add src/app/agent-globals.css src/components/layout/conversation-top-bar.tsx src/app/globals.test.ts
git diff --cached --name-only
git commit -m "feat: orange top bars with logo, pill buttons and white text"
```

（核对暂存区只含 3 个文件）

---

### Task 3: 集成验证

**Files:** 无代码改动

**Interfaces:**
- Consumes: Task 1 + Task 2

- [ ] **Step 1: 前端全量测试**

Run: `npx vitest run`
Expected: 576 passed / 12 failed 基线（失败文件必须仍为已知文件：use-run-event-stream / run-stream-reducer / thought-narrative / run-diagnostics / user-management / 其他并行会话文件；超出立即停下报告）

- [ ] **Step 2: 类型检查**

Run: `npx tsc --noEmit`
Expected: 无本改动文件的新错误（既有测试文件错误记录并继续）

- [ ] **Step 3: 手动视觉清单（dev 核对）**

`npm run dev` 后浏览器逐项核对：

1. 会话页 `http://localhost:3000/agent`：顶栏橙色渐变 + 白字产品名 + "脑"小徽标 + 半透明胶囊（飞书连接带暖橙点）+ 白底「平台登录」+ 头像白描边
2. 管理页（如 `/users`）：顶栏同款渐变 + 白字 + 白色头像
3. 侧栏：三色渐变 + 网格纹理 + 底部光晕 + 右上圆环/光点 + "脑"字 logo 柔光 + AGENT WORKSPACE 眉标（橙点）+ 白胶囊「+ 开始新对话」+ 选中菜单项右侧橙光点 + 分组标签渐变尾线
4. 菜单/会话列表 hover 与点击正常（装饰层不遮挡交互）

- [ ] **Step 4: 记录验证结果**

无需提交；交付说明中记录视觉清单核对结果。

---

## Self-Review

- **Spec 覆盖**：① 顶栏渐变/白字/logo/胶囊/头像 ✅ Task 2(4a-4d, 3a-3b)；② 管理页顶栏 ✅ Task 2(4d)；③ 侧栏渐变/网格/光晕/装饰 ✅ Task 1(4a-4c, 4j)；④ 品牌区脑字/眉标/光带 ✅ Task 1(3a, 4d-4f)；⑤ 新对话白胶囊 ✅ Task 1(3c, 4g)；⑥ 选中橙点/分组尾线 ✅ Task 1(4h-4i)；⑦ 无绿色 ✅ 全部暖橙；⑧ 测试 ✅ 两任务红绿闭环。
- **占位符扫描**：全部步骤含完整代码，无 TBD。
- **类型一致性**：类名（.top-bar-logo/.top-bar-login/.sidebar-decor*/.new-chat-plus）在测试与实现中逐字符一致；断言字符串与写入 CSS 一致。
