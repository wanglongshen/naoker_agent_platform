# 系统优化批（A 类缺陷 + 冷启动 + loop 拆分 + 作品集收尾）设计

- 日期：2026-09-20
- 状态：待用户评审
- 范围：本地自用系统（**不部署服务器**，故不含生产加固、限流、监控、Docker 真机验证）
- 前置：本设计基于四份并行侦察报告，所有"现状"均带 `file:line` 证据

## 1. 背景与目标

功能面已完整，短板在"可信度"（测试基线不干净、有死代码）与"日常体验"（冷启动、侧栏噪音）。本批目标：

1. 清掉全部已定位真缺陷（A1/A3/A4/A5/A6/A8）
2. 让测试基线恢复全绿（A2），后续改动才有可信信号
3. 降低首次检索等待（D4）
4. 把 3,354 行的 `loop.py` 拆成可维护模块（B1），并保留作品集故事
5. 作品集仓库收尾：架构图上线 GitHub Pages（D5）

**明确不做**：B2（legacy SSE 退役）、B3（限流/监控/归档）、D1（任务链结果入口）、D3（评测集扩充 500+）、服务器部署相关一切。

## 2. 逐项设计

### A1 「先追问」死分支

**现状（证据）**：`loop.py:919` 调用 `admission_judgment(run.goal, files_read_ok=not missing_sources, missing_constraints=[])`——`missing_constraints` 硬编码空列表；`admission_judgment`（`workflow_rules.py:170-180`）只有在 `critical` 非空时才返回 `"先追问"`，而 `critical` 来自该参数，故 `loop.py:923-925` 永不执行。`awaiting_question` 的下游机制（DB 暂停 + `run_awaiting_question` 事件）是通的，缺的只是触发条件。`admission_judgment` 的 `goal` 参数当前完全未使用；`ParsedRules.admission_rules` 也从未被读取。

**方案**：新增纯函数 `detect_missing_constraints(goal: str) -> list[str]`（放 `workflow_rules.py`），只识别五类关键约束（预算 / 时间周期 / 核心目标 / 必讲信息 / 成功指标）在目标文本中是否缺失；`loop.py:919` 改为传入该结果。为控制误伤（这是**行为变更**）：

- 仅对**方案类目标**生效（复用现有 `is_plan_goal`）
- 目标含豁免语（"基于已有资料/直接产出/不用问"等）时跳过
- **缺失 ≥ 2 项**才触发追问（只缺 1 项仍直接产出）
- 新增配置 `admission_ask_enabled: bool = True`，一行可关闭回退旧行为
- 问题列表复用并扩展 `_build_questions`：只为缺失项生成问题，上限 5 条

**验收**：单测覆盖 5 类缺失组合与豁免语；真实跑一条缺预算/周期的方案类目标 → 出现 `run_awaiting_question` 且 DB 暂停；一条信息完整的目标 → 不追问，行为与今天一致。

### A3 任务链取消竞态

**现状（证据）**：`api/task_chains.py:146-152` 允许 `queued|running` 取消并写 `cancelled`；`task_chain_repository.py:123-133` `set_chain_status` 是**无条件 ORM 写**（`db.get` + 赋值 + commit，无 WHERE 守卫）；worker 在 `service.py:123` 无条件写 `succeeded`（异常路径 `:116-121` 写 `failed`）→ 取消会被静默覆盖。另有第二重竞态：`session.py:9` `expire_on_commit=False` + `get_chain` 为普通 select（`task_chain_repository.py:41-48`），`service.py:137/332-337/369` 会把身份映射里的**陈旧 `running`** 写回，覆盖阶段中途的取消。`DshTaskExecutor.run` 无取消钩子，只有墙钟超时。

**方案**：

