# 平台扫码登录修复与美化 设计

**日期:** 2026-08-03
**状态:** 已确认设计

## 1. 背景与目标

扫码登录功能（`2026-08-03-platform-login-scan-design.md`）已实现，但实测发现**二维码无法显示**：服务器上裸 headless Chromium 访问抖音（首页/登录页）和小红书全部被反爬拦截（抖音"验证中间页"、小红书"安全验证页"），二维码从未渲染，截图自然无内容。同时扫码弹窗 UI 较朴素，需要美化。

**已确认约束：**
- 部署目标：**Linux 服务器**；开发环境为 Windows（功能必须两平台一致可用）
- 反爬方案：**patchright**（跨平台，API 兼容 Playwright）
- 美化风格：**简约现代**（白底卡片、圆角阴影、状态胶囊），只动扫码弹窗，不重构全局 UI
- 流程改进：二维码真实渲染后才进入 `waiting_scan`；检测不到则明确报错，不让用户对着空白画面干等

## 2. 根因（已实测验证）

### 2.1 初版根因（探针 1-3，patchright headless）

patchright 以 headless 模式访问三个 URL，全部被拦或空白（补丁式 stealth JS 亦无效）：

| URL | patchright headless-shell | patchright 完整 chromium headless | Edge headless |
|---|---|---|---|
| `https://www.douyin.com/` | 验证中间页 | 验证中间页 | 验证中间页 |
| `https://www.douyin.com/login` | 空白页 | 空白页 | 空白页 |
| `https://www.xiaohongshu.com/explore` | 安全验证页 | 安全验证页 | 安全验证页 |

### 2.2 关键实验（探针 4：headed 真实窗口，Edge channel）

| URL | Edge headed（真实窗口） |
|---|---|
| `https://www.douyin.com/` | ✅ 正常首页（24 img，含 2 个 qr-like 元素，登录弹层二维码） |
| `https://www.douyin.com/login` | 空白页（该路径无内容，弃用） |
| `https://www.xiaohongshu.com/explore` | ✅ 正常（61 img，6 个二维码元素） |

**结论：headless 状态本身就是检测点**——与驱动（playwright/patchright）、内核（headless-shell/完整 chromium）、channel（chromium/Edge）无关；真实窗口模式（headed）全部通过。因此方案从"仅 patchright 反检测"升级为 **patchright + headed + xvfb 纵深组合**。

## 3. 反爬对抗（patchright + headed + xvfb）

- 依赖：`pip install patchright`，部署时执行 `patchright install chromium`（写入部署说明）
- **浏览器启动模式**（关键）：`headless=False`（真实窗口）。Windows 开发机直接弹窗（扫码直观可见）；Linux 生产服务器用 **xvfb** 虚拟显示承载真实窗口（`xvfb-run -a` 包装启动命令，对平台无感）
- **channel 配置**：`Settings.web_renderer_channel: str | None = None`（未设置时按平台推断：Windows → `msedge` 本机已装；Linux → `None` 即 patchright 自带 chromium）；`Settings.web_renderer_headless: bool = False`
- 替换点（仅导入与启动，逻辑不变）：
  - `backend/app/services/agent/web_renderer.py`：`from playwright.async_api import async_playwright` → `from patchright.async_api import async_playwright`；launch 参数 `headless=get_settings().web_renderer_headless, channel=get_browser_channel()`
  - `backend/app/services/agent/login_session.py`：`_default_browser_factory` 同上替换
- 保留现有 stealth JS（webdriver 删除、chrome 对象、languages）与随机 UA
- 登录 URL 保持既有 `LOGIN_URLS` 首页（`douyin.com/` 未登录即弹二维码，实测 2 个 qr-like 元素；`xiaohongshu.com/explore` 实测 6 个）——**不用** `douyin.com/login`（实测空白）

## 4. 二维码检测与状态机改进

**规则：`waiting_scan` = 二维码真的渲染出来了。**

```
goto 登录页
  └─► 轮询检测二维码元素（每 1s，最多 20s，QR_WAIT_TIMEOUT=20）
        ├─ 出现 → 状态 waiting_scan（前端显示截图，可扫码）
        └─ 超时 → 状态 error（分级 detail，见下）
```

