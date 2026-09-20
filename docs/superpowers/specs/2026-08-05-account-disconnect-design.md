# 账号退出/换号功能设计

日期：2026-08-05
状态：已批准

## 背景与目标

用户连接飞书账号后无法退出/更换；小红书/抖音登录态无法显式退出。目标：三个平台都支持"退出登录 → 换其他账号"。

## 现状

- 飞书（frontend/src/components/feishu/feishu-connect.tsx + backend/app/api/feishu.py）：OAuth 连接与 status 已实现，**无断开端点**，已连接按钮为 disabled
- 平台登录（frontend/src/components/feishu/platform-login-modal.tsx + backend/app/api/agent_cookies.py）：登录态 = 域名 cookie（www.douyin.com / www.xiaohongshu.com）；`DELETE /api/agent/cookies/{domain}` 端点已存在但前端未暴露；"重新扫码"可覆盖换号

## 飞书退出

**后端**（backend/app/api/feishu.py 新增 + backend/app/services/feishu/client.py）：
- `FeishuClient` 新增 `revoke_token(access_token: str) -> dict`：调飞书 `POST /auth/v3/revoke`（token 换 user_access_token 的 header 方式，与既有 client 一致）
- 新增 `DELETE /api/feishu/connection`：
  - 查当前用户 FeishuToken；无记录 → 200（幂等）
  - 有记录：先尽力 `revoke_token(decrypt(access_token))`（失败仅 logging 警告，不阻塞）；然后删除记录、commit
  - 返回 `success(request, {"connected": False})`

**前端**（feishu-connect.tsx）：
- connected 时：按钮文案改"退出飞书"（DisconnectOutlined 图标），`Popconfirm` 确认 → `DELETE /api/feishu/connection`（csrf: true）→ 成功 message + `setConnected(false)`（按钮变回"连接飞书"）
- 换号流程：退出后点"连接飞书"重新 OAuth

## 平台退出（小红书/抖音）

**前端**（platform-login-modal.tsx）：
- PLATFORMS 行内，`logged` 为 true 时在"重新扫码"按钮旁加"退出登录"按钮（Popconfirm 确认）→ `DELETE /api/agent/cookies/{domain}`（csrf: true）→ 成功 `load()` 刷新（Tag 变"未登录"）
- "重新扫码"按钮保留

## 测试

- 后端 tests/test_feishu.py（若存在则追加，否则新建）：连接后 `DELETE /connection` → 200 且 `/status` 变 connected=false；无 token 时 DELETE → 200；revoke 抛异常时仍删除本地记录（monkeypatch FeishuClient.revoke_token 抛错）
- 前端新建 feishu-connect.test.tsx：connected 渲染"退出飞书"按钮；点击确认调 DELETE；成功后显示"连接飞书"；未连接显示"连接飞书"
- 前端新建 platform-login-modal.test.tsx：已登录行渲染"退出登录"按钮；点击确认调 `DELETE /api/agent/cookies/www.douyin.com`；成功后 Tag 变"未登录"（mock /api/agent/cookies 响应变化）
- 前端测试遵循 jsdom 病理约束（querySelectorAll + textContent，禁页面级 byRole）

**验收**：后端 feishu 相关测试全绿；前端两个新测试文件全绿；`npx eslint` 无新增 error。