1. 仓储新增条件更新 `set_chain_status_if(chain_id, from_statuses, to_status, **fields) -> bool`（`UPDATE ... WHERE id=:id AND status = ANY(:from)` + rowcount 判定），返回是否命中。
2. 所有终态与阶段写改走它：worker 终态 `from=("running",)`；`_begin`/`_stage_*` 的 `running` 回写 `from=("running",)` 并**先重读**状态（或直接用条件更新避免陈旧写）。
3. worker 在每个阶段边界检查链状态：若已 `cancelled`，立即停止后续阶段并**不覆盖**终态。
4. 取消接口改为条件更新（`from=("queued","running")`），命中失败返回 409。

**明确不做（记录在案）**：杀死正在运行的 DSH 子进程——v1 靠阶段边界止损，子任务最长受其 timeout 约束。留待后续。

**验收**：并发测试（取消与终态写交错）断言链最终为 `cancelled` 且不被覆盖；阶段中途取消 → 后续阶段不再执行；取消已终态链 → 409。

### A4 审计页用户列显示用户名

**现状（证据）**：`api/dsh.py:34-41` 的 `_page_sessions` 不 join `User`；`schemas/dsh.py:17-18` 的 `DshSessionAuditItem` 只加 `user_id`；前端 `audit-sessions-table.tsx:30-38` 渲染 `user_id.slice(0,12)`。对照：Agent 审计（`api/agent_audit.py:104-121`）已 join 并返回 `owner_display_name`。

**方案**：`_page_sessions` 在审计路径 left join `User`，取 `coalesce(display_name, username, '')`；schema 增 `username`/`display_name`；前端列优先显示 `display_name || username`，都为空才回退短 id。用户自己的列表接口（`/api/dsh/sessions`）不需要该字段，保持精简。

**验收**：审计接口返回含用户名；前端"DSH 会话"页用户列显示中文名而非 UUID 前缀；`test_dsh_sessions_api.py` 增断言。

### A5 RAG 三个小缺陷

**A5a 停用库占榜（全局检索少给/给不出结果）**
现状：`search.py:162` `fetch_k = max(top_k*3, top_k)` 后按分数取候选，**停用库过滤发生在候选选出之后**（`search.py:177-209`）。停用库若占候选窗口（"平台规则"库占 3,457/5,822 块），全局检索会返回少于 top_k 甚至 0 条。
方案：全局路径（无 `library_id`）也走 `allowed_ids`——缓存"启用库的 chunk id 集合"，与现有版本探针（`search.py:21,55-65` 的 `count(*)+max(created_at)`）同生命周期失效，然后 `store.search(..., allowed_ids=enabled_ids)` 在**打分前**过滤。`include_disabled=True`（超管）时传 `None` 保持现状。
验收：构造"停用库块数 >> fetch_k"的用例，断言全局检索仍返回满 top_k 且全部来自启用库。

**A5b 并发建库 500 → 409**
现状：`api/rag.py:239-248` 先查后插；`rag_repository.py:166-170` 直接 commit；`IntegrityError` 全仓无处理 → 500。
方案：仓储 `create_library`/`rename_library` 捕获 `IntegrityError` → `rollback()` → 抛领域异常；API 层映射为 409 `LIBRARY_NAME_EXISTS`。重命名路径同样处理。
验收：模拟并发插入（测试内直接调用两次绕过预检）断言 409 而非 500。

**A5c 导入部分失败仍报 succeeded**
现状：`rag_ingest_worker.py:141` `status = "failed" if failures == len(items) else "succeeded"`——`0 < failures < len(items)` 时状态 `succeeded` 同时带 `error_message`，记录自相矛盾。
方案：新增终态 `partial`（`0 < failures < len(items)`），前端任务列表/详情增加对应中文标签与颜色；全失败仍 `failed`，全成功仍 `succeeded`。`error_message` 保留最后一条失败原因。
验收：worker 测试覆盖三种边界（全成/部分/全败）；前端标签渲染测试。

### A6 + A8 headless 与 Web 实例共用 DSH_HOME（合并修复）

