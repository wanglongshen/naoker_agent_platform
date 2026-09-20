# Enterprise AI Workspace Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the complete application into 企业智助, a beautiful and restrained private ChatGPT workspace with unified warm visual design, permission-aware administration, and organization-wide conversation oversight for the highest administrator.

**Architecture:** Establish one token-driven Warm Intelligence design system shared by custom CSS and Ant Design, then rebuild the shell and chat around reusable semantic components. Add an administrator-only audit transcript contract so governance reads like a conversation rather than infrastructure JSON, while retaining diagnostics as a secondary layer. Complete the rollout by aligning users, roles, login, permissions, accessibility, and responsive behavior.

**Tech Stack:** Next.js 16, React 19, TypeScript, Ant Design 6, React Markdown, Vitest/React Testing Library, FastAPI, SQLAlchemy Async, Pydantic, pytest/httpx.

## Global Constraints

- Implementation target: `C:\01_agent_loop`; reference projects are read-only.
- Product name is exactly `企业智助` on login, metadata, shell, sidebar, and user-visible product copy.
- Visual direction is Warm Intelligence: deep coffee sidebar, warm white canvas, restrained amber primary actions, and semantic blue/green/yellow/red statuses.
- Light theme only; do not add a dark-theme switch or remote font dependency.
- All authenticated roles land on `/agent`; the highest administrator no longer lands on `/users`.
- Ordinary users can access only their own sessions; backend authorization remains authoritative.
- The highest administrator directly views all users' conversations through governance without confirmation or reason entry.
- Governance UI must not display `特权访问 · 自动留痕` or equivalent wording.
- Thought, search, and tool details are expanded by default, but users may collapse them accessibly.
- Completed AI answer actions contain copy only; do not add regenerate, feedback, export, or source buttons.
- Composer behavior is Enter to send, Shift+Enter for newline, and no submission during IME composition.
- Preserve current streaming, historical-answer, reconnect, Markdown-safety, and richer-answer reconciliation behavior.
- Raw Markdown HTML stays disabled; do not add `rehype-raw`.
- Use breakpoints `640`, `768`, `960`, and `1200` only for new responsive rules.
- `C:\01_agent_loop` has no Git metadata. Do not run commit commands; write RED/GREEN evidence to `.superpowers/sdd/enterprise-ai-redesign-task-N-report.md`.

---

## File Structure And Responsibilities

### New Shared Frontend Units

- `frontend/src/components/layout/app-shell.tsx`: viewport shell, responsive navigation, semantic `<main>`, collapse behavior.
- `frontend/src/components/layout/conversation-top-bar.tsx`: session title, mode, privacy state, sidebar trigger.
- `frontend/src/components/agent/chat-composer.tsx`: shared landing/detail composer with mode, attachments, keyboard behavior, and send state.
- `frontend/src/components/agent/answer-actions.tsx`: copy-only answer action and copied feedback.
- `frontend/src/components/governance/governance-transcript.tsx`: administrator conversation transcript using existing conversation presentation units.
- `frontend/src/components/ui/page-header.tsx`: management/governance title, description, and one primary action.
- `frontend/src/components/ui/data-surface.tsx`: semantic bordered data/table surface with focusable horizontal overflow.
- `frontend/src/components/ui/view-states.tsx`: `PageLoading`, `PageError`, `EmptyState`, `InlineAlert`.
- `frontend/src/lib/audit-session-view.ts`: frontend audit transcript loader and response normalization.

### Backend Contract Additions

- `backend/app/schemas/agent.py`: audit transcript owner/session/turn response schemas.
- `backend/app/api/agent_audit.py`: administrator transcript endpoint and human-readable owner identity.

### Existing Units To Consolidate

- `frontend/src/components/layout/dashboard-shell.tsx`: migrate callers to `AppShell`, then retain a compatibility export only if tests/routes still import it.
- `frontend/src/components/layout/app-sidebar.tsx`: unified navigation, governance group, account block.
- `frontend/src/components/agent/new-conversation-composer.tsx`: reduce to a `ChatComposer` wrapper or remove after callers migrate.
- `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`: docked composer and conversation top bar.
- `frontend/src/components/agent/thought-narrative.tsx`: expanded-by-default accessible process timeline.
- `frontend/src/components/agent/final-answer-panel.tsx`: retain Markdown behavior and add copy-only action.
- `frontend/src/components/ui/ant-design-provider.tsx`: consume shared design tokens.
- `frontend/src/app/globals.css` and `frontend/src/app/agent-globals.css`: consolidate token use and route styling without global focus suppression.

---

### Task 1: Establish The Warm Intelligence Design System And Product Brand

