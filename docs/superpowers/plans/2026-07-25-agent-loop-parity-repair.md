# Agent Loop Full Parity Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully preserve the active Agent Loop conversation, Session navigation, diagnostics, streaming, attachment, audit, and execution behavior in RBAC while adapting only the mandatory RBAC security, data, and visual boundaries.

**Architecture:** `X:\01_agent_loop` remains the source of Agent behavior and component structure. Every usable source file is copied to `X:\01_RBAC` first; the only permitted changes are ownership/authentication, Cookie/CSRF, RBAC API envelopes, UUIDs, attachment IDs, attempt/lease history, `succeeded` status, existing RBAC shell, warm tokens, and audit redaction. The RBAC API stays canonical at `/api/agent/*`; no anonymous `/runs/*` compatibility layer is added.

**Tech Stack:** FastAPI, SQLAlchemy async, PostgreSQL, Alembic, httpx, Pydantic, Next.js 16, React 19, Ant Design 6, TypeScript, Vitest, React Testing Library, pytest.

## Global Constraints

- Copy usable Agent Loop source code before modifying it. Do not implement a functionally equivalent replacement from scratch.
- Every task lists source and target paths. A change that is not a direct copy must be justified by one of: authentication/ownership, Cookie/CSRF, API envelope, UUID, private attachments, attempt/lease, `succeeded`, existing RBAC Shell, warm token, or redaction.
- Retain the existing RBAC `DashboardShell`, authenticated user identity, user/role pages, mobile Drawer, `/api/agent/*` namespace, private attachment flow, and independent Worker process.
- Do not restore anonymous `/runs/*`, standalone `AppShell` ownership of the whole page, inline attachment contents, FastAPI-lifespan Worker startup, or destructive retry.
- Desktop sidebar: `[brand] [collapse button]` at top; Agent/Sessions in the scrollable middle; Users/Roles/Audit immediately above the real account footer; collapse state persists in localStorage; mobile retains Drawer behavior.
- Agent Loop user-visible content remains intact: Session list, composer, first-message attachments, multi-turn conversation, thought stream, final answer, steps, tools, events, timelines, run header/status, and diagnostics.
- All JSON APIs use the RBAC success envelope. SSE remains raw `text/event-stream`; errors must occur before streaming starts.
- User access is owner-only and foreign/missing resources are indistinguishable 404s. `super_admin` is audit-only and must see redacted data.
- The implementation follows TDD: each new regression test must be observed failing before the corresponding production change.

---

## File Map

| Source Agent Loop file | RBAC target | Direct copy | Mandatory adaptations |
|---|---|---|---|
| `backend/app/api/stream.py` | `backend/app/api/agent_stream.py` | replay/subscribe/catch-up/heartbeat logic | owner dependency, Origin validation, short DB sessions, `succeeded` |
| `backend/app/services/event_bus.py` | `backend/app/services/agent/event_bus.py` | bounded queues and subscription logic | publish only after transaction commit, PostgreSQL notification |
| `backend/app/services/background_worker.py` | `backend/app/services/agent/worker.py` | poll loop and semaphore lifecycle | DB claim, full-lifetime semaphore, leases, independent Worker |
| `backend/app/services/agent_loop.py` | `backend/app/services/agent/loop.py` | planner/tool/thought/answer behavior | attempts, private attachments, transaction boundaries, `succeeded` |
| `backend/app/repositories/run_repository.py` | `backend/app/repositories/agent_repository.py` | ordered queries/state intent | UUID, ownership, attempt association, no internal commits |
| `frontend/components/AppShell.tsx` | `frontend/src/components/layout/dashboard-shell.tsx`, `app-sidebar.tsx` | collapse/session-sidebar behavior | RBAC Shell, real user/account, Drawer |
| `frontend/components/HomepageSidebarList.tsx` | `frontend/src/components/agent/session-sidebar-list.tsx` | grouping/title/time/empty/active list | `/agent` links, paged owner sessions, warm tokens |
| `frontend/components/{ThoughtProcess,ThoughtTimeline,StepTimeline,EventStream,Landing*.tsx,RunHeader,RunStatus,DetailConversation}.tsx` | `frontend/src/components/agent/*` | component structures and helper calls | RBAC types, attempt IDs, safe/redacted payloads, Ant outer controls |
| `frontend/lib/{runStreamReducer,thoughtNarrative,typingAnimation,eventNarrative,agentMode}.ts` | `frontend/src/lib/*` | all pure logic | type imports, envelope fields, `succeeded`, attachment IDs |
| `frontend/hooks/{useRunEventStream,useTypingText}.ts` | `frontend/src/hooks/*` | event/reconnect/typing logic | target URL, source-compatible event normalization, bounded retry |
| `frontend/app/globals.css` | `frontend/src/app/agent-globals.css` | Agent component styles/animations | `--agent-*` and warm color tokens, no standalone shell selectors |
| `backend/tests/test_event_streaming.py` | `backend/tests/test_agent_stream.py` | event/replay/fan-out test scenarios | UUID, ownership, envelope/Origin |
| `frontend/{hooks,lib,components}/*.test.ts(x)` | `frontend/src/**/*.test.ts(x)` | test scenarios | Vitest, RBAC paths/status/types |

### Task 1: Normalize the Agent API and audit contracts

**Files:**
- Modify: `backend/app/api/agent.py`
- Modify: `backend/app/api/agent_audit.py`
- Modify: `backend/app/repositories/agent_repository.py`
- Modify: `backend/app/schemas/agent.py`
- Modify: `backend/tests/test_agent_api.py`
- Modify: `backend/tests/test_agent_audit.py`
- Source reference: `X:\01_agent_loop\backend\app\api\runs.py`
- Source reference: `X:\01_agent_loop\backend\app\repositories\run_repository.py`

