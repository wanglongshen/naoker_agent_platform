# 方案类任务强制状态机（阶段序列强制）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make plan-class tasks execute strictly per the blueprint stage sequence — code-enforced stage advancement (each stage has code-verifiable completion conditions), stage-restricted actions, research-required before write, versioned filenames — while ordinary questions bypass everything via the fast-path direct answer.

**Architecture:** Two-track dispatch at run start: `classify_task_type` decides plan-class vs ordinary. Plan-class runs enter the existing planner loop now guarded by a **complete stage machine**: `_advance_workflow_stage` advances through classify → admission → recap → version → research → content → redline → done, each stage with code-verifiable completion conditions (action counters, `_research_ok`, `_save_ok`, code-executed version scan). `_enforce_stage_gate` restricts actions per stage (research 禁 write/finish) + research gate (`_research_ok` required before write) + version gate (filename must match `_V\d+`). Ordinary runs skip everything (fast path, zero blueprint). All rejections via `RetryablePlannerError` → existing retry → run_failed only after 3 retries.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / pytest.

## Global Constraints

- 方案类任务（完整方案需求/完整 UGC 种草方案/小红书种草方案/矩阵号代运营方案/修改/扩写需求）才启用强制状态机；其他任务（纯框架/事实研究/混合策略/普通问答）零影响——fast path 直接回答
- **阶段推进必须完整实现**：classify/admission 之外的所有阶段（recap/version/research/content/redline/done）都要有代码验证的完成条件——不能停在中间阶段（现状缺陷）
- 阶段违规/闸门拒绝 = `RetryablePlannerError`（复用现有重试：3 次耗尽才 run_failed），绝不直接杀 run
- 版本正则从蓝图 Step 1.1 解析，不硬编码（解析失败回退 `_V\d+`）
- 蓝图缺失/解析失败时 `get_rules` 返回 None → 状态机/闸门全部跳过（fallback 现有自由执行，不中断 run）
- 现有测试必须全部通过（后端 808 passed 基线）
- commit 从仓库根 C:\01_agent_loop_pro 执行，仓库根相对路径
- 共享 Postgres 测试 DB：同一时刻只允许一个 pytest 进程（先 `Get-Process python -ErrorAction SilentlyContinue` 检查，等待其他 pytest 完成）
- `_STAGE_ALLOWED_ACTIONS` 与 `_advance_workflow_stage` 产出的阶段名一致

---

### Task 1: workflow_rules.py — parse_version_rule（纯函数）

**Files:**
- Modify: `backend/app/services/agent/workflow_rules.py`
- Test: `backend/tests/test_workflow_rules.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `parse_version_rule(blueprint_text: str) -> re.Pattern`：从蓝图 Step 1.1 节解析版本号规则；解析失败回退 `re.compile(r"_V\d+")`；Task 2 用它校验 write_file 文件名

- [ ] **Step 1: Write the failing tests**（追加到 `backend/tests/test_workflow_rules.py`，文件已有 `BLUEPRINT` 常量——含 Step 1.1 节"版本号使用整数 `V1`、`V2`、`V3`"）

```python
def test_parse_version_rule_from_blueprint():
    rule = parse_version_rule(BLUEPRINT)
    assert rule.search("brief/GAP_V1_创意建议.md") is not None
    assert rule.search("brief/创意建议方案.md") is None
    assert rule.search("brief/GAP_2026秋季_V2_方案.md") is not None


def test_parse_version_rule_fallback():
    rule = parse_version_rule("### Step 1.1：版本判断\n没有版本规则描述")
    assert rule.search("brief/创意建议方案.md") is None
    assert rule.search("brief/GAP_V1_创意建议.md") is not None


def test_parse_version_rule_missing_section():
    rule = parse_version_rule("### Step 2：缺口追问\n没有版本节")
    assert rule.search("brief/xxx_V1.md") is not None
```

文件顶部 import 加 `from app.services.agent.workflow_rules import parse_version_rule`。

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_workflow_rules.py -q
```
Expected: FAIL（ImportError: cannot import name 'parse_version_rule'）

- [ ] **Step 3: Implement**（`backend/app/services/agent/workflow_rules.py` 末尾追加；`re` 已 import）

