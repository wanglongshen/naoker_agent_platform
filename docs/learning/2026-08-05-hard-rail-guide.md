# 硬轨（Hard Rail）学习指南

> Agent Loop 双轨机制中的**代码强制层**：不是靠 LLM"自觉"，而是由代码状态机 + 拦截点 + 重试环保证 Agent 行为符合工作流。
> 配套图：`workflow-dual-track.html`（双轨总览）。本文以 2026-08-05 实际代码为准。

---

## 1. 一分钟理解

**软轨** = 把蓝图全文注入 system prompt，让模型"自觉"遵守 → 模型可能忘、可能跳步。
**硬轨** = 代码强制：一个 8 阶段的显式状态机，每轮 LLM 决策都要过闸门，不合格 → 重试，3 次耗尽 → `run_failed`。**模型可以不自觉，但代码不允许它走错。**

```
用户提问 ──plan_class──> 方案类？──是──> 进入硬轨状态机
                          │
                          否──> fast path 直接回答（无状态机、无闸门）
```

---

## 2. 硬轨全景流程图

```
┌───────────────────────────────────────────────────────────────────────────┐
│                        硬 轨 · 代 码 强 制 层                               │
│                                                                           │
│  用户提问（goal）                                                          │
│      │                                                                    │
│      ▼                                                                    │
│  plan_class ?（LLM 分类：方案类集合？）                                     │
│      │ 否                                                                │
│      ├───────────────► fast path · 直接回答（零状态机·零闸门）              │
│      │ 是                                                                │
│      ▼                                                                    │
│  ┌──────────────────────────────────────────────────────────────────┐     │
│  │              状 态 机（8 阶段，st.stage 驱动）                      │     │
│  │                                                                    │     │
│  │  ① classify ──► ② admission ──► ③ recap ──► ④ version            │     │
│  │                  │（"先追问"→ awaiting_question）                   │     │
│  │                                     │                               │     │
│  │                                     ▼                               │     │
│  │                  ⑤ research ──► ⑥ content ──► ⑦ redline ──► ⑧ done │     │
│  │                                                                    │     │
│  └───────────────▲──────────────────────────────────┬─────────────────┘     │
│                  │ 工具执行结果回写                    │                    │
│                  │ research_ok/save_ok/材料盘点       │ 每轮 LLM 决策       │
│                  │                                  ▼                    │
│                  │                    ┌──────────────────────────┐      │
│                  │                    │ 闸门（_enforce_stage_gate）│      │
│                  │                    │ · 阶段动作白名单            │      │
│                  │                    │ · 研究前置 / 版本 / 结构     │      │
│                  │                    └────────────┬─────────────┘      │
│                  │                                 │ 不合格               │
│                  │ 合格（动作执行）                  ▼                    │
│                  │                    RetryablePlannerError              │
│                  │                                 │                    │
│                  │                    ┌────────────▼─────────────┐      │
│                  └────────────────────┤ 重试环（_schedule_retry）  │      │
│                                        │ 新 attempt · 指数退避      │      │
│                                        │ 保留阶段进度（>1 次不重置） │      │
│                                        └────────────┬─────────────┘      │
│                                                     │ 3 次耗尽            │
│                                                     ▼                    │
│                                        run_failed（不静默放行）            │
│                                                                           │
│  ⑧ done ──► 真实性校验 ──► run_succeeded（原子持久化·commit 后推送）        │
└───────────────────────────────────────────────────────────────────────────┘
```

**关键概念：代码阶段 vs 模型阶段**

| 类型 | 阶段 | 含义 |
|---|---|---|
| 代码阶段 | classify / admission / version / redline | 纯逻辑，`while True` 循环里自动折叠推进，不耗 LLM |
| 模型阶段 | recap / research / content | 必须等模型做动作（读文件/搜索/写文件）才推进 |
| 挂起态 | awaiting_question | admission 判定"先追问"，挂起等用户回答 |

代码在 `_advance_workflow`（loop.py:555-613）：代码阶段一口气跑完（`continue`），模型阶段条件不满足就 `return`，等下一轮。

---

## 3. 入口分流：plan_class