**Files:**
- Modify: `C:\01_agent_loop\frontend\src\app\globals.css`
- Modify: `C:\01_agent_loop\frontend\src\app\agent-globals.css`
- Modify: `C:\01_agent_loop\frontend\src\components\ui\ant-design-provider.tsx`
- Modify: `C:\01_agent_loop\frontend\src\lib\copy.ts`
- Modify: `C:\01_agent_loop\frontend\src\app\layout.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\globals.test.ts`
- Modify: `C:\01_agent_loop\frontend\src\localization.test.ts`

**Interfaces:**
- Produces CSS tokens under `:root` with exact names from the specification.
- Produces `PRODUCT_NAME = "企业智助"` and product copy consumed by shell/login/chat tasks.
- Produces Ant Design theme tokens using the same CSS values rather than a competing palette.

- [ ] **Step 1: Add failing brand and token contract tests**

In `globals.test.ts`, read `globals.css` and assert all required values exist:

```ts
expect(css).toContain("--color-bg-app: #FAF7F3");
expect(css).toContain("--color-sidebar: #2A1812");
expect(css).toContain("--color-primary: #D96313");
expect(css).toContain("--color-text-primary: #2B2521");
expect(css).toContain("--color-border: #E6DDD6");
expect(css).toContain("--bp-sm: 640px");
expect(css).toContain("--bp-md: 768px");
expect(css).not.toMatch(/textarea,\s*input,\s*button\s*\{[^}]*outline:\s*none/s);
```

In `localization.test.ts`, assert the product name and metadata no longer contain `权限管理系统` or `Agent Loop`:

```ts
expect(PRODUCT_NAME).toBe("企业智助");
expect(PRODUCT_SUBTITLE).toMatch(/私有|智能|组织/);
```

- [ ] **Step 2: Run tests and verify RED**

Run from `C:\01_agent_loop\frontend`:

```powershell
npm test -- --run src/app/globals.test.ts src/localization.test.ts
```

Expected: missing token/name assertions fail and the global focus reset assertion fails.

- [ ] **Step 3: Define the shared token system**

Replace the competing warm/agent root variable blocks with one `:root` contract in `globals.css`:

```css
:root {
  --color-bg-app: #FAF7F3;
  --color-bg-surface: #FFFFFF;
  --color-bg-subtle: #F7F2EE;
  --color-sidebar: #2A1812;
  --color-sidebar-elevated: #3B271F;
  --color-primary: #D96313;
  --color-primary-hover: #B94F0C;
  --color-primary-soft: #FFF0E4;
  --color-text-primary: #2B2521;
  --color-text-secondary: #71645C;
  --color-text-muted: #8E7F76;
  --color-border: #E6DDD6;
  --color-border-strong: #D5C8BE;
  --color-info: #4F64DC;
  --color-success: #21804C;
  --color-warning: #A66300;
  --color-danger: #C24141;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-pill: 999px;
  --shadow-sm: 0 3px 10px rgba(67, 42, 28, 0.06);
  --shadow-md: 0 12px 32px rgba(67, 42, 28, 0.09);
  --shadow-lg: 0 24px 64px rgba(42, 24, 18, 0.16);
  --bp-sm: 640px;
  --bp-md: 768px;
  --bp-lg: 960px;
  --bp-xl: 1200px;
}
```

Keep legacy `--agent-*` aliases temporarily only where necessary, mapping them to new tokens rather than retaining different values.

- [ ] **Step 4: Align Ant Design and product copy**

Set provider theme tokens to the shared values:

```tsx
const theme: ThemeConfig = {
  token: {
    colorPrimary: "#D96313",
    colorPrimaryHover: "#B94F0C",
    colorBgLayout: "#FAF7F3",
    colorBgContainer: "#FFFFFF",
    colorText: "#2B2521",
    colorTextSecondary: "#71645C",
    colorBorder: "#E6DDD6",
    borderRadius: 10,
    fontFamily: '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif',
  },
};
```

In `copy.ts` export:

```ts
export const PRODUCT_NAME = "企业智助";
export const PRODUCT_SUBTITLE = "组织专属的私有智能助手";
```

Use `PRODUCT_NAME` in root metadata.

- [ ] **Step 5: Restore universal focus and reduced motion foundations**

Remove the blanket outline reset and add:

```css
:where(a, button, input, textarea, select, [tabindex]):focus-visible {
  outline: 2px solid color-mix(in srgb, var(--color-primary) 72%, white);
  outline-offset: 3px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 6: Run focused and full CSS/name tests**

Run:

```powershell
npm test -- --run src/app/globals.test.ts src/localization.test.ts src/package-scripts.test.ts
```

Expected: all selected tests pass.

- [ ] **Step 7: Record Task 1 evidence**

Write exact RED/GREEN output and changed files to `C:\01_agent_loop\.superpowers\sdd\enterprise-ai-redesign-task-1-report.md`.

### Task 2: Rebuild The Semantic Responsive Shell And Sidebar

**Files:**
- Create: `C:\01_agent_loop\frontend\src\components\layout\app-shell.tsx`
- Create: `C:\01_agent_loop\frontend\src\components\layout\conversation-top-bar.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\layout\dashboard-shell.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\layout\app-sidebar.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\layout\app-header.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\session-sidebar-list.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\layout.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(dashboard)\layout.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\layout\dashboard-shell.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\agent-routes.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\globals.css`

**Interfaces:**
- `AppShell({ children }: { children: ReactNode })` owns viewport, sidebar, Drawer, and semantic `<main>`.
- `ConversationTopBar({ title, mode, privacyLabel, onOpenNavigation })` is available to chat pages.
- `AppSidebar` renders `<nav aria-label="主导航">` and current links use `aria-current="page"`.

- [ ] **Step 1: Write failing semantic and focus tests**

Add tests asserting:

```tsx
expect(screen.getByRole("main")).toBeVisible();
expect(screen.getByRole("navigation", { name: "主导航" })).toBeVisible();
expect(screen.getByRole("link", { name: /企业智助/ })).toBeVisible();
expect(screen.getByRole("link", { name: "开始新对话" })).toHaveAttribute("href", "/agent");
expect(activeSession).toHaveAttribute("aria-current", "page");
```

Add a collapse test that tabs through the page and asserts no hidden sidebar link receives focus. Add a mobile Drawer test asserting its body has the deep-coffee class and focus returns to the trigger after close.

- [ ] **Step 2: Run shell tests and verify RED**

Run:

```powershell
npm test -- --run src/components/layout/dashboard-shell.test.tsx "src/app/(agent)/agent/agent-routes.test.tsx"
```

Expected: main/nav/aria-current/product-name/collapse-focus assertions fail.

- [ ] **Step 3: Implement `AppShell`**

Use semantic structure:

```tsx
export default function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = usePersistentSidebarState();
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <div className="enterprise-shell">
      <aside className="enterprise-sidebar" aria-hidden={collapsed || undefined} inert={collapsed ? true : undefined}>
        <AppSidebar />
      </aside>
      <div className="enterprise-main-column">
        <button className="sidebar-trigger" aria-expanded={!collapsed} aria-label={collapsed ? "展开导航" : "收起导航"} />
        <main className="enterprise-main">{children}</main>
      </div>
      <Drawer className="enterprise-navigation-drawer" open={mobileOpen} onClose={() => setMobileOpen(false)}>
        <AppSidebar onNavigate={() => setMobileOpen(false)} />
      </Drawer>
    </div>
  );
}
```

If React typing rejects boolean `inert`, use `inert={collapsed ? "" : undefined}` through a typed wrapper. Do not leave hidden descendants focusable.

- [ ] **Step 4: Restructure `AppSidebar`**

Render these groups:

```text
企业智助
开始新对话
会话历史（only this section scrolls）
治理中心（permission-gated）
账户：display_name, username, role badge, logout
```

Replace `权限管理系统` and `Agent 运行审计` with `企业智助` and `对话审计`. Keep routes unchanged unless a route migration is explicitly included in Task 6.

- [ ] **Step 5: Implement shell CSS and remove redundant chat header**

Set the shell to `height: 100dvh; overflow: hidden`. Use 248px desktop sidebar, deep coffee Drawer, warm canvas, independent main scroll, and `@media (max-width: 767px)` only for the 768 breakpoint behavior.

Chat layouts render no global account breadcrumb header. Management pages may retain a compatibility wrapper until Task 7 adds local page headers.

- [ ] **Step 6: Verify shell behavior**

Run:

```powershell
npm test -- --run src/components/layout/dashboard-shell.test.tsx "src/app/(agent)/agent/agent-routes.test.tsx" src/components/agent/session-sidebar-list.test.tsx
```

Expected: selected tests pass.

- [ ] **Step 7: Record Task 2 evidence**

Write report to `C:\01_agent_loop\.superpowers\sdd\enterprise-ai-redesign-task-2-report.md`.

### Task 3: Consolidate The Shared Chat Composer And Input Behavior

**Files:**
- Create: `C:\01_agent_loop\frontend\src\components\agent\chat-composer.tsx`
- Create: `C:\01_agent_loop\frontend\src\components\agent\chat-composer.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\new-conversation-composer.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\submit-textarea.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\attachment-input.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\agent-mode-controls.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\sessions\[sessionId]\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\agent-globals.css`

**Interfaces:**
- `ChatComposerProps`:

```ts
type ChatComposerProps = {
  sessionId?: string;
  placeholder: string;
  submitLabel?: string;
  onSubmit: (input: { goal: string; mode: "quick" | "expert"; attachmentIds: string[] }) => Promise<void> | void;
  disabled?: boolean;
  autoFocus?: boolean;
};
```

- `SubmitTextarea` emits submit only for Enter without Shift and without IME composition.

- [ ] **Step 1: Write failing keyboard and attachment tests**

Cover:

```tsx
await user.type(textbox, "问题{enter}");
expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ goal: "问题" }));