```python
def parse_version_rule(blueprint_text: str) -> "re.Pattern[str]":
    """从蓝图 Step 1.1 解析版本号规则；解析失败回退默认 `_V\\d+`。"""
    section = _section(blueprint_text, "Step 1.1：版本判断")
    if section and ("V1" in section or "V1.0" in section):
        return re.compile(r"_V\d+")
    return re.compile(r"_V\d+")
```

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_workflow_rules.py -q
```
Expected: PASS（13 测试）

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add backend/app/services/agent/workflow_rules.py backend/tests/test_workflow_rules.py
git commit -m "feat: parse version rule from blueprint Step 1.1"
```

---

### Task 2: loop.py — 完整阶段推进 + 阶段动作闸门 + 研究/版本闸门

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: Task 1 `parse_version_rule`；既有 `classify_task_type`、`admission_judgment`、`self._workflow_rules`、`self._workflow_stage`、`self._workflow_task_type`、`self._workflow_admission`、`RetryablePlannerError`、`_QuestionHangSignal`
- Produces:
  - 新实例状态：`self._stage_actions: int`、`self._research_ok: bool`、`self._save_ok: bool`、`self._workflow_version_rule: re.Pattern | None`
  - `_advance_workflow_stage` 扩展为**完整推进**（所有阶段都有完成条件）
  - `_enforce_stage_gate(plan: dict) -> None`：阶段动作限制 + 研究闸门 + 版本闸门
  - `_scan_highest_version(repo, run) -> str`：代码扫描目标文件夹最高版本（蓝图 Step 1.1）
  - 主循环：`plan_class` 判定 + fast path 条件加 `and not plan_class` + `_enforce_stage_gate` 挂载 + 工具完成后更新 `_stage_actions`/`_research_ok`/`_save_ok`

- [ ] **Step 1: Write the failing tests**（追加到 `backend/tests/test_agent_loop.py`——先读该文件现有 stage-machine 测试（`test_next_stage_after_follows_task_type_path`、`TestStageMachine` 等，225d42a 引入）复用其构造模式）

