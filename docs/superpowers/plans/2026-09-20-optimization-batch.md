# 实施计划：系统优化批（A 类缺陷 + 冷启动 + loop 拆分 + 作品集收尾）

- 日期：2026-09-20
- 设计依据：`docs/superpowers/specs/2026-09-20-optimization-batch-design.md`
- 执行方式：子代理驱动，按波次并行（W1 六任务并行，W2 三任务并行，W3-W5 串行约束见下）
- 通用规则：每个任务只动本任务列出的文件；先写失败测试再实现；完成即报告逐项结果

**全局命令（所有后端任务）**
```powershell
cd C:\01_agent_loop_pro\backend
X:\python\anaconda\envs\01-rbac\python.exe -m pytest -q <测试文件>
```

---

## W1（六任务并行，文件互不重叠）

### T1 — A5b：并发建库返回 409 而非 500

**文件**：`backend/app/repositories/rag_repository.py`、`backend/app/api/rag.py`、`backend/tests/test_rag_libraries_api.py`

**步骤**

1. 失败测试：`test_library_create_conflict_returns_409_even_without_precheck` —— 直接调用仓储 `create_library(name=<已存在>)` 断言抛 `LibraryNameConflict`；API 层用 monkeypatch 让预检返回 None 但库已存在，断言 409 + `code=LIBRARY_NAME_EXISTS`。
2. 仓储新增领域异常并在插入处捕获：
```python
class LibraryNameConflict(Exception):
    """知识库名称唯一约束冲突（并发插入）。"""

async def create_library(self, **fields: Any) -> RagLibrary:
    lib = RagLibrary(**fields)
    self.session.add(lib)
    try:
        await self.session.commit()
    except IntegrityError as exc:          # from sqlalchemy.exc import IntegrityError
        await self.session.rollback()
        raise LibraryNameConflict(str(exc)) from exc
    return lib
```
3. `rename_library` 同样处理（`rag_repository.py:185-192` 的赋值 + commit 路径）。
4. `api/rag.py` 的 create（`:230-248`）与 rename（`:281-284`）用 try/except 把 `LibraryNameConflict` 映射为
   `raise ApiError(status_code=409, code="LIBRARY_NAME_EXISTS", message="知识库名称已存在")`。
5. 跑 `test_rag_libraries_api.py`、`test_rag_repository.py`。

**完成定义**：新增 2 条测试通过；原有 409 顺序用例仍通过；无 500 路径。

### T2 — A4：审计页用户列显示用户名

**文件**：`backend/app/api/dsh.py`、`backend/app/schemas/dsh.py`、`backend/tests/test_dsh_sessions_api.py`、`frontend/src/components/dsh/audit-sessions-table.tsx`、`frontend/src/components/dsh/audit-sessions-table.test.tsx`（若无则新建）

**步骤**

1. 后端失败测试：审计接口（`/api/dsh/sessions/audit`）断言每条含 `username` 与 `display_name`，且与种子用户一致。
2. `_page_sessions` 增可选参数 `with_owner: bool = False`；为 True 时
```python
stmt = (
    select(DshSession, func.coalesce(User.display_name, User.username, "").label("owner_name"),
           User.username.label("username"))
    .join(User, DshSession.user_id == User.id, isouter=True)
)
```
   行解包后把 `username`/`owner_name` 挂到 ORM 对象上（与 `agent_audit.py:104-121` 同款做法）。
3. `schemas/dsh.py` 的 `DshSessionAuditItem` 增 `username: str = ""`、`display_name: str = ""`；审计路由（`dsh.py:72-92`）传 `with_owner=True`；`/api/dsh/sessions`（用户自己）不传，保持精简。
4. 前端：`audit-sessions-table.tsx:30-38` 的 render 改为
```tsx
render: (_: string, row: DshAuditItem) => (
  <span style={{ fontSize: 12 }}>{row.display_name || row.username || row.user_id.slice(0, 12)}</span>
)
```
   类型同步（`frontend/src/lib/dsh-bridge.ts` 或组件内 interface）。
5. 前端测试：新增 3 条（有 display_name / 只有 username / 都没有 → 短 id）。

**完成定义**：后端 1 条 + 前端 3 条测试通过；审计页实测显示中文名。

### T4 — A5c：导入部分失败标记为 partial

**文件**：`backend/app/workers/rag_ingest_worker.py`、`backend/tests/test_rag_ingest_worker.py`、`frontend/src/components/knowledge/dataset-table.tsx`（状态标签处）

