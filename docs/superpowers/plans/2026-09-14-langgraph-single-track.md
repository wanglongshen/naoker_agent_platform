# LangGraph 单轨化（切轨 + 差分校准）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 LangGraph 成为系统唯一活跃执行轨道（`langgraph_enabled` 默认 True），并用「录制回放逐字节差分」证明与旧 while 轨等价；旧轨代码保留、一行环境变量可回退。

**Architecture:** 差分器 = LLM 录制/回放包装器（env 门控，注入 `DeepSeekClient`）+ 事件归一化 + 双跑驱动（真实 DB、`process_attempt` 入口、`agent_run_events` 全量采集）+ `diff_event_streams` 比对。图轨是唯一被修改方；旧轨只作为基准，一行不改。

**Tech Stack:** Python 3.13（conda env `01-rbac`）、pytest + anyio、SQLAlchemy async、langgraph 0.3.34、PostgreSQL（`DATABASE_URL`）。

## Global Constraints

- **外部行为逐字节保真**：SSE 开关时序、事件类型/顺序/offset、usage 计费数值、各门禁触发与提示、最终 answer 文案（含 fallback）——差分必须 0 差异；差异只允许修图轨，**旧轨一行不改**。
- **归一化必须显式**：任何易变字段（run_id/attempt_id/事件主键/时间戳/内嵌 uuid）的归一化规则逐条写在报告里，不允许用归一化掩盖语义差异。
- **回放必须逐 chunk**：`stream_text` 的 chunk 分段与 `usage_sink` 回调都要回放（计费数值依赖 usage）。
- **旧轨保留**：不删除 `_do_process_attempt` 及其实现；只改默认值与图轨。
- **测试命令**：`cd backend` 后用 `X:\python\anaconda\envs\01-rbac\python.exe -m pytest <file> -q`。
- **提交纪律**：`git add` 只精确加本任务文件；提交前 `git diff --cached --name-only` 核对；避开 `var/`、`.cortexkit/`、`_dsh-*` 等他人文件。
- 新模块不得引入循环 import：`llm_recorder.py` / `event_normalize.py` 只依赖标准库与 `app.core.config`。

---

### Task 1: LLM 录制/回放包装器 + `DeepSeekClient` 接线

**Files:**
- Create: `backend/app/services/agent/llm_recorder.py`
- Modify: `backend/app/services/agent/llm.py`（`__init__`、`create_plan`、`stream_text` 三处）
- Test: `backend/tests/test_llm_recorder.py`

**Interfaces:**
- Produces:
  - `recorder_from_env() -> LlmRecorder | None`（读 `LANGGRAPH_DIFF_RECORD` / `LANGGRAPH_DIFF_REPLAY`，都未设 → None）
  - `LlmRecorder.record_plan(messages: list[dict], response: dict) -> None`
  - `LlmRecorder.record_stream(messages: list[dict], chunks: list[str], usages: list[dict]) -> None`
  - `LlmRecorder.save() -> None`（原子写 JSON）
  - `LlmRecorder.replay_plan(messages: list[dict]) -> dict`
  - `LlmRecorder.replay_stream(messages: list[dict]) -> AsyncIterator[str]`（内部按序触发 usage 回调，见下）
  - `LlmRecorder.bind_usage_sink(sink: Callable[[dict], None] | None) -> None`（回放 stream 前由 client 注入）
  - fixture JSON 结构：`{"scenario": str, "calls": [{"method": "create_plan"|"stream_text", "messages": [...], "response": {...} | null, "chunks": [...] | null, "usages": [...]}]}`
- Consumes: 无（只依赖标准库）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_llm_recorder.py
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_recorder_from_env_returns_none_without_env(monkeypatch):
    from app.services.agent.llm_recorder import recorder_from_env

    monkeypatch.delenv("LANGGRAPH_DIFF_RECORD", raising=False)
    monkeypatch.delenv("LANGGRAPH_DIFF_REPLAY", raising=False)
    assert recorder_from_env() is None