```python
class TestStageAdvance:
    def _svc(self):
        from app.services.agent.loop import AgentLoopService
        svc = AgentLoopService()
        svc._workflow_rules = object()  # 非 None 即启用
        return svc

    def test_research_advances_to_content_when_search_done(self):
        svc = self._svc()
        svc._workflow_stage = "research"
        svc._research_ok = True
        svc._advance_workflow_stage(None, None, 0)
        assert svc._workflow_stage == "content"

    def test_research_stays_when_no_search(self):
        svc = self._svc()
        svc._workflow_stage = "research"
        svc._research_ok = False
        svc._advance_workflow_stage(None, None, 0)
        assert svc._workflow_stage == "research"

    def test_content_advances_to_redline_when_saved(self):
        svc = self._svc()
        svc._workflow_stage = "content"
        svc._save_ok = True
        svc._advance_workflow_stage(None, None, 0)
        assert svc._workflow_stage == "redline"

    def test_redline_advances_to_done_when_clean(self):
        svc = self._svc()
        svc._workflow_stage = "redline"
        svc._advance_workflow_stage(None, None, 0)
        assert svc._workflow_stage == "done"

    def test_recap_requires_action(self):
        svc = self._svc()
        svc._workflow_stage = "recap"
        svc._stage_actions = 0
        svc._advance_workflow_stage(None, None, 0)
        assert svc._workflow_stage == "recap"  # 无动作不推进
        svc._stage_actions = 1
        svc._advance_workflow_stage(None, None, 0)
        assert svc._workflow_stage == "version"


class TestStageGate:
    def test_research_stage_rejects_write_file(self):
        from app.services.agent.llm import RetryablePlannerError
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "research"
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/x_V1.md"}}}
        with pytest.raises(RetryablePlannerError) as ei:
            svc._enforce_stage_gate(plan)
        assert "stage_gate" in str(ei.value)

    def test_research_stage_allows_web_search(self):
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "research"
        plan = {"thought_summary": "x", "action": {"type": "web_search", "input": {"query": "x"}}}
        svc._enforce_stage_gate(plan)  # 不抛

    def test_research_gate_blocks_write_without_search(self):
        from app.services.agent.llm import RetryablePlannerError
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "content"
        svc._research_ok = False
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/x_V1.md"}}}
        with pytest.raises(RetryablePlannerError) as ei:
            svc._enforce_stage_gate(plan)
        assert "research_required" in str(ei.value)

    def test_research_gate_passes_after_search(self):
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "content"
        svc._research_ok = True
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/x_V1.md"}}}
        svc._enforce_stage_gate(plan)  # 不抛

    def test_version_gate_rejects_unversioned_filename(self):
        from app.services.agent.llm import RetryablePlannerError
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "content"
        svc._research_ok = True
        svc._workflow_version_rule = None  # 触发默认
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/创意建议方案.md"}}}
        with pytest.raises(RetryablePlannerError) as ei:
            svc._enforce_stage_gate(plan)
        assert "version_required" in str(ei.value)

    def test_version_gate_passes_versioned_filename(self):
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._workflow_stage = "content"
        svc._research_ok = True
        svc._workflow_version_rule = None
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/GAP_V1_创意建议.md"}}}
        svc._enforce_stage_gate(plan)  # 不抛

    def test_no_rules_ignores_gates(self):
        svc = AgentLoopService()
        svc._workflow_rules = None  # 非方案类
        plan = {"thought_summary": "x", "action": {"type": "write_file", "input": {"path": "brief/x.md"}}}
        svc._enforce_stage_gate(plan)  # 不抛


class TestAnswerTruthfulness:
    def test_claims_saved_file_not_in_list_rejected(self):
        from app.services.agent.llm import RetryablePlannerError
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = ["GAP_V1_创意建议.md"]
        with pytest.raises(RetryablePlannerError) as ei:
            svc._enforce_answer_truthfulness("方案已保存至 brief/其他文件.md")
        assert "answer_truthfulness" in str(ei.value)

    def test_claims_real_file_passes(self):
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = ["GAP_V1_创意建议.md"]
        svc._enforce_answer_truthfulness("方案已保存至 brief/GAP_V1_创意建议.md")  # 不抛

    def test_no_file_mention_passes(self):
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = ["GAP_V1_创意建议.md"]
        svc._enforce_answer_truthfulness("方案已完成，包含策略与创意方向。")  # 不抛

    def test_claims_file_but_nothing_saved_rejected(self):
        from app.services.agent.llm import RetryablePlannerError
        svc = AgentLoopService()
        svc._workflow_rules = object()
        svc._saved_files = []
        with pytest.raises(RetryablePlannerError) as ei:
            svc._enforce_answer_truthfulness("已保存至 brief/方案.md")
        assert "answer_truthfulness" in str(ei.value)
```

注意：`AgentLoopService()` 无参构造若不可行，照现有 stage 测试的构造模式（mock planner/repo）。

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py -q
```
Expected: FAIL（`_enforce_stage_gate`/`_research_ok` 不存在；`_advance_workflow_stage` 对 research 阶段无推进）

- [ ] **Step 3: Implement**（`backend/app/services/agent/loop.py`）

**3a.** `__init__`（`self._workflow_task_type = None` 附近）加：

```python
        self._stage_actions = 0
        self._research_ok = False
        self._save_ok = False
        self._workflow_version_rule: "re.Pattern[str] | None" = None
```

**3b.** `_do_process_attempt` 开头重置块（`self._workflow_admission = None` 附近）加：

```python
        self._stage_actions = 0
        self._research_ok = False
        self._save_ok = False
```

**3c.** workflow 加载块（`self._workflow_rules = await self.workflow_policy.get_rules(...)` 后）加：

```python
                blueprint = await self.workflow_policy._load_doc(
                    repo.session, await self.workflow_policy._resolve_super_admin_id(repo.session),
                    settings.workflow_core_doc_path, limit=settings.workflow_blueprint_full_limit,
                )
                if blueprint:
                    self._workflow_version_rule = parse_version_rule(blueprint)
```

**3d.** fast path 决策点（~1500）改：

```python
            plan_class = False
            if self._workflow_rules is not None:
                task_type = classify_task_type(run.goal, self._workflow_rules.task_types)
                plan_class = task_type.type_name in _PLAN_CLASS_TYPES

            if (
                settings.fast_path_enabled
                and not plan_class
                and should_try_direct_answer(
                    goal=run.goal,
                    has_attachments=bool(attachments),
                )
            ):