**步骤**

1. 失败测试：3 条边界——全成功 `succeeded`；`1/3` 失败 `partial`；`3/3` 失败 `failed`。断言 `processed` 与 `error_message` 同步正确。
2. `_process_import_job` 终态改为：
```python
if failures == len(items):
    final_status = "failed"
elif failures:
    final_status = "partial"
else:
    final_status = "succeeded"
```
3. 前端任务状态标签增加 `partial` → 「部分成功」（橙色），`failed` 「失败」（红），`succeeded` 「成功」（绿）。

**完成定义**：后端 3 条 + 前端标签 1 条测试通过。

### T5 — A2 后端：依赖与陈旧/隔离测试

**文件**：`backend/requirements.txt`、`backend/tests/test_dsh_settings.py`、`backend/tests/test_rag_library_split_migration.py`、`backend/tests/test_agent_blueprint_closure.py`（决策项）

**步骤**

1. 安装缺失依赖（仅环境，不进仓库）：
```powershell
X:\python\anaconda\envs\01-rbac\python.exe -m pip install python-docx openpyxl python-pptx
```
2. `requirements.txt` 在 `pypdf` 一行附近补 `openpyxl`（现缺；`python-docx`/`python-pptx` 已有）。
3. `test_dsh_settings.py::test_dsh_settings_defaults`：断言改为与 `config.py:102` 一致的 `localhost:8010`（或直接读 `Settings().dsh_trusted_hosts` 断言包含默认端口，避免再次漂移）。
4. `test_rag_library_split_migration.py`：修全套运行时的 asyncpg 隔离问题——为该测试使用独立 engine/连接并在 teardown `dispose()`（参考同目录已有独立 engine 的测试写法）；目标：单跑与全套都通过。
5. 决策项 `test_agent_blueprint_closure.py`（当前 untracked）：
   - 先只跑它：`python -m pytest -q tests/test_agent_blueprint_closure.py`
   - 若失败根因是"模型谎称保存了未保存的文件"且修法 ≤ 20 行（扩展 `loop.py` 的 `_enforce_answer_truthfulness` 对"文件名未出现在写文件回执中"的清理），则修复并 `git add` 纳入仓库；
   - 否则删除该 WIP 文件，并在设计文档"决策记录"补一行说明。

**完成定义**：`pytest -q` 输出 0 failed；`requirements.txt` 含 openpyxl；WIP 文件有明确去向。

### T6 — A2 前端：计时器泄漏、陈旧断言与真 bug

**文件**：`frontend/src/lib/thought-narrative.ts`（逻辑）与 `frontend/src/lib/thought-narrative.test.ts`、`frontend/src/hooks/use-run-event-stream.test.ts`、`frontend/src/lib/run-stream-reducer.test.ts`、`frontend/src/components/agent/run-diagnostics.test.tsx`、`frontend/src/components/agent/session-sidebar-list.test.tsx`、`frontend/src/components/users/user-management.test.tsx`

**步骤**

1. **真 bug（先修产品代码）**：`frontend/src/lib/thought-narrative.ts:52-54` 的 `getThoughtDurationSeconds` 在有事件时忽略传入 `nowMs`。改为：进行中（未终结）一律用 `nowMs` 与起始时间差；已终结才用末事件时间。测试断言"进行中随时间推进增长"。
2. `use-run-event-stream.test.ts` 泄漏 fake timers：在每个用例的 `afterEach` 强制 `vi.useRealTimers()`（或把 `vi.useFakeTimers()` 收敛进用例内部并用 try/finally 恢复）；修完 5 条级联应一起变绿。
3. 端口断言 8000 → 8010（对齐 `agent-stream.ts:3` 默认值）。
4. `run-stream-reducer.test.ts`：把 legacy `"completed"` 改为 `"succeeded"`（对照 `types/agent.ts:1`）。
5. `run-diagnostics.test.tsx`：mock 的 `useRunEventStream` 返回值补 `narrativeEvents: []`。
6. `session-sidebar-list.test.tsx`：用 `vi.setSystemTime` 固定"今天"，或把测试数据日期改为相对今天生成，消除 30 天边界依赖。
7. `user-management.test.tsx`：把该文件超时放宽（`vi.setConfig({ testTimeout: 15000 })` 或测试内 `{ timeout: 15000 }`），并确认单跑/全套都通过。

