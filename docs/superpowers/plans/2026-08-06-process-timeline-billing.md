# 过程稿时间线 + 商业化界面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成记录详情新增详细过程稿时间线（从 run 事件流组装）+ 侧边栏"账户"商业化页面（mock 数据）。

**Architecture:** 后端 `GET /api/generations/{log_id}/timeline` 查该 run 的 `agent_run_events`（seq 升序），按事件类型组装时间线条目（thought 全文不截断 / tool 输入输出+耗时 / answer 全文 / terminal 终态）；前端详情弹窗加时间线区块（折叠 + 失败高亮）。商业化为纯前端 mock（常量文件 + 账户页 + 侧边栏入口）。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, React + AntD

**Spec:** `docs/superpowers/specs/2026-08-06-process-timeline-billing-design.md` (434c87e)

## Global Constraints

- 时间线数据源：`agent_run_events`（event_type ∈ {visible_thought_completed, step_completed, answer_completed, run_succeeded, run_failed}），payload 结构已核实（loop.py）：thought={step_index,text,length,fallback}；step={step_index,action_type,tool_call,observation,step_duration_seconds}；answer={stream_id,text,length}；run_failed={error}；run_succeeded={final_answer}
- 思考/答案全文不截断；工具 observation 截断 500 字；不输出凭据/二进制
- 权限：timeline 仅 log 归属者或超管（log.user_id 校验）
- 商业化：无图表库（YAGNI）；mock 常量独立文件 `frontend/src/lib/points-config.ts`；所有展示标注"示例"/"未开放"
- Python 执行器：`X:\python\anaconda\envs\01-rbac\python.exe`；后端测试 workdir `C:\01_agent_loop_pro\backend`；前端 `npx tsc --noEmit` + `npx vitest run`（workdir `C:\01_agent_loop_pro\frontend`）
- **git 纪律**：仓库有并行会话改动——只 `git add` 本任务精确路径，禁 `git add -A`；提交前 `git status --short`
- 后端测试可能被并行会话中间态阻塞（conftest ImportError）——等待或报告 BLOCKED
- 前端测试约定：页面级 byRole 会超时（jsdom 病理）——用 `document.querySelectorAll("button")` + textContent 匹配

---

### Task 1: 后端 timeline API

**Files:**
- Modify: `backend/app/api/generations.py`
- Test: `backend/tests/test_generations_api.py`（追加 Timeline 测试类）

**Interfaces:**
- Consumes: `GenerationLog`（log 归属校验）、`AgentRunEvent`（models/agent.py，run_id/seq/event_type/payload）
- Produces:
  - `GET /api/generations/{log_id}/timeline` → 200 `{steps: [{type, step_index?, content?, action_type?, input?, observation?, duration_seconds?, status?, error?, created_at}]}`；403 LOG_NOT_OWNED；404 LOG_NOT_FOUND
  - 条目类型：thought / tool / answer / terminal

- [ ] **Step 1: 写失败测试**

`backend/tests/test_generations_api.py` 追加（复用现有 fixtures 模式——`_make_session`/`_make_run`/`csrf_headers`/`ordinary_client` 等；timeline 是 GET 不需要 csrf）：