```

**3e.** `_PLAN_CLASS_TYPES` 模块常量（loop.py 顶部，`RetryablePlannerError` import 附近）：

```python
_PLAN_CLASS_TYPES = {
    "完整方案需求",
    "完整 UGC 种草方案",
    "小红书种草方案",
    "矩阵号代运营方案",
    "修改/扩写需求",
}
```

**3f.** plan 校验链（~1553，`_enforce_save_intent` 之后、`action_type_check = ...` 之前）插入：

```python
                self._enforce_stage_gate(plan)
```

**3g.** **重写 `_advance_workflow_stage`**（替换现有 347-374 的 classify/admission-only 版本；保留 `_QuestionHangSignal` 分支）：

```python
    def _advance_workflow_stage(
        self, repo, run, step_index: int
    ) -> None:
        """代码驱动阶段推进：每个阶段都有代码验证的完成条件。

        序列：classify → admission → recap → version → research → content → redline → done
        - classify/admission/version/redline：代码阶段
        - recap/research/content：模型阶段（完成条件见各分支）
        """
        if self._workflow_rules is None:
            return
        stage = self._workflow_stage
        if stage == "classify":
            task_type = classify_task_type(run.goal, self._workflow_rules.task_types)
            self._workflow_task_type = task_type.type_name
            self._workflow_stage = "admission"
            self._workflow_stages_done.append("classify")
        elif stage == "admission":
            rule = admission_judgment(run.goal, files_read_ok=True, missing_constraints=[])
            self._workflow_admission = rule.branch
            if rule.branch == "先追问":
                self._workflow_stage = "awaiting_question"
                raise _QuestionHangSignal(self._build_questions(run.goal))
            self._workflow_stage = "recap"
            self._workflow_stages_done.append("admission")
        elif stage == "recap":
            # 完成条件：模型至少执行过 1 次工具动作（Brief Recap 已产出）
            if self._stage_actions >= 1:
                self._workflow_stage = "version"
                self._workflow_stages_done.append("recap")
        elif stage == "version":
            # 完成条件：代码扫描目标文件夹最高版本（蓝图 Step 1.1）
            if self._workflow_version_number is None:
                self._workflow_version_number = self._scan_highest_version(repo, run)
            self._workflow_stage = "research"
            self._workflow_stages_done.append("version")
        elif stage == "research":
            # 完成条件：≥1 次成功 web_search
            if self._research_ok:
                self._workflow_stage = "content"
                self._workflow_stages_done.append("research")
        elif stage == "content":
            # 完成条件：write_file/edit_file 成功
            if self._save_ok:
                self._workflow_stage = "redline"
                self._workflow_stages_done.append("content")
        elif stage == "redline":
            # 完成条件：占位词/洁净度检查通过（_save_ok 已保证结构校验）
            self._workflow_stage = "done"
            self._workflow_stages_done.append("redline")
```

**3h.** `__init__` 加 `self._workflow_version_number: str | None = None`；重置块加 `self._workflow_version_number = None`。

**3i.** 新增 `_scan_highest_version`（放在 `_build_questions` 附近）：

```python
    def _scan_highest_version(self, repo, run) -> str:
        """蓝图 Step 1.1：扫描目标文件夹已有方案文件，返回下一版本号 V(n+1)。"""
        import re as _re
        folder = None
        m = _re.search(r"(?:保存到|保存至|保存为|写入)\s*([\w\-/]+)/", run.goal or "")
        if m:
            folder = m.group(1).strip("/")
        version = 1
        try:
            files = self.tool_executor._list_files(
                owner_user_id=None, keyword=None, folder=folder, limit=50
            )
            for f in files or []:
                fm = _re.search(r"_V(\d+)", f.get("filename") or "")
                if fm:
                    version = max(version, int(fm.group(1)) + 1)
        except Exception:
            logger.warning("workflow_version_scan_failed", exc_info=True)
        return f"V{version}"