```python
# loop.py 主决策链（简化）
async def _run_plan_cycle(...):
    # ① 软轨：把蓝图全文 + 当前阶段 + 近期工具观察注入 prompt
    plan = await research_planner.generate(...)          # LLM 产出【决策】JSON

    # ② 校验链：正常化 → 结构校验（planner.py:240-299）
    normalized = research_planner._normalize_plan(parsed) # 把散落的字段整理进 action.input
    validated  = research_planner._validate_plan(normalized)  # Pydantic 逐动作校验参数模型

    # ③ 意图闸门：要求保存却选 finish → 拦截（loop.py:855-873）
    plan = self._enforce_save_intent(goal, plan, wrote_file, final_step)

    # ④ 阶段闸门：核心硬轨（loop.py:648-702）
    self._enforce_stage_gate(plan, run.id)
    # ⑤ 重试分派（loop.py:1980-2001）
    except RetryablePlannerError as exc:
        await self._schedule_retryable_failure(repo, ctx, exc)
        return   # 本轮结束，重试 attempt 稍后接管
```

**plan_class 判定**（fast path 与硬轨的分水岭）：
- LLM 一次调用同时产出 `plan_class` + `action`
- `plan_class` ∈ 方案类集合 → 进硬轨状态机
- 否则 → fast path：普通问答，直接回答，无状态机无闸门

---

## 4. 状态机 8 阶段详解

> 真实代码：loop.py:555-613。`st` = workflow state，持有 `stage / research_ok / save_ok / stage_actions / material_inventory_done / version_number / saved_files / required_source_paths` 等字段。

### 阶段 ① classify · 任务分类（代码阶段）

```python
if stage == "classify":
    task_type = classify_task_type(run.goal, st.rules.task_types)
    # 用规则表中的任务类型定义，对 goal 做关键词/语义匹配
    st.task_type = task_type.type_name      # 记录任务类型（如"方案文档"）
    st.stage = "admission"                   # 直接推进，不耗 LLM
    st.stages_done.append("classify")        # 审计轨迹
    continue                                 # while True：继续折叠下一个代码阶段
```

- **推进条件**：`classify_task_type` 完成即推进（纯代码）
- **允许动作**：`read_file / list_files / web_search`
- **注释**：这一步把"用户说了什么"翻译成"这是什么类型的任务"，后续所有规则都按任务类型生效

### 阶段 ② admission · 准入判断（代码阶段）

```python
if stage == "admission":
    missing_sources = self._missing_required_sources(st)
    # 蓝图"必读文件"清单 vs 已读文件，找出没读的
    rule = admission_judgment(run.goal, files_read_ok=not missing_sources, ...)
    st.admission = rule.branch              # "直接执行" / "先追问" / ...
    if rule.branch == "先追问":
        st.stage = "awaiting_question"      # 挂起态：等用户回答
        raise _QuestionHangSignal(self._build_questions(run.goal))  # 中断循环，把问题抛给用户
    st.stage = "recap"
    st.stages_done.append("admission")
    continue
```

- **推进条件**：`admission_judgment` 分支判定完成
- **挂起**：判定"先追问" → `awaiting_question` 态，最多 5 个问题，用户回答后仅能 finish（把回答带回）
- **注释**：**"named but unread"设计**——蓝图里点名要求读取但实际没读的文件，不在 admission 追问，而是交给 recap/read 闸门处理（文件存在就不用问用户要）

### 阶段 ③ recap · Brief 复述（模型阶段）

```python
if stage == "recap":
    if (not self._missing_required_sources(st)          # 必读文件都读了
        and st.material_inventory_done                  # 材料盘点（list_files）完成
        and (st.required_source_paths or st.stage_actions >= 1)):  # 有动作发生
        st.stage = "version"
        st.stages_done.append("recap")
        continue
    return  # 条件不满足：等模型下一轮行动（读文件/盘点）
```

- **推进条件**：无缺失必读源 + 材料盘点完成 + 至少 1 次工具动作
- **允许动作**：`read_file / list_files / web_search`（只读类）
- **注释**：这是"软轨"的复述要求（模型先复述 Brief），但**完成条件的判定是代码强制的**——模型口头上说"我已读完"不算数，必须真实发生过读取动作

### 阶段 ④ version · 版本判断（代码阶段）

```python
if stage == "version":
    if st.version_number is None:
        st.version_number = await self._scan_highest_version(repo, run)
        # 正则从 goal 提取目标文件夹："保存到 brief/" → folder="brief"
        # 列出文件夹内文件，扫 _V(\d+) 取最大编号 +1 → "V3"
    st.stage = "research"
    st.stages_done.append("version")
    continue
```

- **推进条件**：`_scan_highest_version` 完成（文件系统扫描，纯代码）
- **注释**：版本号是**由系统算出并交给模型的**——模型不用猜，闸门还会校验它用的版本号对不对（见拦截点 `version_mismatch`）

