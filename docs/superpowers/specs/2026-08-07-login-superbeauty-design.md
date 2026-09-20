# 登录页超级美化 · 科技神经设计

日期：2026-08-07
状态：设计定稿（浏览器 mockup 三轮确认：B 方向 → 细化版 → 角标变体 2 + 表单美化）

## 1. 背景与目标

登录页当前为"橙色渐变 + 光晕 + 网格 + 眉标/标题/描述/底部字"（`baec270` 已落地）。用户要求**超级美化**：左侧品牌区升级为"科技神经"主题（脑形光晕徽章 + 神经网络节点连线 + 脉动光点），右侧表单区同步精致化。经 mockup 确认：

- **方向**：B · 科技神经（脑壳主题——脑形徽章 + 节点光网）
- **AI 角标**：变体 2 · 橙焰胶囊（橙色渐变胶囊 + 白字 + 绿色发光状态点）
- **表单区**：顶部橙色渐变细条 + 带图标输入框 + 聚焦橙色描边 + 渐变登录按钮

## 2. 改动清单

### 2.1 左侧品牌区（`login/page.tsx` + `globals.css`）

**结构（page.tsx 品牌区新增元素，在 `.login-brand` 内）**：

1. **神经网络 SVG**：内联 SVG（viewBox 320×460、preserveAspectRatio="xMidYMid slice"），9 条连线 `stroke="rgba(255,255,255,.26)" stroke-width="1"`（坐标按 mockup login-b-detail.html 原样）
2. **脉动光点 ×8**：`<span className="login-node">` 定位 div（7px 白圆 + 发光 + `pulse` 动画，间隔分布；2 个 `login-node--slow`）
3. **脑形光晕徽章**：`.login-brain`（150×150，`border-radius: 46% 54% 55% 45% / 50% 46% 54% 50%`，半透明白渐变 + 1.5px 白边 + 内阴影 + 外发光），`::before` 旋转虚线圆环（inset 22px、`spin` 30s 线性），`::after` 发光橙核（36px 径向渐变 `#ffd9a8 → #f97316` + 大光晕）；定位 `right: 36px; top: 50%; translateY(-50%)`
4. **AI 橙焰胶囊**：`.login-ai-chip`（右上角悬浮，22px 高胶囊，`linear-gradient(135deg,#f97316,#c2410c)`，白字 "AI" 字重 800 字距 .08em，右侧 5px 绿点 `#4ade80` 发光，圆角 11px、阴影、1px 白边 35%）
5. **网格纹理**：`.login-brand::before` 现有网格 `background-size: 34px 34px` → **26px 26px**；`::before` 白色光晕两层保留，新增第三层径向 `rgba(255,255,255,.16)` 椭圆光晕于 78% 40%（品牌区右侧聚焦徽章处）
6. **品牌区渐变加深**：`linear-gradient(160deg,#d96313 0%,#c74e0b 55%,#b94f0c 100%)` → `linear-gradient(155deg,#cf5a10 0%,#b94f0c 55%,#9a3d0a 100%)`（与 mockup 一致）

**动画（globals.css 新增 keyframes）**：

```css
@keyframes login-pulse { 0%,100% { opacity: .55; transform: scale(.9); } 50% { opacity: 1; transform: scale(1.15); } }
@keyframes login-spin { to { transform: rotate(360deg); } }
```

- `.login-node { animation: login-pulse 3.2s ease-in-out infinite; }`、`.login-node--slow { animation-duration: 4.6s; }`
- `.login-brain::before { animation: login-spin 30s linear infinite; }`
- **尊重 reduced-motion**：`@media (prefers-reduced-motion: reduce) { .login-node, .login-brain::before { animation: none; } }`

### 2.2 右侧表单区（`login-form.tsx` + `globals.css`）

1. **面板背景**（`.login-panel`）：`background: var(--warm-workspace)` → `linear-gradient(180deg,#fdfaf6 0%,#f6efe8 100%)`，并叠加左上橙色光晕（`::before` radial `rgba(217,99,19,.07)`，45% 截止）
2. **卡片**（`.login-card`）：圆角 16px → 18px；阴影加深（`0 16px 40px rgba(90,50,20,.12), 0 2px 6px rgba(90,50,20,.04)`）；顶部加 3px 橙色渐变细条（`::before { content:""; position:absolute; top:0; left:0; right:0; height:3px; background:linear-gradient(90deg,#d96313,#b94f0c,#e8963e); }`，需 `overflow:hidden`）
3. **输入框**（`.login-card .ant-input/.ant-input-password`）：height 42px → 44px、圆角 10px、背景 `#fdfbf9`；**prefix 图标**（login-form.tsx 给用户名/密码输入框加 `prefix={<UserOutlined />}` / `prefix={<LockOutlined />}`，antd 自带，图标容器圆角底色 `#fbeee1`、橙字——用 CSS：`.login-card .ant-input-prefix { background:#fbeee1; border-radius:7px; padding:5px; color:#c97b3d; margin-right:8px; }`）；聚焦态已有橙描边 + 光晕（保留）
4. **按钮**：`height: 44px → 46px`、圆角 11px、阴影加重（`0 10px 22px rgba(201,84,12,.30)`）、`letter-spacing: .2em`
5. **卡片底部行**：新增"忘记密码"（橙字 `#c9691e`，暂为纯文本不接跳转）+ "V1.0" 版本号小字（`.login-card-foot`，`display:flex; justify-content:space-between; margin-top:14px; font-size:10px; color:#b3947c;`）——**登录表单内**（login-form.tsx 底部，antd Form 之后）

### 2.3 测试

- `login/page.test.tsx`：追加断言——品牌区存在 `.login-brain`（`container.querySelector(".login-brain")`）、AI 胶囊文本 "AI"、`login-node` 数量 8
- `globals.test.ts`：追加断言——`login-pulse` keyframes、`login-brand` 渐变含 `#cf5a10`、`.login-card::before` 渐变条、`.login-card .ant-input-prefix` 规则
- 既有断言（脑壳工作台/AI SOLUTION WORKSPACE/BRAIN SHELL/描述文案）不变

## 3. 不做的事

- 不动布局结构（左品牌区/右表单区比例、断点隐藏逻辑）
- 不加"忘记密码"实际功能（仅视觉占位；真实找回密码不在本期）
- 不动导航栏与其他页面（本 spec 只覆盖登录页）
- 不加第三方图标库（用 antd 内置 UserOutlined/LockOutlined）

## 4. 验证方式

1. 前端测试：`login/page.test.tsx` + `globals.test.ts` + 全量回归（基线 573 passed / 12 既有失败，失败文件与本改动零交集）
2. 手动视觉清单（浏览器）：
   - 品牌区：深橙渐变 + 26px 网格 + 神经连线 + 8 个脉动光点 + 脑形徽章（旋转虚线环 + 发光橙核）+ 橙焰 AI 胶囊
   - 表单区：米色渐变面板 + 左上光晕 + 卡片渐变条 + 图标输入框 + 渐变按钮 + 底部行
   - `prefers-reduced-motion` 下动画静止