**Direct-copy intent:** Preserve old ordered Session/run/step/event read semantics from `runs.py` and `RunRepository`; adapt only the route prefix, RBAC envelope, UUIDs, ownership, attempts, and audit redaction.

**Interfaces produced:**

```python
GET /api/agent/sessions/{session_id}/runs -> success(request, list[AgentRunResponse])
GET /api/agent/runs/{run_id}/steps -> success(request, list[AgentStepResponse])
GET /api/agent/runs/{run_id}/attempts/{attempt_id}/steps -> 404 unless attempt.run_id == run_id
GET /api/agent/audit/sessions/{session_id}/runs -> success(request, list[AgentRunResponse])
GET /api/agent/audit/runs/{run_id}/attempts -> success(request, AgentAttemptListResponse)
GET /api/agent/audit/runs/{run_id}/events?cursor=&page_size= -> success(request, {items, next_seq})
```

- [ ] **Step 1: Add failing API ownership and audit-shape tests**

```python
async def test_attempt_steps_return_404_when_attempt_is_not_for_the_owned_run(admin_client, csrf_headers):
    first_run, second_run = await create_two_owned_runs(admin_client, csrf_headers)
    attempt_id = (await admin_client.get(f"/api/agent/runs/{second_run}/attempts")).json()["data"]["items"][0]["id"]
    response = await admin_client.get(f"/api/agent/runs/{first_run}/attempts/{attempt_id}/steps")
    assert response.status_code == 404

async def test_audit_session_runs_and_cursor_events_have_real_shapes(super_admin_client, seeded_agent_run):
    runs = await super_admin_client.get(f"/api/agent/audit/sessions/{seeded_agent_run.session_id}/runs")
    events = await super_admin_client.get(f"/api/agent/audit/runs/{seeded_agent_run.id}/events?page_size=1")
    assert runs.json()["data"][0]["id"] == str(seeded_agent_run.id)
    assert set(events.json()["data"]) == {"items", "next_seq"}
```

- [ ] **Step 2: Verify the tests fail for the missing association/shape behavior**

Run: `python -m pytest tests/test_agent_api.py tests/test_agent_audit.py -k "attempt_steps_return or audit_session_runs" -v`  
Expected: FAIL because the attempt is queried by ID alone and the audit child routes do not exist.

- [ ] **Step 3: Copy query structure, then apply required ownership/attempt adaptation**

```python
# backend/app/repositories/agent_repository.py
async def get_steps_for_run_attempt(self, run_id: uuid.UUID, attempt_id: uuid.UUID) -> list[AgentStep] | None:
    attempt = await self.session.scalar(
        select(AgentRunAttempt).where(
            AgentRunAttempt.id == attempt_id,
            AgentRunAttempt.run_id == run_id,
        )
    )
    if attempt is None:
        return None
    return await self.list_steps(attempt.id)
```

Use the source repository's creation-order session-run query. Add the user route and granular audit child routes. When an attempt does not belong to the requested run, return `ApiError(status_code=404, code="RESOURCE_NOT_FOUND", message="运行尝试不存在")`. Do not add fake aggregate objects or `/admin` aliases.

- [ ] **Step 4: Define only response models that the backend actually returns**

```python
class AgentAuditCursorPage(BaseModel):
    items: list[AgentAuditEvent]
    next_seq: int | None
```

Keep audit session/run detail models flat. Add separate list responses for runs and attempts. Do not add `runs`, `attempts`, `steps`, or `events` to a detail schema unless the corresponding endpoint serializes it.

- [ ] **Step 5: Verify API and authorization regression tests**

Run: `python -m pytest tests/test_agent_api.py tests/test_agent_audit.py tests/test_agent_authorization.py -v`  
Expected: PASS; foreign/mismatched attempt resources return 404 and audit cursor shape is stable.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/agent.py backend/app/api/agent_audit.py backend/app/repositories/agent_repository.py backend/app/schemas/agent.py backend/tests/test_agent_api.py backend/tests/test_agent_audit.py
```

### Task 2: Restore source-compatible SSE event semantics and final answers

**Files:**
- Modify: `backend/app/schemas/agent.py`
- Modify: `backend/app/api/agent_stream.py`
- Modify: `backend/app/services/agent/loop.py`
- Modify: `frontend/src/types/agent.ts`
- Modify: `frontend/src/lib/agent-stream.ts`
- Modify: `frontend/src/lib/run-stream-reducer.ts`
- Modify: `frontend/src/hooks/use-run-event-stream.ts`
- Modify: `frontend/src/lib/run-stream-reducer.test.ts`
- Modify: `frontend/src/hooks/use-run-event-stream.test.ts`
- Modify: `backend/tests/test_agent_stream.py`
- Source reference: `X:\01_agent_loop\backend\app\api\stream.py`
- Source reference: `X:\01_agent_loop\frontend\lib\runStreamReducer.ts`
- Source reference: `X:\01_agent_loop\frontend\hooks\useRunEventStream.ts`
- Source reference: `X:\01_agent_loop\backend\tests\test_event_streaming.py`

**Direct-copy intent:** Copy the old stream encoder/replay protocol, reducer cases, event allow-list, and tests. Adapt only `run_succeeded -> succeeded`, RBAC event payload fields, ownership, and final-answer response type.

**Interfaces produced:**

```ts
type AgentStreamEvent = {
  seq: number;
  type: AgentStreamEventType;
  event_type: AgentStreamEventType;
  run_id: string;
  timestamp: string;
  created_at: string;
  payload: Record<string, unknown>;
};

