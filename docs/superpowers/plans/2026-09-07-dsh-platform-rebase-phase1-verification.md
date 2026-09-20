# DSH 平台化改造 · 一期验收手测清单（spec 3.8）

> 配套：`2026-09-07-dsh-platform-rebase-phase1.md`（任务/文件清单）、设计文档 3.8「一期验收清单」（唯一口径）。
> 运行冒烟脚本先行：`powershell -ExecutionPolicy Bypass -File scripts\dsh_smoke.ps1`（自动化覆盖处复制其输出留档）。

## 前置条件（执行前逐项核对）

- [ ] `backend/` 下 `alembic upgrade head` 完成（dsh_instances / dsh_sessions 存在；可 grep `backend/var/api_uvicorn.log` 无迁移报错）
- [ ] API 运行中：`uvicorn app.main:app --port 8000`（backend 工作目录；`GET http://127.0.0.1:8000/health` → `{"data":{"status":"ok"}}`）
- [ ] DSH 二进制可用：`DSH_INSTANCE_MODE=dev_bin` 时 `dsh --version`；`vendored` 时 `deepseek-harness/apps/cli/lib/bin.js` 已构建
- [ ] `backend/.env`：`DEEPSEEK_API_KEY`、`INITIAL_ADMIN_*`、`CORS_ORIGINS` 就绪
- [ ] 前端（手测必需；冒烟可选）：`npm run serve`（或 `npm run dev`），`http://localhost:3000`
- [ ] 准备两个访问用户：admin（super_admin）与普通用户 B（或注册新用户），文件区已上传至少 1 个文本附件

## 验收清单（spec 3.8 六条）

### 1) 新用户登录 → /agent → 实例自动启动 → DSH UI 渲染 + 皮肤生效 → 发消息流式回复

| 步骤 | 操作 | 预期结果 | 通过口 |
|---|---|---|---|
| 1.1 | 注册新用户（或未登录）→ 登录 → 进入 `/agent` | 状态条显示实例 `starting` → `running`；iframe 加载 DSH Web UI；无白屏/502 | 状态条 state=running；页面出现 DSH 界面 |
| 1.2 | DSH「设置 → 皮肤管理」选择已装皮肤（maid-atelier/鲸鱼娘） | 皮肤切换立即生效，布局/配色/角色形象变化 | 截图皮肤生效前后对比 |
| 1.3 | 输入一条测试消息，模型 deepseek-official 或 deepseek-v4-flash-vision-exp，发送 | DSH 流式回复逐字出现，无中断错误 | 收到完整回复（截图回复末尾） |

自动化覆盖：冒烟脚本 `scripts/dsh_smoke.ps1` ①③④⑥（health、CSRF 登录+restart→running、代理 HTML、同步）；实例状态与开关 API 由 `backend/tests/test_dsh_instance_manager.py` 覆盖。渲染与消息链路本身为手测项。

### 2) 对话内调用文件工具读已上传附件 → 内容准确出现

| 步骤 | 操作 | 预期结果 | 通过口 |
|---|---|---|---|
| 2.1 | 在对话中用「检索品牌方已上传资料库/文件」类自然语言触发 `platform_search_files` | 工具返回该用户可访问的文件列表（id/标题/类型），且列表中包含步骤前置环境上传的测试文档 | 工具调用日志含目标文件标题 |
| 2.2 | 让模型 `platform_read_file` 读取该文档，提问文档内具体数据点 | 回复内容与文档原文一致，非编造 | 回复文本与文档关键段落逐字比对通过 |

自动化覆盖：无（工具注册/参数编码由 `dsh-platform/packages/server-connector/tests/connector.test.ts` 单测覆盖；端到端为手测项）。

### 3) 审计页出现该会话（super_admin 可见、他人不可见）

| 步骤 | 操作 | 预期结果 | 通过口 |
|---|---|---|---|
| 3.1 | 管理员登录 → 审计页「DSH 会话」Tab | 能看到步骤 1/2 里该用户的会话行（标题/turn_count/最近活动时间） | 会话行存在于列表（截图） |
| 3.2 | 普通用户 B 登录 | B 看不到该会话；B 的 `GET /api/dsh/sessions/audit` 返回 403；`GET /api/dsh/sessions` 仅返回 B 自己的 | 列表/响应均无他人会话 |

自动化覆盖：`backend/tests/test_dsh_sessions_api.py`（本人只见本人、audit 全员、非 super_admin 403）；`backend/tests/test_dsh_session_sync.py`（同步 upsert/覆盖语义）。手测补审计页 Tab 渲染与可见性。

### 4) 用户 B 直接访问 `/api/dsh-proxy/<A>/**` → 404

