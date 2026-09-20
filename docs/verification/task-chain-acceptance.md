# 三期任务链端到端验收记录（真实运行）

- 日期：2026-09-15
- 计划：`docs/superpowers/plans/2026-09-15-plan-generation-chain.md`（T9）
- 环境：本机 Windows；后端 `127.0.0.1:8000`（新代码）；独立 `task_chain_worker` 进程；DSH 实例模式 `dev_bin`（vendored CLI，headless profile）；开发库 `rbac`（含已入库的行业知识库 192 篇 / 1,501 chunks）
- 方式：以 `admin` 登录 → `POST /api/task-chains` 创建真实任务链 → worker 领取执行 → 轮询阶段时间线 → 校验交付文件、积分流水、usage 口径

## 1. 结论

| 项 | 结果 |
|---|---|
| 任务链真实跑通 | ✅ 两次均 `succeeded`（10 个阶段，含 1 次 review 回环） |
| 方案产出（≤10 分钟） | ✅ 运行 1：**6 分 08 秒**；⚠️ 运行 2：**10 分 40 秒**（含平台 API 中断与知识库检索，见 §4） |
| 交付物落盘 | ✅ 两次都产出 Markdown 文件到 `file_objects`（运行 1：24 KB / 运行 2：55 KB） |
| 知识库检索真链路 | ✅ 运行 2 的方案正文含 **37 处 `school.jinritemai.com` 来源引用**（经 DSH `knowledge_search` → `/api/rag/search`） |
| 计费 | ✅ 运行 2 按真实 usage 计费：**1,477,293 tokens → 148 积分**（`point_transactions` 有 `consume -148`） |
| review 回环 | ✅ 两次都触发「结构/质检未过 → 重新起草」并成功收敛（阶段表可见 `draft_plan → review_gate → draft_plan → review_gate`） |

## 2. 运行 1（08:00:42 → 08:06:50，368s）

| # | 阶段 | 起止 | 耗时 |
|---|---|---|---|
| 1 | collect_input | 08:00:42 → 08:00:42 | 0s |
| 2 | research_agenda | 08:00:42 → 08:00:48 | 6s |
| 3 | run_research | 08:00:48 → 08:02:34 | 106s |
| 4 | draft_plan（第 1 稿） | 08:02:34 → 08:04:30 | 116s |
| 5 | review_gate（未过） | 08:04:30 | 0s |
| 6 | draft_plan（第 2 稿） | 08:04:30 → 08:05:36 | 66s |
| 7 | review_gate（通过） | 08:05:36 | 0s |
| 8 | polish | 08:05:36 → 08:06:50 | 74s |
| 9 | deliver | 08:06:50 | 0s |
| 10 | bill | 08:06:50 | 0s |

- 交付文件：`方案_20260915080650.md`（24,002 B，12,215 字符，23 个 `##` 小节），SHA256 `d68327d85b19…`
- 计费：`tokens=200000 / points=20` —— 这是**任务级固定积点降级**（当时 usage 采集有缺陷，见 §3）
- 该次运行方案正文里出现「平台行业知识库接口本次持续 500 不可用」——正是这句话暴露了 RAG 检索的真机缺陷（见 §3）

## 3. 验收过程中发现并修复的真缺陷（都有提交）

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 首次运行 `run_research` 阶段直接失败（`NotImplementedError`） | worker 进程使用 Windows **SelectorEventLoop**，`asyncio.create_subprocess_exec` 不支持子进程 | `executor._spawn` 增加 `subprocess.Popen` 线程兜底（与实例管理器同口径），新增单测覆盖；`da36134` |
| 2 | `collect_dsh_usage` 恒为 0 → 计费只能走固定积点 | 真实 DSH 事件把 usage 放在 **`data.usage`**（实测 headless 事件：`{"type":"assistant/message","time":1789459554094,"data":{...,"usage":{...}}}`），采集器只读顶层 `usage` | 采集器兼容 `data.usage`（保留顶层回退），新增真实事件形态单测；`da36134` |
| 3 | DSH 侧 `knowledge_search` 调用持续 HTTP 500 | API 侧常驻 `_SessionRepo` 只有 `iter_embeddings/chunk_signature`，而 `RagSearchService` 取块/取文档走 `repo.session` → 命中守卫 `RuntimeError` | `_SessionRepo` 增加 `get_chunks_by_ids/get_documents_by_ids`（各自短事务），检索服务优先用仓储方法、保留 session 回退；`da36134` |
| 4 | 任务链首次运行时 `LangGraph` 状态在第二节点丢键（内联修复） | `StateGraph(dict)` 是「整段覆盖」语义 | 改为 `TypedDict` 状态（各字段独立通道）；`a2d428c` |

