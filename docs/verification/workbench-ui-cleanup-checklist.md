# 工作台界面整理 — 验收清单与实测结果

- 日期：2026-09-17
- 设计：`docs/superpowers/specs/2026-09-17-workbench-ui-cleanup-design.md`
- 计划：`docs/superpowers/plans/2026-09-17-workbench-ui-cleanup.md`

## 1. 六项改动与证据

| # | 改动 | 状态 | 证据 |
| --- | --- | --- | --- |
| 1 | 下线「方案中心」 | ✅ | 页面 + 4 个组件 + 其测试已删（`f1da1b82`）；`GET /generations` → **404**（实测）；后端任务链保留 |
| 2 | 侧栏顺序 | ✅ | 我的文件 → 账户 → 对话审计 → 文件管理 → **知识库管理** → 用户管理 → 角色管理 → DSH 设置（组件测试断言相邻关系） |
| 3 | DSH 设置常显 | ✅ | 实例未运行也渲染（测试覆盖）；点击 → `/agent?settings=1` → 桥就绪后发 `open-settings` 并清参数（`3d9a40f3`） |
| 4 | 会话清理 + 专业示例对话 | ✅ | 清理 17 个会话目录 + 17 行同步记录；播种 5 条真实对话（`acf61b2b`） |
| 5 | 顶栏统一（方案 A） | ✅ | 全站单一 `AppHeader`；`ConversationTopBar`、`top-bar-user-wrapper` 已删；下拉含飞书/平台登录（`a168866a`） |
| 6 | DSH 工作区占满内容区 | ✅ | 真实 DOM 测量定位根因并修复（`e7fe4c01`） |

## 2. 第 4 项：播种的 5 条示例对话

| # | 标题（DSH 生成的精炼标题） |
| --- | --- |
| 1 | 新品抖音千川投放策略 |
| 2 | 短视频内容选题与脚本框架设计 |
| 3 | 直播间转化率提升关键动作 |
| 4 | 广告投放合规风险点 |
| 5 | 拆解生鲜经营案例提炼打法 |

- 5 条全部 `exit=0`（86.3s / 39.2s / 19.4s / 30.2s / 47.1s），磁盘上 5 个 `session.jsonl.zstd`，`dsh_sessions` 恰好 5 行且标题与磁盘一致。
- 标题由 DSH 的 `session-title-first-prompt-llm` 插件生成（LLM 精炼），比问题原文更短更专业。

## 3. 第 6 项：根因与修复（实测，非猜测）

**先测量后修改**：通过插件桥加临时 `probe-layout` 命令 + 系统 Edge 无头模式（CDP 直连）读取真实 DOM：

- 修复前：AppFrame 内联 `grid-template-columns: 0px 1290px 0px`，内容列宽 1290px，**右侧空白 280px**（= 侧栏默认宽度）。
- **真实根因**（既不是我原先猜的「右轨残留」，也不是「会话列宽度限制」）：隐藏例程 `replay()` 读的是 `getComputedStyle` 的**已用值**，把第一轨置 0 后写回，`minmax(0,1fr)` 被固化成像素 `1290px` → 中间轨被冻结，右侧空出 280px。
- 修复：`zeroFirstTrack` 在中间轨为纯像素时恢复 `minmax(0, 1fr)`；`replay()` 优先读内联逻辑值（避免过渡期读到旧值撤销 details 面板/窗口缩放）。
- 修复后实测：内联 `0px minmax(0px, 1fr) 0px` → 内容列宽 **1570px、右侧空白 0**；打开 details 面板时 `0px minmax(0,1fr) 360px`（details 360px 保留、无空隙）；设置面板 overlay 尺寸正常。
- 临时探针已移除（served bundle 已无 `probe-layout`）。

## 4. 回归测试

| 层 | 命令 | 结果 |
| --- | --- | --- |
| 前端（布局/工作区/飞书/流式） | `npx vitest run src/components/layout src/components/dsh src/components/feishu src/components/agent/agent-streaming.test.tsx` | **136 passed**（10 files） |
| DSH 插件 | `pnpm test`（server-connector） | 29 passed |
| 后端 | `pytest tests/test_dsh_sessions_reset.py` | 3 passed |

基线说明（与本轮无关，已核实）：
- `npx tsc --noEmit` 在测试文件里的历史类型错误（`agent-streaming.test.tsx` 等缺 `menu_permissions`、`beforeEach` 未导入、正则 flag）属既有基线；本轮对 `agent-streaming.test.tsx` 的改动仅为顶栏相关行（已核对 diff）。
- `.next/dev/types/.../generations/page.ts` 是 Next 开发缓存的过期类型产物（页面已删、路由实测 404），重启 dev server 后自愈。

## 5. 浏览器验收清单（待用户确认）

- [ ] 侧栏无「方案中心」；手动访问 `/generations` 得到 404
- [ ] 侧栏顺序：我的文件 → 账户 → 对话审计 → 文件管理 → 知识库管理 → 用户管理 → 角色管理 → DSH 设置
- [ ] 在 `/knowledge`、`/files` 等任意页面都能看到「DSH 设置」；点击后进入工作区并自动打开设置面板
- [ ] 侧栏会话列表只剩 5 条示例对话，标题如上表
- [ ] 顶栏全站一致；右上角头像下拉里有「飞书已连接/连接飞书」「平台登录」，均可打开弹窗
- [ ] DSH 工作区内容左右占满、右侧无空白（进 `/agent` 时实例会自动拉起，首次 5-20 秒）

## 6. 已知边界

- DSH web 实例当前为停止状态（清理/播种时主动停掉）；用户进入 `/agent` 会自动拉起并加载修复后的插件。
- 布局修正依赖 DSH 内部 class 与网格行为，已写入 `dsh-platform/NOTES.md`；DSH 升级时需回归这一项。
- 示例对话消耗真实 token（5 次调用，约 3 分钟）。