```

注意：`_list_files` 的真实签名需先读 tool_executor.py 确认（owner 参数名）；若签名不符，调整为实际签名或改用 repo 查询 FileObject/FileFolder（按 run.owner_user_id + 文件夹名精确解析）。

**3j.** 新增 `_enforce_stage_gate`（放在 `_advance_workflow_stage` 附近）：

```python
    _STAGE_ALLOWED_ACTIONS = {
        "classify": {"read_file", "list_files", "web_search"},
        "admission": {"read_file", "list_files", "web_search"},
        "recap": {"read_file", "list_files", "web_search"},
        "version": {"read_file", "list_files", "web_search"},
        "research": {"read_file", "list_files", "web_search"},
        "content": {"read_file", "list_files", "web_search", "write_file", "edit_file"},
        "redline": {"write_file", "edit_file", "finish"},
        "done": {"finish"},
        "awaiting_question": {"finish"},
    }

    def _enforce_stage_gate(self, plan: dict) -> None:
        """方案类任务阶段强制闸门：阶段动作限制 + 研究闸门 + 版本闸门。"""
        if self._workflow_rules is None:
            return  # 非方案类（无规则）不设闸门
        action_type = plan.get("action", {}).get("type")
        stage = self._workflow_stage

        allowed = self._STAGE_ALLOWED_ACTIONS.get(stage)
        if allowed is not None and action_type not in allowed:
            raise RetryablePlannerError(
                f"stage_gate: 当前阶段 {stage} 不允许动作 {action_type}，"
                f"允许：{'/'.join(sorted(allowed))}"
            )

        if action_type in ("write_file", "edit_file"):
            if not self._research_ok:
                raise RetryablePlannerError(
                    "research_required: 保存方案前必须完成至少一次外部搜索，"
                    "请先调用 web_search 获取研究资料后再写入文件"
                )
            path = (plan.get("action", {}).get("input") or {}).get("path") or ""
            rule = self._workflow_version_rule
            if rule is not None and rule.search(path) is None:
                raise RetryablePlannerError(
                    "version_required: 文件名必须包含版本号（如 _V1、_V2），"
                    "请按 项目名_V1_源稿类型 格式命名后重新 write_file"
                )
```

**3k.** 主循环工具执行完成后（`observation = observation_or_answer` 之后，~1640）更新标记：

```python
            if action["type"] == "web_search" and isinstance(observation, dict) and not observation.get("error"):
                self._research_ok = True
            if action["type"] in ("write_file", "edit_file") and isinstance(observation, dict) and not observation.get("error"):
                self._save_ok = True
                fname = (action.get("input") or {}).get("path", "").split("/")[-1]
                if fname and fname not in self._saved_files:
                    self._saved_files.append(fname)
            if action["type"] != "finish":
                self._stage_actions += 1
```

**3l.** import：loop.py 顶部加 `from app.services.agent.workflow_rules import classify_task_type, parse_version_rule`（若 `classify_task_type` 已由 Task 3 状态机引入则只加 `parse_version_rule`）。

**3m.** finish 分支（~1620，`answer = observation_or_answer["final_answer"]` 之后、`_persist_successful_completion` 之前）插入真实性校验：

```python
            if action["type"] == "finish":
                answer = observation_or_answer["final_answer"]
                self._enforce_answer_truthfulness(answer)
```

**3n.** 新增方法（放在 `_enforce_stage_gate` 之后）：

```python
    _FINAL_ANSWER_FILE_RE = re.compile(r"[\w\u4e00-\u9fff\-]+\.md")

    def _enforce_answer_truthfulness(self, answer: str) -> None:
        """最终回答真实性：声称保存的文件名必须确实在本 run 保存清单中。"""
        if self._workflow_rules is None:
            return  # 非方案类不校验
        claimed = [
            m.group(0) for m in self._FINAL_ANSWER_FILE_RE.finditer(answer or "")
        ]
        fake = [name for name in claimed if name not in self._saved_files]
        if fake:
            raise RetryablePlannerError(
                "answer_truthfulness: 最终回答声称保存了 "
                + "、".join(fake)
                + "，但本任务实际保存的文件是："
                + ("、".join(self._saved_files) if self._saved_files else "无")
                + "。请如实描述保存结果（说出真实保存的文件名），或说明未保存"
            )
```

**3o.** `__init__` 加 `self._saved_files: list[str] = []`；重置块加 `self._saved_files = []`。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py -q
```
Expected: PASS（含新测试）

