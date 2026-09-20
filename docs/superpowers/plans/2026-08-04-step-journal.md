# Step Journal — 本 run 步骤轨迹注入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the agent from repeatedly re-reading the same file by injecting a lightweight "steps taken in this run" journal into every planner call, so the model always knows it already read a file / ran a search / attempted a write.

**Architecture:** The main loop in `loop.py` already maintains `previous_observation` (single-step context, overwritten each step). We add a `step_journal: list[str]` alongside it, appended after every executed step with a one-line summary (`步骤N: read_file(brief_test.md) → 成功`). The journal (last 10 entries, truncated) is passed into `planner._build_messages` and rendered into the user prompt as a "本任务已执行步骤" block. A system-prompt line tells the model not to re-read already-read files. `_build_merged_messages` inherits it via its delegation to `_build_messages`.

**Tech Stack:** Python 3.11 / FastAPI / pytest.

## Global Constraints

- 不改变工具行为：read_file 本身不动，不做文件内容缓存（YAGNI）
- 不新增 DB 表/列/迁移；不新增网络调用
- 主循环每步工具执行后追加 journal 条目；journal 最多保留最近 10 条；渲染时每条截断 200 字符
- 现有测试必须全部通过（后端 737 passed 基线）
- commit 从仓库根 C:\01_agent_loop_pro 执行，仓库根相对路径
- 共享 Postgres 测试 DB：同一时刻只允许一个 pytest 进程（先 `Get-Process python -ErrorAction SilentlyContinue`）

---

### Task 1: planner._build_messages 渲染 step journal

**Files:**
- Modify: `backend/app/services/agent/planner.py`
- Test: `backend/tests/test_agent_tools.py`

**Interfaces:**
- Consumes: 现有 `_build_messages(goal, step_index, previous_observation, session_history=None, web_enabled=True, final_step=False)`（planner.py:148-157 附近）
- Produces: 新参数 `step_journal: list[str] | None = None`；user_prompt 含"本任务已执行步骤"块；system_prompt 含"已读取过的文件不要重复读取"引导语

- [ ] **Step 1: Write the failing test**（追加到 `backend/tests/test_agent_tools.py`，先读该文件确认 import 与测试风格）

```python
def test_build_messages_renders_step_journal():
    messages = ResearchPlanner()._build_messages(
        "读取 brief_test.md 并写方案保存到 brief/",
        2,
        {"type": "read_file", "observation": "..."},
        session_history=None,
        web_enabled=True,
        final_step=False,
        step_journal=[
            "步骤1: read_file(brief_test.md) → 成功",
            "步骤2: web_search(GAP成毅营销) → 5条结果",
        ],
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "本任务已执行步骤" in prompt
    assert "步骤1: read_file(brief_test.md)" in prompt
    assert "步骤2: web_search(GAP成毅营销)" in prompt


def test_build_messages_step_journal_has_no_repeat_guidance():
    messages = ResearchPlanner()._build_messages(
        "简单问题", 0, None, web_enabled=True, step_journal=None
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "不要重复读取" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tools.py::test_build_messages_renders_step_journal tests/test_agent_tools.py::test_build_messages_step_journal_has_no_repeat_guidance -q
```
Expected: FAIL（TypeError: 多余参数 step_journal / prompt 无 journal 字样）

- [ ] **Step 3: Implement**

**3a.** `backend/app/services/agent/planner.py` `_build_messages` 签名（~154 行后）加参数：

```python
        web_enabled: bool = True,
        final_step: bool = False,
        step_journal: list[str] | None = None,
    ) -> list[dict[str, str]]:
```

**3b.** system_prompt（~195-201 行）追加引导语：

```python
        system_prompt = (
            "你是一个研究型 Agent 规划器。你必须只返回合法 JSON，且顶层只能包含 thought_summary 和 action 两个字段。\n"
            f"{action_policy}"
            f"{final_step_policy}"
            "所有 thought_summary 使用简体中文。不要输出 markdown 代码块或额外说明。"
            "已读取过的文件不要重复读取，直接基于已获得的内容继续；如需复核某段内容可用 edit_file 目标定位，不要整体重读。"
        )
```

**3c.** user_prompt（~209-218 行）在 `history_block` 之后插入 journal 块：

```python
        journal_block = "无"
        if step_journal:
            journal_block = "\n".join(f"- {entry[:200]}" for entry in step_journal[-10:])

        user_prompt = (
            f"当前目标：{goal}\n"
            f"网络权限：{'开启' if web_enabled else '关闭'}\n"
            f"当前步数：{step_index}\n"
            f"是否最后一步：{'是，必须选择 finish' if final_step else '否'}\n"
            f"上一轮观察结果：{observation_text}\n"
            f"本任务已执行的步骤：\n{journal_block}\n"
            f"会话历史：\n{history_block}\n"
            "你现在必须决定下一步唯一动作。"
            ...
        )
```

注意：journal 渲染放 `history_block` 之前（先看到本 run 轨迹再看到跨 run 历史）。