fireEvent.keyDown(textbox, { key: "Enter", shiftKey: true });
expect(onSubmit).not.toHaveBeenCalled();
expect(textbox).toHaveValue(expect.stringContaining("\n"));

fireEvent.compositionStart(textbox);
fireEvent.keyDown(textbox, { key: "Enter", isComposing: true });
expect(onSubmit).not.toHaveBeenCalled();
```

Test whitespace-only disabled send, mode value, keyboard-operable attachment trigger, inline file chip, removal button, and `role="alert"` upload error.

- [ ] **Step 2: Run composer tests and verify RED**

Run:

```powershell
npm test -- --run src/components/agent/chat-composer.test.tsx
```

Expected: new test file fails before implementation; existing submit convention fails Shift+Enter requirement.

- [ ] **Step 3: Implement `ChatComposer`**

Use a real form and keep the API payload shape:

```tsx
async function submit() {
  const goal = value.trim();
  if (!goal || uploading || disabled) return;
  await onSubmit({ goal, mode, attachmentIds });
  setValue("");
}
```

Use one mode control in the toolbar. Do not render duplicate capability tags.

- [ ] **Step 4: Correct keyboard semantics**

Update `SubmitTextarea`:

```tsx
if (
  event.key === "Enter" &&
  !event.shiftKey &&
  !event.nativeEvent.isComposing
) {
  event.preventDefault();
  event.currentTarget.form?.requestSubmit();
}
```

Ctrl/Cmd+Enter has no special newline behavior; it follows standard Enter send unless product tests explicitly require otherwise. Shift+Enter remains newline.

- [ ] **Step 5: Refactor attachments**

Use a visible/focusable button that calls `inputRef.current?.click()`. Render chips in document flow:

```tsx
<button type="button" aria-label="添加附件" onClick={openPicker}>
  <PaperClipOutlined aria-hidden="true" />
</button>
<input ref={inputRef} type="file" hidden multiple onChange={handleFiles} />
<div className="composer-files">{files.map(renderChip)}</div>
{error ? <div role="alert">{error}</div> : null}
```

- [ ] **Step 6: Migrate landing and session pages**

Use `ChatComposer` for both create-run paths. Keep existing `agentApi.createSession`/`createRun` contracts and session invalidation. The session composer is placed outside the transcript scroll region and docked at the bottom.

- [ ] **Step 7: Run focused composer/page tests**

Run:

```powershell
npm test -- --run src/components/agent/chat-composer.test.tsx src/components/agent/agent-streaming.test.tsx "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx"
```

Expected: all selected tests pass.

- [ ] **Step 8: Record Task 3 evidence**

Write report to `C:\01_agent_loop\.superpowers\sdd\enterprise-ai-redesign-task-3-report.md`.

### Task 4: Redesign Chat Landing, Conversation, Timeline, And Copy Action

**Files:**
- Create: `C:\01_agent_loop\frontend\src\components\agent\answer-actions.tsx`
- Create: `C:\01_agent_loop\frontend\src\components\agent\answer-actions.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\sessions\[sessionId]\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\session-conversation-stream.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\thought-narrative.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\final-answer-panel.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\agent-streaming.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\agent-globals.css`

**Interfaces:**
- `AnswerActions({ text }: { text: string })` exposes copy only.
- `ThoughtNarrative` defaults expanded and supplies accessible disclosure semantics.
- Session page uses `ConversationTopBar` and docked `ChatComposer`.

- [ ] **Step 1: Write failing chat presentation tests**

Add assertions for:

```tsx
expect(screen.getByRole("heading", { level: 1, name: session.title })).toBeVisible();
expect(screen.getByRole("button", { name: "收起思考过程" })).toHaveAttribute("aria-expanded", "true");
expect(screen.getByRole("region", { name: "思考与工具过程" })).toBeVisible();
expect(screen.getByRole("button", { name: "复制回答" })).toBeVisible();
expect(screen.queryByRole("button", { name: /重新生成|反馈|导出/ })).not.toBeInTheDocument();
```

Mock `navigator.clipboard.writeText`, click copy, and assert the complete Markdown string and `已复制` feedback.

- [ ] **Step 2: Run chat tests and verify RED**

Run:

```powershell
npm test -- --run src/components/agent/agent-streaming.test.tsx src/components/agent/answer-actions.test.tsx "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx"
```

Expected: missing copy component and disclosure/title semantics fail.

- [ ] **Step 3: Implement copy-only answer actions**

```tsx
export default function AnswerActions({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }
  return <button type="button" onClick={copy} aria-label="复制回答">{copied ? "已复制" : "复制"}</button>;
}
```

Do not add other answer actions.

- [ ] **Step 4: Add accessible always-expanded process timeline**

Keep initial state `true`. Add stable IDs:

```tsx
<button
  type="button"
  aria-expanded={expanded}
  aria-controls={regionId}
  onClick={() => setExpanded((value) => !value)}