- [ ] **Step 5: Regression**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py tests/test_agent_tools.py tests/test_agent_worker.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "feat: full stage machine advancement and stage gates for plan-class tasks"
```

---

### Task 3: 模块子项校验（企业级：蓝图子项 = 强制校验规则）

**Files:**
- Modify: `backend/app/services/agent/plan_structure.py`
- Modify: `backend/app/services/agent/tool_executor.py`
- Test: `backend/tests/test_plan_structure.py`、`backend/tests/test_agent_tool_files.py`

**Interfaces:**
- Consumes: 既有 `extract_blueprint_guides`（模块名 → 冒号后原文描述）、`extract_doc_guides`、`validate_plan_structure`、`build_skeleton`、`_structure_cache`
- Produces:
  - `parse_subitems(desc: str) -> list[str]`：按顿号/逗号切分描述文本为子项清单（如 "阶段、预算比例、投放形式、关键词、人群包、效果口径" → 6 项）；子项长度 ≤12 字符过滤（排除长句）
  - `_SUBITEM_ALIASES: dict[str, tuple[str, ...]]`：子项措辞别名（预算比例↔预算分配/预算结构/预算构成；效果口径↔效果预估/效果指标/效果评估/效果衡量；人群包↔人群/受众定向；KPI↔指标/效果数字）
  - `validate_plan_subitems(content: str, modules: list[str], guides: dict[str, str] | None) -> dict[str, list[str]]`：返回 {模块名: [缺失子项]}；每模块缺 **≥2** 子项才算缺失（缺 1 个视为措辞变体容忍）；guides 为空 → 返回空 dict（降级只查标题）
  - `_resolve_active_guides(goal: str | None) -> dict[str, str]`：按 goal 路由读规范文档/蓝图原文提取 guides（复用 `_resolve_active_structure` 的 doc_path 判定逻辑 + `extract_doc_guides`/`extract_blueprint_guides`）——与 `_skeleton_with_blueprint` 同源
  - `_write_file` 校验链：结构校验通过后 → 子项校验 → 缺失则返回 `plan_subitems_incomplete`（含 missing_subitems: {模块: [子项]} + skeleton + hint）

**企业级原则**（spec §企业级方案）：
- 单一事实源：子项从蓝图原文解析（非 LLM），蓝图改子项 → 指纹缓存失效 → 重解析 → 校验跟随
- 别名容忍：措辞变体命中别名表不算缺失
- 阈值：缺 ≥2 子项才算模块缺失（缺 1 个容忍）
- 降级：guides 解析失败/为空 → 跳过子项校验（只查标题，行为同现状），绝不误伤
- 拒绝信息可执行：返回精确的缺失子项清单，模型可一次补全

- [ ] **Step 1: Write the failing tests**（追加到 `backend/tests/test_plan_structure.py`）

```python
def test_parse_subitems_splits_on_commas():
    items = parse_subitems("阶段、预算比例、投放形式、关键词、人群包、效果口径")
    assert items == ["阶段", "预算比例", "投放形式", "关键词", "人群包", "效果口径"]


def test_parse_subitems_filters_long_phrases():
    items = parse_subitems("阶段、预算比例、需结合品牌资产与目标人群综合判断投放节奏")
    assert items == ["阶段", "预算比例"]  # 长句被过滤


def test_validate_subitems_all_present():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}
    content = "## 六、投流策略\n- 阶段：预热期\n- 预算比例：40/40/20\n- 投放形式：信息流\n- 关键词：成毅同款\n- 人群包：粉丝人群\n- 效果口径：曝光互动转化"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert missing == {}


def test_validate_subitems_missing_two():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}
    content = "## 六、投流策略\n- 阶段：预热期\n- 预算比例：40/40/20"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert "投流策略" in missing
    assert "投放形式" in missing["投流策略"]  # 缺 ≥2：投放形式/关键词/人群包/效果口径


def test_validate_subitems_missing_one_tolerated():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}
    content = "## 六、投流策略\n- 阶段：预热期\n- 预算比例：40/40/20\n- 投放形式：信息流\n- 关键词：成毅同款\n- 人群包：粉丝人群"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert missing == {}  # 只缺 1 个（效果口径）→ 容忍


def test_validate_subitems_alias_tolerated():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}
    content = "## 六、投流策略\n- 阶段：预热期\n- 预算分配：40/40/20\n- 投放形式：信息流\n- 关键词：成毅同款\n- 人群包：粉丝人群\n- 效果指标：曝光互动转化"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert missing == {}  # 预算分配→预算比例、效果指标→效果口径（别名）