**完成定义**：`npx vitest run` 0 failed；`thought-narrative` 新增 1 条断言进行中时长递增的测试。

### T7 — D4：RAG 冷启动后台预热

**文件**：`backend/app/main.py`、`backend/app/core/config.py`、`backend/app/api/rag.py`（或 `services/rag/search.py` 暴露 `warmup()`）、`backend/tests/test_rag_warmup.py`（新建）

**步骤**

1. 失败测试：`warmup()` 调用后，store 的矩阵已加载且 provider 模型已就绪（用 fake provider/store 断言调用顺序）；配置关闭时不预热。
2. `config.py` 增 `rag_warmup_on_startup: bool = True`。
3. `RagSearchService` 增 `async def warmup(self) -> None`：先 `self.provider.embed(["warmup"])`（触发本地模型加载），再 `await self.store.search(<零向量>, 1, allowed_ids=set())` 或直接调用 store 的 `_ensure()`（择一，避免产生真实候选）；记录
```python
logger.info("rag_warmup_done elapsed_ms=%s chunks=%s", elapsed_ms, chunk_count)
```
4. `main.py` lifespan 中在 `yield` 前用 `asyncio.create_task` 启动预热（**不阻塞启动**），并保存任务引用；异常只 `logger.warning`。

**完成定义**：新增测试通过；重启后端日志出现 `rag_warmup_done`；重启后立即检索实测 < 2s（写入验收记录）。

---

## W2（三任务并行）

### T3 — A5a：全局检索按"启用库"预过滤

**文件**：`backend/app/services/rag/search.py`、`backend/app/services/rag/store.py`（如需）、`backend/tests/test_rag_search_library_filter.py`

**步骤**

1. 失败测试：构造 1 个启用库（3 块）+ 1 个停用库（60 块，向量更接近查询），`top_k=5`；断言全局检索返回 5 条且全部来自启用库（修复前会不足 5 条）。
2. `search.py` 在版本探针缓存中同时缓存"启用库 chunk id 集合"：
```python
self._enabled_ids: set[uuid.UUID] | None = None   # 与 _signature 同生命周期失效

async def _load_enabled_chunk_ids(self) -> set[uuid.UUID]:
    # SELECT rag_chunks.id FROM rag_chunks
    #   JOIN rag_documents ON ... JOIN rag_libraries ON ...
    #  WHERE rag_libraries.retrieval_enabled IS TRUE AND rag_documents.status = 'ready'
```
3. 全局路径（`library_id is None` 且 `include_disabled_libraries is False`）改为
   `allowed_ids = await self._enabled_chunk_ids()`，再 `store.search(vectors[0], fetch_k, allowed_ids=allowed_ids)`；显式库路径逻辑不变；超管 `include_disabled=True` 仍传 `None`。
4. 确认 `store.py` 的 `allowed_ids` 分支已在打分前过滤（`store.py:75-82`）；缓存失效复用现有 `count(*)+max(created_at)` 探针。

**完成定义**：新测试通过；原有 `test_rag_search_library_filter.py`、`test_rag_api.py`、`test_rag_store.py`、`test_rag_search_freshness.py` 全通过；全局检索 P95 不劣化（记录实测毫秒）。

### T8 — A1：启用「先追问」分支

**文件**：`backend/app/services/agent/workflow_rules.py`、`backend/app/services/agent/loop.py`、`backend/app/core/config.py`、`backend/tests/test_workflow_rules.py`、`backend/tests/test_agent_loop.py`

**步骤**

1. 失败测试（`test_workflow_rules.py`）：
   - `detect_missing_constraints("帮我写一份新品上市方案")` 命中 ≥2 项（如预算、时间周期、成功指标）；
   - 含"预算 50 万、周期 3 个月、目标 GMV 1000 万"的目标 → 缺失 <2；
   - 含豁免语"基于已有资料直接产出，不用问" → 返回 `[]`；
   - 非方案类目标 → 返回 `[]`（由调用方 `is_plan_goal` 决定，函数本身不做豁免判断——按此实现，豁免只在调用方）。
