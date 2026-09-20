# Fixed Conversation Toolbar And Fast Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the enterprise chat header fixed and branded while adding professional answer actions and fast, resilient session navigation.

**Architecture:** Put the right-workspace header in the persistent agent layout so route pages own only scrollable content. Add browser-side feedback and session cache helpers; the session page renders cached data immediately, revalidates safely, cancels obsolete loads, and bounds diagnostics work.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Vitest, Testing Library, Ant Design, browser Clipboard/Web Share/Speech APIs.

## Global Constraints

- Render `企业智助` as the only ordinary-chat top-bar heading on landing and session routes.
- Do not change backend APIs, RBAC, audit retention, or agent execution contracts.
- All newly created ordinary-agent runs use `mode: "quick"`.
- Use 20-24px rounded line icons with accessible labels, visible focus, subdued gray-blue defaults, and restrained hover surfaces.
- Feedback is mutually exclusive local-only `localStorage` state keyed by run ID.
- Share uses `navigator.share`, falling back to copying the current session URL.
- Failed or aborted cache refreshes must not replace visible cached data.
- Preserve existing event/step partial-failure warnings.

---

## File Structure

- `frontend/src/app/(agent)/layout.tsx`: persistent authenticated workspace chrome and fixed header.
- `frontend/src/app/(agent)/agent/page.tsx`: landing content without duplicate header/user fetch.
- `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`: cache-aware session content and regeneration callback.
- `frontend/src/components/layout/conversation-top-bar.tsx`: branded header and account menu.
- `frontend/src/components/agent/answer-actions.tsx`: icon toolbar, feedback, copy/share status.
- `frontend/src/components/agent/answer-speech-button.tsx`: matching icon-only speech action.
- `frontend/src/components/agent/final-answer-panel.tsx`: action context forwarding.
- `frontend/src/components/agent/session-conversation-stream.tsx`: session/run forwarding.
- `frontend/src/components/agent/session-sidebar-list.tsx`: Next route prefetch.
- `frontend/src/lib/answer-feedback.ts`: guarded local feedback/share utilities.
- `frontend/src/lib/session-view-cache.ts`: in-memory cache operations.
- `frontend/src/lib/agent-session-view.ts`: bounded-concurrency diagnostics loading.
- `frontend/src/app/agent-globals.css`: layout, skeleton, toolbar styles.

### Task 1: Persistent Branded Header

**Files:**
- Modify: `frontend/src/app/(agent)/layout.tsx`
- Modify: `frontend/src/app/(agent)/agent/page.tsx`
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`
- Modify: `frontend/src/components/layout/conversation-top-bar.tsx`
- Modify: `frontend/src/app/agent-globals.css`
- Test: `frontend/src/components/agent/agent-streaming.test.tsx`
- Test: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx`

**Interfaces:**
- Produces: `ConversationTopBar({ currentUser }: { currentUser: CurrentUser })` with a fixed `企业智助` h1.

- [ ] **Step 1: Write failing header tests**

```tsx
test("renders one fixed 企业智助 heading instead of the session title", async () => {
  mockLoadAgentSessionView.mockResolvedValue({ session, turns: [], warnings: [] });
  render(<AgentLayout><SessionDetailPage /></AgentLayout>);
  expect(await screen.findByRole("heading", { level: 1, name: "企业智助" })).toBeVisible();
  expect(screen.queryByRole("heading", { level: 1, name: "测试会话" })).not.toBeInTheDocument();
  expect(document.querySelectorAll(".conversation-top-bar")).toHaveLength(1);
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run src/components/agent/agent-streaming.test.tsx src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx`

Expected: FAIL because the session route owns a title-based top bar.

- [ ] **Step 3: Implement persistent layout chrome**

```tsx
// app/(agent)/layout.tsx
<AuthenticatedPage>
  {(user) => <AppShell currentUser={user}>
    <ConversationTopBar currentUser={user} />
    <div className="agent-route-content">{children}</div>
  </AppShell>}
</AuthenticatedPage>

// conversation-top-bar.tsx
<header className="conversation-top-bar"><h1>企业智助</h1>{accountMenu}</header>
```