>
  {expanded ? "收起思考过程" : "展开思考过程"}
</button>
{expanded ? (
  <div id={regionId} role="region" aria-label="思考与工具过程">
    {blocks.map((block) => renderNarrativeBlock(block))}
  </div>
) : null}
```

Completed reasoning stays static; only active incomplete reasoning types progressively.

- [ ] **Step 5: Restyle landing and conversation**

Landing copy uses `今天想完成什么？` and `企业智助`. Conversation uses a 720-780px reading column, warm-soft user bubbles, unboxed AI Markdown, fine timeline, semantic statuses, and no nonfunctional glyph.

Keep all current streaming/reconciliation logic intact.

- [ ] **Step 6: Run focused chat tests**

Run:

```powershell
npm test -- --run src/components/agent/answer-actions.test.tsx src/components/agent/agent-streaming.test.tsx "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx"
```

Expected: all selected tests pass.

- [ ] **Step 7: Record Task 4 evidence**

Write report to `C:\01_agent_loop\.superpowers\sdd\enterprise-ai-redesign-task-4-report.md`.

### Task 5: Add The Administrator Audit Transcript Contract

**Files:**
- Modify: `C:\01_agent_loop\backend\app\schemas\agent.py`
- Modify: `C:\01_agent_loop\backend\app\api\agent_audit.py`
- Modify: `C:\01_agent_loop\backend\tests\test_agent_api.py`
- Modify: `C:\01_agent_loop\backend\tests\test_agent_stream.py` only if shared fixtures require it
- Modify: `C:\01_agent_loop\frontend\src\types\agent.ts`
- Modify: `C:\01_agent_loop\frontend\src\lib\agent-api.ts`
- Create: `C:\01_agent_loop\frontend\src\lib\audit-session-view.ts`
- Create: `C:\01_agent_loop\frontend\src\lib\audit-session-view.test.ts`

**Interfaces:**
- Adds `GET /api/agent/audit/sessions/{session_id}/transcript` for highest administrators.
- Adds `agentApi.getAuditRun(runId)` using `/api/agent/audit/runs/{runId}`.
- Adds `agentApi.getAuditSessionTranscript(sessionId)`.

Define response shapes:

```python
class AuditOwnerSummary(BaseModel):
    id: UUID
    username: str
    display_name: str
    roles: list[str]

class AuditTranscriptTurn(BaseModel):
    run: AgentRunResponse
    steps: list[AgentRunStepResponse]
    events: list[AgentRunEventResponse]

class AuditSessionTranscriptResponse(BaseModel):
    session: AgentSessionResponse
    owner: AuditOwnerSummary
    turns: list[AuditTranscriptTurn]
