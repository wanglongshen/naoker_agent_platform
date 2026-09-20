# Agent Loop Source-First Session Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-establish the Agent Loop Session right-side experience by copying the source files first, then applying only mandatory RBAC adaptations and making Session loading resilient to partial API failures.

**Architecture:** `X:\01_agent_loop` is the behavioral source of truth for the Session page, conversation stream, reducer, SSE hook, thought narrative, final answer, composer, textarea, and attachment interaction. Each source file is copied to its RBAC target before edits; only imports, RBAC API envelopes, UUID/ownership, Cookie/CSRF, `succeeded`, private attachment IDs, `/agent` routes, and terminal refresh are changed. A small RBAC session-view loader isolates API normalization and per-run failure handling so the copied view components keep the Agent Loop structure.

**Tech Stack:** Next.js 16, React 19, TypeScript, Vitest, React Testing Library, Ant Design only at existing RBAC shell/error boundaries, FastAPI JSON envelopes, PostgreSQL-backed Agent APIs.

## Global Constraints

- Copy usable Agent Loop source code before modifying it. Do not implement a functionally equivalent replacement from scratch.
- The source file is the behavioral baseline; every non-copy change must be justified as import path, RBAC API envelope, UUID, owner/authentication, Cookie/CSRF, `succeeded`, private attachment ID, `/agent` route, or terminal refresh.
- Do not add new Card/Tag wrappers or redesign the copied Agent Loop right-side JSX.
- Do not restore the deleted home-page history list. Session history remains in the RBAC left sidebar.
- Do not alter the already working Worker, DeepSeek `deepseek-v4-flash`, backend SSE event protocol, attempt/lease, retry, attachment storage, or RBAC permission model except where a test proves an API response contract is wrong.
- A failure in one historical Run must not blank the entire Session. The Session and Run list are required data; events/steps for an individual Run are optional diagnostics.
- Never expose cookies, JWTs, API keys, attachment text, provider response bodies, or raw exception text in UI or logs.
- Preserve the source Session page content order: user message, timestamp/status, thought narrative, final answer, continuation composer.
- Preserve Agent Loop stream replay, cursor, delta, deduplication, reconnect, terminal close, and final-answer behavior.

---

## Current Baseline And Scope

Already complete and retained:

```text
RBAC DashboardShell and Session sidebar
Agent API namespace and owner checks
Private attachment upload and attachment IDs
Independent Worker process
DeepSeek provider call using deepseek-v4-flash
Attempt/lease/retry persistence
Committed backend SSE events
Frontend EventSource backend base URL and withCredentials
Agent Loop thought/final-answer components and reducer
```

Current gaps to fix:

```text
SessionConversationStream differs from the source by Ant Card wrapping and added coupling.
SessionDetailPage collapses all API failures into “加载会话失败”.
One historical Run event/step failure blanks the whole Session.
Agent API envelope normalization is not centralized for all Session data calls.
Source-first copy traceability is not recorded per target file.
The Session page has no request cancellation or stale-response protection.
```

## Source-To-Target Map

| Source file copied first | RBAC target | Allowed post-copy adaptations |
|---|---|---|
| `X:\01_agent_loop\frontend\app\sessions\[id]\page.tsx` | `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx` | client-side auth loading, `agentApi`, `/agent`, private attachment IDs, terminal refresh |
| `X:\01_agent_loop\frontend\components\SessionConversationStream.tsx` | `frontend/src/components/agent/session-conversation-stream.tsx` | Agent types/imports, `succeeded`, optional terminal callback only |
| `X:\01_agent_loop\frontend\hooks\useRunEventStream.ts` | `frontend/src/hooks/use-run-event-stream.ts` | RBAC SSE URL, Cookie credentials, terminal callback, typed Agent event |
| `X:\01_agent_loop\frontend\lib\runStreamReducer.ts` | `frontend/src/lib/run-stream-reducer.ts` | Agent types, `succeeded`, RBAC event aliases |
| `X:\01_agent_loop\frontend\components\ThoughtNarrative.tsx` | `frontend/src/components/agent/thought-narrative.tsx` | Agent types and event field names only |
| `X:\01_agent_loop\frontend\components\FinalAnswerPanel.tsx` | `frontend/src/components/agent/final-answer-panel.tsx` | Agent types, safe markdown, removed pending-answer placeholder, `succeeded` |
| `X:\01_agent_loop\frontend\components\ComposerForm.tsx` | `frontend/src/components/agent/composer-form.tsx` | Cookie/CSRF client submit boundary |
| `X:\01_agent_loop\frontend\components\SubmitTextarea.tsx` | `frontend/src/components/agent/submit-textarea.tsx` | existing Ant input wrapper only if required by RBAC form system |
| `X:\01_agent_loop\frontend\components\AttachmentInput.tsx` | `frontend/src/components/agent/attachment-input.tsx` | private upload endpoint, attachment IDs, pending first-message files |