## 4. 运行 2（08:19:05 创建 → 08:22:05 领取 → 08:32:45 完成）

| # | 阶段 | 起止 | 耗时 |
|---|---|---|---|
| 1 | collect_input | 08:22:05 | 0s |
| 2 | research_agenda | 08:22:05 → 08:22:12 | 7s |
| 3 | run_research | 08:22:12 → 08:24:04 | 112s |
| 4 | draft_plan（第 1 稿） | 08:24:04 → 08:25:30 | 86s |
| 5 | review_gate（未过） | 08:25:30 | 0s |
| 6 | draft_plan（第 2 稿） | 08:25:30 → 08:29:23 | 233s |
| 7 | review_gate（通过） | 08:29:23 | 0s |
| 8 | polish | 08:29:23 → 08:32:45 | 202s |
| 9-10 | deliver + bill | 08:32:45 | 0s |

- 交付文件：`方案_20260915083245.md`（55,341 B，28,326 字符，15 个 `##` 小节）
- 正文引用真实知识库来源 37 处（`school.jinritemai.com`），并显式说明「内部知识库无该品类 GMV 数据」——检索命中与未命中都被如实标注
- 计费：`tokens=1,477,293 / points=148`（`consume` 流水 ref = chain_id）
- **超时因素**（诚实记录）：① 该次运行期间后端进程被外部中断约 4 分钟，DSH 侧工具调用失败后重试；② 知识库检索（CPU 本地 embedding）与更长的第 2 稿/修订稿；③ 领取前排队 3 分钟（worker 未运行）不计入处理时长
- 口径说明：设计目标写的是「P95 ≤10 分钟」，两次样本（6m08s / 10m40s）不足以构成 P95，后续应累积更多真实运行再定论

## 5. 已知边界与后续

1. **Docker 镜像未在本机验证**（本机无 Docker）：`deploy/` 的改动仅静态校验，需在部署服务器跑一次 `docker compose up -d --build` 并执行 README 冒烟。
2. **取消竞态**：运行中取消后，worker 仍可能把链写成 `succeeded/failed`（覆盖 `cancelled`）；服务层缺状态守卫（T5 报告已记录）。
3. **平台 LLM token 未计入**：任务链内平台侧 LLM 调用（调研清单）暂未累加 token，`state["llm_tokens"]` 恒 0；当前由 DSH usage 覆盖主要成本，如后续需要精确到平台侧可补。
4. **计费口径**：usage 采集为 0 时按 `task_chain_flat_points`（默认 20 积分）降级，属设计允许的兜底。
5. **测试环境稳定性**：验收脚本以 WMI 方式启动后端，运行期间进程曾两次被外部结束（无异常栈、无 shutdown 日志，判断为宿主/终端侧终止）；生产/日常开发请用 PyCharm 或 `scripts/start-backend.ps1` 常驻。

## 6. 复现步骤

```powershell
# 1) 迁移 + 起后端（PyCharm 或脚本）
cd backend; X:\python\anaconda\envs\01-rbac\python.exe -m alembic upgrade head
X:\python\anaconda\envs\01-rbac\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2) 另开终端起任务链 worker
cd backend; X:\python\anaconda\envs\01-rbac\python.exe -m app.workers.task_chain_worker

# 3) 登录后在「方案中心」发布任务（或 POST /api/task-chains），观察 8 阶段时间线
```