def test_record_then_replay_roundtrip(tmp_path: Path, monkeypatch):
    from app.services.agent.llm_recorder import LlmRecorder

    path = tmp_path / "s1.json"
    rec = LlmRecorder(mode="record", path=path, scenario="s1")
    rec.record_plan([{"role": "user", "content": "hi"}], {"thought_summary": "t", "action": {"type": "finish", "input": {"answer": "a"}}})
    rec.record_stream([{"role": "user", "content": "hi"}], ["你", "好"], [{"total_tokens": 7}])
    rec.save()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["scenario"] == "s1"
    assert [c["method"] for c in data["calls"]] == ["create_plan", "stream_text"]

    rep = LlmRecorder(mode="replay", path=path, scenario="s1")
    assert rep.replay_plan([{"role": "user", "content": "hi"}])["action"]["type"] == "finish"

    usages: list[dict] = []
    rep.bind_usage_sink(usages.append)

    async def _collect():
        return [c async for c in rep.replay_stream([{"role": "user", "content": "hi"}])]

    import asyncio

    assert asyncio.run(_collect()) == ["你", "好"]
    assert usages == [{"total_tokens": 7}]


def test_replay_exhaustion_raises(tmp_path: Path):
    from app.services.agent.llm_recorder import LlmRecorder, ReplayExhaustedError

    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"scenario": "x", "calls": []}), encoding="utf-8")
    rep = LlmRecorder(mode="replay", path=path, scenario="x")
    with pytest.raises(ReplayExhaustedError):
        rep.replay_plan([{"role": "user", "content": "hi"}])