Remove route-level `ConversationTopBar` and redundant `fetchCurrentUser` effects. Use a 56px flex-fixed header and `agent-route-content { flex: 1; min-height: 0; overflow: hidden; }`; retain the route’s own transcript scroll boundary.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --run src/components/agent/agent-streaming.test.tsx src/app/(agent)/agent/agent-page.test.tsx src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/(agent)/layout.tsx src/app/(agent)/agent/page.tsx src/app/(agent)/agent/sessions/[sessionId]/page.tsx src/components/layout/conversation-top-bar.tsx src/app/agent-globals.css src/components/agent/agent-streaming.test.tsx src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx
git commit -m "feat: keep enterprise chat header fixed"
```

### Task 2: Safe Feedback, Share, And Icon Toolbar

**Files:**
- Create: `frontend/src/lib/answer-feedback.ts`
- Create: `frontend/src/lib/answer-feedback.test.ts`
- Modify: `frontend/src/components/agent/answer-actions.tsx`
- Modify: `frontend/src/components/agent/answer-speech-button.tsx`
- Modify: `frontend/src/components/agent/final-answer-panel.tsx`
- Modify: `frontend/src/components/agent/session-conversation-stream.tsx`
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`
- Modify: `frontend/src/app/agent-globals.css`
- Test: `frontend/src/components/agent/answer-actions.test.tsx`

**Interfaces:**
- Produces: `type AnswerFeedback = "like" | "dislike" | null`.
- Produces: `readAnswerFeedback(runId)`, `writeAnswerFeedback(runId, next)`, `shareAnswer({ text, url })`.
- Produces: `AnswerActions({ ownerId, text, sessionId, onRegenerate })`.

- [ ] **Step 1: Write failing helper and UI tests**

```ts
test("feedback is mutually exclusive by run id", () => {
  writeAnswerFeedback("run-1", "like");
  expect(readAnswerFeedback("run-1")).toBe("like");
  writeAnswerFeedback("run-1", "dislike");
  expect(readAnswerFeedback("run-1")).toBe("dislike");
});
```

```tsx
test("renders all terminal-answer action names", () => {
  render(<AnswerActions ownerId="run-1" sessionId="s1" text="回答" onRegenerate={vi.fn()} />);
  ["复制回答", "朗读回答", "重新生成回答", "赞回答", "不喜欢回答", "转发回答"].forEach((name) =>
    expect(screen.getByRole("button", { name })).toBeVisible());
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run src/lib/answer-feedback.test.ts src/components/agent/answer-actions.test.tsx`

Expected: FAIL because helper and four toolbar actions do not exist.

- [ ] **Step 3: Implement helpers and toolbar**

```ts
export type AnswerFeedback = "like" | "dislike" | null;
const key = (runId: string) => `agent-answer-feedback:${runId}`;
export function readAnswerFeedback(runId: string): AnswerFeedback {
  try { const value = localStorage.getItem(key(runId)); return value === "like" || value === "dislike" ? value : null; }
  catch { return null; }
}
export function writeAnswerFeedback(runId: string, next: AnswerFeedback): AnswerFeedback {
  try { next ? localStorage.setItem(key(runId), next) : localStorage.removeItem(key(runId)); } catch {}
  return next;
}
export async function shareAnswer({ text, url }: { text: string; url: string }) {
  if (typeof navigator.share === "function") { await navigator.share({ text, url }); return "shared" as const; }
  await navigator.clipboard.writeText(url); return "copied" as const;
}
```

Render copy, speech, regenerate, thumbs-up, thumbs-down, and share icon buttons in that order. Each SVG uses `21x21`, `fill="none"`, `stroke="currentColor"`, `strokeWidth={1.9}`, rounded caps and joins. Set `title`, `aria-label`, status live region, selected feedback state, and 36px target styles. Regenerate creates a new run with `run.goal`, fixed `quick` mode, no attachments, invalidates session state, and reloads without deleting old turns.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --run src/lib/answer-feedback.test.ts src/components/agent/answer-actions.test.tsx src/components/agent/agent-streaming.test.tsx`

Expected: PASS, including disabled regeneration while pending and terminal-only actions.

- [ ] **Step 5: Commit**

```bash
git add src/lib/answer-feedback.ts src/lib/answer-feedback.test.ts src/components/agent/answer-actions.tsx src/components/agent/answer-speech-button.tsx src/components/agent/final-answer-panel.tsx src/components/agent/session-conversation-stream.tsx src/app/(agent)/agent/sessions/[sessionId]/page.tsx src/app/agent-globals.css src/components/agent/answer-actions.test.tsx
git commit -m "feat: add professional answer action toolbar"
```

### Task 3: Cache And Bound Session Diagnostics

**Files:**
- Create: `frontend/src/lib/session-view-cache.ts`
- Create: `frontend/src/lib/session-view-cache.test.ts`
- Modify: `frontend/src/lib/agent-session-view.ts`
- Modify: `frontend/src/lib/agent-session-view.test.ts`
- Modify: `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`

**Interfaces:**
- Produces: `readSessionView(sessionId)`, `writeSessionView(view)`, `invalidateSessionView(sessionId)`, `clearSessionViewCache()`.
- Produces: `mapWithConcurrency(items, limit, mapper)` internal helper; diagnostic job limit is four runs, with two API calls per run.

- [ ] **Step 1: Write failing cache and concurrency tests**

```ts
test("returns cached view until explicitly invalidated", () => {
  writeSessionView(view);
  expect(readSessionView("session-1")).toEqual(view);
  invalidateSessionView("session-1");
  expect(readSessionView("session-1")).toBeNull();
});

