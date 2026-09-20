# 平台登录获取设计（手动 Cookie 导入 + 半自动登录窗口）

- 日期：2026-08-07
- 背景：抖音/小红书登录在自动化（无头）环境下被平台风控静默拦截——短信验证码发送被拒、扫码后强制验证、弹窗静默关闭。根因是平台对自动化浏览器指纹的短信/登录接口拦截（日志证据：fill 正确、点击成功、但无验证码到达且弹窗关闭）。
- 方案：**双路径**——A. 手动 Cookie 导入（通用，含无桌面远端 Linux）；B. 半自动可见窗口登录（本机有桌面环境）。两者登录态统一存入 `user_web_cookies`（AES-GCM 加密），后续搜索/详情抓取无头 + cookie 注入。

## 1. 范围

**改**：后端 `agent_cookies.py`（新增 import 端点）、`login_session.py`（可见窗口）、前端平台登录中心（platform-login-modal.tsx）。
**不改**：`/search`、`/detail`（无头渲染 + cookie 注入）、`fetch_platform_search`、笔记采集链路。

## 2. 方案 A：手动 Cookie 导入

### 2.1 后端 `POST /api/agent/cookies/import`

- 入参：`{cookies: [{name, value, domain, path, expires, secure, httpOnly}]}`（Cookie-Editor "Export as JSON" 格式，≤500 条）
- 鉴权：`get_current_user` + `require_csrf`
- 校验（任一不满足 → 422）：
  - `cookies` 非空列表
  - 每条 name/value 为非空字符串
  - domain 解析后 host 匹配 `douyin.com` / `xiaohongshu.com` 或其子域（含 `.douyin.com` 前缀点号形式）
- 处理：过滤无效项 → 按平台分组（douyin.com 后缀 → douyin，xiaohongshu.com 后缀 → xiaohongshu）→ 复用 `cookies_to_string`（`name=value; ...`）→ `save_user_cookie(owner, DOMAIN_BY_PLATFORM[platform], cookie_str)`
- 响应：`{saved: {platform: count}}`（不返回 cookie 内容）
- 存储/注入复用现有链路：`_parse_cookie_string`（tool_executor）在搜索/详情时把 `name=value; ...` 还原为 Playwright cookie 列表

### 2.2 前端（平台登录中心）

- 新增"手动导入 Cookie"tab（每平台入口或统一 tab）：
  - Textarea 粘贴 JSON + 保存按钮
  - 三步指引：① Chrome 打开平台网页并登录 ② 安装 Cookie-Editor 扩展 → Export as JSON ③ 粘贴保存
  - 保存成功 → 提示"已保存 {N} 条，可开始搜索"；422 → 显示错误

## 3. 方案 B：半自动可见窗口登录（替换现有无头扫码）

### 3.1 可见窗口

`_default_browser_factory` 的 chromium.launch 改为 `headless=False`（登录会话专用；搜索/详情路径的 `render_page` 不受影响）。

### 3.2 窗口生命周期

| 事件 | 行为 |
|---|---|
| 用户完成登录（`detect_login_signal` 命中 + `assess_login_expired` 不命中） | status=logged_in → `_export_cookie` 存库 → 关闭浏览器 |
| 用户手动关闭窗口 | watch 循环 evaluate 异常 + `page.is_closed()` → status=error，detail="window_closed" |
| 超时（TTL 900s） | status=timeout → 关闭浏览器 |
| 无桌面环境（launch 失败） | status=error，detail="environment_no_display: 当前环境无桌面，请使用手动导入 Cookie 登录" |
| 平台拦截页（platform_blocked） | 保留现有重试逻辑 |

`_watch_login` 异常处理增强：区分"窗口已关"（window_closed）与瞬时错误（继续轮询）。

### 3.3 TTL

`SESSION_TTL_SECONDS` 改为 900（15 分钟）。

### 3.4 现有机制保持不变

- 会话池 / supersede（重复发起自动作废旧会话）
- `_export_cookie` / `save_user_cookie`（AES-GCM 加密）
- verify 表单检测与提交（可见窗口下用户直接在窗口操作，代码路径保留）

## 4. 前端登录中心改动

1. 移除二维码展示（`/frame` 轮询删除）——扫码入口改为可见窗口模式：
   - `starting`："正在打开浏览器窗口…"
   - `waiting_scan`："浏览器窗口已弹出，请在弹出的窗口中扫码或完成登录（无桌面环境请改用手动导入 Cookie）"
   - `logged_in`：成功提示（现有）
   - `timeout`："登录超时，请重新发起"
   - `error`：显示 detail（window_closed / environment_no_display 有专用文案）
2. 新增"手动导入 Cookie"tab（方案 A）
3. 800ms `/status` 轮询保持

## 5. 测试

### 后端

1. **import API**（test_agent_cookies.py）：有效 JSON 保存（按平台分组、count 正确）、domain 白名单拒绝（evil.com → 422）、空/无效项过滤、CSRF 缺失失败、cookie 加密存储（DB 无明文）
2. **可见窗口**（test_login_session_manager.py）：launch 带 headless=False 断言
3. **窗口关闭**：evaluate 异常 + is_closed() → error/window_closed
4. **无桌面**：launch 抛异常 → error/environment_no_display
5. **TTL**：SESSION_TTL_SECONDS == 900 断言
6. 既有测试回归（supersede / verify / 登录成功导出 / platform_blocked 重试）

### 前端

7. 手动导入 tab 渲染 + 提交（mock api）
8. 状态提示文案（starting/waiting_scan/logged_in/error）
9. `/frame` 不再被调用

## 6. 风险与对策

| 风险 | 对策 |
|---|---|
| 无桌面环境窗口不显示 | launch 失败 → environment_no_display 明确提示；A 路径兜底 |
| 用户关窗口后 watch 误判 | is_closed() 检测区分 window_closed 与瞬时错误 |
| 15 分钟 TTL 占用会话池 | supersede 自动清理；timeout 自动关窗 |
| 导入 cookie 过期 | 过期后搜索降级 login_required；用户重新导入/可见窗口登录 |
| 导入 cookie 含敏感值 | 加密存储（现有）；响应不返回内容；日志不打印 value |

## 7. 验收标准

1. 手动导入：粘贴 Cookie-Editor JSON → 保存成功 → `fetch_platform_search` 带登录态（非 login_required）
2. 可见窗口（本机）：发起登录 → 弹出窗口 → 用户完成登录 → logged_in → cookie 自动存库
3. 无桌面环境（远端）：可见窗口启动失败 → 明确提示改用手动导入
4. 用户关闭窗口 → "登录窗口已关闭"提示（非静默卡死）
5. 超时 15 分钟 → timeout + 窗口自动关闭
6. `/search` `/detail` 保持无头（不受影响）