**现状（证据）**：headless 子任务用 `settings.dsh_home_root_path / str(user_id)`（`executor.py:153-155`），与 Web 实例**完全同一目录**（`instance_manager.py:190`）。每次 `dsh` 启动都会"治愈"共享的 `profiles/node_modules` 符号链接农场（`profile-boot.ts:98-103` → `app-boot/src/profile.ts:204-255`，`ensureSymlink` 是 **unlink + 重建**），而调研阶段会**并行**起最多 5 个 headless 进程（`service.py:237` `asyncio.gather`）→ 正在运行的 Web 实例可能在解析模块时瞬间丢失链接，这正是"跑完任务链后 iframe 报错"的最强候选。项目自己的 NOTES 也记载共用 home 并发不安全（`dsh-platform/NOTES.md:517`）。另：headless 会话因此进入用户 home 的 `sessions/`，被 `dsh_sync_worker` 同步进 `dsh_sessions`，污染侧栏（A6）。

**方案**：headless 使用**独立 home** `<root>/<user_id>-headless/`：

1. `service.py` 调用执行器时传 `home_dir`（执行器已支持该参数，`executor.py:145-155`；`_prepare_home` 幂等，会自动装连接器 + 写 headless 注入 + 拷 skills）。
2. 计费扫描（`service.py:353-357` 读 Web home 的会话 JSONL 采集 usage）改为扫 headless home。
3. 一次性清理：删除用户 Web home 中由 headless 产生的历史会话目录（`NOTES.md:511` 证实 headless 会话位于 `--<home-path-encoded>--` 项目目录下，可精确识别），并从 `dsh_sessions` 删除对应行。
4. 不做：连接器侧 cwd 过滤（隔离后新会话不再进入 Web home，无需过滤）。

**副作用与取舍**：headless 不再继承用户 `settings.yaml`（模型/皮肤个性化）——任务链本就固定模型，可接受；首次运行新 home 需一次性安装连接器插件（秒级）。

**验收**：连跑两次真实任务链，全程 Web 实例（`/agent`）不重启、不报错；跑完后侧栏不再出现新的 UUID 标题会话；`dsh_sessions` 不再增长任务链会话；计费仍能取到真实 usage（积分扣减数值与改动前同量级）。

### A2 测试基线恢复全绿

**后端现状（实测）**：`6 failed, 1283 passed`（全套约 12 分钟）。逐条：
| 失败 | 性质 | 处置 |
| --- | --- | --- |
| `test_file_reader.py` DOCX/XLSX/PPTX（3 条） | 环境缺依赖 `python-docx`/`openpyxl`/`python-pptx` | 安装；并把 `openpyxl` 补进 `requirements.txt`（现缺） |
| `test_dsh_settings.py::test_dsh_settings_defaults` | 陈旧断言（期望 8000，`config.py:102` 已是 8010） | 改断言对齐配置 |
| `test_rag_library_split_migration.py::test_eight_libraries_exist_after_migration` | 仅在全套运行时 `asyncpg InterfaceError`（单跑通过）→ 测试隔离/事件循环问题 | 修测试隔离（独立 engine/连接或显式清理） |
| `test_agent_blueprint_closure.py`（**未跟踪 WIP 文件**） | 断言"模型谎称保存了别的文件"——编码真实的反幻觉要求（对照 `loop.py:1058-1081` `_enforce_answer_truthfulness`） | 先评估：若修法小（扩展真值校验）则采纳并纳入仓库；否则删除该 WIP 文件并在设计记录中登记 |

**前端现状（实测）**：`14 failed, 643 passed`。逐条：
| 失败 | 性质 | 处置 |
| --- | --- | --- |
| `use-run-event-stream.test.ts` 5 条级联 | 一个用例泄漏 fake timers（`vi.useRealTimers()` 未执行）→ 下游 4 条失败 | 修泄漏（保证 teardown 恢复真实计时器） |
| 端口 8000 vs 8010 | 陈旧期望 | 改断言 |
| `run-stream-reducer.test.ts` legacy 状态 `completed` | 陈旧（该状态已不在 `AgentRunStatus`） | 改断言 |
| `run-diagnostics.test.tsx` 4 条 | mock 缺 `narrativeEvents` 字段 | 补 mock |
| `session-sidebar-list.test.tsx` | 测试数据日期超 30 天（时间依赖） | 固定时钟/改数据 |
| `user-management.test.tsx` | 全套下超时，单跑通过 → flaky | 放宽超时或隔离 |
| **`thought-narrative.test.ts`** | **真产品 bug**：`thought-narrative.ts:52-54` `getThoughtDurationSeconds` 在有事件时忽略传入的 `nowMs` → 思考中时长不刷新 | 修实现（有事件时仍以 `nowMs` 计算进行中时长） |