type AgentRun = {
  // existing fields
  result: { final_answer?: string } | null;
};
```

- [ ] **Step 1: Copy source event/reducer tests and add RBAC terminal regressions**

```ts
it("persists answer_completed text for a replayed succeeded run", () => {
  const next = reduceRunStream(initialState, {
    seq: 9,
    type: "answer_completed",
    event_type: "answer_completed",
    run_id: "run-1",
    timestamp: "2026-07-25T00:00:00Z",
    created_at: "2026-07-25T00:00:00Z",
    payload: { stream_id: "answer-run-1", text: "历史最终答案" },
  });
  expect(next.answerText).toBe("历史最终答案");
  expect(next.run?.result?.final_answer).toBe("历史最终答案");
});

it("maps run_succeeded to a closed succeeded state", () => {
  const next = reduceRunStream(initialState, succeededEvent);
  expect(next.run?.status).toBe("succeeded");
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run src/lib/run-stream-reducer.test.ts src/hooks/use-run-event-stream.test.ts`  
Expected: FAIL because `answer_completed` does not persist text/result and `run_succeeded` is not recognized everywhere.

- [ ] **Step 3: Copy source compatibility aliases into the RBAC stream boundary**

```python
class AgentRunEventResponse(BaseModel):
    # existing fields
    @property
    def type(self) -> str:
        return self.event_type

    @property
    def timestamp(self) -> datetime:
        return self.created_at
```

Serialize `type` and `timestamp` in SSE JSON while retaining `event_type` and `created_at`. Add actual emitted names to the frontend event union/list: `run_succeeded`, `run_cancel_requested`, and `visible_thought_paused`.

- [ ] **Step 4: Copy reducer final-answer behavior and adapt status names**

```ts
case "answer_completed": {
  const finalText = readText(event.payload, "text") ?? state.answerText;
  return {
    ...state,
    lastSeq: event.seq,
    events: appendEvent(state.events, event),
    answerText: finalText,
    run: setRunFinalAnswer(state.run, finalText),
  };
}
case "run_succeeded":
  return { ...state, lastSeq: event.seq, events: appendEvent(state.events, event), run: setRunStatus(state.run, "succeeded"), connection: "closed" };
```

Keep source delta/offset/stream ID behavior unchanged. In `parseStreamEvent`, normalize a backend event missing aliases into `{type: event.event_type, timestamp: event.created_at}` as defense-in-depth.

- [ ] **Step 5: Copy and adapt source SSE race tests**

Migrate source fan-out, replay -> subscribe -> catch-up, `Last-Event-ID` precedence, `after_seq`, heartbeat, and terminal-final-catch-up test cases into `backend/tests/test_agent_stream.py`. Adapt client authentication/Origin and UUID fixtures, but retain source ordering assertions.

- [ ] **Step 6: Verify GREEN**

Run: `python -m pytest tests/test_agent_stream.py -v; npm test -- --run src/lib/run-stream-reducer.test.ts src/hooks/use-run-event-stream.test.ts`  
Expected: PASS; a replayed final answer renders after reload and terminal streams close without reconnecting.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/agent.py backend/app/api/agent_stream.py backend/app/services/agent/loop.py backend/tests/test_agent_stream.py frontend/src/types/agent.ts frontend/src/lib/agent-stream.ts frontend/src/lib/run-stream-reducer.ts frontend/src/lib/run-stream-reducer.test.ts frontend/src/hooks/use-run-event-stream.ts frontend/src/hooks/use-run-event-stream.test.ts
```

### Task 3: Copy the complete Session sidebar behavior into the RBAC shell

**Files:**
- Create: `frontend/src/components/agent/session-sidebar-list.tsx`
- Create: `frontend/src/components/agent/session-sidebar-list.test.tsx`
- Create: `frontend/src/lib/agent-session-store.ts`
- Modify: `frontend/src/components/layout/dashboard-shell.tsx`
- Modify: `frontend/src/components/layout/app-sidebar.tsx`
- Modify: `frontend/src/app/globals.css`
- Modify: `frontend/src/app/agent-globals.css`
- Modify: `frontend/src/app/(agent)/agent/page.tsx`
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`
- Source reference: `X:\01_agent_loop\frontend\components\AppShell.tsx`
- Source reference: `X:\01_agent_loop\frontend\components\HomepageSidebarList.tsx`
- Source reference: `X:\01_agent_loop\frontend\app\globals.css`

**Direct-copy intent:** Copy `HomepageSidebarList` grouping/title/time/empty/active list behavior verbatim into a target component. Copy desktop collapse state from `AppShell`; replace only the standalone shell with `DashboardShell`, old links with `/agent/*`, static user footer with RBAC account footer, and colors with warm tokens.

**Interfaces produced:**

```ts
export function useAgentSessionStore(): {
  sessions: AgentSession[];
  loading: boolean;
  hasMore: boolean;
  refresh: () => Promise<void>;
  loadMore: () => Promise<void>;
};

export function invalidateAgentSessions(): void;
```

- [ ] **Step 1: Copy old sidebar tests into a new failure suite**

```tsx
it("groups sessions by update month and highlights the active session", async () => {
  render(<SessionSidebarList sessions={sessions} activeSessionId="session-2" />);
  expect(screen.getByText("2026-07")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "最新会话" })).toHaveAttribute("href", "/agent/sessions/session-2");
});

it("keeps management navigation above the account footer and Agent sessions in the middle", () => {
  render(<DashboardShell currentUser={superAdmin}><div /></DashboardShell>);
  expect(screen.getByText("用户管理").compareDocumentPosition(screen.getByText("超级管理员"))).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run src/components/agent/session-sidebar-list.test.tsx "src/app/(agent)/agent/agent-routes.test.tsx"`  
Expected: FAIL because no copied Session list/store exists and the current submenu has no grouping/refresh behavior.

- [ ] **Step 3: Copy `HomepageSidebarList` as the target Session list**

Copy the source grouping code, `toGroupLabel`, `useMemo`, title fallback, empty state, selected state, and update timestamp. Replace source `<a href="/sessions/...">` with `next/link` to `/agent/sessions/${session.id}`. Add a warm-token class only where source blue styles conflict.

```tsx
export default function SessionSidebarList({ sessions, activeSessionId, onNavigate }: Props) {
  const groupedSessions = useMemo(() => groupSessionsByMonth(sessions), [sessions]);
  return <div className="agent-session-sidebar-list">{/* copied source list structure */}</div>;
}
```

- [ ] **Step 4: Copy AppShell collapse semantics into `DashboardShell`**

```tsx
const STORAGE_KEY = "agent-loop-sidebar";
const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(true);

