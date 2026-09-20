# DSH 侧栏合并 · 验收清单

- 计划：`docs/superpowers/plans/2026-09-12-dsh-sidebar-merge.md`
- 设计：`docs/superpowers/specs/2026-09-12-dsh-sidebar-merge-design.md`
- 视觉稿：`.superpowers/brainstorm/ui-merge-01/content/layout-merge-v4.html`、`states-v5.html`

## 自动化验证（已通过）

| 项 | 命令 | 结果 |
|---|---|---|
| 插件包全量测试 | `cd dsh-platform/packages/server-connector && npx vitest run` | 5 files / 22 tests passed |
| 插件包类型检查 | `pnpm run typecheck` | exit 0 |
| 前端定向测试（侧栏/路由/桥） | `cd frontend && npm test -- --run src/components/layout src/components/agent/dsh-nav-section.test.tsx src/components/dsh "src/app/(agent)/agent"` | 全绿 |
| 前端全量 | `npm test -- --run` | 与基线一致（12-14 个既有 SSE/时间类 flaky 失败，均不引用本计划模块） |
| 后端 DSH 域回归 | `cd backend && python -m pytest tests/test_dsh_*.py -q` | 全绿 |

## 服务端预验证（已通过）

- 实例 boot 图包含插件：`GET http://127.0.0.1:3163/` 的 `__DSH_BOOT__` 含 `@naoker/dsh-platform-connector`（rev 与 `lib/client.js` sha1 一致）。
- 插件 bundle 可服务：`GET /plugins/@naoker/dsh-platform-connector/client.js` → 200，含 `data-naoker-nav` / `naoker-nav-hide` / `installBridge`。
- 修复项（live 验证中发现）：`DSH_HOME` 曾以相对路径传给子进程（子进程 cwd=repo_root）→ 实例实际跑在 repo 根下的空 home，插件/配置都在 `backend/var/dsh`，导致客户端插件从未加载。已修：`Settings.dsh_home_root_path` 绝对化（锚定 backend/），实例管理器与同步 worker 统一使用；重启后 boot 图与 bundle 均正常。

## 浏览器手测清单（需在真实浏览器执行）

前置：后端 `127.0.0.1:8000`、前端 `localhost:3000`、DSH 实例已运行（`/api/dsh/instances/me` state=running）。

1. **单一侧栏**：登录 `admin / ChangeMe-Strong1` → 打开「Agent 工作台」（`/agent`）：只有一个侧栏；DSH 原生侧栏不可见（无残留空列/接缝）；品牌=脑壳工作台。
2. **工作区与会话**：③ 区显示真实工作区（如 `01_agent_loop_pro`、`HC_ZiChan` 等）与会话（标题+相对时间）；与直接打开 `http://127.0.0.1:3163/` 的 DSH 原版一致。
3. **会话切换**：点击会话 → 右侧立即切换；当前项高亮；运行中会话显示绿点。
4. **功能全保留**：`+ 新会话`（侧栏顶部白底按钮）、搜索（🔍 展开输入框）、过滤（⚙ 图标 → 原生菜单）、＋新建工作区（目录选择弹窗）、`DSH 设置`（页脚菜单、角色管理下方）→ 全部可用且与 DSH 原生行为一致。
5. **深链**：刷新页面 → 自动恢复上次会话；URL 带 `?session=<id>`。
6. **实例重建**：点顶部「重建」→ 状态 A（正在启动…）→ E（正常）；会话不丢；深链在重建后仍生效。
7. **legacy 回退**：`/agent/legacy` 与 `/agent/sessions/*` → 旧界面与旧会话列表正常（aria-current 高亮）。
8. **其它页面**：`/users`、`/roles`、`/files` 等 → 侧栏无会话区；`/agent/audit|files|debug` → 无 DSH 区。

## T1 spike 遗留的 live 验证项（并入上面手测）

1. 零宽隐藏后 AppFrame 重渲染（窗口缩放/开合设置面板）不出现残留空列 → 手测 1/4。
2. 设置面板在零宽侧栏下全屏可见（fixed 逃逸裁剪）→ 手测 4。
3. 目录选择弹窗实际形态（native OS 选择器 vs 页面内 Modal）→ 手测 4。
4. 过滤菜单/新建工作区菜单 portal 定位可读可用 → 手测 4。
5. 运行实例 locale（zh/en）命中哪一支 aria-label → 手测 4（选择器已双写覆盖）。

## 已知边界与生产待办

- `＋新建工作区` 在生产多用户环境会暴露服务器目录选择器（安全隐患，三期加限制）。
- 侧栏搜索结果为平台自渲染（走 `ctx.sessions.search` 服务），不点原生搜索框（原生搜索 UI 在隐藏列内会被裁剪）。
- 实例管理器的"收养"逻辑：API 重启后若旧实例进程仍活着会被收养（不重启），修改插件后需先杀进程再重启（本次已踩到）。