2. `workflow_rules.py` 新增纯函数（规则表为常量，便于审计）：
```python
_CRITICAL_CONSTRAINT_PATTERNS: dict[str, tuple[str, ...]] = {
    "预算": ("预算", "费用", "投入", "roi 目标", "万元", "元/天"),
    "时间周期": ("周期", "时间", "排期", "上线时间", "个月", "周内", "天内"),
    "核心目标": ("目标", "要达成", "提升", "增长", "转化率目标"),
    "必讲信息": ("必须包含", "必讲", "卖点", "必须提及"),
    "成功指标": ("指标", "kpi", "考核", "达标", "验收标准"),
}

def detect_missing_constraints(goal: str) -> list[str]:
    text = (goal or "").lower()
    return [name for name, keys in _CRITICAL_CONSTRAINT_PATTERNS.items()
            if not any(k in text for k in keys)]
```
3. `config.py` 增 `admission_ask_enabled: bool = True`。
4. `loop.py:917-928` 改为：
```python
if stage == "admission":
    missing_sources = self._missing_required_sources(st)
    missing = []
    if self.admission_ask_enabled and is_plan_goal(run.goal) and not _RESEARCH_EXEMPT_GOAL_RE.search(run.goal or ""):
        missing = detect_missing_constraints(run.goal)
        if len(missing) < 2:
            missing = []
    rule = admission_judgment(run.goal, files_read_ok=not missing_sources, missing_constraints=missing)
    st.admission = rule.branch
    if rule.branch == "先追问":
        st.stage = "awaiting_question"
        raise _QuestionHangSignal(self._build_questions(run.goal, missing=missing))
    st.stage = "recap"
    st.stages_done.append("admission")
    continue
```
   （`__init__` 增 `self.admission_ask_enabled = getattr(settings, "admission_ask_enabled", True)`；导入 `is_plan_goal` 已存在，`_RESEARCH_EXEMPT_GOAL_RE` 同文件可用。）
5. `_build_questions(goal, missing=None)`：missing 非空时优先为每项生成一个问题（模板常量），再补齐原有固定问题，总数 ≤5。
6. `test_agent_loop.py` 增：缺 ≥2 项 → `_QuestionHangSignal` 且 stage 为 `awaiting_question`；完整目标 → 不抛；开关关闭 → 不抛。

**完成定义**：新增 ≥6 条测试通过；`test_agent_loop.py`、`test_langgraph_*` 全通过；`LANGGRAPH_ENABLED=false` 旧轨同样生效（两轨共用 `_advance_workflow_stage`）。

### T9 — A8+A6：headless 独立 DSH_HOME + 历史清理

**文件**：`backend/app/services/task_chain/service.py`、`backend/app/core/config.py`（如需）、`backend/tests/test_task_chain_service.py`、`backend/scripts/cleanup_headless_sessions.py`（新建）

**步骤**

1. 失败测试（service 层，mock 执行器）：断言 `_run_subtask` 调用执行器时传入了 `home_dir == settings.dsh_home_root_path / f"{user_id}-headless"`。
2. `service.py` 的 `_run_subtask`（`:163-168`）改为：
```python
headless_home = self.settings.dsh_home_root_path / f"{user_id}-headless"
result = await self.executor.run(user_id=user_id, task=task, home_dir=headless_home)
```
3. 计费扫描改指 headless home：`_stage_bill`（`:353-357`）把 `dsh_home_root_path / str(chain.user_id)` 换成同一个 `f"{user_id}-headless"` 路径；若取不到 usage 仍按既有降级路径（固定积点）并记录 warning。
4. 清理脚本 `cleanup_headless_sessions.py`（幂等、带 `--dry-run`）：
   - 删除 `<root>/<uid>/sessions/` 下**项目目录名形如 `--*var-dsh-<uid>--`** 的会话目录（即 headless 在 Web home 留下的会话，依据 `NOTES.md:511`）；
   - 从 `dsh_sessions` 删除这些会话对应行（先打印再删，`--dry-run` 只打印）。
5. 真实验收（见 T13）：连跑两次任务链，Web 实例不重启、侧栏无新增 UUID 会话、`dsh_sessions` 不增长、积分扣减非零。

**完成定义**：单测通过；清理脚本 `--dry-run` 输出与预期一致；真实运行记录写入验收文档。

---

## W3

### T10 — A3：任务链取消竞态

**文件**：`backend/app/repositories/task_chain_repository.py`、`backend/app/services/task_chain/service.py`、`backend/app/api/task_chains.py`、`backend/tests/test_task_chain_repository.py`、`backend/tests/test_task_chain_api.py`

**步骤**