```

- [ ] **Step 2: 确认失败**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_llm_recorder.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `llm_recorder.py`**

```python
# backend/app/services/agent/llm_recorder.py
"""LLM 录制/回放（LangGraph 差分校准用，env 门控，生产默认不生效）。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable


class ReplayExhaustedError(RuntimeError):
    pass


@dataclass
class LlmRecorder:
    mode: str  # "record" | "replay"
    path: Path
    scenario: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    _cursor: int = 0
    _usage_sink: Callable[[dict], None] | None = None

    def __post_init__(self) -> None:
        if self.mode == "replay":
            self.calls = json.loads(Path(self.path).read_text(encoding="utf-8"))["calls"]

    # ---- record ----
    def record_plan(self, messages: list[dict], response: dict) -> None:
        self.calls.append({"method": "create_plan", "messages": messages,
                           "response": response, "chunks": None, "usages": []})

    def record_stream(self, messages: list[dict], chunks: list[str], usages: list[dict]) -> None:
        self.calls.append({"method": "stream_text", "messages": messages,
                           "response": None, "chunks": chunks, "usages": usages})

    def save(self) -> None:
        payload = {"scenario": self.scenario, "calls": self.calls}
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(self.path).with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ---- replay ----
    def _next(self, method: str) -> dict[str, Any]:
        if self._cursor >= len(self.calls):
            raise ReplayExhaustedError(f"no recorded call at cursor {self._cursor} for {method}")
        call = self.calls[self._cursor]
        if call["method"] != method:
            raise ReplayExhaustedError(
                f"recorded method mismatch at {self._cursor}: expected {call['method']}, got {method}")
        self._cursor += 1
        return call

    def bind_usage_sink(self, sink: Callable[[dict], None] | None) -> None:
        self._usage_sink = sink

    def replay_plan(self, messages: list[dict]) -> dict:
        return self._next("create_plan")["response"]

    async def replay_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        call = self._next("stream_text")
        for chunk in call["chunks"] or []:
            yield chunk
        for usage in call["usages"] or []:
            if self._usage_sink is not None:
                self._usage_sink(usage)


def recorder_from_env() -> LlmRecorder | None:
    record_path = os.environ.get("LANGGRAPH_DIFF_RECORD")
    replay_path = os.environ.get("LANGGRAPH_DIFF_REPLAY")
    if record_path:
        return LlmRecorder(mode="record", path=Path(record_path),
                           scenario=Path(record_path).stem)
    if replay_path:
        return LlmRecorder(mode="replay", path=Path(replay_path),
                           scenario=Path(replay_path).stem)
    return None
```

- [ ] **Step 4: 跑测试至绿**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_llm_recorder.py -q` → PASS

- [ ] **Step 5: 接线 `llm.py`（录制/回放分支）**

`__init__` 增加：
```python
        from app.services.agent.llm_recorder import recorder_from_env
        self._recorder = recorder_from_env()
```
`create_plan` 开头（在 api_key 检查之前）增加：
```python
        if self._recorder is not None and self._recorder.mode == "replay":
            return self._recorder.replay_plan(messages)
```
`create_plan` 返回前（真实调用成功后）增加：
```python
        if self._recorder is not None and self._recorder.mode == "record":
            self._recorder.record_plan(messages, parsed)
            self._recorder.save()
```
（`parsed` 用实现里的返回变量名，按实际代码调整。）

`stream_text` 开头增加：
```python
        if self._recorder is not None and self._recorder.mode == "replay":
            self._recorder.bind_usage_sink(usage_sink)
            async for chunk in self._recorder.replay_stream(messages):
                yield chunk
            return
```
真实流式路径：把 yield 出去的 chunk 收集到 `recorded_chunks`，把 `usage_sink` 调用包一层同时记入 `recorded_usages`；在 `async with` 结束（正常完成）后：
```python
            if self._recorder is not None and self._recorder.mode == "record":
                self._recorder.record_stream(messages, recorded_chunks, recorded_usages)
                self._recorder.save()
```
（注意：异常路径不落盘，保持"只录成功调用"。）

- [ ] **Step 6: 回归 llm 既有测试 + 提交**

Run: `X:\python\anaconda\envs\01-rbac\python.exe -m pytest tests/test_agent_loop.py tests/test_llm_recorder.py -q` → 全绿

```bash
git add backend/app/services/agent/llm_recorder.py backend/app/services/agent/llm.py backend/tests/test_llm_recorder.py
git commit -m "feat(langgraph-diff): llm recorder/replayer with env gating"
```

---

### Task 2: 事件归一化 + 差分封装

**Files:**
- Create: `backend/app/services/agent/event_normalize.py`
- Test: `backend/tests/test_event_normalize.py`

**Interfaces:**
- Produces: `normalize_events(events: list[dict]) -> list[dict]`；`NORMALIZATION_RULES: list[str]`（写进报告用）；`diff_normalized(old, new) -> list[str]`（归一化后调 `langgraph_runner.diff_event_streams`）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_event_normalize.py
from __future__ import annotations


def test_normalize_replaces_volatile_fields():
    from app.services.agent.event_normalize import normalize_events

    events = [
        {"id": "11111111-1111-1111-1111-111111111111", "event_type": "step_started",
         "created_at": "2026-09-14T10:00:00.123456+00:00",
         "payload": {"stream_id": "error-22222222-2222-2222-2222-222222222222", "step_index": 0}},
        {"id": "33333333-3333-3333-3333-333333333333", "event_type": "answer_delta",
         "created_at": "2026-09-14T10:00:01.000000+00:00",
         "payload": {"delta": "文本", "offset": 0, "run_id": "44444444-4444-4444-4444-444444444444"}},
    ]
    out = normalize_events(events)
    assert out[0]["id"] == "<id>"
    assert out[0]["created_at"] == "<ts>"
    assert out[0]["payload"]["stream_id"] == "error-<uuid>"
    assert out[1]["payload"]["delta"] == "文本"
    assert out[1]["payload"]["run_id"] == "<uuid>"


def test_normalize_keeps_semantics_and_diff_empty():
    from app.services.agent.event_normalize import diff_normalized, normalize_events

    a = [{"event_type": "x", "payload": {"n": 1}}]
    b = [{"event_type": "x", "payload": {"n": 1}}]
    assert diff_normalized(normalize_events(a), normalize_events(b)) == []
    c = [{"event_type": "x", "payload": {"n": 2}}]
    assert diff_normalized(normalize_events(a), normalize_events(c)) != []
```

- [ ] **Step 2: 确认失败** → `-m pytest tests/test_event_normalize.py -q` FAIL

- [ ] **Step 3: 实现**

```python
# backend/app/services/agent/event_normalize.py
"""差分前的事件归一化：只抹平易变标识/时间戳，不掩盖语义差异。"""
from __future__ import annotations

import re
from typing import Any

from app.services.agent.langgraph_runner import diff_event_streams

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)?")

NORMALIZATION_RULES = [
    "事件主键 id → <id>",
    "键名 in {created_at, updated_at, started_at, finished_at, completed_at} 的字符串值 → <ts>",
    "任意字符串值中的 UUID 子串 → <uuid>（保留前后缀，如 error-<uuid>）",
    "任意字符串值中的 ISO 时间戳子串 → <ts>",
]

_TS_KEYS = {"created_at", "updated_at", "started_at", "finished_at", "completed_at"}


def _norm_value(key: str | None, value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _norm_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm_value(None, v) for v in value]
    if isinstance(value, str):
        if key in _TS_KEYS and TS_RE.fullmatch(value):
            return "<ts>"
        value = UUID_RE.sub("<uuid>", value)
        value = TS_RE.sub("<ts>", value)
        return value
    return value


def normalize_events(events: list[dict]) -> list[dict]:
    out: list[dict] = []
    for event in events:
        item = dict(event)
        if "id" in item:
            item["id"] = "<id>"
        item = _norm_value(None, item)
        out.append(item)
    return out


def diff_normalized(old: list[dict], new: list[dict]) -> list[str]:
    return diff_event_streams(normalize_events(old), normalize_events(new))
```

- [ ] **Step 4: 跑绿 + 提交**

```bash
git add backend/app/services/agent/event_normalize.py backend/tests/test_event_normalize.py
git commit -m "feat(langgraph-diff): event normalization + diff wrapper"
```

---

### Task 3: 差分驱动脚本（场景定义 + 双跑 + 报告）

**Files:**
- Modify: `backend/scripts/langgraph_differential.py`（从占位变实现）
- Test: `backend/tests/test_langgraph_differential.py`

**Interfaces:**
- Consumes: Task 1 `LlmRecorder`/`recorder_from_env`；Task 2 `normalize_events`/`diff_normalized`
- Produces:
  - `SCENARIOS: list[dict]`（`{"id": 1..10, "name": str, "goal": str, "settings": {key: value}, "attachments": list}`）
  - `async def run_scenario(scenario: dict, *, graph: bool, recorder: LlmRecorder | None) -> list[dict]`（真实 test DB：建用户/会话/run/attempt → `claim_next_attempt` → `service.process_attempt` → `list_events` 全量返回）
  - CLI：`--record <id>|--all`、`--diff <id>|--all`、`--report <path>`（默认 `docs/langgraph-eval/report.md`）

- [ ] **Step 1: 写失败测试（合成场景，不依赖真实 LLM/DB 行为差异）**

```python
# backend/tests/test_langgraph_differential.py
from __future__ import annotations

import pytest


def test_scenarios_cover_ten_matrix_entries():
    from scripts.langgraph_differential import SCENARIOS

    assert len(SCENARIOS) == 10
    assert {s["id"] for s in SCENARIOS} == set(range(1, 11))
    assert all(s["goal"] for s in SCENARIOS)


@pytest.mark.anyio
async def test_run_scenario_captures_events_for_both_tracks(monkeypatch):
    """用脚本化 FakeClient 跑一个 finish-only 场景，双轨事件流应都非空。"""
    from scripts import langgraph_differential as mod

    events_old = await mod.run_scenario(SCENARIOS_FIXTURE, graph=False, recorder=None)
    events_graph = await mod.run_scenario(SCENARIOS_FIXTURE, graph=True, recorder=None)
    assert events_old and events_graph
    assert mod.diff_normalized(events_old, events_graph) == []
```

（`SCENARIOS_FIXTURE` 用模块内最小场景 + monkeypatch `AgentLoopService._stream_planning` 返回 finish 计划、`llm_client` 用 FakeClient；实现细节按现有 `tests/test_langgraph_driver.py` 的 fake repo/DB 模板。）

- [ ] **Step 2: 确认失败** → `-m pytest tests/test_langgraph_differential.py -q` FAIL

- [ ] **Step 3: 实现脚本**

骨架（DB 部分照抄 `tests/test_agent_loop.py:540-600` 的 test_db/`claim_next_attempt`/`process_attempt` 模板；`monkeypatch` 换成脚本内的显式替换）：

```python
# backend/scripts/langgraph_differential.py
"""录制回放差分：同一 fixture 驱动旧轨与图轨，逐字节 diff agent_run_events。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.services.agent import AgentLoopService
from app.services.agent.event_normalize import NORMALIZATION_RULES, diff_normalized
from app.services.agent.llm_recorder import LlmRecorder