- [ ] **Step 4: Run test to verify it passes**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_tools.py -q
```
Expected: PASS（含 2 新测试）

- [ ] **Step 5: Commit**（从仓库根）

```bash
git add backend/app/services/agent/planner.py backend/tests/test_agent_tools.py
git commit -m "feat: render in-run step journal in planner prompt"
```

---

### Task 2: 主循环维护 step_journal 并传入

**Files:**
- Modify: `backend/app/services/agent/loop.py`
- Test: `backend/tests/test_agent_loop.py`

**Interfaces:**
- Consumes: Task 1 的 `_build_messages(..., step_journal=...)` 新参数
- Produces: 主循环 `_do_process_attempt` 内 `step_journal: list[str]` 变量（每步工具完成后追加）；两处 `_build_messages` 调用传 `step_journal=step_journal`

- [ ] **Step 1: Write the failing test**（追加到 `backend/tests/test_agent_loop.py`——先读该文件确认现有集成测试风格与 mock 方式）

```python
    async def test_main_loop_passes_step_journal_to_planner(self):
        # 构造: run goal="读取 brief 并写方案保存到 brief/"
        # 第一步: read_file 成功（observation 无 error）
        # 第二步: planner._build_messages 收到 step_journal 含 "步骤1"
        ...
```

**关键**：先读 `test_agent_loop.py` 中已有的主循环测试（搜索 `_do_process_attempt` 或 `attempt` fixture），复用其 mock 模式（fake repo / monkeypatch planner._build_messages 捕获参数）。若主循环集成测试构造复杂，改为单元级验证——直接调用 `_build_merged_messages`（loop.py:739 附近）传 step_journal 断言 prompt 含 journal：

```python
    def test_merged_messages_inherit_step_journal(self):
        service = AgentLoopService()
        messages = service._build_merged_messages(
            goal="写方案保存到 brief/",
            step_index=1,
            previous_observation={"observation": "ok"},
            session_history=None,
            web_enabled=True,
            final_step=False,
            step_journal=["步骤1: read_file(brief_test.md) → 成功"],
        )
        prompt = "\n".join(message["content"] for message in messages)
        assert "本任务已执行步骤" in prompt
        assert "read_file(brief_test.md)" in prompt
```

注意 `_build_merged_messages` 需要加 `step_journal` 参数并透传给 `planner._build_messages`（Task 2 范围）——测试驱动先 RED。

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/test_agent_loop.py -q
```
Expected: 新测试 FAIL（`_build_merged_messages` 无 step_journal 参数 / prompt 无 journal）

- [ ] **Step 3: Implement**

**3a.** `_build_merged_messages`（loop.py:739 附近）签名加 `step_journal: list[str] | None = None`，内部委托调用加 `step_journal=step_journal`。

**3b.** 主循环 `_do_process_attempt`（loop.py:1330 附近）：

- 初始化处（`previous_observation = None` 旁）加：

```python
        step_journal: list[str] = []
```

- 两处 planner 调用（loop.py:1379-1386 `planner_messages` 与 1390-1397 `merged_messages`）各加 `step_journal=step_journal,`

- 每步工具执行完成后（loop.py:1520 附近 `previous_observation = observation; step_index += 1` 之前）追加 journal 条目：

```python
            journal_entry = (
                f"步骤{step_index + 1}: {action['type']}"
                f"({self._journal_target(action)}) → "
                f"{'成功' if isinstance(observation, dict) and not observation.get('error') else '失败'}"
            )
            step_journal.append(journal_entry)
            step_journal = step_journal[-10:]
```

- 新增辅助方法 `_journal_target`（放在 `_sanitize_action` 附近）：

```python
    @staticmethod
    def _journal_target(action: dict[str, Any]) -> str:
        payload = (action.get("input") or {}).get("content")
        if action["type"] == "read_file":
            return str((action.get("input") or {}).get("path") or (action.get("input") or {}).get("file_id") or "?")
        if action["type"] in {"write_file", "edit_file"}:
            return str((action.get("input") or {}).get("path") or "?")
        if action["type"] == "web_search":
            return str((action.get("input") or {}).get("query") or "?")
        if action["type"] == "list_files":
            return str((action.get("input") or {}).get("keyword") or "全部")
        if action["type"] in {"feishu_read_doc", "feishu_edit_doc", "feishu_share_doc"}:
            return str((action.get("input") or {}).get("doc_token") or "?")
        if action["type"] == "feishu_create_doc":
            return str((action.get("input") or {}).get("title") or "?")
        return payload if isinstance(payload, str) else str((action.get("input") or {}))[:50]
```

注意：`action` 是脱敏前的原始 plan dict（`action = plan["action"]`，loop.py:1433），input 字段完整可用。finish 动作不追加 journal（主循环 1481 行 finish 分支直接 return，不会走到 journal 追加点——确认追加点位于 finish 分支之后）。

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
git commit -m "feat: maintain in-run step journal and feed planner each step"
```

---

### Task 3: 集成验证

**Files:**
- Verify only（不改代码）

- [ ] **Step 1: 后端全量**（仅一个 pytest 进程；先 `Get-Process python -ErrorAction SilentlyContinue`）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -m pytest tests/ -q
```
Expected: 737+ passed（零失败）

- [ ] **Step 2: 冒烟 — 构造一次带 journal 的 planner 调用**（直连验证渲染）

```
cd C:\01_agent_loop_pro\backend
python -X utf8 -c "import sys; sys.path.insert(0, r'C:\01_agent_loop_pro\backend'); from app.services.agent.planner import ResearchPlanner; m = ResearchPlanner()._build_messages('写方案保存到brief/', 2, {'a': 1}, step_journal=['步骤1: read_file(brief_test.md) → 成功', '步骤2: web_search(x) → 5条']); print('\n'.join(x['content'] for x in m)[-400:])"
```
Expected: 输出末尾含 "本任务已执行的步骤" 与两条 journal 条目

- [ ] **Step 3: Report** — 无提交；回报用户：后端测试数 + 冒烟输出确认