test("does not start more than four run diagnostic jobs", async () => {
  // Mock six runs; each diagnostic mapper increments an active counter before awaiting a deferred promise.
  // Assert maxActive <= 4, resolve all deferred promises, then await loadAgentSessionView.
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run src/lib/session-view-cache.test.ts src/lib/agent-session-view.test.ts`

Expected: FAIL because no cache exists and all run diagnostics start at once.

- [ ] **Step 3: Implement cache, queue, and background refresh**

```ts
const cache = new Map<string, AgentSessionView>();
export const readSessionView = (id: string) => cache.get(id) ?? null;
export const writeSessionView = (view: AgentSessionView) => cache.set(view.session.id, view);
export const invalidateSessionView = (id: string) => cache.delete(id);
```

```ts
async function mapWithConcurrency<T, R>(items: T[], limit: number, mapper: (item: T) => Promise<R>) {
  const results = new Array<R>(items.length); let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) { const index = cursor++; results[index] = await mapper(items[index]!); }
  }));
  return results;
}
```

In the page: initialize visible session state from cache; begin revalidation without clearing cached turns; write only successful active-generation results; abort the previous controller before each load; invalidate before creating/continuing/regenerating a run. Render a skeleton only when no cached view exists.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- --run src/lib/session-view-cache.test.ts src/lib/agent-session-view.test.ts src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx`

Expected: PASS; existing warning and reconciliation tests remain green.

- [ ] **Step 5: Commit**

```bash
git add src/lib/session-view-cache.ts src/lib/session-view-cache.test.ts src/lib/agent-session-view.ts src/lib/agent-session-view.test.ts src/app/(agent)/agent/sessions/[sessionId]/page.tsx src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx
git commit -m "perf: cache and bound session detail loading"
```

### Task 4: Sidebar Prefetch And Full Verification

**Files:**
- Modify: `frontend/src/components/agent/session-sidebar-list.tsx`
- Modify: `frontend/src/components/agent/session-sidebar-list.test.tsx`
- Modify: `frontend/src/app/agent-globals.css`

**Interfaces:**
- Consumes: `useRouter().prefetch(href: string)`.
- Produces: hover/focus/viewport session route prefetch with no impact on active link semantics.

- [ ] **Step 1: Write failing prefetch test**

```tsx
test("prefetches a session on pointer enter and keyboard focus", async () => {
  const user = userEvent.setup();
  render(<SessionSidebarList sessions={sessions} activeSessionId={null} />);
  const link = screen.getByRole("link", { name: "最新会话" });
  await user.hover(link);
  await user.tab();
  expect(mockPrefetch).toHaveBeenCalledWith("/agent/sessions/s1");
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run src/components/agent/session-sidebar-list.test.tsx`

Expected: FAIL because links do not call `router.prefetch`.

- [ ] **Step 3: Implement idempotent prefetch**

```tsx
const router = useRouter();
const prefetched = useRef(new Set<string>());
function prefetch(id: string) {
  const href = `/agent/sessions/${id}`;
  if (!prefetched.current.has(href)) { prefetched.current.add(href); router.prefetch(href); }
}
<Link href={href} onMouseEnter={() => prefetch(session.id)} onFocus={() => prefetch(session.id)} />
```

Add a compact loading skeleton style for uncached session views; do not alter desktop/mobile sidebar dimensions.

- [ ] **Step 4: Verify GREEN and build**

Run: `npm test -- --run src/components/agent/session-sidebar-list.test.tsx`

Expected: PASS.

Run: `npm test -- --run`

Expected: PASS with no failures.

Run: `npm run build`

Expected: production build exits 0 and lists `/agent`, `/agent/sessions/[sessionId]`, and `/login`.

- [ ] **Step 5: Commit**

```bash
git add src/components/agent/session-sidebar-list.tsx src/components/agent/session-sidebar-list.test.tsx src/app/agent-globals.css
git commit -m "perf: prefetch conversation routes"
```