FIXTURE_DIR = Path("docs/langgraph-eval/fixtures")
REPORT_PATH = Path("docs/langgraph-eval/report.md")

SCENARIOS: list[dict] = [
    {"id": 1, "name": "普通问答 fast path", "goal": "你好，介绍一下你自己", "settings": {"fast_path_enabled": True}, "attachments": []},
    {"id": 2, "name": "方案类全流程", "goal": "基于已有资料写一份新品上市的广告营销方案", "settings": {}, "attachments": []},
    {"id": 3, "name": "必读文件未读→先追问", "goal": "基于已有资料写一份传播方案", "settings": {}, "attachments": []},
    {"id": 4, "name": "研究前置门禁", "goal": "写一份竞品分析方案", "settings": {}, "attachments": []},
    {"id": 5, "name": "版本规则", "goal": "把方案更新到 V2 版本", "settings": {}, "attachments": []},
    {"id": 6, "name": "结构校验拒稿→骨架补全", "goal": "写一份投放策略方案", "settings": {}, "attachments": []},
    {"id": 7, "name": "重试耗尽 run_failed", "goal": "写一份年度营销方案", "settings": {}, "attachments": []},
    {"id": 8, "name": "附件引用", "goal": "参考我上传的附件写一份推广方案", "settings": {}, "attachments": ["<录制时上传一个 md 附件>"]},
    {"id": 9, "name": "质检闭环", "goal": "写一份完整的品牌营销方案", "settings": {"quality_review_max_rounds": 2}, "attachments": []},
    {"id": 10, "name": "计费/usage", "goal": "写一份简短的营销方案", "settings": {}, "attachments": []},
]


