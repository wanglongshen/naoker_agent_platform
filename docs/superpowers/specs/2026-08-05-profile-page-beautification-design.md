# 个人资料页美化设计

日期：2026-08-05
状态：已批准

## 背景与目标

个人资料页 `/settings/profile`（frontend/src/components/profile/profile-page.tsx）当前为单列朴素排布：头像+按钮与两个表单竖排在一张 DataSurface 里，缺乏层次与系统质感。目标：按系统 Warm Intelligence 设计语言（米色底 #FAF7F3、暖橙主色 #D96313、深棕侧栏、暖色阴影、大圆角）重做为"通栏横幅 + 双卡"结构，视觉精致且与系统一致。

## 页面结构

```
PageHeader「个人资料 / 管理你的头像、基本信息和密码」
├── 通栏横幅（米白底）
│    光环头像 96px | 姓名 / @账号 · 角色Tag / 邮箱 | [上传头像] [移除头像]
│    （右上角淡橙装饰同心圆）
├── 卡1 基本信息（UserOutlined 图标标题 + 分隔线）
│    姓名（前缀 UserOutlined）/ 邮箱（MailOutlined）/ 手机号（PhoneOutlined）
│    [保存]（SaveOutlined，primary）
└── 卡2 安全设置（LockOutlined 图标标题 + 分隔线）
      旧密码 / 新密码 / 确认新密码（前缀 LockOutlined）
      说明文字：新密码需至少 8 位，且同时包含字母和数字
      [修改密码]（SafetyOutlined，primary）
```

## 视觉细节

**横幅 `.profile-hero`**：
- 背景 `var(--color-bg-subtle)`，圆角 `var(--radius-lg)`，内边距 32px，position: relative，底部内侧 1px 淡橙描边（`color-mix(in srgb, var(--color-primary) 18%, transparent)`）
- 装饰：绝对定位右上角两个同心圆（`border: 1px solid color-mix(in srgb, var(--color-primary) 22%, transparent)`，直径 180px/120px，border-radius 50%），pointer-events: none，不遮挡按钮
- 头像：外层 `.profile-avatar-ring`（padding 4px，`background: linear-gradient(140deg, var(--color-primary), #fba05a)`，border-radius 50%）包 `<Avatar size={88}>`；无头像时显示 UserOutlined 图标
- 信息列：姓名 22px/700 `--color-text-primary`；`@账号` 14px `--color-text-muted`；角色标签：每个角色一个 Tag（background `--color-primary-soft`、字色 `--color-primary`、border-radius 999px、padding 2px 10px、font-size 12px）；邮箱 13px `--color-text-secondary` 带 MailOutlined 小图标
- 按钮组（margin-left: auto，垂直居中）：上传头像 = primary 按钮（UploadOutlined）；移除头像 = danger text 按钮（DeleteOutlined），仅 avatarUrl 存在时显示；其下 12px muted 提示"支持 PNG/JPG/GIF/WebP，不超过 2MB"
- 布局：flex 行，头像与信息列 gap 24px，按钮组推至右侧

**双卡 `.profile-card`**：
- 白底 `--color-surface`，圆角 `--radius-lg`，阴影 `--shadow-sm`，padding 28px，margin-top 24px
- 卡标题行：图标 18px（`--color-primary`）+ 标题 17px/600 + 底部 1px `--color-border` 分隔线，下边距 20px；「基本信息」UserOutlined、「安全设置」LockOutlined
- 表单宽度 max-width 460px；输入框 prefix 图标（User/Mail/Phone/Lock 对应）；label 12.5px `--color-text-secondary`
- 提交按钮 primary + 图标（SaveOutlined / SafetyOutlined）；密码卡末尾说明文字 12px `--color-text-muted`

**响应式**：横幅在 768px 以下改为纵向（头像居中、按钮跟随信息列下方左对齐）；双卡内容窄不受影响。

## 组件与交互改动

- `profile-page.tsx` JSX 重构为三段（横幅 + 卡1 Form + 卡2 Form）；新增元素：光环头像容器、装饰圆环、角色 Tag 列表（`currentUser.roles`）、`@账号`、邮箱行、前缀图标、按钮图标、密码说明文字
- 新增全局 CSS 类到 `frontend/src/app/globals.css`：`.profile-hero`、`.profile-avatar-ring`、`.profile-decor-circle`、`.profile-info`、`.profile-name`、`.profile-account`、`.profile-roles`、`.profile-card`、`.profile-card-title`
- 头像上传/移除、保存资料、修改密码的 handler 与 API 调用（api()/csrf/FormData）**零改动**；隐藏 `input[type="file"]` 保留

## 测试

`frontend/src/components/profile/profile-page.test.tsx`：
- 现有 4 个测试选择器全部继续命中（Form label 与按钮文案不变：姓名/邮箱/手机号/旧密码/新密码/确认新密码、保 存/修改密码、`input[type="file"]`）
- 新增 1 个断言测试：横幅渲染 @账号与角色标签（mock currentUser 带 roles）
- 测试约束：禁止页面级 byRole（jsdom 病理），沿用 querySelectorAll+textContent 模式

**验收**：`npx vitest run src/components/profile/profile-page.test.tsx` 全绿（4 既有 + 1 新增）；`npx eslint` 0 errors；后端无改动。