1. 失败测试（仓储）：`set_chain_status_if(chain_id, from_statuses=("running",), to_status="succeeded")` 在链已是 `cancelled` 时返回 False 且不改库。
2. 仓储新增：
```python
async def set_chain_status_if(self, chain_id, from_statuses, to_status, **fields) -> bool:
    stmt = (
        update(TaskChain)
        .where(TaskChain.id == chain_id, TaskChain.status.in_(from_statuses))
        .values(status=to_status, **fields)
    )
    result = await self.db.execute(stmt)
    await self.db.commit()
    return result.rowcount == 1
```
3. `service.py`：`_begin`（`:111`）与阶段回写（`:137/332-337/369`）改为条件更新（`from_statuses=("running",)`，用于回写 `running` 时改为"若当前不是 running 则跳过并记日志"）；终态（`:116-123`）改为 `set_chain_status_if(..., from_statuses=("running",), to_status=...)`，未命中时 `logger.info("chain_terminal_skipped_already_terminal")`。
4. 阶段边界取消检查：`run_chain` 在每次 `_stage_*` 之前重读链状态（`expire_on_commit` 语义下用 `select` + `populate_existing` 或直接查 status 字段），若为 `cancelled` → 直接返回，不写任何终态。
5. API 取消（`:146-152`）改为 `set_chain_status_if(from_statuses=("queued","running"), to_status="cancelled", finished_at=...)`；未命中 → 409。
6. 新增并发用例：monkeypatch 让终态写与取消交错，断言最终为 `cancelled`；另一用例断言"阶段中途取消后不再进入下一阶段"。

**完成定义**：新增 ≥4 条测试通过；`test_task_chains_api.py` 原有用例全通过；真实取消一次运行中的链，终态保持 `cancelled`。

### T11a — B1 第一步：抽 `agent/quality_gate.py`

**文件**：`backend/app/services/agent/quality_gate.py`（新建）、`backend/app/services/agent/loop.py`

**步骤**

1. 新建模块，**原样搬迁**（不改逻辑）下列成员（行号见设计文档 B1 表）：`_quality_injection_hints`、`_prepare_quality_injection`、`_load_blueprint_full`、`_run_quality_review`、`_read_file_content_for_review`、`_format_review_hint`、`_enforce_answer_truthfulness`、`_enforce_save_intent`、`_enforce_final_step`、`_has_save_intent`、`_verified_save_answer`、`_merge_save_answer`。
2. 以**混入类**形式提供，避免改动 `AgentLoopService` 的继承链以外的东西：
```python
class QualityGateMixin:
    """质量自审与门禁（从 loop.py 原样搬迁）。"""
```
   `loop.py` 中 `class AgentLoopService(QualityGateMixin)`，删除已搬迁方法体，保留门面 re-export（`from app.services.agent.quality_gate import QualityGateMixin`）。
3. 迁移私有模块常量（若被搬迁方法使用，如 `_FINAL_ANSWER_FILE_RE`）到新模块，并在 `loop.py` 保留同名 re-export 供既有引用。
4. 验证：`pytest -q tests/test_agent_loop.py tests/test_quality_review.py tests/test_plan_quality_injection.py tests/test_agent_blueprint_closure.py` + 全量后端。

**完成定义**：全量后端 0 失败；`loop.py` 行数下降 ≥ 300；`git diff --name-only` 仅 `backend/app/services/agent/*`。

---

## W4

### T11b — B1 第二步：抽 `agent/tool_dispatch.py`

同 T11a 手法，搬迁：`_tool_event_payload`、`_sanitize_url`、`_sanitize_action`、`_journal_target`、`_sanitize_observation`、`_record_observation`、`_inject_observation_history`、`_looks_like_unsafe_visible_thought_chunk`、`_finalize_visible_thought`、`_finalize_pre_tool_visible_thought`、`_extract_goal_from_messages`、`_stream_visible_thought_with_tool_interleave`。`class AgentLoopService(ToolDispatchMixin, QualityGateMixin)`。

**完成定义**：全量后端 0 失败；工具交错相关定向测试通过。

### T12 — D5：作品集仓库收尾（Pages + README）

**文件**：本地导出目录（临时）与 GitHub 仓库；仓库内 `index.html`（新建）、`README.md`

**步骤**