async def run_scenario(scenario: dict, *, graph: bool, recorder: LlmRecorder | None) -> list[dict]:
    """真实 test DB 跑一次 attempt，返回该 run 的全量事件（list[dict]）。"""
    ...


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", default=None)
    parser.add_argument("--diff", default=None)
    parser.add_argument("--report", default=str(REPORT_PATH))
    args = parser.parse_args()
    if args.record:
        asyncio.run(_record(args.record))
    elif args.diff:
        asyncio.run(_diff(args.diff, Path(args.report)))
```

`_record(id)`: `os.environ["LANGGRAPH_DIFF_RECORD"] = str(FIXTURE_DIR / f"scenario-{id}.json")` → `run_scenario(scenario, graph=False, recorder=None)`（Recorder 由 `DeepSeekClient` 内部从 env 自建；跑完 fixture 已落盘）→ 打印 LLM 调用数。
`_diff(id, report)`: 设 `LANGGRAPH_DIFF_REPLAY` → `run_scenario(graph=False)` 与 `run_scenario(graph=True)` 各一次 → `diff_normalized` → 报告追加：场景名、事件数、差异列表、归一化规则（首次写入时输出 `NORMALIZATION_RULES`）。

- [ ] **Step 4: 跑绿 + 提交**

```bash
git add backend/scripts/langgraph_differential.py backend/tests/test_langgraph_differential.py
git commit -m "feat(langgraph-diff): scenario driver with record/replay + report"
```

---

### Task 4: 图轨遗留保真项核对与补齐

**Files:**
- Modify: `backend/app/services/agent/loop.py`（仅 `_do_node_*` 图轨实现）
- Test: `backend/tests/test_langgraph_fidelity.py`（追加）

**Interfaces:** 无新接口；补齐 2026-08-27 计划 T8 遗留：
1. 附件格式（`attachments` 进入图状态后的形状与旧轨一致）
2. plan 节点内 `_commit_repo` 调用点
3. `pre_generated_thought` 线程（图状态 → 最终 answer 路径）

- [ ] **Step 1: 逐项核对现状**（读 `_do_node_plan`/`_do_node_execute`/`_do_node_finalize` 与旧轨对应段），把缺的写成失败测试
- [ ] **Step 2: 失败确认 → 修图轨至绿**
- [ ] **Step 3: 跑 `tests/test_langgraph_*.py` 全绿 + 提交**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_langgraph_fidelity.py
git commit -m "fix(langgraph): close deferred fidelity gaps in graph nodes"
```

