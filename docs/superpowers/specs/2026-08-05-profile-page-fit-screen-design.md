# 个人资料页一屏居中设计

日期：2026-08-05
状态：已批准

## 背景与目标

个人资料页（frontend/src/components/profile/profile-page.tsx）当前内容纵向堆叠，普通屏幕下超出视口需滚动，且内容左对齐。目标：内容在**一个屏幕内完整放下**，且**整体水平居中**（双卡并排）。

## 布局结构

- 页面根容器改为全高居中：`display: flex; min-height: 100%; justify-content: center; align-items: center`——PageHeader、横幅、双卡作为整体在屏幕内垂直水平居中。实现时验证 `min-height: 100%` 对 `.warm-executive-content` 生效；不生效则改用 `min-height: calc(100dvh - 顶栏高度)`（顶栏高度以实际布局为准，实现时确认）
- 内容列 `max-width: 960px; width: 100%` 作为居中单元

## 双卡并排

- 新增 `.profile-cards` 包裹层：`display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 20px`——左「基本信息」、右「安全设置」
- 卡片 `margin-top: 0`（由 grid 控制）；padding 28px → 24px

## 紧凑化（保证一屏）

- 横幅 padding 32px → 28px；头像 88px → 80px；姓名 22px → 20px；信息列 gap 8px → 6px
- 卡标题 padding-bottom 16px → 12px、margin-bottom 20px → 16px
- 表单 max-width 460px 不变（两栏各约 440px 宽）
- 密码说明文字、按钮、提示文字不变

## 响应式

- `<900px`：双卡回退纵向堆叠（此时允许页面滚动）
- `<768px`：横幅纵向逻辑保留（现有规则不动）

## 组件与 CSS 改动

- `frontend/src/components/profile/profile-page.tsx`：双卡包进 `.profile-cards` div；根容器加居中类（或 `style`）；其余 JSX 不变
- `frontend/src/app/globals.css`：追加/修改 `.profile-cards`、根居中类；调整 `.profile-hero`/`.profile-card`/`.profile-card-title` 的间距值

## 测试

`frontend/src/components/profile/profile-page.test.tsx`：
- 现有 5 个测试选择器全部不受影响（label/按钮文案/结构类名不变）
- 新增 1 个断言：两个 `.profile-card-title` 同时渲染（双卡并存）

**验收**：`npx vitest run src/components/profile/profile-page.test.tsx` 全绿（5 既有 + 1 新增）；`npx eslint` 0 errors。