| 步骤 | 操作 | 预期结果 | 通过口 |
|---|---|---|---|
| 4.1 | B 登录后手动 `GET http://localhost:8000/api/dsh-proxy/<A的uid>/`（或浏览器直开 `http://localhost:3000/dsh-proxy/<A的uid>/`） | 返回 404（与资源不存在不可区分；不是 403/500） | HTTP 状态 404 |
| 4.2 | B 未登录状态访问同路径 | 按平台现有语义 401/403 | 未登录语义与现有接口一致 |

自动化覆盖：`backend/tests/test_dsh_proxy.py::test_proxy_non_owner_404`（属主强校验 404）、`test_proxy_requires_login`。

### 5) 空闲回收 → 实例重启 → 会话保留

| 步骤 | 操作 | 预期结果 | 通过口 |
|---|---|---|---|
| 5.1 | 在 A 的 `/agent` 正常使用并完成一轮对话；等待超过 `DSH_IDLE_SECONDS`（默认 600s）无操作 | `GET /api/dsh/instances/me` → state 变为 `stopped`；DSH 进程退出（SIGTERM→30s→kill） | 状态接口 stopped |
| 5.2 | 再次访问 `/agent` | 实例自动重启为 `running`；历史会话列表仍在（<home>/sessions/*.jsonl.zstd 未被清） | 历史会话可见并可继续对话 |
| 5.3 | 同步 worker 运行后查询 `dsh_sessions` | 会话行保留且 turn_count 持续累计 | python 查询行数 >0（或冒烟脚本 ⑥ 输出） |

自动化覆盖：`backend/tests/test_dsh_instance_manager.py`（sweep_idle/停止优雅期/幂等 ensure_running）；`backend/tests/test_dsh_session_sync.py`。真机「重启后保留」为手测项。

### 6) 手册：任意社区 DSH 插件安装到该实例 profile 即生效（鲸鱼娘为验证样例）

| 步骤 | 操作 | 预期结果 | 通过口 |
|---|---|---|---|
| 6.1 | 属主 A 执行两步法：`cd backend`；`$env:DSH_HOME="$PWD\var\dsh\<A的uid>"`；`dsh plugin --profile web add dsh-deep-whale（或任意含 dsh.bundle.patch 的插件目录/仓库）` | 命令完成无报错；`<home>/profiles/web/package.json` 出现插件依赖与 `dsh.profile.bundles` 条目（声明了 patch 才进层栈） | 依赖条目存在（cat 核对） |
| 6.2 | `/agent` 点击「重建」（或 `POST /api/dsh/instances/me/restart`，注意 CSRF） | 实例重启后插件生效：皮肤管理列表中该皮肤出现（鲸鱼娘样例）；若为工具插件则工具注册成功 | 皮肤可选/工具可调用（截图） |
| 6.3 | 验证「替换 home 路径不生效」：在默认 home（无 DSH_HOME）执行 `dsh plugin add` | 平台实例无任何变化（以示锚定正确） | 6.1 的依赖条目未出现在全局 profile |

自动化覆盖：无（插件安装为本机操作链）；`connector.test.ts` 覆盖平台插件自身语义，`backend/tests/test_dsh_instance_config.py` 覆盖平台注入的 patch/skills 文本。

## 自动化覆盖对照（可在 CI/冒烟复跑的最小集）

| 用途 | 命令（backend/ 下） | 覆盖项 |
|---|---|---|
| 一期冒烟（进程外） | `powershell -ExecutionPolicy Bypass -File scripts\dsh_smoke.ps1` | ①②③④⑤⑥ 的 API/DB 级断言（⑤ 前端可选 SKIP；⑥ 无对话时行数可为 0） |
| 代理+属主 404 | `python -m pytest tests/test_dsh_proxy.py -v` | 验收 #4 |
| 实例生命周期 | `python -m pytest tests/test_dsh_instance_manager.py -v` | 验收 #1（状态机会话）、#5（sweep 逻辑） |
| 会话同步/API | `python -m pytest tests/test_dsh_session_sync.py tests/test_dsh_sessions_api.py -v` | 验收 #3 |
| 配置注入 | `python -m pytest tests/test_dsh_instance_config.py -v` | 验收 #6 的平台注入侧 |
| 插件单测 | `cd dsh-platform/packages/server-connector; npm test` | 验收 #2 的工具注册侧 |

## 证据记录

逐条通过后填写（截图按用户要求：截图存 `docs/superpowers/plans/` 或仅文字证据，二选一）：

| 日期 | 执行人 | 验收项 | 结果（PASS/FAIL） | 证据（截图文件名 / 文字说明） |
|---|---|---|---|---|
|  |  | 1 | ☐ |  |
|  |  | 2 | ☐ |  |
|  |  | 3 | ☐ |  |
|  |  | 4 | ☐ |  |
|  |  | 5 | ☐ |  |
|  |  | 6 | ☐ |  |

> 任一 FAIL：先在 `backend/var/api_uvicorn.log` 与 DSH 进程日志定位；属实现缺陷则记录 issue 并复跑冒烟脚本回归；禁止「未验证即标 PASS」。
