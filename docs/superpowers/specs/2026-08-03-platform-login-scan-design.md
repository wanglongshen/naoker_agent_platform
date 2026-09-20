# 平台扫码登录（抖音/小红书登录态获取）设计

**日期:** 2026-08-03
**状态:** 已确认设计

## 1. 背景与目标

当前方案（`2026-08-03-douyin-deep-scrape-design.md`）通过用户 Cookie 解决抖音/小红书反爬问题，但要求用户手动从浏览器开发者工具复制 Cookie 字符串——**非技术用户无法完成此操作**。

本设计的目标：让用户通过**手机扫码**方式完成抖音/小红书登录态配置，零技术门槛。用户点击"扫码登录"→ 弹窗显示服务器浏览器的实时画面（二维码）→ 手机 App 扫码 → 登录态自动存入系统 → agent 抓取自动使用。

**已确认约束：**
- 部署形态：**服务器部署**，用户通过浏览器远程访问
- 交互范围：**仅扫码 + 刷新**（MVP，不做点击/键盘交互）
- 过期处理：**自动检测验证页 → 标记登录态过期 → 引导重新扫码**
- 方案选择：**仅方案 A（托管浏览器扫码）**，不做手动粘贴入口
- 多租户隔离：每个用户的登录态只能自己使用，用户之间、超管均不可见

## 2. 架构

```
┌────────────┐  截图轮询(800ms)   ┌──────────────────┐
│  前端 Modal │ ◄───────────────  │ API 层            │
│  (扫码画面)  │ ── start/status ─► │ /api/agent/      │
└────────────┘                   │  login-sessions/* │
                                └────────┬─────────┘
                                         │ 接管会话
                                ┌────────▼─────────┐
                                │ web_renderer 进程  │
                                │ LoginSessionManager│
                                │ (按用户隔离 context)│
                                └────────┬─────────┘
                                         │ 登录成功自动
                                ┌────────▼─────────┐
                                │ user_web_cookies 表 │
                                │ (复用 AES 加密)      │
                                └──────────────────┘
```

- **LoginSessionManager** 运行在现有 `web_renderer` 进程内（新增模块），管理登录会话生命周期
- 每个会话 = 一个独立 Playwright browser context + 独立临时用户数据目录，按 `owner_user_id` 隔离
- 登录成功后自动导出 cookies → 写入现有 `user_web_cookies` 表（复用 `feishu/crypto.py` 的 AES-GCM 加密）
- 抓取链路（`_fetch_web_content` 自动加载 Cookie）**零改动**

## 3. API 设计

端点前缀 `/api/agent/`（归属校验见第 5 节）：

| 端点 | 请求 | 作用 |
|---|---|---|
| `POST /login-sessions` | `{"platform": "douyin" \| "xiaohongshu"}` | 启动扫码会话，返回 `{session_id, status}` |
| `GET /login-sessions/{id}/frame` | — | 取最新截图帧，返回 `{image: <jpeg base64>}` |
| `GET /login-sessions/{id}/status` | — | 返回 `{status: waiting_scan\|logged_in\|timeout\|error, detail?}` |
| `POST /login-sessions/{id}/refresh` | — | 重新加载登录页（二维码失效时） |
| `DELETE /login-sessions/{id}` | — | 用户关闭弹窗时取消会话 |

登录 URL 映射：
- `douyin` → `https://www.douyin.com/`（未登录会自动跳转/呈现扫码登录）
- `xiaohongshu` → `https://www.xiaohongshu.com/explore`（未登录呈现登录弹层）

## 4. 登录会话生命周期

1. **启动**：`start(owner_user_id, platform)` → 创建独立 context + 临时用户数据目录（`var/login_sessions/<user_id>/<session_id>/`）→ 打开平台登录页 → 状态 `waiting_scan`
2. **轮询截图**：前端每 800ms 取一帧（JPEG，quality 60，缩放至宽度 ≤ 900px）
3. **登录成功检测（双保险）**：
   - 信号检测（每 1.5s）：URL 变化 + 页面出现已登录特征（用户头像/昵称/首页流元素）+ context 中出现登录凭证 cookie（抖音 `pass_token`，小红书 `web_session`）——凭证 cookie 出现是强信号
   - 信号命中后，用该 context 抓一次平台首页，返回非验证页且 text 长度 > 500 才判定 `logged_in`
4. **登录成功**：导出 context cookies → `save_user_cookie(owner_user_id, domain, cookie_string)` → 关闭 context → 删除数据目录 → 状态 `logged_in`（前端自动关闭弹窗，列表刷新）
5. **超时**：总时长 10 分钟未成功 → 状态 `timeout` → 清理资源
6. **主动取消**：`DELETE` → 立即清理
7. **孤儿回收**：进程启动时扫描 `var/login_sessions/`，删除 last_modified > 10 分钟的数据目录（崩溃恢复）