### 阶段 ⑤ research · 外部研究（模型阶段）

```python
if stage == "research":
    if st.research_ok:          # 至少 1 次成功的 web_search 结果已被验证
        st.stage = "content"
        st.stages_done.append("research")
        continue
    return                      # 没研究完：等模型搜索
```

- **推进条件**：`research_ok == True`（≥1 次成功 web_search）
- **允许动作**：`read_file / list_files / web_search`
- **注释**：研究阶段只准做只读动作——**不允许写文件**（白名单没有 write/edit），这是阶段闸门最直观的体现

### 阶段 ⑥ content · 内容产出（模型阶段）

```python
if stage == "content":
    if st.save_ok:              # write_file / edit_file 成功（工具观察无 error）
        st.stage = "redline"
        st.stages_done.append("content")
        continue
    return                      # 没写成功：等模型写
```

- **推进条件**：`save_ok == True`（write/edit 成功且验证通过）
- **允许动作**：`read_file / list_files / web_search / write_file / edit_file`（首次放开写）
- **注释**：走到 content = 研究已就绪（前置闸门保证），此时才允许动笔

### 阶段 ⑦ redline · 红线校验（代码阶段）

```python
if stage == "redline":
    st.stage = "done"
    st.stages_done.append("redline")
    continue
```

- **推进条件**：进入即通过（占位词/洁净度等校验在写文件闸门处已执行）
- **允许动作**：`write_file / edit_file / finish`（可以继续修，也可以收尾）

### 阶段 ⑧ done · 完成（代码阶段）

```python
if stage == "done":
    # 允许动作只剩 finish
    # 收尾时还要过 finish 专属闸门 + 真实性校验（见下）
    return
```

- **允许动作**：仅 `finish`
- **终态链**：finish → `_enforce_answer_truthfulness` → `_persist_successful_completion`（answer_completed + step_completed + run_succeeded + result 同一事务）→ commit → SSE 推送

---

## 5. 拦截点（闸门）全解

> 真实代码：loop.py:636-733（`_STAGE_ALLOWED_ACTIONS` + `_enforce_stage_gate` + `_enforce_answer_truthfulness`）。全部抛 `RetryablePlannerError` → 走重试环，**不判死**。

### 5.1 阶段动作白名单（stage_gate）

```python
_STAGE_ALLOWED_ACTIONS = {
    "classify":   {"read_file", "list_files", "web_search"},
    "admission":  {"read_file", "list_files", "web_search"},
    "recap":      {"read_file", "list_files", "web_search"},
    "version":    {"read_file", "list_files", "web_search"},
    "research":   {"read_file", "list_files", "web_search"},
    "content":    {"read_file", "list_files", "web_search", "write_file", "edit_file"},
    "redline":    {"write_file", "edit_file", "finish"},
    "done":       {"finish"},
    "awaiting_question": {"finish"},
}

def _enforce_stage_gate(plan, run_id):
    st = self._wf(run_id)
    if st.rules is None:
        return                      # 非方案类（无蓝图规则）不设闸门
    action_type = plan["action"]["type"]
    allowed = _STAGE_ALLOWED_ACTIONS.get(st.stage)
    if action_type not in allowed:
        raise RetryablePlannerError(
            f"stage_gate: 当前阶段 {st.stage} 不允许动作 {action_type}，"
            f"允许：{'/'.join(sorted(allowed))}")
```

**设计意图**：阶段决定了"现在可以做什么"。模型在 research 阶段想提前写文件 → 拦截，必须先把研究做完。这是防止"跳步"的最终防线。

### 5.2 写入前置三重闸（write/edit 触发）

```python
if action_type in ("write_file", "edit_file"):
    # ① 材料盘点闸：写入前必须 list_files 盘点过
    if not st.material_inventory_done:
        raise RetryablePlannerError(
            "material_inventory_required: 写入前必须先调用 list_files 盘点"
            " Brief、QA、历史方案和相关附件")

    # ② 必读源闸：蓝图点名的必读文件必须真实读过
    missing = self._missing_required_sources(st)
    if missing:
        raise RetryablePlannerError(
            "required_source_not_read: 写入前必须真实读取用户指定文件：" + "、".join(missing))

    # ③ 研究闸：必须已完成 ≥1 次外部搜索
    if not st.research_ok:
        raise RetryablePlannerError(
            "research_required: 保存方案前必须完成至少一次外部搜索，"
            "请先调用 web_search 获取研究资料后再写入文件")
```