- **二维码识别**（`QR_SELECTORS: dict[str, list[str]]`，每平台候选 selector 列表 + 兜底规则）：
  - 候选 selector：`img[src*="qrcode"]`、`canvas`、登录容器内 `img`
  - 兜底规则：页面**非验证页**（复用 `is_verification_page`）且出现任一 `img` 元素 → 视为疑似二维码
  - 初始候选（E2E 实测后可按平台校准）：douyin 与 xiaohongshu 通用 `["img[src*='qrcode']", "canvas", "img"]` + 兜底
- **错误分级**（`detail` 字段，前端据此显示不同文案）：
  - `platform_blocked` → 页面命中验证页特征 → "平台安全验证拦截，请稍后重试"
  - `qr_timeout` → 20 秒未检测到二维码 → "二维码加载超时，请点击刷新"
  - `browser_failed` → Playwright 启动/导航异常 → "浏览器启动失败，请稍后重试"
- 截图轮询、凭证检测（`detect_login_signal`）、双保险验证、cookie 导出链路**全部不变**

## 5. 前端美化（简约现代）

**平台列表视图**（Modal 主体）：
- 平台卡片：圆形平台图标（CSS 实现：抖音=黑底音符 "♪"，小红书=红底 "红"）+ 平台名 + 右侧状态胶囊（`已登录`=绿 / `未登录`=灰）+ "扫码登录"主按钮
- 卡片 hover 微阴影、圆角 10px、浅灰底

**扫码弹窗视图**：
- 顶部：平台名 + 状态徽标（"等待扫码"带呼吸动画圆点）
- 中部：二维码容器——白底卡片、圆角 12px、内边距 16px、居中；加载中显示 Spin；二维码图片圆角 8px、最大宽 300px
- 引导文案："打开 {平台} App 扫一扫，确认登录"
- 底部操作区：主按钮"刷新二维码" + 次级"取消登录"
- 错误提示条：红底圆角，按错误分级显示文案 + "重试"按钮（重试 = 重新 POST 启动会话）

## 6. 改动范围

**新增：** 无新文件（复用现有组件）

**修改：**
- `backend/app/core/config.py`：新增 `web_renderer_headless: bool = False`、`web_renderer_channel: str | None = None` 与 `get_browser_channel()` 平台推断助手
- `backend/app/services/agent/login_session.py`：patchright 导入；headed launch + channel；`QR_SELECTORS` 常量；`_wait_for_qr(record)` 方法（返回 True/raise 分级错误）；`_open_and_watch` 流程接入
- `backend/app/services/agent/web_renderer.py`：patchright 导入；headed launch + channel
- `backend/requirements.txt`（或等价依赖清单）：加 `patchright`
- `frontend/src/components/feishu/platform-login-modal.tsx`：样式与错误处理升级
- `backend/tests/test_login_session_manager.py`：追加 QR 等待路径测试
- 部署说明（`README.md` 或等价位置）：`patchright install chromium` + Linux 生产 `xvfb-run` 启动方式

**不变：** `web_cookie_store.py`、`tool_executor.py`、`planner.py`、`agent_login_sessions.py`、worker 端点、API 层、`conversation-top-bar.tsx`

## 7. 测试策略

- **单测（追加到 test_login_session_manager.py）**：
  - QR 检测函数分支：候选 selector 命中 / 兜底命中 / 验证页不命中
  - `_wait_for_qr` 超时 → `qr_timeout` 错误；验证页 → `platform_blocked`；命中 → `waiting_scan`
  - 路径：fake context 扩展 `query_selector` 返回元素或 None（按注入场景）
- **E2E（真实）**：重启 worker → 前端"平台登录"→ 抖音扫码 → 手机确认 → 断言卡片"已登录" + agent 抓取返回真实内容（非验证页）
- **前端**：`tsc --noEmit` 无新错误
- **反爬通过率不做自动化断言**（只能真实 E2E 验证）

## 8. YAGNI（不做）

- 代理 IP 池、验证码自动破解、登录态模拟（不引入账号安全风险）
- 全局 UI 重构
- UI 组件测试框架引入
- 平台 selector 的运行时热配置（代码常量即可）