```python
class TestGenerationTimeline:
    @pytest.mark.anyio
    async def test_timeline_assembles_events_in_order(
        self, test_db, ordinary_client, ordinary_user
    ):
        from app.models.agent import AgentRunEvent
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            log = GenerationLog(
                folder_id=None,
                user_id=ordinary_user.id,
                session_id=session.id,
                run_id=run.id,
                input_text=run.goal,
                status="succeeded",
            )
            db.add(log)
            await db.flush()
            evs = [
                AgentRunEvent(run_id=run.id, event_type="visible_thought_completed",
                              payload={"step_index": 0, "text": "先查资料", "length": 4}),
                AgentRunEvent(run_id=run.id, event_type="step_completed",
                              payload={"step_index": 0, "action_type": "read_file",
                                       "tool_call": {"path": "docs/a.md"},
                                       "observation": {"file_id": "x", "filename": "a.md"},
                                       "step_duration_seconds": 1.5}),
                AgentRunEvent(run_id=run.id, event_type="answer_completed",
                              payload={"text": "最终方案", "length": 4}),
                AgentRunEvent(run_id=run.id, event_type="run_succeeded",
                              payload={"final_answer": "最终方案"}),
            ]
            db.add_all(evs)
            await db.commit()

        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        assert resp.status_code == 200, resp.text
        steps = resp.json()["data"]["steps"]
        assert [s["type"] for s in steps] == ["thought", "tool", "answer", "terminal"]
        assert steps[0]["content"] == "先查资料"
        assert steps[1]["action_type"] == "read_file"
        assert steps[1]["input"]["path"] == "docs/a.md"
        assert "a.md" in steps[1]["observation"]
        assert steps[1]["duration_seconds"] == 1.5
        assert steps[2]["content"] == "最终方案"
        assert steps[3]["status"] == "succeeded"

    @pytest.mark.anyio
    async def test_timeline_failed_run_has_error(
        self, test_db, ordinary_client, ordinary_user
    ):
        from app.models.agent import AgentRunEvent
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            log = GenerationLog(
                folder_id=None, user_id=ordinary_user.id, session_id=session.id,
                run_id=run.id, input_text=run.goal, status="succeeded",
            )
            db.add(log)
            await db.flush()
            db.add(AgentRunEvent(run_id=run.id, event_type="run_failed",
                                 payload={"error": "max_steps_exceeded"}))
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        steps = resp.json()["data"]["steps"]
        assert steps[0]["type"] == "terminal"
        assert steps[0]["status"] == "failed"
        assert steps[0]["error"] == "max_steps_exceeded"

    @pytest.mark.anyio
    async def test_timeline_other_users_log_forbidden(
        self, test_db, ordinary_client, ordinary_user, admin_client, admin_user
    ):
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, admin_user.id)
            run = await _make_run(db, admin_user.id, session)
            log = GenerationLog(
                folder_id=None, user_id=admin_user.id, session_id=session.id,
                run_id=run.id, input_text=run.goal, status="succeeded",
            )
            db.add(log)
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        assert resp.status_code == 403

    @pytest.mark.anyio
    async def test_timeline_no_events_empty(self, test_db, ordinary_client, ordinary_user):
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            log = GenerationLog(
                folder_id=None, user_id=ordinary_user.id, session_id=session.id,
                run_id=run.id, input_text=run.goal, status="succeeded",
            )
            db.add(log)
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        assert resp.json()["data"]["steps"] == []

    @pytest.mark.anyio
    async def test_timeline_observation_truncated(
        self, test_db, ordinary_client, ordinary_user
    ):
        from app.models.agent import AgentRunEvent
        from app.models.generation_log import GenerationLog

        async with test_db() as db:
            session = await _make_session(db, ordinary_user.id)
            run = await _make_run(db, ordinary_user.id, session)
            log = GenerationLog(
                folder_id=None, user_id=ordinary_user.id, session_id=session.id,
                run_id=run.id, input_text=run.goal, status="succeeded",
            )
            db.add(log)
            await db.flush()
            db.add(AgentRunEvent(run_id=run.id, event_type="step_completed",
                                 payload={"step_index": 0, "action_type": "web_search",
                                          "tool_call": {"query": "测试"},
                                          "observation": "x" * 2000,
                                          "step_duration_seconds": 0.1}))
            await db.commit()
        resp = await ordinary_client.get(f"/api/generations/{log.id}/timeline")
        obs = resp.json()["data"]["steps"][0]["observation"]
        assert len(obs) <= 500
```

（fixtures `admin_user` 若不存在照 test_generations_api.py 现有模式定义；`AgentRunEvent.seq` DB 生成省略。）

- [ ] **Step 2: 运行确认失败**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_generations_api.py::TestGenerationTimeline -q --no-header`
Expected: FAIL（404）

- [ ] **Step 3: 实现 timeline 端点**

`backend/app/api/generations.py` 追加：

```python
from app.models.agent import AgentRun, AgentRunEvent, AgentSession