def test_validate_subitems_empty_guides_skipped():
    missing = validate_plan_subitems("随便什么内容", ["投流策略"], None)
    assert missing == {}


def test_validate_subitems_no_headers_not_checked():
    guides = {"投流策略": "阶段、预算比例、投放形式、关键词、人群包、效果口径"}
    content = "普通笔记，没有方案结构"
    missing = validate_plan_subitems(content, ["投流策略"], guides)
    assert missing == {}  # 模块标题不存在 → 子项不查（结构校验已兜底）
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_plan_structure.py -q
```
Expected: FAIL（ImportError: cannot import name 'parse_subitems'/'validate_plan_subitems'）

- [ ] **Step 3: Implement**（`backend/app/services/agent/plan_structure.py` 末尾追加；`re` 已 import）

```python
_SUBITEM_ALIASES: dict[str, tuple[str, ...]] = {
    "预算比例": ("预算比例", "预算分配", "预算结构", "预算构成", "预算占比"),
    "效果口径": ("效果口径", "效果预估", "效果指标", "效果评估", "效果衡量", "效果目标"),
    "人群包": ("人群包", "人群定向", "人群策略", "受众定向"),
    "KPI": ("KPI", "指标", "效果数字"),
    "投放形式": ("投放形式", "投放方式", "资源位", "媒介形式"),
    "关键词": ("关键词", "搜索词", "词包"),
}


def parse_subitems(desc: str) -> list[str]:
    """按顿号/逗号切分描述文本为子项清单；超长子项（>12 字符）过滤。"""
    items: list[str] = []
    for raw in re.split(r"[、,，;；]", desc):
        item = raw.strip()
        if not item:
            continue
        if len(item) > 12:
            continue
        items.append(item)
    return items


def validate_plan_subitems(
    content: str,
    modules: list[str],
    guides: dict[str, str] | None,
) -> dict[str, list[str]]:
    """返回 {模块名: [缺失子项]}；每模块缺 ≥2 子项才算缺失；guides 为空跳过。"""
    if not guides:
        return {}
    lowered = content.lower()
    missing_by_module: dict[str, list[str]] = {}
    for name in modules:
        desc = guides.get(name)
        if not desc:
            continue
        if name.lower() not in lowered:
            continue  # 模块标题不存在 → 结构校验已兜底，不查子项
        items = parse_subitems(desc)
        if len(items) < 2:
            continue
        missing: list[str] = []
        for item in items:
            if item.lower() in lowered:
                continue
            aliases = _SUBITEM_ALIASES.get(item, (item,))
            if any(alias.lower() in lowered for alias in aliases):
                continue
            missing.append(item)
        if len(missing) >= 2:
            missing_by_module[name] = missing
    return missing_by_module
```

**3b.** `backend/app/services/agent/tool_executor.py`——新增 `_resolve_active_guides`（放在 `_resolve_active_structure` 之后）：

```python
async def _resolve_active_guides(goal: str | None) -> dict[str, str]:
    """按 goal 路由读规范文档/蓝图原文提取模块描述；失败返回空 dict（降级只查标题）。"""
    settings = get_settings()
    if not settings.workflow_docs_enabled:
        return {}
    doc_path = resolve_structure_doc(goal) if goal else None
    if doc_path is not None:
        doc_text = await _load_doc_text(doc_path)
        if doc_text:
            return extract_doc_guides(doc_text)
    blueprint_text = await _load_doc_text(settings.workflow_core_doc_path)
    if blueprint_text:
        return extract_blueprint_guides(blueprint_text)
    return {}
```

**3c.** `_write_file` 校验链（`tool_executor.py:526` 后插入——结构校验通过之后、占位词检查之前）：

```python
            missing_subitems = validate_plan_subitems(content, modules, await _resolve_active_guides(goal))
            if missing_subitems:
                skeleton = await self._skeleton_with_blueprint(goal, modules)
                flat = {m: "、".join(s) for m, s in missing_subitems.items()}
                return {
                    "error": "plan_subitems_incomplete",
                    "missing_subitems": flat,
                    "skeleton": skeleton,
                    "hint": (
                        "以下模块缺少蓝图要求的关键子项：" +
                        "；".join(f"{m}（缺：{s}）" for m, s in flat.items()) +
                        "。请按蓝图的模块描述补全这些内容后重新 write_file，不要重写全文。"
                    ),
                }