**注释**：三个闸门把"读够 → 研究过 → 才准写"变成不可绕过的物理约束。注意措辞全部是**指导性的**（"请先调用 web_search"）——重试时模型能根据消息自我纠正。

### 5.3 版本闸（version_required / version_mismatch）

```python
path = plan["action"]["input"].get("path") or ""
rule = st.version_rule or re.compile(r"_V\d+")
if rule.search(path) is None:
    raise RetryablePlannerError(
        "version_required: 文件名必须包含版本号，当前目录下一版本为 {st.version_number or 'V1'}")
if st.version_number and version_match.group(0).lstrip("_") != st.version_number:
    raise RetryablePlannerError(
        "version_mismatch: 当前目录下一版本应为 {st.version_number}，实际文件名为 {path}")
```

**注释**：不只是"必须有版本号"，还要求**版本号与系统扫描出的下一版本一致**——防止模型乱写 V9 覆盖别人。

### 5.4 finish 专属闸（收尾时）

```python
if action_type == "finish":
    # 必读源未读完 → 拦截
    if st.required_source_paths and missing_sources:
        raise RetryablePlannerError("required_source_not_read: 结束前必须真实读取用户指定文件…")
    # 有保存意图但没盘点 → 拦截
    if st.save_receipts and not st.material_inventory_done:
        raise RetryablePlannerError("material_inventory_required: 尚未完成材料盘点")
    # 保存的文件没有通过回读 SHA-256 校验 → 拦截
    if st.save_receipts and not st.verified_save_receipts:
        raise RetryablePlannerError("save_not_verified: 保存文件尚未通过回读 SHA-256 校验")
```

### 5.5 保存意图闸（_enforce_save_intent，loop.py:855-873）

```python
def _enforce_save_intent(goal, plan, wrote_file, final_step):
    action = plan.get("action") or {}
    if (not wrote_file                        # 本 run 还没成功写过文件
        and action.get("type") == "finish"    # 模型却想直接结束
        and self._has_save_intent(goal)):     # 而用户目标是"保存/写入…"
        raise RetryablePlannerError(
            "save_intent_unfulfilled" if final_step
            else "save_intent_requires_write_tool")
    return plan
```

**注释**：用户说"写一份方案保存到 brief/"，模型却想用 finish 直接交回答 → 拦截：**要求保存就必须真的调 write/edit**。`wrote_file` 只在 write/edit 成功（observation 无 error）时置位。

### 5.6 回答真实性闸（_enforce_answer_truthfulness，loop.py:709-733）

```python
_FINAL_ANSWER_FILE_RE = re.compile(
    r"(?:保存|写入|生成|导出|落盘|另存|输出|存放)\s*(?:到|至|为|在|了)?\s*[`'\"]?[\w\u4e00-\u9fff\-/]+\.md")

def _enforce_answer_truthfulness(answer, run_id):
    if st.rules is None:
        return                              # 非方案类不校验
    claimed = _FINAL_ANSWER_FILE_RE.findall(answer)      # 提取"声称保存了 X.md"
    fake = [name for name in claimed if name not in st.saved_files]
    if fake:
        raise RetryablePlannerError(
            "answer_truthfulness: 最终回答声称保存了 {fake}，但实际保存的是 {saved_files}…")
```

**注释**：
- 只匹配"保存/写入/生成…"**语境**后的文件名——只提到读取/引用不算
- 防止模型**幻觉式收尾**："已保存到 xxx.md"但实际没写 → 拦截，强制如实描述

### 5.7 结构校验链（planner.py:240-299，属于软轨前置，但失败即重试）

```python
def _normalize_plan(raw_plan):   # 字段整理：answer/method/url 散落在外 → 归入 action.input
    ...

def _validate_plan(raw_plan):
    parsed = PlannerResponse.model_validate(raw_plan)     # 决策 JSON 整体校验
    input_models = { "web_search": WebSearchInput, "write_file": WriteFileInput, ... }
    # 每个动作类型对应一个 Pydantic 参数模型，逐动作校验 input 字段
    return parsed