**验收**：后端 `pytest -q` 0 失败；前端 `npx vitest run` 0 失败；两条命令写入验收清单。

### D4 RAG 冷启动预热

**现状（证据）**：API 进程首个检索请求承担两笔懒加载——本地 embedding 模型（约 20-24s，`embedding.py:63` `SentenceTransformer(...)`）与全量向量矩阵（5,822 块 ≈11.9MB，`store.py:45-61`，由 `api/rag.py:104-109` 全表读取）。`lifespan`（`main.py:41-52`）目前无任何预热。文档实测首次 36.4s、后续 52-90ms。

**方案**：在 `lifespan` 启动**后台任务**（不阻塞启动）预热 embedding 模型 + 向量矩阵，并记录耗时日志；新增配置 `rag_warmup_on_startup: bool = True`（可关）。预热失败只记 warning，不影响启动。仅 API 进程需要（worker 不用）。

**验收**：重启后端后立即检索，首次响应 < 2s（模型与矩阵已就绪）；日志出现预热完成行；关闭开关后行为回到现状。

### B1 拆分 loop.py（3,354 行）

**现状（证据）**：单文件含 LEGACY while 轨（`_do_process_attempt` L2232-2676）、LANGGRAPH 轨（节点 L2678-3000 + 驱动 L3024-3267）、共享阶段机/门禁/流式/消息构建/质检/工具派发等约 120 个成员。`__init__` 读 `settings.langgraph_enabled`（L263），分叉点 L2224-2230。外部依赖面：`AgentLoopService`、`agent_loop_service` 单例、`_AttemptContext`、`_RunWorkflowState`、`_QuestionHangSignal`、`_WfProxy`、`should_try_direct_answer`、`remove_visible_thought_overlap`、`classify_agent_failure`、`init/shutdown/set_redis_bridge`，以及测试直接引用的 `RetryablePlannerError`。

**方案（零调用方改动的搬迁式重构）**：按职责拆成三个模块，`loop.py` 保留为**门面**（re-export 全部公共符号 + 单例 + 桥接函数），因此 `from app.services.agent.loop import ...` 的既有调用方与测试**一律不改**。

| 模块 | 内容 |
| --- | --- |
| `agent/quality_gate.py` | 质量自审（`_run_quality_review`、`_read_file_content_for_review`、`_format_review_hint`）、结构/答案真值门（`_enforce_answer_truthfulness`、`_enforce_save_intent`、`_enforce_final_step`、`_has_save_intent`、`_verified_save_answer`、`_merge_save_answer`）、质量注入（`_quality_injection_hints`、`_prepare_quality_injection`、`_load_blueprint_full`） |
| `agent/tool_dispatch.py` | 工具事件与清洗（`_tool_event_payload`、`_sanitize_*`、`_journal_target`）、工具交错流式（`_stream_visible_thought_with_tool_interleave` 及其依赖的 `_looks_like_unsafe_visible_thought_chunk`/`_finalize_*`）、观测记录（`_record_observation`、`_inject_observation_history`） |
| `agent/execution_kernel.py` | 状态与代理（`_AttemptContext`、`_RunWorkflowState`、`_WfProxy`、`_WF_ATTR_MAP`）、阶段机（`_advance_workflow_stage`、`_next_stage_after`、`_STAGE_ALLOWED_ACTIONS`、`_scan_highest_version`）、门禁（`_enforce_stage_gate`、`_missing_required_sources*`）、两条驱动（`_do_process_attempt`、`_do_process_attempt_graph`、`process_attempt`、`_maybe_run_graph_or_loop`）、图节点（`_do_node_*`、`_execute_one_step`、`_wf_to_state`/`_state_to_wf`）、流式与消息构建、会话/附件、重试调度、计费累积 |