## 5. 多租户隔离（三条铁律）

1. **会话归属校验**：所有 `login-sessions/{id}/*` 端点校验 `session.owner_user_id == current_user.id`，非本人一律 403
2. **存储天然隔离**：`user_web_cookies` 所有读写按 `owner_user_id` 过滤（现有实现已如此）；**不新增任何跨用户查看端点**；超管没有管理入口——超管看到的列表也只是自己的
3. **Agent 抓取身份绑定**：`_fetch_web_content` 加载 Cookie 时 `owner_user_id` 严格取发起会话的用户本人；代码审计确认 worker 传参链路无替换他人 ID 的路径

## 6. 过期检测闭环

- `_fetch_web_content` 返回中增加 `login_expired: bool`：
  - 判定条件：渲染结果 `platform` 命中（douyin/xiaohongshu）且 text 命中验证页特征（`captcha`/`verify_data`/`验证中间页`）且 text 长度 < 500
- agent 在回复中提示"抖音登录态已过期，请重新扫码登录"
- 前端：会话消息附带提示；平台登录中心徽标显示"已过期"，点击"重新扫码"一键续期

## 7. 前端交互

**"平台登录中心" Modal**（改造现有 `web-cookie-modal.tsx`）：
- 平台卡片列表：抖音、小红书，各显示状态徽标 `未登录 / 已登录`
- 状态来源：`GET /api/agent/cookies`（已有）——有记录 = 已登录，无记录 = 未登录
- 点"扫码登录"→ 内嵌弹窗：实时画面（截图轮询）+ "二维码失效？刷新"按钮 + 关闭按钮
- 登录成功后自动回到列表并刷新状态
- **移除手动粘贴 Cookie 表单**（原 Cookie 字符串输入框删除；列表仅展示 domain 与状态，不展示明文/密文）
- 过期提示：agent 检测到 `login_expired` 时在回复文本中提示"登录态已过期，请打开平台登录中心重新扫码"；用户据此手动重新扫码（MVP 不跨会话持久化过期状态）

## 8. 错误处理

| 场景 | 行为 |
|---|---|
| 启动失败（Playwright 不可用） | 返回错误，前端提示"登录服务不可用，请稍后重试" |
| 平台改版/网络异常 | 状态 `error`，前端提示刷新重试 |
| 同一用户已有活跃会话 | 拒绝新会话，返回"已有进行中的登录，请先完成或取消"（409） |
| 二维码过期 | 前端显示"二维码失效"，用户点刷新 |
| 登录态过期抓取 | agent 提示 + 前端徽标"已过期" |

## 9. 测试策略

- **单元**：登录会话状态机转换（waiting_scan→logged_in/timeout）、验证页特征识别函数、Cookie 字符串转 Playwright cookie 列表（已有）、数据目录清理逻辑、per-user 并发互斥
- **集成（mock Playwright）**：启动→模拟登录完成→断言 cookies 写入 `user_web_cookies`（解密后含凭证 cookie 名）
- **隔离测试**：用户 B 访问用户 A 的会话帧/状态 → 403；用户 B 的列表看不到 A 的平台；用户 A 抓取不加载用户 B 的 Cookie
- **前端**：tsc 编译检查

## 10. YAGNI（不做）

- 点击/键盘交互的远程浏览器（仅扫码+刷新）
- 同一用户多会话并发
- 平台扩展界面化（卡片配置项预留扩展点，MVP 仅抖音+小红书）
- 手动粘贴 Cookie 入口
- 跨用户查看/管理登录态的端点

## 11. 复用与改动清单

**新增：**
- `backend/app/services/agent/login_session.py`（LoginSessionManager + 检测逻辑）
- `backend/app/api/agent_login_sessions.py`（登录会话路由）
- `backend/tests/test_login_session.py`、`backend/tests/test_agent_login_sessions.py`
- `frontend/src/components/feishu/platform-login-modal.tsx`（平台登录中心 + 扫码弹窗）

**修改：**
- `backend/app/workers/web_renderer.py`（挂载 LoginSessionManager 路由）
- `backend/app/services/agent/tool_executor.py`（`login_expired` 字段）
- `backend/app/services/agent/planner.py`（提示词：过期提示文案）
- `frontend/src/components/feishu/web-cookie-modal.tsx`（改造为平台登录中心，移除手动粘贴）
- `frontend/src/components/layout/conversation-top-bar.tsx`（按钮文案/图标）

**不变：**
- `user_web_cookies` 表结构与存储层（`web_cookie_store.py`）
- 加密方案（`feishu/crypto.py`）
- 抓取链路（`render_page` 签名与返回结构，仅新增 `login_expired` 判定）