---

### Task 5: 场景矩阵真实录制（10 条 fixture）

**Files:**
- Create: `docs/langgraph-eval/fixtures/scenario-1..10.json`

- [ ] **Step 1: 逐条录制**：`cd backend; X:\python\anaconda\envs\01-rbac\python.exe scripts/langgraph_differential.py --record <id>`
  - 前置：`backend/.env` 有可用 `DEEPSEEK_API_KEY`；`DATABASE_URL` 指向开发库；网络可用。
- [ ] **Step 2: 校验 fixture**：10 个文件存在、JSON 合法、每条 `calls` 非空、`create_plan`/`stream_text` 都有覆盖（场景 1/3/7 可能无 create_plan，按实际记录并在报告说明）
- [ ] **Step 3: 提交**

```bash
git add docs/langgraph-eval/fixtures
git commit -m "test(langgraph-diff): record 10-scenario llm fixtures"
```

---

### Task 6: 全矩阵差分 + 图轨差异修复至 0

**Files:**
- Modify: `backend/app/services/agent/loop.py`（仅图轨）、`backend/app/services/agent/langgraph_runner.py`（必要时）
- Create/Update: `docs/langgraph-eval/report.md`

- [ ] **Step 1: 跑全矩阵**：`python scripts/langgraph_differential.py --diff all`
- [ ] **Step 2: 逐条修差异**（每条场景一个循环：定位 → 修图轨 → 重跑该场景 → 0 差异）
- [ ] **Step 3: 全矩阵 0 差异后跑 `tests/test_langgraph_*.py` + `tests/test_agent_loop.py` 全绿**
- [ ] **Step 4: 提交**

```bash
git add backend/app/services/agent/loop.py backend/app/services/agent/langgraph_runner.py docs/langgraph-eval/report.md
git commit -m "fix(langgraph): reach byte-fidelity with old track across 10 scenarios"
```

---

### Task 7: 翻默认值 + 回退说明 + 全量回归

**Files:**
- Modify: `backend/app/core/config.py:40`（`langgraph_enabled: bool = True`）
- Modify: `backend/.env.example`（`LANGGRAPH_ENABLED=false` 回退说明）
- Modify: `backend/tests/test_settings_langgraph_flag.py`（默认 True 断言 + 显式 false 仍可）
- Test: 全量 `backend/tests`

- [ ] **Step 1: 改测试断言（先红）**：`test_langgraph_flag_default_false` → 改名为 `test_langgraph_flag_default_true` 并断言 True；`monkeypatch.setenv("LANGGRAPH_ENABLED", "false")` 断言可回退
- [ ] **Step 2: 改默认值至绿**
- [ ] **Step 3: 全量回归**：`X:\python\anaconda\envs\01-rbac\python.exe -m pytest -q`（对比基线失败清单，不得新增）
- [ ] **Step 4: 提交**

```bash
git add backend/app/core/config.py backend/.env.example backend/tests/test_settings_langgraph_flag.py
git commit -m "feat(langgraph): default to single-track (langgraph_enabled=True) with env rollback"
```

---

### Task 8: 真实任务抽查 + 文档收尾

**Files:**
- Create: `docs/verification/langgraph-single-track-checklist.md`
- Update: `docs/langgraph-eval/report.md`（定稿：矩阵结果 + 归一化规则 + 回退方式）

- [ ] **Step 1: 写抽查清单**（4 类真实任务：普通问答 / 方案类全流程 / 门禁触发 / 附件引用；每条给操作步骤与预期）
- [ ] **Step 2: 用户手测**（后端 + worker + 前端在线；记录每条结果与 run id）
- [ ] **Step 3: 文档定稿 + 提交**

```bash
git add docs/verification/langgraph-single-track-checklist.md docs/langgraph-eval/report.md
git commit -m "docs: langgraph single-track acceptance checklist + differential report"
```