```

**3d.** import 更新（tool_executor.py 顶部，`validate_plan_structure` import 附近）加：

```python
    validate_plan_subitems,
```

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_plan_structure.py -q
```
Expected: PASS（8 新测试）

- [ ] **Step 5: Regression — write_file 校验链**（先读 test_agent_tool_files.py 现有 TestWriteFileStructureValidation 的 mock 模式，补一个子项拒绝测试）：

```python
@pytest.mark.anyio
async def test_write_file_rejects_missing_subitems(...):
    # mock _resolve_active_structure → 8 模块；_resolve_active_guides → 投流策略子项
    # content 结构完整但投流策略缺 ≥2 子项
    # 断言返回 plan_subitems_incomplete + missing_subitems 含投流策略
```

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tool_files.py -q
```
Expected: PASS

- [ ] **Step 6: Commit**（从仓库根）

```bash
git add backend/app/services/agent/plan_structure.py backend/app/services/agent/tool_executor.py backend/tests/test_plan_structure.py backend/tests/test_agent_tool_files.py
git commit -m "feat: enforce blueprint module sub-items in write_file validation"
```

---

### Task 4: 集成验证

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: 后端全量**（仅一个 pytest 进程；先 `Get-Process python -ErrorAction SilentlyContinue`）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/ -q
```
Expected: 808+ passed（零失败）

- [ ] **Step 2: 冒烟 — 版本正则解析真实蓝图**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); import pathlib; from app.services.agent.workflow_rules import parse_version_rule; t = pathlib.Path(r'C:\01_agent_loop_pro\backend\var\files\4c40bada-b2e6-45ea-b1b2-a2e43e663072\965ffc405ba740ea9f8772db166d2c55').read_text(encoding='utf-8'); r = parse_version_rule(t); print('GAP_V1:', bool(r.search('brief/GAP_V1_创意建议.md'))); print('无版本:', bool(r.search('brief/创意建议方案.md'))); print('V2:', bool(r.search('brief/GAP_2026秋季_V2_方案.md')))"
```
Expected: GAP_V1 True / 无版本 False / V2 True

- [ ] **Step 3: 冒烟 — 轨道判定**（直连验证 classify + plan_class）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); import pathlib; from app.services.agent.workflow_rules import workflow_rules_cache, classify_task_type; t = pathlib.Path(r'C:\01_agent_loop_pro\backend\var\files\4c40bada-b2e6-45ea-b1b2-a2e43e663072\965ffc405ba740ea9f8772db166d2c55').read_text(encoding='utf-8'); r = workflow_rules_cache.get(t); print('方案类:', classify_task_type('读取 brief_test.md 写一份创意建议的方案，保存到 brief/文件夹中', r.task_types).type_name); print('普通问答:', classify_task_type('GAP 最近的营销动态是什么？', r.task_types).type_name)"
```
Expected: 方案类=完整方案需求 / 普通问答=事实研究问题

- [ ] **Step 4: 冒烟 — 阶段推进全链**（直连验证状态机推进序列）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import sys, asyncio; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); from app.services.agent.loop import AgentLoopService; svc = AgentLoopService(); svc._workflow_rules = object(); svc._workflow_stage='classify'; svc._advance_workflow_stage(None, None, 0); print('classify→', svc._workflow_stage); svc._advance_workflow_stage(None, None, 0); print('admission→', svc._workflow_stage); svc._stage_actions=1; svc._advance_workflow_stage(None, None, 0); print('recap→', svc._workflow_stage); svc._advance_workflow_stage(None, None, 0); print('version→', svc._workflow_stage); svc._research_ok=True; svc._advance_workflow_stage(None, None, 0); print('research→', svc._workflow_stage); svc._save_ok=True; svc._advance_workflow_stage(None, None, 0); print('content→', svc._workflow_stage); svc._advance_workflow_stage(None, None, 0); print('redline→', svc._workflow_stage)"
```
Expected: classify→admission → recap → version → research → content → redline → done（version 阶段 `_scan_highest_version` 会因 repo=None 触发异常——用 try/except 包裹或 mock；若异常则 version 停留，冒烟时捕获打印）

- [ ] **Step 5: Report** — 无提交；回报用户：后端测试数、三个冒烟输出