```

- [ ] **Step 1: Write failing backend authorization/contract tests**

Add tests:

```python
async def test_super_admin_reads_other_users_transcript(client, super_admin_cookie, foreign_session):
    response = await client.get(
        f"/api/agent/audit/sessions/{foreign_session.id}/transcript",
        cookies=super_admin_cookie,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["owner"]["display_name"]
    assert data["turns"][0]["run"]["session_id"] == str(foreign_session.id)

async def test_ordinary_user_cannot_read_audit_transcript(
    client,
    ordinary_user_cookie,
    foreign_session,
):
    response = await client.get(
        f"/api/agent/audit/sessions/{foreign_session.id}/transcript",
        cookies=ordinary_user_cookie,
    )
    assert response.status_code == 403
```

Assert event redaction still applies and another user's final answer is available through the authorized audit contract.

- [ ] **Step 2: Run backend audit tests and verify RED**

Run:

```powershell
python -m pytest tests/test_agent_api.py -k "audit and transcript" -q
```

Expected: endpoint not found or schema missing.

- [ ] **Step 3: Implement transcript query and schemas**

Inside `agent_audit.py`, require the existing super-admin dependency. Query the session, owner `User`, ordered runs, steps, and events. Reuse the existing redaction helper before serializing event payloads. Use persisted `run.result.final_answer` where available.

Return 404 for nonexistent sessions and never fall back to owner-scoped endpoints.

- [ ] **Step 4: Add frontend API contracts**

```ts
getAuditRun: (runId: string) => api.get<AgentRun>(`/api/agent/audit/runs/${runId}`),
getAuditSessionTranscript: (sessionId: string) =>
  api.get<AuditSessionTranscript>(`/api/agent/audit/sessions/${sessionId}/transcript`),
```

Create `loadAuditSessionView(sessionId)` that returns owner/session/turns in the same rendering-ready structure used by `SessionConversationStream`, without calling owner-scoped APIs.

- [ ] **Step 5: Write frontend loader tests**

Mock the transcript endpoint, call `loadAuditSessionView`, and assert owner identity, run order, final answer, steps, events, and warnings. Assert no call to `/api/agent/runs/{id}`.

- [ ] **Step 6: Run backend/frontend focused tests**

Run in parallel:

```powershell
python -m pytest tests/test_agent_api.py -k "audit and transcript" -q
```

```powershell
npm test -- --run src/lib/audit-session-view.test.ts src/lib/agent-api.test.ts
```

Expected: selected tests pass.

- [ ] **Step 7: Record Task 5 evidence**

Write report to `C:\01_agent_loop\.superpowers\sdd\enterprise-ai-redesign-task-5-report.md`.

### Task 6: Redesign Governance Around People, Conversations, Transcript, And Diagnostics

**Files:**
- Create: `C:\01_agent_loop\frontend\src\components\governance\governance-transcript.tsx`
- Create: `C:\01_agent_loop\frontend\src\components\governance\governance-transcript.test.tsx`
- Create: `C:\01_agent_loop\frontend\src\components\ui\page-header.tsx`
- Create: `C:\01_agent_loop\frontend\src\components\ui\data-surface.tsx`
- Create: `C:\01_agent_loop\frontend\src\components\ui\view-states.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\audit\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\audit\sessions\[sessionId]\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\audit\runs\[runId]\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\audit\audit-pages.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\agent-globals.css`

**Interfaces:**
- `GovernanceTranscript({ view }: { view: AuditSessionView })` renders the standard conversation stream plus owner context and collapsible diagnostics.
- Governance filters call audit sessions with `user_id`, keyword/client filter, date/status/mode/network controls supported by current or added contracts.

- [ ] **Step 1: Write failing governance tests**

Assert:

```tsx
expect(screen.getByRole("heading", { name: "治理中心" })).toBeVisible();
expect(screen.getByLabelText("筛选人员")).toBeVisible();
expect(screen.getByText(owner.display_name)).toBeVisible();
expect(screen.getByText(owner.username)).toBeVisible();
expect(screen.getByRole("region", { name: "对话全文" })).toBeVisible();
expect(screen.getByRole("button", { name: "展开运行诊断" })).toHaveAttribute("aria-expanded", "false");
expect(screen.queryByText(/特权访问|自动留痕/)).not.toBeInTheDocument();
```

Assert run detail uses `getAuditRun`, not `getRun`.

- [ ] **Step 2: Run governance tests and verify RED**

Run:

```powershell
npm test -- --run "src/app/(agent)/agent/audit/audit-pages.test.tsx" src/components/governance/governance-transcript.test.tsx
```

Expected: missing transcript/filters/human identity/API usage assertions fail.

- [ ] **Step 3: Implement governance list and filters**

Use `PageHeader`, one compact summary row, one responsive filter bar, and one `DataSurface`. Display names/usernames first and UUID only in a copyable metadata field.

Do not add visible privileged-access copy.

- [ ] **Step 4: Implement transcript-first session detail**

Load `loadAuditSessionView`. Render `GovernanceTranscript`, which uses the same `SessionConversationStream` presentation in read-only mode. Hide composer. Keep thought/tool process expanded by default.

Add a collapsed diagnostics section containing attempts, steps, events, timing, retries, and IDs.

- [ ] **Step 5: Correct audit run detail API**

Replace `agentApi.getRun(runId)` with `agentApi.getAuditRun(runId)`. Keep attempts/events audit endpoints and add breadcrumb navigation back to the session rather than dropping context.

- [ ] **Step 6: Implement responsive governance behavior**

At desktop, use people/conversation/transcript hierarchy without squeezing raw three-column content below 960px. Below 960px, use progressive list → session → transcript navigation. Below 768px, filters open in a Drawer.

- [ ] **Step 7: Run governance tests**

Run:

```powershell
npm test -- --run "src/app/(agent)/agent/audit/audit-pages.test.tsx" src/components/governance/governance-transcript.test.tsx src/lib/audit-session-view.test.ts
```

Expected: selected tests pass and prohibited wording is absent.

- [ ] **Step 8: Record Task 6 evidence**

Write report to `C:\01_agent_loop\.superpowers\sdd\enterprise-ai-redesign-task-6-report.md`.

### Task 7: Align User And Role Management With The Unified System

**Files:**
- Modify: `C:\01_agent_loop\frontend\src\components\users\user-management.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\users\user-table.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\users\user-drawer.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\users\user-management.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\users\user-drawer.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\roles\role-management.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\roles\role-table.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\roles\role-drawer.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\roles\role-management.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(dashboard)\layout.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\globals.css`

**Interfaces:**
- Users/roles use `PageHeader`, `DataSurface`, and shared view-state components from Task 6.
- `/users` keeps `user:read`; `/roles` keeps `role:read` without inherited `user:read`.

- [ ] **Step 1: Write failing permission and mutation-safety tests**

Add tests:

```tsx
test("role:read user reaches roles without user:read", async () => {
  mockCurrentUser({ permissions: ["role:read"] });
  render(<DashboardLayout><RolesPage /></DashboardLayout>);
  expect(await screen.findByRole("heading", { name: "角色与权限" })).toBeVisible();
  expect(screen.queryByText("无权访问")).not.toBeInTheDocument();
});

test("editing a user initializes existing role ids", async () => {
  render(<UserDrawer open user={makeUser({ roles: [roleA, roleB] })} onClose={vi.fn()} onSuccess={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(mockUpdateUser).toHaveBeenCalledWith(
    expect.any(String),
    expect.objectContaining({ role_ids: [roleA.id, roleB.id] }),
  );
});

test("role status is changed through the dedicated action, not the edit drawer", () => {
  render(<RoleDrawer open role={makeRole()} onClose={vi.fn()} onSuccess={vi.fn()} />);
  expect(screen.queryByLabelText("角色状态")).not.toBeInTheDocument();
});

test("management table scroll region is keyboard focusable", () => {
  const { container } = render(<UserTable users={makeUsers(2)} loading={false} />);
  expect(container.querySelector(".data-surface-scroll")).toHaveAttribute("tabindex", "0");
});
```

Add mobile Drawer width assertions and footer reachability.

- [ ] **Step 2: Run management tests and verify RED**

Run:

```powershell
npm test -- --run src/components/users/user-management.test.tsx src/components/users/user-drawer.test.tsx src/components/roles/role-management.test.tsx
```

Expected: role initialization, layout gate, and scroll/focus tests fail.

- [ ] **Step 3: Remove the shared `user:read` dashboard gate**

Make the shared dashboard layout require authentication only. Retain page-level `ProtectedPage` checks:

```tsx
// /users => user:read
// /roles => role:read
```

- [ ] **Step 4: Correct user role initialization**

When editing:

```ts
form.setFieldsValue({
  ...user,
  role_ids: user.roles.map((role) => role.id),
});
```

Do not submit `role_ids: []` unless the user explicitly removes every role.

- [ ] **Step 5: Align role status behavior**

Either include status in the PUT contract if backend accepts it, or remove the editable status field and use the existing dedicated status action. Prefer the existing dedicated status action to avoid changing backend semantics unnecessarily.

- [ ] **Step 6: Apply unified management layout**

Use local `PageHeader`, compact filter bar, restrained metrics, one white `DataSurface`, accessible horizontal overflow, structured skeleton, shared empty/error states, and responsive full-width Drawers below 768px.

- [ ] **Step 7: Run management tests**

Run:

```powershell
npm test -- --run src/components/users/user-management.test.tsx src/components/users/user-drawer.test.tsx src/components/users/user-dialogs.test.tsx src/components/roles/role-management.test.tsx
```

Expected: selected tests pass.

- [ ] **Step 8: Record Task 7 evidence**

Write report to `C:\01_agent_loop\.superpowers\sdd\enterprise-ai-redesign-task-7-report.md`.

### Task 8: Rebrand Login, Normalize Redirects, And Complete Acceptance

**Files:**
- Modify: `C:\01_agent_loop\frontend\src\app\(auth)\login\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\auth\login-form.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\auth\login-form.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\globals.css`
- Modify: `C:\01_agent_loop\frontend\src\app\agent-globals.css`
- Modify: `C:\01_agent_loop\README.md`
- Modify: `C:\01_agent_loop\frontend\README.md`

**Interfaces:**
- Successful login default destination is `/agent` for every role.
- A validated same-origin callback may override the default only if current auth code already supports it safely.

- [ ] **Step 1: Write failing login redirect and brand tests**

Update tests to assert:

```tsx
expect(screen.getByText("企业智助")).toBeVisible();
expect(screen.getByText(/组织专属的私有智能助手/)).toBeVisible();
expect(mockPush).toHaveBeenCalledWith("/agent");
```

Run the same assertion for ordinary and super-admin responses. Assert `/users` is no longer the default.

- [ ] **Step 2: Run login tests and verify RED**

Run:

```powershell
npm test -- --run src/components/auth/login-form.test.tsx src/localization.test.ts
```

Expected: super-admin redirect and old branding assertions fail.

- [ ] **Step 3: Implement the unified login experience**

Use 企业智助 brand, private organizational AI message, restrained warm split layout, accessible form, and `/agent` redirect for all users.

Do not expose governance access details on the login page.

- [ ] **Step 4: Update documentation copy**

Update README product description and startup screenshots/route descriptions without changing documented development credentials or exposing secrets.

- [ ] **Step 5: Run complete automated verification**

Run frontend:

```powershell
npm test -- --run
npm run build
```

Run backend:

```powershell
python -m pytest tests/test_agent_api.py tests/test_agent_stream.py tests/test_agent_loop.py tests/test_agent_tools.py tests/test_agent_worker.py -q
```

Expected: all newly touched suites pass. If the two known retry mock failures remain, document their unchanged stack traces separately and verify no new failure exists.

- [ ] **Step 6: Execute permission matrix acceptance**

Using synthetic test identities, verify:

| Identity | Chat | Own sessions | Other sessions | Users | Roles | Governance |
|---|---|---|---|---|---|---|
| Ordinary user | yes | yes | no | no | no | no |
| User manager | yes | yes | no | according to `user:*` | no unless authorized | no |
| Role manager | yes | yes | no | no unless authorized | according to `role:*` | no |
| Highest administrator | yes | yes | yes | yes | yes | yes |

- [ ] **Step 7: Execute real Edge visual acceptance**

Use an isolated Edge profile and synthetic non-private data. Do not use Quark.

Capture and verify:

1. Login at 1440x900 and 390x844.
2. Chat landing at 1366x768, 390x844, and 320x568.
3. Conversation with expanded process timeline, streaming answer, completed answer, and copy action.
4. Docked composer with mobile keyboard simulation and long attachment names.
5. Governance home, people filter, another user's transcript, and diagnostics.
6. User and role pages with responsive Drawers.
7. Sidebar expanded/collapsed/Drawer focus behavior.
8. 200% and 400% zoom.
9. Reduced motion.

The governance UI must be searched for `特权访问` and `自动留痕`; neither phrase may be visible.

- [ ] **Step 8: Record final evidence**

Write report to `C:\01_agent_loop\.superpowers\sdd\enterprise-ai-redesign-task-8-report.md` with screenshots, viewport list, synthetic IDs, test output, residual risks, and rollback notes. Do not record private conversation content or secrets.

---

## Parallel Execution Map

After Task 1 completes:

- Task 2 shell and Task 5 backend audit contract can run in parallel because they touch separate files.

After Task 2 completes:

- Task 3 composer can begin.
- Task 7 management can begin after Task 6 shared UI primitives exist; do not start it earlier.

After Task 3 completes:

- Task 4 chat presentation can begin.

After Task 5 completes:

- Task 6 governance UI can begin.

Task 8 runs only after Tasks 2, 4, 6, and 7 are complete.

Every task requires an independent specification-compliance and code-quality review before its dependents start. If a review rejects a task, fix and rerun the task's focused tests before continuing.

## Definition Of Done

- 企业智助 branding is consistent across metadata, login, shell, chat, governance, and documentation.
- One token system drives Ant Design and custom UI.
- Chat is the default experience for all roles.
- The shell, sidebar, Drawer, scroll boundaries, and focus behavior work across target viewports.
- One ChatComposer powers landing and continuation flows with ChatGPT keyboard conventions.
- Process details remain expanded by default and accessible.
- Completed answers expose copy only.
- Highest administrators directly read all users' transcripts through audit endpoints.
- Governance does not visibly display prohibited privileged-access wording.
- User and role permission gates and mutation safety are correct.
- Full frontend tests and build pass; backend touched tests pass with any unrelated baseline failures explicitly separated.
- Real Edge desktop/mobile/zoom/reduced-motion and permission acceptance is archived with synthetic data.