执行顺序（每步独立验证）：**① 抽 quality_gate → ② 抽 tool_dispatch → ③ 抽 execution_kernel**（最后一步最大）。每步跑：定向测试 → 全量后端测试 → 差分器。

**安全网**：`LANGGRAPH_ENABLED` 两轨都在；`docs/langgraph-eval/report.md` 的 10/10 零差异差分 + 全量 1,289 条后端测试。

**验收**：三步完成后全量测试 0 失败；差分报告仍 10/10 零差异；`loop.py` 降到 < 800 行且只含门面与桥接；无调用方 import 变更（`git diff --name-only` 证明只有 `backend/app/services/agent/*` 变动）。

### D5 作品集收尾（GitHub Pages + README）

**现状（证据）**：GitHub 仓库已上线（`wanglongshen/naoker_agent_platform`），但本地导出目录 `…\Temp\opencode\naoker-public` **已被清空**（0 文件、非 git 仓库）→ 需按既有流程重新导出。根目录 7 个架构图 HTML **完全自包含**（无外链 CSS/JS/图片），适合直接做 Pages。README 当前无任何图片引用。

**方案**：

1. 重新执行脱敏导出流水线（`git archive` → 剔除 `backend/var/**` → 口令脱敏 → 修复中文文件名 → 重建单提交仓库 → 推送），流程已记入项目记忆。
2. 仓库根保留 7 个架构图 HTML；新增 `index.html` 落地页（自包含，链接 README 与各图）。
3. 开启 GitHub Pages（从 `main` 分支根目录发布）→ 架构图获得在线地址，README 增加 Pages 链接与架构图链接。
4. README 增加"界面截图"小节（占位 + 说明），截图文件由用户提供后补入 `docs/screenshots/`（我无法生成真实界面截图）。

**验收**：Pages 地址可访问且 7 张图正常渲染；README 链接可达；仓库无 `backend/var/**`、无口令残留（复用上次核验脚本）。

## 3. 任务依赖与波次

```
W1(并行) T1 A5b · T2 A4 · T4 A5c · T5 A2后端 · T6 A2前端 · T7 D4
W2(并行) T3 A5a · T8 A1 · T9 A8+A6
W3       T10 A3 · T11a 抽 quality_gate
W4       T11b 抽 tool_dispatch · T12 D5
W5       T11c 抽 execution_kernel
W6       T13 端到端验收（真实运行）
```

约束：T8 必须先于 T11（同文件）；T9 必须先于 T10（同文件 `service.py`）；T3 与 T4 文件不重叠可并行。

## 4. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| A1 行为变更误伤（多问用户） | 仅方案类 + 缺失 ≥2 项 + 豁免语 + `admission_ask_enabled` 开关 |
| B1 拆分引入回归 | 搬迁式（不重写逻辑）+ 门面保持 import 面 + 差分器 + 全量测试 + 分三步各自验证 |
| A8 隔离后计费取不到 usage | 计费扫描改指 headless home，验收断言积分扣减非零且量级一致 |
| A2 前端 fake timer 修复引发新失败 | 只动测试的 teardown 与断言，不动产品代码（除 #8 真 bug） |
| D5 导出再次丢失/污染 | 流水线固化为脚本步骤，导出后跑敏感项核验再推送 |

## 5. 验收总清单

1. 后端 `pytest -q` 0 失败（约 1,289 条）
2. 前端 `npx vitest run` 0 失败（约 657 条）
3. 差分器 `docs/langgraph-eval/report.md` 仍 10/10 零差异
4. 真实运行：一条完整方案任务链跑通；全程 Web 实例不崩；侧栏无任务链会话；积分扣减非零
5. A1 手测：缺约束目标被追问、完整目标不追问
6. A5a 手测：全局检索在停用库存在时仍返回满 top_k
7. D4 手测：重启后首次检索 < 2s
8. D5：Pages 可访问、仓库无敏感文件