useEffect(() => setDesktopSidebarOpen(localStorage.getItem(STORAGE_KEY) !== "closed"), []);
function toggleDesktopSidebar() {
  setDesktopSidebarOpen((open) => {
    localStorage.setItem(STORAGE_KEY, open ? "closed" : "open");
    return !open;
  });
}
```

Render `[brand][collapse button]` in the Sider header. Keep the mobile Drawer unchanged. When collapsed on desktop, animate the Sider out, make content full-width, and render a fixed expand button at content top-left.

- [ ] **Step 5: Arrange the fixed sidebar regions**

Render the Agent Session area in the flex-growing middle section. Render user/role/audit entries as individual fixed items immediately above the account footer. The Agent list owns scroll overflow; management navigation and account footer never scroll with sessions. Add a `/agent` new-conversation link above Session groups and a load-more button when `hasMore`.

- [ ] **Step 6: Add shared refresh/invalidation**

`invalidateAgentSessions()` dispatches an `agent-sessions-invalidated` browser event. `useAgentSessionStore` listens for it and refetches page 1. Call it after `createSession`, after successful continuation run creation, and after successful initial attachment-to-run creation. Do not copy the source three-second `AutoRefresh` full-page reload.

- [ ] **Step 7: Verify GREEN**

Run: `npm test -- --run src/components/agent/session-sidebar-list.test.tsx "src/app/(agent)/agent/agent-routes.test.tsx" src/components/layout/dashboard-shell.test.tsx`  
Expected: PASS; grouping, active state, empty state, load-more, fixed management links, footer ordering, and collapse persistence pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/agent/session-sidebar-list.tsx frontend/src/components/agent/session-sidebar-list.test.tsx frontend/src/lib/agent-session-store.ts frontend/src/components/layout/dashboard-shell.tsx frontend/src/components/layout/app-sidebar.tsx frontend/src/app/globals.css frontend/src/app/agent-globals.css "frontend/src/app/(agent)/agent/page.tsx" "frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx" "frontend/src/app/(agent)/agent/agent-routes.test.tsx"
```

### Task 4: Restore first-message attachment flow from Agent Loop composer