### Task 1: Freeze Source Parity And Add Session-View Contracts

**Files:**
- Create: `frontend/src/lib/agent-session-view.ts`
- Create: `frontend/src/lib/agent-session-view.test.ts`
- Modify: `frontend/src/types/agent.ts`
- Modify: `frontend/src/lib/agent-api.ts`
- Source reference: `X:\01_agent_loop\frontend\app\sessions\[id]\page.tsx`
- Source reference: `X:\01_agent_loop\frontend\components\SessionConversationStream.tsx`

**Interfaces:**

```ts
export type AgentSessionTurn = {
  run: AgentRun;
  steps: AgentConversationStep[];
  events: AgentRunEvent[];
  warning: AgentLoadWarning | null;
};

export type AgentLoadWarning = {
  scope: "session" | "runs" | "events" | "steps";
  sessionId: string;
  runId?: string;
  status?: number;
  code?: string;
  requestId?: string;
  message: string;
};

export type AgentSessionView = {
  session: AgentSession;
  turns: AgentSessionTurn[];
  warnings: AgentLoadWarning[];
};

export async function loadAgentSessionView(
  sessionId: string,
  signal?: AbortSignal,
): Promise<AgentSessionView>;
```

- [ ] **Step 1: Copy source Session data shape into a failing contract test**

```ts
it("returns source-shaped turns while isolating one failed historical run", async () => {
  vi.mocked(agentApi.getSession).mockResolvedValue(session);
  vi.mocked(agentApi.getSessionRuns).mockResolvedValue([run1, run2]);
  vi.mocked(agentApi.getRunEvents).mockResolvedValueOnce(events1).mockRejectedValueOnce(new ApiError(502, "UPSTREAM", "events unavailable", null, "req-2"));
  vi.mocked(agentApi.getRunSteps).mockResolvedValue(steps1);

  const view = await loadAgentSessionView("session-1");

  expect(view.session).toEqual(session);
  expect(view.turns).toHaveLength(2);
  expect(view.turns[0]).toMatchObject({ run: run1, events: events1, warning: null });
  expect(view.turns[1]).toMatchObject({ run: run2, events: [], steps: [] });
  expect(view.warnings).toEqual([expect.objectContaining({ scope: "events", runId: run2.id, requestId: "req-2" })]);
});
```

- [ ] **Step 2: Run the test to verify RED**

Run: `npm test -- --run src/lib/agent-session-view.test.ts`  
Expected: FAIL because the source-shaped session loader does not exist.

- [ ] **Step 3: Normalize the API error contract**

Extend `ApiError` only with the already available `status`, `code`, `details`, and `requestId`. Add one normalizer:

```ts
function toAgentLoadWarning(error: unknown, scope: AgentLoadWarning["scope"], sessionId: string, runId?: string): AgentLoadWarning {
  if (error instanceof ApiError) {
    return { scope, sessionId, runId, status: error.status, code: error.code, requestId: error.requestId, message: agentLoadMessage(scope, error.status, error.code) };
  }
  return { scope, sessionId, runId, message: agentLoadMessage(scope, undefined, undefined) };
}
```