def _sanitize_observation(observation) -> str:
    if observation is None:
        return ""
    if isinstance(observation, str):
        return observation[:500]
    if isinstance(observation, dict):
        parts = []
        for key in ("error", "file_id", "filename", "path", "folder_path", "query", "title", "summary"):
            value = observation.get(key)
            if value is not None:
                parts.append(f"{key}: {value}")
        if parts:
            return "; ".join(parts)[:500]
        text = str(observation)
        return text[:500]
    return str(observation)[:500]


def _timeline_entry(ev: AgentRunEvent) -> dict | None:
    p = ev.payload or {}
    created_at = ev.created_at.isoformat() if ev.created_at else ""
    base = {"created_at": created_at}
    if ev.event_type == "visible_thought_completed":
        return {**base, "type": "thought", "step_index": p.get("step_index"),
                "content": p.get("text", "")}
    if ev.event_type == "step_completed":
        return {**base, "type": "tool", "step_index": p.get("step_index"),
                "action_type": p.get("action_type", ""),
                "input": p.get("tool_call") or {},
                "observation": _sanitize_observation(p.get("observation")),
                "duration_seconds": p.get("step_duration_seconds")}
    if ev.event_type == "answer_completed":
        return {**base, "type": "answer", "content": p.get("text", "")}
    if ev.event_type == "run_failed":
        return {**base, "type": "terminal", "status": "failed", "error": p.get("error", "")}
    if ev.event_type == "run_succeeded":
        return {**base, "type": "terminal", "status": "succeeded"}
    return None


