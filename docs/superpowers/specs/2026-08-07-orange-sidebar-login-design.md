# 左侧导航栏 + 登录页左侧 · 品牌橙视觉设计

日期：2026-08-07
状态：设计定稿（用户已在浏览器 mockup 中确认：方向 B 品牌橙 + 导航栏选中态"白底橙字"）

## 1. 背景与目标

当前左侧导航栏（`.enterprise-sidebar`）与登录页左侧品牌区（`.login-brand`）均为**深棕黑渐变 + 橙色点缀**（`--color-sidebar: #2A1812`、`--color-sidebar-elevated: #3B271F`，登录页 `#170d09 → #2b1b15 → #1f1211`）。用户要求整体改为**品牌橙**，风格：简洁、好看、大气、专业。

经浏览器 mockup 三轮确认（3 方向对比 → 细化 → 定稿）：

- **配色**：B · 品牌橙渐变 `#D96313 → #C74E0B → #B94F0C`（延续项目现有主色 `--color-primary: #D96313`，全站按钮/链接/选中态天然统一）
- **导航栏选中态**：白底橙字（`background:#fff; color:#a03c08` + 轻阴影），对比最强
- **登录页左侧**：橙渐变 + 右上/左下双层光晕 + 极淡网格纹理 + 眉标/标题/描述/底部小字

## 2. 改动清单（全部在 `frontend/src/app/globals.css` + 2 处同色文字）

### 2.1 主题变量（驱动渐变两端）
- `:root` 中 `--color-sidebar: #2A1812` → `#D96313`
- `:root` 中 `--color-sidebar-elevated: #3B271F` → `#B94F0C`

一处改动自动带动：`.enterprise-sidebar` 渐变、`.enterprise-navigation-drawer .ant-drawer-body`、`.warm-executive-sider`（legacy 布局）。

### 2.2 导航栏（sidebar）细项
- `.sidebar-brand-mark`：橙渐变 logo（`linear-gradient(140deg,#fba05a,var(--warm-primary))`）→ **白底橙字**（`background:#fff; color:#c74e0b`），与登录页 mark 一致（橙色底上的 logo 不再用橙渐变）
- `.sidebar-management .ant-menu-dark .ant-menu-item-selected`：半透明橙 `rgba(232,117,22,.18)` + 橙色左边条 → **白底橙字**（`background:#fff; color:#a03c08; font-weight:700; box-shadow:0 3px 10px rgba(0,0,0,.18)`），删除左边条或改为 `border-left` 保留？——**删除左边条**（白底已足够强）
- `.sidebar-management .ant-menu-dark .ant-menu-item-selected .anticon`：`color: var(--warm-primary)` → `#a03c08`
- `.sidebar-session-list-wrapper .session-item-active`：半透明橙 `rgba(232,117,22,.14)` → **半透明白** `rgba(255,255,255,.20)` + 左边条改白色（会话列表在橙底上）
- 菜单普通项文字 `rgba(255,255,255,.72)`、hover 半透明白、账户区/徽章半透明白：**不变**（橙底上均自然协调）

### 2.3 登录页左侧（`.login-brand`）
- 背景：`linear-gradient(160deg,#170d09 0%,#2b1b15 55%,#1f1211 100%)` → `linear-gradient(160deg,#d96313 0%,#c74e0b 55%,#b94f0c 100%)`
- `::before` 光晕：`rgba(224,107,18,...)` 橙色光晕（橙底上不可见）→ **白色调**（`rgba(255,255,255,.18)` / `.10` 两处），并叠加极淡网格纹理（`linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px) 34px` 网格）
- `.login-brand-mark`：橙渐变 → **白底橙字**（`background:#fff; color:#c74e0b`），`::after` 白色内框线删除或改橙
- 标题 `#fdf8f2`、描述 `rgba(253,248,242,.50)`：**不变**（白字在橙底对比良好）
- 新增眉标（kicker）与底部小字：可选，**不做**（保持现有结构最小改动；文案与结构不动）

### 2.4 同色系文字（跟随深棕 → 橙的语义一致性）
- `frontend/src/app/(agent)/account/points/page.tsx:14` `INK = "#2A1812"` → `#7C4A32` 或保留深棕？——**保留不动**（积分页正文文字用深棕是内容色，非导航品牌色，改橙色会降低可读性）。⚠️ 若用户希望全站深棕改为橙，另行处理——本期不动。
- `frontend/src/components/users/redeem-codes-modal.tsx:143` 同理由，**不动**

### 2.5 测试同步
- `frontend/src/app/globals.test.ts:16` 断言 `--color-sidebar: #2A1812` → 更新为 `#D96313`（并补 `--color-sidebar-elevated: #B94F0C` 断言）

## 3. 不做的事

- 不动导航栏/登录页的**布局结构**与**文案**（标题、描述原样）
- 不动登录页右侧表单卡配色（已是白卡 + 橙色主按钮）
- 不动其他页面的配色（正文深棕文字保留，可读性优先）
- 不加暗色主题切换（现无此机制）
- 不动 `--color-primary` 本身（按钮/链接/焦点全站主色，已是 #D96313）

## 4. 验证方式

1. 前端测试：`globals.test.ts` 更新后全量回归（基线 539 passed / 11 既有失败，失败文件与本改动零交集）
2. 手动视觉清单（改动后浏览器逐项核对）：
   - 登录页 `http://localhost:3000/login`：左侧橙色渐变 + 光晕 + 网格 + 白字
   - 导航栏：橙渐变背景、品牌 logo 白底橙字、选中菜单白底橙字、会话列表选中态半透明白
   - 移动端（≤960px）：登录页左侧隐藏逻辑不变