```

**注释**：LLM 输出的 JSON 是**不可信的**。`_validate_plan` 用 Pydantic 把每个动作的参数模型验一遍（缺字段/类型错 → ValueError → 重试），再加上 write_file 的**结构完整性校验**（`plan_subitems_incomplete`：模块/子项缺失 → 返回骨架让模型补全，不直接保存）。完整结构校验在 `tool_executor`（write_file 工具内，基于蒸馏摘要的模块清单）。

---

## 6. 重试环与保进度（最精妙的设计）

> 真实代码：loop.py:879-904（`_schedule_retryable_failure`）、loop.py:203-205（`_maybe_reset_workflow_state`）。

```python
async def _schedule_retryable_failure(repo, ctx, exc) -> bool:
    # 只处理"可重试"异常；其他异常继续上抛（如模型流式 IO 错误外的致命错误）
    if not isinstance(exc, (RetryablePlannerError, RetryableStreamingError,
                            RetryableToolError, asyncio.TimeoutError, httpx.HTTPError)):
        raise exc
    if ctx.attempt.attempt_number >= settings.max_retry_attempts:   # 默认 3 次
        return False        # 耗尽 → 调用方标记 run_failed

    # 当前 attempt 标记 failed（记录失败码，截断 64 字符）
    await repo.transition_attempt_status(ctx.attempt, {"running"}, "failed",
                                         failure_code=str(exc)[:64], finished_at=now)
    # 排程新 attempt（保留 run_id 上下文）
    retry_attempt = await repo.schedule_retry_attempt(ctx.run, ctx.attempt, str(exc))
    return True

# 关键：新 attempt 启动时——
def _maybe_reset_workflow_state(run_id, attempt_number):
    if attempt_number <= 1:
        # 首次 attempt 才从头初始化状态机
        ...
        return
    # attempt > 1：不重置！保留 stage / research_ok / save_ok / version_number …
    # 模型从"被拦截的地方"继续推进，而不是从头再来
```

**重试语义表**

| 项 | 行为 |
|---|---|
| 触发 | 任何 Retryable* 错误 / LLM 超时 / HTTP 错误 |
| 退避 | `base * 2^(attempt-1)`，封顶 `retry_backoff_max_seconds`（指数退避） |
| 上限 | `max_retry_attempts`（默认 3）耗尽 → `run_failed` |
| 进度 | attempt > 1 **保留状态机进度**（修复前：模型被"从头开始"卡死） |
| 消息 | 拦截消息原文作为失败码/提示传给新 attempt → 模型据此改正 |

**为什么保进度重要**：早期版本 attempt>1 会重置状态机，模型每次重试都回到 classify——"研究已完成"等成果全部丢失，模型永远走不到 content。修复后模型收到的是"你在 content 阶段、版本应为 V3、文件名没版本号"——一次改正即可推进。

---

## 7. 终态：原子持久化

```python
# loop.py:1662 / _persist_successful_completion
# 成功路径 = 一个事务写四样东西：
#   1. answer_completed 事件（最终回答）
#   2. step_completed 事件（步骤完成）
#   3. attempt → succeeded
#   4. run → succeeded + run.result（保存结果清单）
# 全部 commit 成功后，才把事件推送到 EventBus → SSE
```

**注释**："先落库，再推送"——内存里有的，DB 里一定有（`publish_after_commit` 约束）。失败路径同样严肃：重试耗尽 → `run_failed`，**绝不静默放行**（哪怕回答看起来不错，硬轨要求没达标就是失败）。

---

## 8. 源码导航表（按需精读）

| 内容 | 位置 |
|---|---|
| 阶段推进循环（8 阶段 + awaiting_question） | `loop.py:555-613` |
| 版本扫描 `_scan_highest_version` | `loop.py:615-634` |
| 阶段白名单 `_STAGE_ALLOWED_ACTIONS` | `loop.py:636-646` |
| 阶段闸门 `_enforce_stage_gate`（写/结束前置） | `loop.py:648-702` |
| 回答真实性 `_enforce_answer_truthfulness` | `loop.py:709-733` |
| 保存意图闸 `_enforce_save_intent` | `loop.py:855-873` |
| 重试调度 `_schedule_retryable_failure` | `loop.py:879-904` |
| 保进度 `_maybe_reset_workflow_state` | `loop.py:203-205` |
| 主决策链（注入→校验→闸门→重试） | `loop.py:1973-2041` |
| 决策 JSON 正常化 + 参数校验 | `planner.py:240-299` |
| 工具侧结构校验（write_file 骨架/模块清单） | `tool_executor.py`（`plan_structure_incomplete` 等） |

## 9. 一句话总结

> **硬轨 = 显式状态机（8 阶段，代码折叠推进） + 闸门（6 类拦截，全部可重试） + 重试环（保进度、指数退避、3 次耗尽判死） + 原子终态（先落库后推送，不静默放行）。**
> 它保证的不是"模型聪明"，而是"模型再笨也不会走错流程"。