**Files:**
- Modify: `frontend/src/components/agent/attachment-input.tsx`
- Modify: `frontend/src/components/agent/new-conversation-composer.tsx`
- Modify: `frontend/src/app/(agent)/agent/page.tsx`
- Modify: `frontend/src/lib/agent-api.ts`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`
- Create: `frontend/src/app/(agent)/agent/agent-page.test.tsx`
- Source reference: `X:\01_agent_loop\frontend\components\AttachmentInput.tsx`
- Source reference: `X:\01_agent_loop\frontend\components\NewConversationComposer.tsx`
- Source reference: `X:\01_agent_loop\frontend\app\sessions\page.tsx`

**Direct-copy intent:** Copy old local file-selection behavior, limits, file labels, and composer interaction. Replace inline `file.text()` payloads with the mandatory RBAC sequence Session -> multipart upload -> attachment IDs -> Run.

- [ ] **Step 1: Write first-message attachment flow tests**

```tsx
it("creates a session, uploads selected files, then creates the first run with attachment IDs", async () => {
  render(<AgentPage />);
  await user.upload(screen.getByLabelText("添加附件"), new File(["report"], "report.txt", { type: "text/plain" }));
  await user.type(screen.getByPlaceholderText("给 Agent Loop 发送消息"), "请总结附件");
  await user.click(screen.getByRole("button", { name: "发送消息" }));
  await waitFor(() => expect(agentApi.createSession).toHaveBeenCalledOnce());
  expect(agentApi.uploadAttachment).toHaveBeenCalledWith("session-1", expect.any(FormData));
  expect(agentApi.createRun).toHaveBeenCalledWith("session-1", expect.objectContaining({ attachment_ids: ["attachment-1"] }));
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run "src/app/(agent)/agent/agent-page.test.tsx" src/components/agent/agent-streaming.test.tsx`  
Expected: FAIL because the root composer hides attachment input without a session ID.

- [ ] **Step 3: Copy file selection UI and split selection from upload**

Copy source `AttachmentInput` selection UX into a `selectedFiles` controlled mode:

```ts
type PendingAttachment = { file: File; key: string };
type AttachmentInputProps = {
  sessionId?: string;
  pendingFiles?: PendingAttachment[];
  onPendingFilesChange?: (files: PendingAttachment[]) => void;
  onUploaded?: (ids: string[]) => void;
};
```

When `sessionId` is missing, select and display files only. When `sessionId` exists, upload as current RBAC behavior. Keep source limits (five files, two MB per file), but use server validation as the authority.

- [ ] **Step 4: Copy source session action order and adapt to private uploads**

```ts
const session = await agentApi.createSession(goal.slice(0, 80));
const attachmentIds = await Promise.all(
  pendingFiles.map(async ({ file }) => agentApi.uploadAttachment(session.id, toFormData(file)).then((attachment) => attachment.id))
);
await agentApi.createRun(session.id, { goal, mode, network_enabled: true, attachment_ids: attachmentIds });
invalidateAgentSessions();
router.push(`/agent/sessions/${session.id}`);
```

On session/upload/run failure retain the goal and pending files; show a phase-specific alert. Do not call `File.text()` or transmit attachment contents in JSON.

- [ ] **Step 5: Verify GREEN**

Run: `npm test -- --run "src/app/(agent)/agent/agent-page.test.tsx" src/components/agent/agent-streaming.test.tsx`  
Expected: PASS; first and follow-up messages both retain Agent Loop selection UX while using RBAC private upload IDs.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/agent/attachment-input.tsx frontend/src/components/agent/new-conversation-composer.tsx "frontend/src/app/(agent)/agent/page.tsx" frontend/src/lib/agent-api.ts frontend/src/components/agent/agent-streaming.test.tsx "frontend/src/app/(agent)/agent/agent-page.test.tsx"
```

### Task 5: Copy all retained Agent diagnostics into Session pages

**Files:**
- Create: `frontend/src/components/agent/{detail-conversation,event-stream,event-narrative,landing-event-stream,landing-run-event-timeline,selected-run-event-stream,run-header,run-status,step-timeline,thought-process,thought-timeline}.tsx`
- Create: `frontend/src/components/agent/run-diagnostics.test.tsx`
- Modify: `frontend/src/components/agent/session-conversation-stream.tsx`
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`
- Modify: `frontend/src/lib/agent-api.ts`
- Modify: `frontend/src/types/agent.ts`
- Modify: `frontend/src/app/agent-globals.css`
- Source reference: `X:\01_agent_loop\frontend\components\{DetailConversation,EventStream,eventNarrative,LandingEventStream,LandingRunEventTimeline,LandingSelectedRunEventStream,RunHeader,RunStatus,StepTimeline,ThoughtProcess,ThoughtTimeline}.tsx`
- Source reference: `X:\01_agent_loop\frontend\app\sessions\[id]\page.tsx`

**Direct-copy intent:** Copy every listed source diagnostic component before changes. Adapt imports, `completed -> succeeded`, route/API calls, attempt fields, private/redacted values, and Ant controls only where source controls do not fit the RBAC shell.

**Interfaces produced:**

```ts
export type AgentStep = {
  id: string;
  attempt_id: string;
  step_number: number;
  thought_summary: string | null;
  action_type: string | null;
  action_payload: Record<string, unknown> | null;
  observation: Record<string, unknown> | null;
  status: string;
  created_at: string;
};

agentApi.getRunAttempts(runId): Promise<PaginatedResponse<AgentRunAttempt>>
agentApi.getAttemptSteps(runId, attemptId, page, pageSize): Promise<PaginatedResponse<AgentStep>>
```

- [ ] **Step 1: Copy source component tests and add a complete diagnostics fixture**

```tsx
it("renders copied run header, status, thought timeline, steps, tools, and cursor-loaded event stream", async () => {
  render(<DetailConversation run={succeededRun} attempts={[attempt]} steps={[step]} events={[event]} />);
  expect(screen.getByText("已完成")).toBeInTheDocument();
  expect(screen.getByText("工具调用")).toBeInTheDocument();
  expect(screen.getByText("步骤 1")).toBeInTheDocument();
  expect(screen.getByText("run_succeeded")).toBeInTheDocument();
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run src/components/agent/run-diagnostics.test.tsx`  
Expected: FAIL because the retained source diagnostic modules do not exist in RBAC.

- [ ] **Step 3: Copy source files one-for-one**

Copy each source file into the named target. Preserve component hierarchy, labels, event narrative mappings, expand/collapse behavior, and CSS classes. Apply only these changes:

```text
@/lib/api                    -> @/types/agent and @/lib/agent-api
completed                    -> succeeded
run_id-based Step            -> attempt_id-based AgentStep
old raw event API            -> agentApi cursor methods
raw observation/tool payload -> owner-safe or audit-redacted payload
```

Do not replace diagnostic components with generic Ant Tables. Ant `Collapse`, `Button`, and `Tag` may wrap copied content where needed for accessibility, but copied information hierarchy remains visible.

- [ ] **Step 4: Compose copied diagnostics into the existing session conversation**

Load attempts, current/latest attempt steps, initial events, and paged historical events for every run in creation order. Terminal and active runs both start with REST events/steps; SSE adds deltas only for the latest active run. Use the copied `DetailConversation` inside `SessionConversationStream`, so the user sees the same Agent Loop diagnostic content below the normal thought/final-answer content.

- [ ] **Step 5: Restore complete structured step payloads in the API client**

Do not reduce step payloads to anonymous `{step_index,...}` objects. Map the RBAC fields into the new explicit `AgentStep` type, preserving action payload, JSON observation, timestamps, and attempt ID. The backend type change in Task 7 ensures observation is structured JSON.

- [ ] **Step 6: Copy missing styles**

Copy all styles used by the retained source diagnostic components from `X:\01_agent_loop\frontend\app\globals.css` into `frontend/src/app/agent-globals.css`. Keep original layout/spacing/animation selectors; replace only old generic variables with `--agent-*` or existing warm tokens. Do not import source `.app-shell`, `.sidebar`, `.workspace`, or global `html/body` rules.

- [ ] **Step 7: Verify GREEN**

Run: `npm test -- --run src/components/agent/run-diagnostics.test.tsx src/components/agent/agent-streaming.test.tsx; npm run build`  
Expected: PASS and build succeeds; user Session pages display all copied diagnostics without changing RBAC shell navigation.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/agent frontend/src/app/agent-globals.css "frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx" frontend/src/lib/agent-api.ts frontend/src/types/agent.ts
```

### Task 6: Align audit pages with real granular audit APIs

**Files:**
- Modify: `frontend/src/lib/agent-api.ts`
- Modify: `frontend/src/app/(agent)/agent/audit/page.tsx`
- Modify: `frontend/src/app/(agent)/agent/audit/sessions/[sessionId]/page.tsx`
- Modify: `frontend/src/app/(agent)/agent/audit/runs/[runId]/page.tsx`
- Create: `frontend/src/app/(agent)/agent/audit/audit-pages.test.tsx`
- Source reference: `X:\01_agent_loop\frontend\components\{EventStream,RunHeader,RunStatus,StepTimeline}.tsx`
- RBAC reference: `backend/app/api/agent_audit.py`

**Direct-copy intent:** Reuse copied diagnostics from Task 5. The only adaptations are real `/audit` paths, cursor pagination, super-admin-only access, and redacted fields.

- [ ] **Step 1: Write failing audit contract tests**

```tsx
it("loads audit session runs through the real audit endpoint", async () => {
  render(<AuditSessionPage params={Promise.resolve({ sessionId: "session-1" })} />);
  await waitFor(() => expect(agentApi.listAuditSessionRuns).toHaveBeenCalledWith("session-1"));
});

it("loads later audit events with next_seq instead of repeating page one", async () => {
  render(<AuditRunPage params={Promise.resolve({ runId: "run-1" })} />);
  await user.click(screen.getByRole("button", { name: "加载更多事件" }));
  expect(agentApi.getAuditRunEvents).toHaveBeenLastCalledWith("run-1", 37, 50);
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run "src/app/(agent)/agent/audit/audit-pages.test.tsx"`  
Expected: FAIL because current API client calls `/admin` and expects non-existent aggregate shapes.

- [ ] **Step 3: Replace fake aggregate client declarations with granular methods**

```ts
listAuditSessionRuns: (sessionId: string) => api<AgentRun[]>(`/api/agent/audit/sessions/${sessionId}/runs`),
getAuditRunAttempts: (runId: string) => api<PaginatedResponse<AgentRunAttempt>>(`/api/agent/audit/runs/${runId}/attempts`),
getAuditAttemptSteps: (runId: string, attemptId: string, page = 1, pageSize = 50) => api<PaginatedResponse<AgentStep>>(`/api/agent/audit/runs/${runId}/attempts/${attemptId}/steps?page=${page}&page_size=${pageSize}`),
getAuditRunEvents: (runId: string, cursor?: number, pageSize = 50) => api<{ items: AgentRunEvent[]; next_seq: number | null }>(`/api/agent/audit/runs/${runId}/events?${new URLSearchParams({ ...(cursor ? { cursor: String(cursor) } : {}), page_size: String(pageSize) })}`),
```

Remove every `/api/agent/admin` path. Pages compose the returned data and pass it to copied Task 5 diagnostics. Never create `EventSource` for audit routes.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --run "src/app/(agent)/agent/audit/audit-pages.test.tsx" "src/app/(agent)/agent/agent-routes.test.tsx"`  
Expected: PASS; no `/admin` request, cursor advances, and audit fields remain redacted.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/agent-api.ts "frontend/src/app/(agent)/agent/audit" 
```

### Task 7: Repair attempt persistence and Worker reliability

**Files:**
- Create: `backend/alembic/versions/<revision>_agent_attempt_schedule_and_observation.py`
- Modify: `backend/app/models/agent.py`
- Modify: `backend/app/repositories/agent_repository.py`
- Modify: `backend/app/services/agent/loop.py`
- Modify: `backend/app/services/agent/worker.py`
- Modify: `backend/app/services/agent/event_bus.py`
- Modify: `backend/app/db/session.py`
- Modify: `backend/tests/test_agent_repository.py`
- Modify: `backend/tests/test_agent_worker.py`
- Modify: `backend/tests/test_agent_loop.py`
- Source reference: `X:\01_agent_loop\backend\app\services\{agent_loop,background_worker,event_bus}.py`
- Source reference: `X:\01_agent_loop\backend\app\repositories\run_repository.py`

**Direct-copy intent:** Preserve source polling, semaphore, retry-backoff calculation, worker lifecycle, event persistence ordering, and loop behavior. Adapt only PostgreSQL claim/lease/attempt semantics and remove source destructive retries.

**Interfaces produced:**

```python
class AgentRunAttempt(Base):
    not_before: Mapped[datetime | None]

class AgentStep(Base):
    observation: Mapped[dict[str, Any] | None] = mapped_column(JSON)

async def AgentRepository.claim_next_attempt(worker_id: str) -> AgentRunAttempt | None:
    """Atomically claim the oldest queued attempt whose not_before is due."""

async def AgentRepository.recover_expired_attempts(now: datetime | None = None) -> int:
    """Fail expired attempts and schedule one immutable replacement when retry budget remains."""

async def AgentRepository.schedule_retry_attempt(
    run: AgentRun, failed_attempt: AgentRunAttempt, error: str
) -> AgentRunAttempt:
    """Persist a queued retry attempt with exponential-backoff not_before time."""
```

- [ ] **Step 1: Write failing concurrency/lease/retry/observation tests**

```python
async def test_worker_renews_lease_while_process_attempt_is_running(worker, long_running_loop, queued_attempt):
    await worker.process_claimed_attempt(queued_attempt.id)
    assert long_running_loop.observed_lease_extensions >= 1

async def test_expired_attempt_creates_delayed_replacement_attempt(session, expired_attempt):
    await AgentRepository(session).recover_expired_attempts(now=datetime.now(UTC))
    attempts = await AgentRepository(session).list_attempts(expired_attempt.run_id)
    assert len(attempts) == 2
    assert attempts[-1].status == "queued"
    assert attempts[-1].not_before is not None

async def test_step_observation_round_trips_as_json(session, attempt):
    step = await AgentRepository(session).add_step(attempt.id, 1, "think", "calculator", {}, {"value": 42}, "succeeded")
    assert step.observation == {"value": 42}
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_agent_worker.py tests/test_agent_repository.py tests/test_agent_loop.py -k "renews_lease or expired_attempt_creates or observation_round" -v`  
Expected: FAIL because leases are not renewed, recovery does not enqueue an attempt, and observation is Text.

- [ ] **Step 3: Migrate source retry backoff into attempt scheduling**

Copy the source `schedule_retry()` delay calculation:

```python
delay_seconds = min(
    settings.retry_backoff_base_seconds * (2 ** max(retry_number - 1, 0)),
    settings.retry_backoff_max_seconds,
)
```

Create a new immutable queued attempt with `not_before=now + timedelta(seconds=delay_seconds)`. Update `claim_next_attempt()` to filter `not_before IS NULL OR not_before <= now`. Do not mutate or delete the failed attempt.

- [ ] **Step 4: Make Worker concurrency and leases cover full execution**

Copy source semaphore intent, but hold it around `_process_attempt` rather than only claim creation:

```python
async with self._semaphore:
    renewal = asyncio.create_task(self._renew_lease_until_finished(attempt_id))
    try:
        await self._loop.process_attempt(attempt_id, self.worker_id)
    finally:
        renewal.cancel()
        with suppress(asyncio.CancelledError):
            await renewal
```

`_renew_lease_until_finished` sleeps `max(1, worker_lease_seconds // 3)` seconds, opens its own short session, calls `renew_lease`, and exits when renewal returns false.

- [ ] **Step 5: Publish events only after commit**

Use `AsyncSession` transaction lifecycle in the loop service:

```python
pending_events.append(PersistedEvent(run_id=event.run_id, seq=event.seq))
await session.commit()
for event in pending_events:
    await agent_event_bus.publish_after_commit(event)
```

Call the existing PostgreSQL notification helper only after commit. Keep DB replay as the source of truth; a missed notification must never lose an event.

- [ ] **Step 6: Create and verify migration**

Run: `alembic revision --autogenerate -m "agent attempt schedule and observation"` from `backend`.

Review the revision: change `agent_steps.observation` to JSON/JSONB and add nullable `agent_run_attempts.not_before` plus queue index `(status, not_before, created_at)`. Do not modify RBAC tables.

Run: `alembic upgrade head; python -m pytest tests/test_agent_worker.py tests/test_agent_repository.py tests/test_agent_loop.py -v`  
Expected: PASS; old source retry semantics are preserved without destructive history.

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions backend/app/models/agent.py backend/app/repositories/agent_repository.py backend/app/services/agent/loop.py backend/app/services/agent/worker.py backend/app/services/agent/event_bus.py backend/app/db/session.py backend/tests/test_agent_repository.py backend/tests/test_agent_worker.py backend/tests/test_agent_loop.py
```

### Task 8: Port remaining Agent Loop utility and component tests

**Files:**
- Create: `frontend/src/hooks/use-typing-text.test.ts`
- Create: `frontend/src/lib/typing-animation.test.ts`
- Create: `frontend/src/lib/thought-narrative.test.ts`
- Modify: `frontend/src/components/agent/agent-streaming.test.tsx`
- Modify: `frontend/src/lib/agent-api.test.ts`
- Modify: `backend/tests/test_agent_tools.py`
- Modify: `backend/tests/test_agent_loop.py`
- Source reference: `X:\01_agent_loop\frontend\hooks\useTypingText.test.ts`
- Source reference: `X:\01_agent_loop\frontend\lib\{typingAnimation,thoughtNarrative,api}.test.ts`
- Source reference: `X:\01_agent_loop\frontend\components\{AgentModeControls,NewConversationComposer,streamingUi}.test.tsx`
- Source reference: `X:\01_agent_loop\backend\tests\{test_agent_tools,test_llm_streaming}.py`

**Direct-copy intent:** Copy source tests first and change only imports, test runner syntax, RBAC event/status names, API envelope and private attachment expectations.

- [ ] **Step 1: Copy source tests without production changes**

Copy each named source test file to the target path. Convert Jest `describe/it/expect` imports to Vitest only. Preserve source assertions for punctuation typing, visible thought block generation, mode behavior, composer submit keys, safe markdown, tool sanitization, planner policy, checkpoints, and final answer failure.

- [ ] **Step 2: Run copied tests to identify adaptation deltas**

Run: `npm test -- --run src/hooks/use-typing-text.test.ts src/lib/typing-animation.test.ts src/lib/thought-narrative.test.ts src/components/agent/agent-streaming.test.tsx; python -m pytest tests/test_agent_tools.py tests/test_agent_loop.py -v`  
Expected: initially fail only on import paths, `completed -> succeeded`, API envelope fields, or private attachment behavior.

- [ ] **Step 3: Apply only expected test adaptations**

Replace:

```text
completed -> succeeded
web_enabled -> network_enabled
inline attachment content -> attachment ID / extracted context
old /runs paths -> /api/agent paths
Jest imports -> Vitest imports
```

Do not weaken source assertions. Add explicit tests for source-compatible final-answer replay, first-message attachments, `run_succeeded`, and audit redaction.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --run; python -m pytest tests/test_agent_tools.py tests/test_agent_loop.py tests/test_agent_stream.py -v`  
Expected: PASS; all copied source behavior is protected by RBAC-adapted tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/use-typing-text.test.ts frontend/src/lib/typing-animation.test.ts frontend/src/lib/thought-narrative.test.ts frontend/src/components/agent/agent-streaming.test.tsx frontend/src/lib/agent-api.test.ts backend/tests/test_agent_tools.py backend/tests/test_agent_loop.py
```

### Task 9: Full migration validation and operations update

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-25-agent-loop-parity-repair-design.md` only if implementation requires an approved correction
- Create: `backend/tests/test_agent_parity_e2e.py`
- Create: `frontend/src/app/(agent)/agent/agent-parity.e2e.test.tsx`

**Interfaces:**
- Consumes all prior tasks.
- Produces an end-to-end parity test checklist and operator documentation for the restored Agent experience.

- [ ] **Step 1: Write end-to-end parity tests**

```python
async def test_owned_user_can_create_session_upload_first_attachment_enqueue_run_and_read_diagnostics(client, csrf_headers):
    session = await client.post("/api/agent/sessions", json={"title": "报告"}, headers=csrf_headers)
    attachment = await client.post(f"/api/agent/sessions/{session.json()['data']['id']}/attachments", files={"file": ("report.txt", b"data", "text/plain")}, headers=csrf_headers)
    run = await client.post(f"/api/agent/sessions/{session.json()['data']['id']}/runs", json={"goal": "总结", "mode": "quick", "attachment_ids": [attachment.json()['data']['id']]}, headers=csrf_headers)
    assert (await client.get(f"/api/agent/sessions/{session.json()['data']['id']}/runs")).status_code == 200
    assert (await client.get(f"/api/agent/runs/{run.json()['data']['id']}/steps")).status_code == 200
```

```tsx
it("keeps the full Agent Loop flow visible inside the RBAC shell", async () => {
  render(<AgentSessionPage />);
  expect(await screen.findByText("思考过程")).toBeInTheDocument();
  expect(screen.getByText("事件流")).toBeInTheDocument();
  expect(screen.getByText("步骤时间线")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run end-to-end tests and fix only integration defects**

Run: `python -m pytest tests/test_agent_parity_e2e.py -v; npm test -- --run "src/app/(agent)/agent/agent-parity.e2e.test.tsx"`  
Expected: PASS; all active Agent Loop behavior is reachable through RBAC boundaries.

- [ ] **Step 3: Update operations documentation**

Document the canonical routes and behavior:

```text
/agent                         Session home, first-message attachment flow
/agent/sessions/{id}           Multi-turn Agent Loop conversation and diagnostics
/agent/audit                   Super-admin redacted diagnostics
python -m app.workers.agent_worker
python -m app.workers.agent_maintenance
```

State the desktop sidebar persists `agent-loop-sidebar`, mobile uses Drawer, event streams need proxy buffering disabled, and attempts are immutable/retried through leases.

- [ ] **Step 4: Run final quality gates**

Run: `alembic upgrade head; python -m pytest -q` from `backend`  
Expected: all Agent and existing RBAC tests pass.

Run: `npm test -- --run; npm run build` from `frontend`  
Expected: all Vitest tests pass and Next production build exits 0.

Run: `git diff --check; git status --short` from repository root  
Expected: no whitespace errors; no uncommitted generated storage/test artifacts are staged.

- [ ] **Step 5: Commit**

```bash
git add README.md backend/tests/test_agent_parity_e2e.py "frontend/src/app/(agent)/agent/agent-parity.e2e.test.tsx"
```

## Plan Self-Review

### Spec coverage

| Specification requirement | Task coverage |
|---|---|
| Direct-copy-first migration rule and source/target traceability | Global constraints, file map, Tasks 1-9 |
| Session sidebar placement, grouping, refresh, collapse, Drawer | Task 3 |
| First-message and follow-up private attachments | Task 4 and Task 9 |
| Full Agent Loop diagnostics/components/styles | Task 5 |
| SSE replay, aliases, final answer, event ordering | Task 2 |
| Audit real API contract and redaction | Tasks 1 and 6 |
| Worker leases, retry delay, commit publication, attempt history | Task 7 |
| Resource association and owner isolation | Task 1 |
| Source test migration and RBAC regression coverage | Tasks 2, 3, 7, 8, 9 |
| Backend/frontend/build/migration verification | Task 9 |

### Placeholder scan

No unresolved implementation placeholders exist. Alembic revision filename is intentionally generated by Alembic; its required schema changes and validation commands are explicit in Task 7.

### Type consistency

- `AgentStep` becomes the shared explicit frontend diagnostic type before Tasks 5-6 consume it.
- User and audit API paths use `/api/agent/*` and `/api/agent/audit/*` consistently.
- Event cursor field is `after_seq` for user events and `cursor`/`next_seq` for audit events, matching their backend contracts.
- Terminal run status is `succeeded`; source `completed` appears only as a migration instruction.