1. 重新导出（复用既有流水线，顺序固定）：
   1) `git archive HEAD | tar -x` 到临时目录；
   2) 删除 `backend/var/**`（1861 个运行时数据文件）；
   3) 口令脱敏（`ChangeMe-Strong1`/`ChangeMe-Demo1` → `ChangeMe-*`）与 4 个中文 `.cmd` 文件名修复（用 Python 脚本，避免控制台编码问题）；
   4) 敏感项核验：`git ls-files | grep -E 'backend/var/|\.env$|node_modules'` 必须为 0；
   5) `git init -b main` + 单提交 + 推送（`GIT_SSH_COMMAND` 指定 `agent_loop_deploy` 密钥）。
2. 新增自包含 `index.html` 落地页（内联 CSS）：标题 + 一句话简介 + 链接 README 与 7 张架构图（`system-architecture-diagrams.html` 等）。
3. GitHub Pages：`Settings → Pages → Source: main / (root)` → 保存；等待发布后访问 `https://wanglongshen.github.io/naoker_agent_platform/`。
4. `README.md` 增：Pages 在线架构图链接 + 各图链接 + "界面截图"小节（占位说明，截图由用户提供后放 `docs/screenshots/`）。
5. 核验：Pages 可访问；7 张图渲染正常；仓库无敏感文件。

**完成定义**：Pages 地址可用；README 链接可达；核验脚本输出全绿。

---

## W5

### T11c — B1 第三步：抽 `agent/execution_kernel.py`

**步骤**

1. 搬迁（原样）：状态类与代理（`_AttemptContext`、`_RunWorkflowState`、`_WfProxy`、`_WF_ATTR_MAP`）、阶段机与门禁（`_advance_workflow_stage`、`_next_stage_after`、`_STAGE_ALLOWED_ACTIONS`、`_scan_highest_version`、`_enforce_stage_gate`、`_missing_required_sources*`、`_extract_required_source_files`、`_receipt_matches_path`）、两条驱动与图节点（`process_attempt`、`_process_attempt_internal`、`_maybe_run_graph_or_loop`、`_do_process_attempt`、`_do_process_attempt_graph`、`_do_node_*`、`_execute_one_step`、`_wf_to_state`/`_state_to_wf`/`_wf_fields_list`、`_run_graph`）、流式与消息构建、会话/附件、重试调度、计费累积、`should_try_direct_answer`。
2. `loop.py` 收缩为门面：`class AgentLoopService(ExecutionKernelMixin, ToolDispatchMixin, QualityGateMixin)`（若搬迁后无需 mixin 也可改为直接 re-export 全部公共符号）+ `agent_loop_service` 单例 + `redis_bridge` 桥接函数 + `remove_visible_thought_overlap` + `classify_agent_failure` + `RetryablePlannerError` re-export。
3. 验证顺序（每步通过再下一步）：定向测试 → 全量后端 `pytest -q` → 差分器（`LANGGRAPH_DIFF_*` 回放 10 场景，报告必须 10/10 零差异）。

**完成定义**：全量后端 0 失败；差分 10/10 零差异；`loop.py` < 800 行；无调用方改动。

---

## W6

### T13 — 端到端验收（真实运行，不写代码）

1. 用一键脚本起全栈（后端 8010 / 前端 3001 / 四个 worker）。
2. **A8/A6/A3 联合验收**：真实发一条方案任务链 → 全程观察 `/agent` 不重启不报错 → 完成后检查侧栏无新增 UUID 会话、`dsh_sessions` 无增长、积分扣减非零 → 再发一条并中途取消，终态保持 `cancelled` 且不再进入下一阶段。
3. **A1 验收**：发一条"帮我做一份新品上市方案"（缺预算/周期）→ 应出现追问与暂停；再发一条信息完整的目标 → 不追问。
4. **A5a 验收**：停用一个大库后全局检索仍返回满 top_k。
5. **D4 验收**：重启后端后立即检索，实测首次响应 < 2s，日志含 `rag_warmup_done`。
6. **A2 验收**：后端 `pytest -q` 与前端 `npx vitest run` 双双 0 失败。
7. 把以上实测数据写入 `docs/verification/optimization-batch-checklist.md` 并提交。

**完成定义**：清单 8 项全部有实测证据；文档提交。

---

## 提交规范

- 每任务独立提交，信息格式：`fix(A5b): 并发建库返回 409 而非 500` / `refactor(B1a): 抽出 quality_gate` / `chore(D5): 作品集 Pages 与 README 链接`
- 提交前 `git diff --cached --name-only` 核对暂存区，只含本任务文件
- 不提交 `backend/var/**`、`.env`、临时脚本
