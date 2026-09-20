# 顶部导航栏橙色化 + 侧栏点缀美化 设计

日期：2026-08-07
状态：设计定稿（浏览器 mockup 四轮确认：A 一体橙 → 细化版 → 点缀增强 → 去绿点/去头像点）

## 1. 背景与目标

顶部导航栏（`.conversation-top-bar` 会话页 / `.app-header` 管理页）目前为白底；左侧导航栏已是品牌橙但平淡。用户要求：**顶部导航栏也变橙色**，两侧导航栏再点缀美化。最终确认稿 = A · 一体橙 + 点缀增强版（去掉全部绿色元素与头像状态点，状态色统一暖橙 `#ffd9a8`）。

## 2. 改动清单

### 2.1 顶栏橙色化（`agent-globals.css` + `conversation-top-bar.tsx` + `app-header.tsx`）

1. **背景渐变**：`.conversation-top-bar`（agent-globals.css:3004）`background: var(--color-bg-surface)` → `linear-gradient(160deg,#e8751d 0%,#d96313 50%,#b94f0c 100%)`；`border-bottom` → `1px solid rgba(255,255,255,.16)`；追加 `::after` 渐变高光线（`linear-gradient(90deg, rgba(255,255,255,.4), rgba(255,255,255,.05))`，位于底部 1px）
2. **产品名**：`.conversation-top-bar h1` → `color: #fff`
3. **小徽标**：conversation-top-bar.tsx 在 `<h1>` 前加 `<span className="top-bar-logo" aria-hidden="true">脑</span>`；CSS：26×26 白底橙字圆角 8px + 轻阴影
4. **按钮胶囊化**（`.conversation-top-bar .ant-btn` 统一）：默认**半透明胶囊**（`background: rgba(255,255,255,.16); color: #fff; border: 1px solid rgba(255,255,255,.38); border-radius: 14px;`），并加 `::before` 暖橙状态点（`#ffd9a8` 5px 发光）；平台登录按钮 JSX 加 `className="top-bar-login"` → **白底橙字**（`background: rgba(255,255,255,.94); color: #a03c08;`，清除 `::before` 圆点）
5. **头像区**：`.top-bar-user-btn` 文字 `color: #fff`；`.top-bar-user-name` `rgba(255,255,255,.85)`；`.top-bar-avatar` 白色描边
6. **管理页顶栏**：`.app-header`（agent-globals.css:169）同款渐变 + 白字（菜单按钮/标题/账户下拉白字），头像描边白色

### 2.2 侧栏点缀（`globals.css` + `app-sidebar.tsx`）

1. **渐变**：`.enterprise-sidebar`（globals.css:66）→ `linear-gradient(160deg,#e8751d 0%,#d96313 50%,#b94f0c 100%)` + `overflow: hidden`；`:root` `--color-sidebar: #D96313` → `#e8751d`（drawer 同步）
2. **网格 + 底部光晕**：`.app-sidebar::before`（absolute inset 0、pointer-events none、z-index 1）：30px 网格 `rgba(255,255,255,.045)` + 底部 110px 径向光晕 `radial-gradient(ellipse at 50% 120%, rgba(255,255,255,.16), transparent 60%)`；`.app-sidebar` 内容 z-index ≥ 2
3. **装饰元素**：app-sidebar.tsx 品牌区后加 `<div className="sidebar-decor" aria-hidden="true"><span className="sidebar-decor-ring" /><span className="sidebar-decor-ring sidebar-decor-ring--dashed" /><span className="sidebar-decor-spark" /><span className="sidebar-decor-spark sidebar-decor-spark--slow" /></div>`；CSS：容器 absolute inset 0 overflow hidden pointer-events none；ring 110px 细圆（`border:1px solid rgba(255,255,255,.14)`，right:-34px top:96px）+ dashed 82px（`border:1px dashed rgba(255,255,255,.12)`，right:-20px top:110px）；spark 6px 白圆发光（right:26px top:34px）+ 4px 慢点（right:64px top:170px）
4. **品牌区**：
   - mark 内容 `DatabaseOutlined` → **"脑"字**（app-sidebar.tsx JSX），CSS 加 `box-shadow: 0 4px 12px rgba(0,0,0,.20), 0 0 14px rgba(255,255,255,.25)`
   - 加**眉标**：`sidebar-title` 后加 `<span className="sidebar-descriptor">AGENT WORKSPACE</span>`（类已存在 globals.css:89，改样式：白 48% + `::before` 4px 暖橙点 `#ffd9a8` 发光）
   - `.sidebar-brand` 的 `border-bottom` → 渐变光带 `::after`（`linear-gradient(90deg, rgba(255,255,255,.28), rgba(255,255,255,.02))`，1px，bottom:-1px）
5. **开始新对话**：`.new-chat-link` 改白胶囊（`background: rgba(255,255,255,.94); color: #a03c08; font-weight: 700; box-shadow: 0 4px 12px rgba(0,0,0,.16);`）；JSX 内图标换为 `<span className="new-chat-plus" aria-hidden="true">+</span>`（17px 橙渐变方块 `linear-gradient(135deg,#d96313,#b94f0c)` 白字）
6. **菜单选中**：`.sidebar-management .ant-menu-dark .ant-menu-item-selected::after` 加右侧暖橙光点（`content:""; position:absolute; right:12px; top:50%; transform:translateY(-50%); width:5px; height:5px; border-radius:50%; background:#f97316; box-shadow:0 0 6px 2px rgba(249,115,22,.5);`）——antd menu item 自带 position relative，直接生效
7. **会话分组标签**：`.sidebar-session-list-wrapper .sidebar-group-label` 色值 `rgba(255,255,255,.25)` → `.45`，加 `::after` 渐变尾线（flex 1、`linear-gradient(90deg, rgba(255,255,255,.14), transparent)`）

### 2.3 测试

- `globals.test.ts`：追加断言——`.enterprise-sidebar` 含 `#e8751d`、`.app-sidebar::before` 网格、`.sidebar-decor-ring`、`.new-chat-plus`、`.sidebar-brand::after` 渐变
- `globals.test.ts` 新增读取 `agent-globals.css` 的断言块——`.conversation-top-bar` 渐变、`.top-bar-logo`、`.conversation-top-bar .ant-btn` 胶囊、`.top-bar-login` 白底
- 既有断言（`--color-sidebar: #D96313`）→ 同步为 `#e8751d`；组件测试（h1 文本/品牌链接名）不受影响（grep 确认无 DatabaseOutlined 测试引用）

## 3. 不做的事

- 不做飞书连接"已连接/未连接"状态区分（统一半透明胶囊 + 橙点，视觉一致）
- 不在会话列表行加状态点（选中态已有白色左边条，避免动列表结构）
- 不加动画（登录页已表达动态诉求，导航栏保持静态专业）
- 不动顶栏/侧栏布局结构与菜单项
- 绿色元素全部排除（状态色统一暖橙 #ffd9a8 / #f97316）

## 4. 验证方式

1. 前端测试：globals.test.ts + 全量回归（基线 576 passed / 12 既有失败）
2. 手动视觉清单：会话页顶栏橙色渐变 + 白字 + 小徽标 + 胶囊按钮（平台登录白底、飞书连接半透明带橙点）+ 头像；管理页顶栏同款；侧栏网格/光晕/圆环/光点/眉标/白胶囊新对话/选中橙点/分组尾线