`agentLoadMessage()` returns stable Chinese messages for 401/403/404/502 and a generic service-unavailable message. It never includes raw server error text.

- [ ] **Step 4: Implement per-run tolerant loading**

```ts
export async function loadAgentSessionView(sessionId: string, signal?: AbortSignal): Promise<AgentSessionView> {
  const session = await agentApi.getSession(sessionId, signal);
  const runs = await agentApi.getSessionRuns(sessionId, signal);
  const results = await Promise.all(runs.map(async (run) => {
    try {
      const [events, steps] = await Promise.all([
        agentApi.getRunEvents(run.id, 0, signal),
        agentApi.getRunSteps(run.id, signal),
      ]);
      return { run, events, steps, warning: null };
    } catch (error) {
      const warning = toAgentLoadWarning(error, "events", sessionId, run.id);
      return { run, events: [], steps: [], warning };
    }
  }));
  return { session, turns: results, warnings: results.flatMap(({ warning }) => warning ? [warning] : []) };
}
```

If the Session or Run list request fails, throw a normalized `AgentSessionLoadError` containing `scope`, `status`, `code`, and `requestId`; these are required data and cannot be silently replaced with an empty Session.

- [ ] **Step 5: Add AbortSignal to read-only Agent API methods**

Change only signatures and `fetch` init propagation:

```ts
getSession: (sessionId: string, signal?: AbortSignal) => api<AgentSession>(path, { signal }),
getSessionRuns: (sessionId: string, signal?: AbortSignal) => api<AgentRun[]>(path, { signal }),
getRunEvents: (runId: string, afterSeq = 0, signal?: AbortSignal) =>
  api<{ items: AgentRunEvent[] }>(`/api/agent/runs/${runId}/events?after_seq=${afterSeq}`, { signal }),
getRunSteps: (runId: string, signal?: AbortSignal) =>
  api<AgentConversationStep[]>(`/api/agent/runs/${runId}/steps`, { signal }),
```

- [ ] **Step 6: Verify GREEN**