@router.get("/generations/{log_id}/timeline")
async def generation_timeline(
    request: Request,
    log_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    log = await db.get(GenerationLog, log_id)
    if log is None:
        raise ApiError(status_code=404, code="LOG_NOT_FOUND", message="生成记录不存在")
    if str(log.user_id) != str(current_user.id):
        raise ApiError(status_code=403, code="LOG_NOT_OWNED", message="无权访问该记录")
    result = await db.execute(
        select(AgentRunEvent)
        .where(AgentRunEvent.run_id == log.run_id)
        .order_by(AgentRunEvent.seq.asc())
    )
    steps = [
        entry
        for entry in (_timeline_entry(ev) for ev in result.scalars().all())
        if entry is not None
    ]
    return success(request, {"steps": steps})
```

（路由顺序：`/generations/{log_id}/timeline` 与既有 `/generations?folder_id=` 不冲突——GET 集合 vs GET 详情路径。注意与现有 `/generations` GET 路由并存无冲突。）

- [ ] **Step 4: 运行确认通过**

Run: `& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/test_generations_api.py -q --no-header`
Expected: 全部通过（16 个：11 既有 + 5 timeline）

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/generations.py backend/tests/test_generations_api.py
git commit -m "feat: generation timeline API assembling run events into draft steps"
```

---

### Task 2: 前端过程稿时间线

**Files:**
- Modify: `frontend/src/lib/api.ts`（`getGenerationTimeline(logId)` + `GenerationTimelineStep` 类型）
- Modify: `frontend/src/components/files/generation-records-modal.tsx`（详情弹窗加时间线区块）
- Test: `frontend/src/components/files/generation-records-modal.test.tsx` 或现有文件页测试（`file-management.test.tsx`——若记录 Modal 已有测试则扩展）

**Interfaces:**
- Consumes: T1 契约：`GET /api/generations/{log_id}/timeline` → `{steps: [{type, step_index?, content?, action_type?, input?, observation?, duration_seconds?, status?, error?, created_at}]}`
- Produces: 无

- [ ] **Step 1: api.ts 加类型与函数**

`frontend/src/lib/api.ts` 追加：

```ts
export interface GenerationTimelineStep {
  type: "thought" | "tool" | "answer" | "terminal";
  step_index?: number;
  content?: string;
  action_type?: string;
  input?: Record<string, unknown>;
  observation?: string;
  duration_seconds?: number;
  status?: "succeeded" | "failed";
  error?: string;
  created_at: string;
}

export async function getGenerationTimeline(logId: string) {
  return api<{ steps: GenerationTimelineStep[] }>(`/api/generations/${logId}/timeline`);
}
```

- [ ] **Step 2: 详情弹窗加时间线区块**

`frontend/src/components/files/generation-records-modal.tsx`：
1. import 加 `getGenerationTimeline`、`GenerationTimelineStep`、`useEffect`（已 import？核实）
2. state：`const [timeline, setTimeline] = useState<GenerationTimelineStep[] | null>(null);`
3. 详情打开时加载（detailLog 变化 effect）：

```tsx
useEffect(() => {
  if (!detailLog) {
    setTimeline(null);
    return;
  }
  let alive = true;
  getGenerationTimeline(detailLog.id)
    .then((d) => {
      if (alive) setTimeline(d.steps);
    })
    .catch(() => {
      if (alive) setTimeline([]);
    });
  return () => {
    alive = false;
  };
}, [detailLog]);
```

4. 详情 Modal 内"生成结果"之后加"过程稿"区块：

```tsx
<div>
  <div style={{ fontWeight: 600, marginBottom: 4 }}>过程稿</div>
  {timeline === null ? (
    <div style={{ fontSize: 13, color: "#888" }}>加载中…</div>
  ) : timeline.length === 0 ? (
    <div style={{ fontSize: 13, color: "#888" }}>暂无过程记录</div>
  ) : (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 360, overflowY: "auto" }}>
      {timeline.map((step, idx) => (
        <TimelineStepView key={idx} step={step} />
      ))}
    </div>
  )}
</div>
```

5. 新组件（同文件底部或同目录 `timeline-step-view.tsx`——**同文件**内定义函数组件）：

```tsx
const STEP_META: Record<string, { icon: string; label: string; color: string }> = {
  thought: { icon: "💭", label: "思考", color: "#2f54eb" },
  tool: { icon: "🔧", label: "工具", color: "#722ed1" },
  answer: { icon: "📄", label: "答案", color: "#52c41a" },
  terminal: { icon: "✅", label: "完成", color: "#52c41a" },
};

function TimelineStepView({ step }: { step: GenerationTimelineStep }) {
  const [expanded, setExpanded] = useState(false);
  const meta = STEP_META[step.type] ?? { icon: "•", label: step.type, color: "#888" };
  const isFailed = step.type === "terminal" && step.status === "failed";
  return (
    <div
      style={{
        border: `1px solid ${isFailed ? "#ff4d4f" : "#f0f0f0"}`,
        borderRadius: 8,
        padding: "8px 10px",
        background: isFailed ? "#fff2f0" : "#fafafa",
        cursor: "pointer",
      }}
      onClick={() => setExpanded((v) => !v)}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
        <span>{meta.icon}</span>
        <span style={{ fontWeight: 600, color: meta.color }}>
          {step.type === "tool"
            ? `${meta.label} · ${step.action_type}${step.step_index !== undefined ? `（步骤 ${step.step_index + 1}）` : ""}`
            : `${meta.label}${step.step_index !== undefined ? `（步骤 ${step.step_index + 1}）` : ""}`}
        </span>
        {step.duration_seconds !== undefined && (
          <span style={{ color: "#888" }}>耗时 {step.duration_seconds.toFixed(1)}s</span>
        )}
        {isFailed && <span style={{ color: "#cf1322" }}>失败</span>}
        <span style={{ marginLeft: "auto", color: "#bbb" }}>{expanded ? "收起" : "展开"}</span>
      </div>
      {expanded && (
        <div style={{ marginTop: 8, fontSize: 13, whiteSpace: "pre-wrap" }}>
          {step.type === "tool" ? (
            <>
              {step.input && Object.keys(step.input).length > 0 && (
                <pre style={{ background: "#fff", borderRadius: 4, padding: 8, fontSize: 12, margin: "0 0 8px" }}>
                  {JSON.stringify(step.input, null, 2)}
                </pre>
              )}
              {step.observation && <div style={{ color: "#444" }}>{step.observation}</div>}
            </>
          ) : step.type === "terminal" && step.error ? (
            <div style={{ color: "#cf1322" }}>{step.error}</div>
          ) : (
            <div>{step.content ?? ""}</div>
          )}
        </div>
      )}
    </div>
  );
}
```

（注意：初始展开策略——failed 终态自动展开：在 TimelineStepView 用 `useState(isFailed)` 作为初始 expanded；thought/answer 默认收起，tool 默认收起——**修正**：初始 `expanded` 用 `useState(step.type === "terminal" && step.status === "failed")`。）

- [ ] **Step 3: 测试**

若 `generation-records-modal` 无独立测试文件，则新建 `frontend/src/components/files/generation-records-modal.test.tsx`（照现有测试约定：`vi.mock("@/lib/api")` + `mockApi` + `querySelectorAll("button")` + textContent，禁页面级 byRole）：

```tsx
import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: mockApi,
    listGenerations: () => mockApi("/api/generations"),
    getGenerationTimeline: (logId: string) => mockApi(`/api/generations/${logId}/timeline`),
  };
});

import GenerationRecordsModal from "@/components/files/generation-records-modal";

const LOG = {
  id: "log-1",
  folder_id: null,
  folder_name: "",
  user_id: "u1",
  session_id: "s1",
  run_id: "r1",
  input_text: "写一个方案",
  final_md_file_id: null,
  final_answer: "最终方案内容",
  feishu_doc_url: "",
  status: "succeeded",
  error: "",
  created_at: "2026-08-06T10:00:00Z",
};

const STEPS = [
  { type: "thought", step_index: 0, content: "先查资料再写", created_at: "2026-08-06T10:00:01Z" },
  {
    type: "tool",
    step_index: 0,
    action_type: "read_file",
    input: { path: "docs/a.md" },
    observation: "file_id: x; filename: a.md",
    duration_seconds: 1.5,
    created_at: "2026-08-06T10:00:02Z",
  },
  { type: "answer", content: "最终方案内容", created_at: "2026-08-06T10:00:03Z" },
  { type: "terminal", status: "succeeded", created_at: "2026-08-06T10:00:04Z" },
];

function mockEndpoints(overrides: Record<string, unknown> = {}) {
  mockApi.mockImplementation((path: string) => {
    if (overrides[path] !== undefined) return Promise.resolve(overrides[path]);
    if (path === "/api/generations") return Promise.resolve({ logs: [LOG], total: 1 });
    if (path === "/api/generations/log-1/timeline") return Promise.resolve({ steps: STEPS });
    return Promise.resolve(undefined);
  });
}

describe("GenerationRecordsModal timeline", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  test("detail loads and renders timeline steps", async () => {
    const user = userEvent.setup();
    mockEndpoints();
    render(<GenerationRecordsModal open folderId={null} onClose={() => {}} />);
    const detailBtn = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find((b) =>
      /详\s*情/.test(b.textContent || "")
    );
    expect(detailBtn).not.toBeNull();
    await user.click(detailBtn!);

    expect(await screen.findByText("过程稿")).toBeTruthy();
    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith("/api/generations/log-1/timeline");
    });
    expect(await screen.findByText(/思考（步骤 1）/)).toBeTruthy();
    expect(await screen.findByText(/工具 · read_file（步骤 1）/)).toBeTruthy();
    expect(await screen.findByText(/答案/)).toBeTruthy();
  });

  test("failed terminal shows error and auto-expands", async () => {
    const user = userEvent.setup();
    mockEndpoints({
      "/api/generations/log-1/timeline": {
        steps: [
          {
            type: "terminal",
            status: "failed",
            error: "max_steps_exceeded",
            created_at: "2026-08-06T10:00:04Z",
          },
        ],
      },
    });
    render(<GenerationRecordsModal open folderId={null} onClose={() => {}} />);
    const detailBtn = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find((b) =>
      /详\s*情/.test(b.textContent || "")
    );
    await user.click(detailBtn!);

    expect(await screen.findByText("失败")).toBeTruthy();
    expect(await screen.findByText("max_steps_exceeded")).toBeTruthy();
  });

  test("empty timeline shows placeholder", async () => {
    const user = userEvent.setup();
    mockEndpoints({ "/api/generations/log-1/timeline": { steps: [] } });
    render(<GenerationRecordsModal open folderId={null} onClose={() => {}} />);
    const detailBtn = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find((b) =>
      /详\s*情/.test(b.textContent || "")
    );
    await user.click(detailBtn!);
    expect(await screen.findByText("暂无过程记录")).toBeTruthy();
  });
});
```

（注意：若 `GenerationRecordsModal` 的 props 名与现有实现不同（如 open/folderId/onClose）——读现有文件按实际 props 调整；`/详\s*情/` 容忍 antd v6 双字按钮自动加空格。timeline 接口 mock 路径需与 `getGenerationTimeline` 实际拼接一致。）

- [ ] **Step 4: 前端验证**

Run: `npx tsc --noEmit`（workdir `C:\01_agent_loop_pro\frontend`）——本任务文件零新增错误
Run: `npx vitest run src/components/files/`——通过

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/components/files/generation-records-modal.tsx frontend/src/components/files/<test文件>
git commit -m "feat: process timeline (detailed drafts) in generation record detail"
```

---

### Task 3: 商业化界面（账户页 + mock）

**Files:**
- Create: `frontend/src/lib/points-config.ts`
- Create: `frontend/src/app/(agent)/account/points/page.tsx`（或对应目录——参照 `(dashboard)/settings` 页面结构，若无 (agent)/account 目录则新建）
- Modify: `frontend/src/components/layout/app-sidebar.tsx`（导航加"账户"入口）
- Test: `frontend/src/app/(agent)/account/points/page.test.tsx` 或页面级测试（如项目已有页面测试模式）

**Interfaces:**
- Consumes: 无后端依赖
- Produces: 无

- [ ] **Step 1: 写 mock 常量文件**

`frontend/src/lib/points-config.ts`：

```ts
export const POINTS_PER_TOKEN = 0.001; // 1 token = 0.001 积点（示例比例，待定）
export const MOCK_BALANCE = 12345; // 示例余额
export const MOCK_USAGE_WEEK = { tokens: 152300, points: 152.3 };
export const MOCK_USAGE_MONTH = { tokens: 842000, points: 842 };
export const PLANS = [
  { name: "体验版", points: 10000, price: "¥29", desc: "适合个人试用", badge: "推荐" },
  { name: "标准版", points: 50000, price: "¥99", desc: "适合小型团队" },
  { name: "专业版", points: 200000, price: "¥299", desc: "适合深度使用" },
];
```

- [ ] **Step 2: 账户页**

`frontend/src/app/(agent)/account/points/page.tsx`（参照现有页面模式——读一个现有页面（如 (dashboard)/settings/profile 结构）保持布局一致：page 容器 + 标题）：

```tsx
"use client";

import { Button, Card, Col, Progress, Row, Statistic, Tag } from "antd";
import { message } from "antd";
import { MOCK_BALANCE, MOCK_USAGE_MONTH, MOCK_USAGE_WEEK, PLANS, POINTS_PER_TOKEN } from "@/lib/points-config";

export default function PointsPage() {
  return (
    <div style={{ padding: 24, maxWidth: 960, margin: "0 auto" }}>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>我的积点</h2>
        <div style={{ color: "#8c8c8c", fontSize: 13 }}>示例数据 · 未开放</div>
      </div>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic title="当前余额" value={MOCK_BALANCE} suffix="积点" />
            <div style={{ fontSize: 12, color: "#8c8c8c", marginTop: 4 }}>示例数据 · 未开放</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="本周用量" value={MOCK_USAGE_WEEK.tokens} suffix="token" />
            <Progress percent={Math.round((MOCK_USAGE_WEEK.points / 200) * 100)} size="small" />
            <div style={{ fontSize: 12, color: "#8c8c8c" }}>
              约 {MOCK_USAGE_WEEK.points} 积点
            </div>
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="本月用量" value={MOCK_USAGE_MONTH.tokens} suffix="token" />
            <Progress percent={Math.round((MOCK_USAGE_MONTH.points / 1000) * 100)} size="small" />
            <div style={{ fontSize: 12, color: "#8c8c8c" }}>
              约 {MOCK_USAGE_MONTH.points} 积点
            </div>
          </Card>
        </Col>
      </Row>

      <Card title="积分规则" style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 13, color: "#555", lineHeight: 1.8 }}>
          <div>· 积点是本系统的虚拟计费单位，后台按 token 消耗换算后扣减。</div>
          <div>· 当前换算比例（示例）：1 token ≈ {POINTS_PER_TOKEN} 积点，正式比例待定。</div>
          <div>· 第一版仅展示界面，不产生真实扣费。</div>
        </div>
      </Card>

      <Card title="套餐 / 充值">
        <Row gutter={16}>
          {PLANS.map((p) => (
            <Col span={8} key={p.name}>
              <Card
                size="small"
                title={
                  <span>
                    {p.name}
                    {p.badge && <Tag color="blue" style={{ marginLeft: 8 }}>{p.badge}</Tag>}
                  </span>
                }
                style={{ marginBottom: 8 }}
              >
                <div style={{ fontSize: 20, fontWeight: 600 }}>{p.points.toLocaleString()} 积点</div>
                <div style={{ color: "#8c8c8c", fontSize: 13, margin: "4px 0 8px" }}>{p.price}</div>
                <div style={{ fontSize: 13, color: "#555", marginBottom: 12 }}>{p.desc}</div>
                <Button
                  block
                  onClick={() => message.info("套餐功能即将上线")}
                >
                  即将上线
                </Button>
              </Card>
            </Col>
          ))}
        </Row>
        <div style={{ fontSize: 12, color: "#8c8c8c", marginTop: 4 }}>以上为示例内容，正式计费与支付功能尚未开放。</div>
      </Card>
    </div>
  );
}
```

- [ ] **Step 3: 侧边栏入口**

`frontend/src/components/layout/app-sidebar.tsx`——读导航菜单结构（items 数组，/agent/files、/files 等），在合适分组（用户区/管理区之前或之后）加：

```tsx
{
  key: "/account/points",
  icon: <WalletOutlined />,
  label: <Link href="/account/points" onClick={onNavigate}>{copy.navigation.points ?? "账户"}</Link>,
},
```

（`WalletOutlined` 从 `@ant-design/icons` import；`copy.navigation` 若无 points 键则直接用字面量"账户"或加进 `frontend/src/lib/copy.ts`——**用字面量"账户"最简单**，避免改 copy.ts。）

- [ ] **Step 4: 验证 + 测试**

Run: `npx tsc --noEmit`——本任务文件零新增错误
测试（页面测试若项目有先例则加一个简单渲染测试，断言"当前余额""即将上线"存在；若无先例可只做 tsc + vitest 现有套件无回归）：
Run: `npx vitest run src/components/layout/`（若侧边栏有测试——断言"账户"入口渲染）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/points-config.ts "frontend/src/app/(agent)/account/points/page.tsx" frontend/src/components/layout/app-sidebar.tsx <test文件>
git commit -m "feat: points/billing UI page with mock data and sidebar entry"
```

---

### Task 4: E2E 验证与收尾

- [ ] **Step 1: 后端回归（隔离 DB）**

```powershell
$env:TEST_DATABASE_URL="postgresql+asyncpg://rbac:rbac_local_password@127.0.0.1:5432/rbac_test_timeline"
& "X:\python\anaconda\envs\01-rbac\python.exe" -m pytest tests/ -q --no-header
```
Expected: 全过或仅已知失败（pypdf 4 + 并行会话既有失败）；timeline 相关全绿。

- [ ] **Step 2: 用户实测**

1. Agent 会话让 AI 生成一个方案（写 md）→ run 完成
2. 文件页 → 生成记录 → 详情 → **过程稿**区块出现：思考步骤全文、工具调用（输入/输出/耗时）、答案、终态
3. 故意失败场景（可选）：让 AI 做不可能任务 → 详情里 failed 红色高亮 + 失败原因
4. 侧边栏"账户"入口 → 积点页：余额/用量/规则/套餐占位显示，标注"示例/未开放"
5. 点"即将上线" → 提示

- [ ] **Step 3: 提交校准修复（如有）**

```bash
git add <精确路径>
git commit -m "fix: timeline/billing E2E calibration"
```
（仅当有修复。）
