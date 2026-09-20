# LangGraph 单轨化（SP1）验收清单

- 日期：2026-09-14
- 计划：`docs/superpowers/plans/2026-09-14-langgraph-single-track.md`
- 设计：`docs/superpowers/specs/2026-09-14-langgraph-single-track-design.md`
- 差分报告：`docs/langgraph-eval/report.md`（10 场景，10/10 零差异）

## 1. 交付状态

| 项 | 状态 | 证据 |
|---|---|---|
| LangGraph 成为默认执行引擎 | ✅ | `backend/app/core/config.py` `langgraph_enabled: bool = True`（提交 `8fb4232`） |
| 旧 while 轨回退开关 | ✅ | `.env` 设 `LANGGRAPH_ENABLED=false` 即回旧轨（测试 `test_settings_langgraph_flag.py`） |
| 录制/回放差分器 | ✅ | `backend/scripts/langgraph_differential.py`（`--record/--diff`，见 §3 用法） |
| 10 条场景 fixture（真实 LLM + 真实 web 录制） | ✅ | `docs/langgraph-eval/fixtures/scenario-1..10.json` |
| 全矩阵差分 0 差异 | ✅ | `docs/langgraph-eval/report.md`：10 场景 old/graph 事件数一致、diffs=0 |
| 全量回归 | ✅ | `pytest -q`：1124 passed / 5 failed（5 条均非本轮引入，见 §5） |

## 2. 差分矩阵结果（`docs/langgraph-eval/report.md`）

| # | 场景 | 覆盖分支 | old/graph 事件 | 差异 |
|---|---|---|---|---|
| 1 | 普通问答 fast path | `fast_path_enabled` 直答 | 10 / 10 | 0 |
| 2 | 方案类全流程 | 调研→写文件→结构门禁→质检→交付 | 846 / 846 | 0 |
| 3 | 必读文件未读→先追问 | `run_awaiting_question`（平台样本门禁路径） | 839 / 839 | 0 |
| 4 | 研究前置门禁 | 阶段机 research→content | 837 / 837 | 0 |
| 5 | 版本规则 | `version_mismatch` 门禁 + 多 attempt 重试 | 598 / 598 | 0 |
| 6 | 结构校验拒稿→骨架补全 | `plan_structure_incomplete`→骨架补全 | 1077 / 1077 | 0 |
| 7 | 重试耗尽 run_failed | 确定性故障注入 → 3 attempt 全失败 → `run_failed` | 269 / 269 | 0 |
| 8 | 附件引用 | 附件进 planner + `invalid_tool_input` 重试 | 605 / 605 | 0 |
| 9 | 质检闭环 | `quality_review_started/completed` | 974 / 974 | 0 |
| 10 | 计费/usage | usage 累计 → 积分扣减 | 841 / 841 | 0 |

差分方法：同一 fixture 分别驱动旧轨（`langgraph_enabled=False`）与图轨（`True`），
采集 `agent_run_events` 全量事件，经 `event_normalize` 归一化（易变字段：事件 id、
时间戳、UUID、ISO 时间、`stream_id` 按首现顺序编号）后逐字节比对；
回放期非确定性 web 工具（web_search/fetch_web_content/http_request/fetch_platform_search）
替换为固定返回（工具层为两轨共享代码，其内部行为不属轨道差异）。

## 3. 差分器用法（复现/回归）

```powershell
cd backend
$env:WEB_TOOL_ALLOW_NON_GLOBAL_TARGETS="true"   # 仅本机 fake-IP 环境需要（默认关闭，生产必须 false）
X:\python\anaconda\envs\01-rbac\python.exe -m scripts.langgraph_differential --record 3   # 录制单场景（真实 LLM）
X:\python\anaconda\envs\01-rbac\python.exe -m scripts.langgraph_differential --diff all   # 全矩阵差分
```

- fixture 与报告在仓库根 `docs/langgraph-eval/`。
- 录制会向测试库（`rbac_test`）seed 工作流文档（`scripts/diff_seed.py`，幂等、只读开发库）。
- 场景 7 用确定性故障注入（脚本层 monkeypatch，不改 `app/**`）。

## 4. 人工抽查清单（真实任务，浏览器/API）

| # | 操作 | 期望 |
|---|---|---|
| 1 | 登录后发普通问答（如「你好」） | 流式回复正常，无 plan/思考事件，速度快 |
| 2 | 发方案类任务（如「写一份 XX 新品上市方案」） | 出现调研→写文件→质检→交付；文件落盘可下载；answer 含真实文件名/路径/SHA |
| 3 | 带必读文件的任务（工作流规则要求先读） | 先读文件再产出；未读时被门禁拦截 |
| 4 | 上传附件后要求「参考附件写方案」 | 附件内容进入规划与产出 |
| 5 | 触发版本规则（同名 `_V2.md` 目标） | 版本号被纠正为下一版本 |
| 6 | 观察积分 | run 成功后积分按 usage 扣减 |
| 7 | 回退演练：`.env` 设 `LANGGRAPH_ENABLED=false` 重启后端 | 任务仍可完成（走旧 while 轨） |

## 5. 已知边界与后续待办

1. **「先追问」分支当前不可达（生产缺陷，本轮仅记录）**：`admission_judgment(..., missing_constraints=[])` 硬编码空列表（`backend/app/services/agent/loop.py:906`），
   缺「预算/时间周期/核心目标」时应反问用户的分支永远不会触发；场景 3 实际覆盖的是平台样本门禁的 `run_awaiting_question`。
   需要单独设计「缺失约束如何计算」再启用（用户已确认本轮不动）。
2. **`create_plan` 零覆盖**：223+ 次真实录制全部走 `stream_text`（merged planner），差分不覆盖 `create_plan` 路径。
3. **场景 4 的 `research_required` 错误分支**：正常流程下阶段机先 research，该错误路径在场景 7 fixture 中出现（跨场景覆盖）。
4. **回放期 web 工具为确定性桩**：仅回放生效；录制为真实网络。工具层是两轨共享代码，故不构成轨道差异面。
5. **全量回归中 5 条非本轮失败**：`test_file_reader.py` 4 条（本机缺 `pypdf/docx/openpyxl/pptx` 依赖）+ `test_agent_blueprint_closure.py` 1 条（他人未跟踪的 WIP 测试文件，不在 git 中）。
6. **测试基建坑**：`test_alembic_config.py` 调用 `get_settings.cache_clear()`，之后 `get_settings()` 返回新对象，而 app 模块持有的旧 settings 引用不受影响——
   需要 patch 模块级 `settings` 才能打中真实执行路径（已在本轮相关测试中处理）。