Run: `npm test -- --run src/lib/agent-session-view.test.ts src/lib/agent-api.test.ts`  
Expected: PASS; one failed historical Run no longer rejects the whole Session view.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/agent-session-view.ts frontend/src/lib/agent-session-view.test.ts frontend/src/types/agent.ts frontend/src/lib/agent-api.ts
```

### Task 2: Copy SessionConversationStream Source Exactly Then Adapt Types

**Files:**
- Modify: `frontend/src/components/agent/session-conversation-stream.tsx`
- Modify: `frontend/src/components/agent/run-diagnostics.test.tsx`
- Source: `X:\01_agent_loop\frontend\components\SessionConversationStream.tsx`

**Copy rule:** Before any edits, copy the full source file into the target. The first target diff must contain only import path/type changes. Do not keep `Card`, `Tag`, `statusTagColor`, or other RBAC-added wrappers. The root empty state must be the source `<div className="empty-card">`; each turn must be `<section className="session-turn-block">`.

**Interfaces produced:**

```ts
export default function SessionConversationStream({
  turns,
  onTerminalState,
}: {
  turns: AgentSessionTurn[];
  onTerminalState?: (run: AgentRun) => void;
}): JSX.Element;
```

- [ ] **Step 1: Add a source-parity DOM test before replacing the component**

```tsx
it("matches the Agent Loop Session turn structure", () => {
  const { container } = render(<SessionConversationStream turns={[turn]} />);
  expect(container.querySelector(".detail-conversation-stack > .session-turn-block")).toBeInTheDocument();
  expect(container.querySelector(".session-turn-block > .message-row-user")).toBeInTheDocument();
  expect(container.querySelector(".session-turn-block > .session-turn-meta")).toBeInTheDocument();
  expect(container.querySelector(".session-turn-block > .thought-narrative-block")).toBeInTheDocument();
  expect(container.querySelector(".session-turn-block > .final-answer-panel")).toBeInTheDocument();
  expect(container.querySelector(".session-turn-block > .ant-card")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify RED**

Run: `npm test -- --run src/components/agent/run-diagnostics.test.tsx`  
Expected: FAIL because the current RBAC component wraps the turn in Ant `Card`.

- [ ] **Step 3: Copy the source file and apply only allowed adaptations**

Copy source JSX unchanged, then make these exact substitutions:

```text
@/components/FinalAnswerPanel -> @/components/agent/final-answer-panel
@/components/ThoughtNarrative -> @/components/agent/thought-narrative
@/hooks/useRunEventStream -> @/hooks/use-run-event-stream
Run/RunEvent/Step -> AgentRun/AgentRunEvent/AgentConversationStep
completed -> succeeded
```

Keep the `onTerminalState` callback only on the hook invocation; it is an RBAC terminal-refresh boundary and must not change DOM structure.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --run src/components/agent/run-diagnostics.test.tsx src/components/agent/agent-streaming.test.tsx`  
Expected: PASS; source DOM hierarchy is restored and all Agent content remains visible.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/agent/session-conversation-stream.tsx frontend/src/components/agent/run-diagnostics.test.tsx
```

### Task 3: Copy Session Detail Right-Side Page And Use the Resilient Loader

**Files:**
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`
- Create: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx` if not already present
- Modify: `frontend/src/components/agent/session-conversation-stream.tsx`
- Source: `X:\01_agent_loop\frontend\app\sessions\[id]\page.tsx`

**Copy rule:** Copy the source page body and right-side JSX first. Preserve header, source conversation stack, continuation Composer, toolbar, attachment position, and source spacing. Do not introduce a new detail layout or an Ant page wrapper.

- [ ] **Step 1: Add failing page loading tests**

```tsx
it("renders available turns with a warning when one run diagnostics request fails", async () => {
  mockLoader.mockResolvedValue({ session, turns: [{ run, steps: [], events: [], warning: { scope: "events", message: "事件回放不可用" } }], warnings: [{ scope: "events", message: "事件回放不可用" }] });
  render(<SessionDetailPage />);
  expect(await screen.findByText("测试会话")).toBeInTheDocument();
  expect(screen.getByText("事件回放不可用")).toBeInTheDocument();
  expect(screen.queryByText("加载会话失败")).not.toBeInTheDocument();
});

it("shows a specific request error when the required Session request fails", async () => {
  mockLoader.mockRejectedValue(new AgentSessionLoadError("session", 404, "RESOURCE_NOT_FOUND", "req-404"));
  render(<SessionDetailPage />);
  expect(await screen.findByText("会话不存在或无权访问")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify RED**

Run: `npm test -- --run "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx"`  
Expected: FAIL because the page calls APIs directly, catches all errors as `加载会话失败`, and has no warning rendering.

- [ ] **Step 3: Replace direct API fan-out with `loadAgentSessionView`**

```tsx
const abortRef = useRef<AbortController | null>(null);
const loadSession = useCallback(async () => {
  abortRef.current?.abort();
  const controller = new AbortController();
  abortRef.current = controller;
  setLoading(true);
  try {
    const view = await loadAgentSessionView(sessionId, controller.signal);
    if (controller.signal.aborted) return;
    setSession(view.session);
    setTurns(view.turns);
    setWarnings(view.warnings);
  } catch (error) {
    if (!controller.signal.aborted) setError(toSessionPageError(error));
  } finally {
    if (!controller.signal.aborted) setLoading(false);
  }
}, [sessionId]);
```

Do not show raw `error.message`. `toSessionPageError()` maps required Session/Run failures to stable Chinese UI messages and preserves request ID only in a development log.

- [ ] **Step 4: Render warnings outside the copied conversation turn structure**

Warnings are an RBAC data-integrity boundary, not a replacement for Agent content. Render one compact alert above the copied `SessionConversationStream`:

```tsx
{warnings.length > 0 ? (
  <Alert type="warning" showIcon message="部分历史执行记录暂时无法加载，已保留可用对话内容。" description={warnings.map(toWarningText).join("；")} />
) : null}
```

Do not add warning markup inside the source Session turn JSX.

- [ ] **Step 5: Preserve source Composer with RBAC attachment adaptation**

Keep the source Composer order and class names. The only differences are:

```text
client action -> RBAC handleContinue
session hidden field -> sessionId closure
inline attachment contents -> private attachment IDs
webEnabled -> network_enabled
```

- [ ] **Step 6: Verify GREEN**

Run: `npm test -- --run "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx" src/components/agent/run-diagnostics.test.tsx; npm run build`  
Expected: PASS; required failures are specific, optional historical diagnostics are partial, and copied right-side structure remains unchanged.

- [ ] **Step 7: Commit**

```bash
git add "frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx" "frontend/src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx" frontend/src/components/agent/session-conversation-stream.tsx
```

### Task 4: Source-First Copy Audit For Stream, Narrative, Answer, Composer And Attachment

**Files:**
- Modify: `frontend/src/hooks/use-run-event-stream.ts`
- Modify: `frontend/src/lib/run-stream-reducer.ts`
- Modify: `frontend/src/components/agent/thought-narrative.tsx`
- Modify: `frontend/src/components/agent/final-answer-panel.tsx`
- Modify: `frontend/src/components/agent/composer-form.tsx`
- Modify: `frontend/src/components/agent/submit-textarea.tsx`
- Modify: `frontend/src/components/agent/attachment-input.tsx`
- Create: `frontend/src/lib/source-parity-manifest.ts`
- Create: `frontend/src/lib/source-parity-manifest.test.ts`
- Source references: corresponding files listed in the Source-To-Target Map

**Interfaces:**

```ts
export type SourceParityEntry = {
  source: string;
  target: string;
  copiedBeforeAdaptation: true;
  adaptations: string[];
};

export const agentLoopSourceParity: readonly SourceParityEntry[];
```

- [ ] **Step 1: Add manifest test**

```ts
it("records every copied Agent Loop Session source and only approved adaptations", () => {
  expect(agentLoopSourceParity.length).toBeGreaterThanOrEqual(9);
  for (const entry of agentLoopSourceParity) {
    expect(entry.copiedBeforeAdaptation).toBe(true);
    expect(entry.source).toContain("X:\\01_agent_loop");
    expect(entry.adaptations.every((item) => ["import", "api envelope", "UUID", "ownership", "Cookie/CSRF", "succeeded", "attachment IDs", "/agent", "terminal refresh", "safe markdown"].some((allowed) => item.includes(allowed)))).toBe(true);
  }
});
```

- [ ] **Step 2: Run RED**

Run: `npm test -- --run src/lib/source-parity-manifest.test.ts`  
Expected: FAIL because the source parity manifest does not exist.

- [ ] **Step 3: Copy each source file and compare structure before adaptation**

For each target, save the source-to-target mapping in `source-parity-manifest.ts`. Use a direct copy first. Then apply only:

```text
Agent type imports
RBAC event aliases
succeeded terminal status
SSE base URL and withCredentials
safe markdown link rendering
private attachment upload IDs
terminal callback
```

Do not change event reducer case order, stream offsets, `streamId` deduplication, typing animation behavior, thought block ordering, Composer class names, or attachment chip behavior.

- [ ] **Step 4: Run source behavior tests**

Run: `npm test -- --run src/hooks/use-run-event-stream.test.ts src/lib/run-stream-reducer.test.ts src/components/agent/agent-streaming.test.tsx src/components/agent/run-diagnostics.test.tsx src/lib/source-parity-manifest.test.ts`  
Expected: PASS; source behaviors remain covered after direct-copy adaptation.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/use-run-event-stream.ts frontend/src/lib/run-stream-reducer.ts frontend/src/components/agent/thought-narrative.tsx frontend/src/components/agent/final-answer-panel.tsx frontend/src/components/agent/composer-form.tsx frontend/src/components/agent/submit-textarea.tsx frontend/src/components/agent/attachment-input.tsx frontend/src/lib/source-parity-manifest.ts frontend/src/lib/source-parity-manifest.test.ts
```

### Task 5: End-To-End Session Loading, API Error And Production Verification

**Files:**
- Create: `frontend/src/app/(agent)/agent/sessions/[sessionId]/session-loading.e2e.test.tsx`
- Modify: `frontend/src/lib/agent-session-view.test.ts`
- Modify: `README.md`

- [ ] **Step 1: Add end-to-end contract tests**

```tsx
it("loads a successful historical Session and replays final answer", async () => {
  mockApiSequence({ session, runs: [run], events: [runQueued, runStarted, answerCompleted, runSucceeded], steps: [] });
  render(<SessionDetailPage />);
  expect(await screen.findByText(run.goal)).toBeInTheDocument();
  expect(await screen.findByText("你好！有什么我可以协助您的吗？")).toBeInTheDocument();
});

it("keeps Session content when one historical Run events endpoint returns 502", async () => {
  mockApiSequence({ session, runs: [run1, run2], eventsByRun: { [run1.id]: events1, [run2.id]: new ApiError(502, "UPSTREAM", "", null, "req-2") } });
  render(<SessionDetailPage />);
  expect(await screen.findByText(run1.goal)).toBeInTheDocument();
  expect(screen.getByText("部分历史执行记录暂时无法加载，已保留可用对话内容。")).toBeInTheDocument();
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run "src/app/(agent)/agent/sessions/[sessionId]/session-loading.e2e.test.tsx"`  
Expected: FAIL until the source-first page and tolerant loader are integrated.

- [ ] **Step 3: Run all frontend quality gates**

Run: `npm test -- --run` from `frontend`.  
Expected: all existing and new tests pass.

Run: `npm run build` from `frontend`.  
Expected: Next production build succeeds with `/agent/sessions/[sessionId]` generated as a dynamic route.

- [ ] **Step 4: Run backend contract gates**

Run from `backend`:

```powershell
alembic upgrade head
python -m pytest tests/test_agent_api.py tests/test_agent_stream.py tests/test_agent_loop.py tests/test_agent_worker.py -q
```

Expected: existing API/SSE/Worker/loop tests pass; no backend behavior changes are introduced by the frontend source-first migration.

- [ ] **Step 5: Update README migration traceability**

Add a short section documenting:

```text
Agent Loop source files are copied before RBAC adaptation.
Session right-side layout remains source-owned.
Only listed RBAC boundaries are adapted.
Partial historical diagnostics do not blank a Session.
```

- [ ] **Step 6: Commit**

```bash
git add "frontend/src/app/(agent)/agent/sessions/[sessionId]/session-loading.e2e.test.tsx" frontend/src/lib/agent-session-view.test.ts README.md
```

## Parallel Execution Order

The tasks have shared files and must be executed in this order:

```text
Batch 1: Task 1
Batch 2: Task 2
Batch 3: Task 3
Batch 4: Task 4
Batch 5: Task 5
```

Task 1 must establish the session loader and API signal contracts before Task 3 integrates the page. Task 2 must restore the component DOM before Task 3 composes the page. Task 4 audits shared stream/render files after the core Session structure is stable. Task 5 is the final end-to-end gate.

## Self-Review

### Coverage

| Requirement | Task |
|---|---|
| Copy Agent Loop source before adaptation | Global constraints, Tasks 2-4 |
| Preserve right-side DOM and content order | Tasks 2-3 |
| Robust Session loading | Tasks 1 and 3 |
| Partial historical Run failure isolation | Task 1 |
| API envelope/error normalization | Task 1 |
| Abort/stale response protection | Tasks 1 and 3 |
| SSE/reducer/source stream behavior | Task 4 |
| Final answer/thought/composer/attachment parity | Tasks 2 and 4 |
| End-to-end validation | Task 5 |

### Explicit Non-Goals

- No new Worker architecture.
- No new Session history section on the home page.
- No new diagnostics dashboard in the Session right-side content.
- No redesign of Agent Loop visual hierarchy.
- No deletion of existing audit-only components.

### Placeholder Scan

No TODO/TBD/FIXME or vague implementation steps are used. All planned interfaces, file paths, tests, expected failures, commands, and commit messages are explicit.
