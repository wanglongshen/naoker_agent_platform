# Paginate Run Events Fetch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch ALL run events (not just the first 50) so `visible_thought_completed` (and the complete thinking text) reaches the frontend.

**Architecture:** Backend `/runs/{run_id}/events` already supports `after_seq` + `page_size` (default 50, max 200). Frontend `getRunEvents` currently makes ONE request with no `page_size`. Change it to loop: request `page_size=200` pages using the last event's `seq` as the next `after_seq`, until an empty page returns.

**Tech Stack:** TypeScript

## Global Constraints

- Backend unchanged — `page_size` max is 200 (`Query(50, ge=1, le=200)` at `backend/app/api/agent.py:314`)
- Events come back ascending by `seq` (repository `list_events_after_seq` limits ascending)
- Existing callers keep the same signature `getRunEvents(runId, afterSeq, signal)`
- All existing tests must pass

---

### Task 1: Paginate getRunEvents in agent-api.ts

**Files:**
- Modify: `frontend/src/lib/agent-api.ts:47-49`
- Test: `frontend/src/lib/agent-api.test.ts`

**Interfaces:**
- Consumes: `AgentRunEvent[]` items from `/api/agent/runs/{runId}/events?after_seq=X&page_size=200`
- Produces: Full `AgentRunEvent[]` across all pages (same signature as before)

- [ ] **Step 1: Read existing test patterns**

Read `frontend/src/lib/agent-api.test.ts` (4 tests exist). Identify how the `api()` helper / `fetch` is mocked in this file. Follow the SAME mocking pattern for the new test.

- [ ] **Step 2: Write the failing test**

Append to `frontend/src/lib/agent-api.test.ts` (adapt the mock setup to match the file's existing pattern — replace the placeholder `mockFetch` call with whatever the file uses):

```typescript
test("getRunEvents paginates until all events are fetched", async () => {
  const page1 = Array.from({ length: 200 }, (_, i) => makeEvent(i + 1));
  const page2 = Array.from({ length: 30 }, (_, i) => makeEvent(201 + i));
  const requests: string[] = [];

  mockFetch((url: string) => {
    requests.push(url);
    if (url.includes("after_seq=0")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ items: page1 }) });
    }
    if (url.includes("after_seq=200")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ items: page2 }) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ items: [] }) });
  });

  const events = await agentApi.getRunEvents("run-1", 0);
  expect(events).toHaveLength(230);
  expect(requests.length).toBe(3);
  expect(requests[0]).toContain("page_size=200");
  expect(requests[1]).toContain("after_seq=200");
  expect(requests[2]).toContain("after_seq=230");
});

function makeEvent(seq: number) {
  return {
    id: `run-1:${seq}`,
    run_id: "run-1",
    attempt_id: null,
    seq,
    event_type: "test_event",
    type: "test_event",
    payload: {},
    created_at: "2026-01-01T00:00:00Z",
    timestamp: "2026-01-01T00:00:00Z",
  };
}
```

Note: `makeEvent` should be defined inside the describe block or at file scope depending on existing structure.

- [ ] **Step 3: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/lib/agent-api.test.ts -t "paginates" -v
```

Expected: FAIL — single request, returns only the first page (or the mock gets no `page_size=200`).

- [ ] **Step 4: Implement pagination in getRunEvents**

Replace lines 47-49 of `frontend/src/lib/agent-api.ts`:

```typescript
  getRunEvents: async (runId: string, afterSeq = 0, signal?: AbortSignal) => {
    const all: AgentRunEvent[] = [];
    let after = afterSeq;
    while (true) {
      const result = await api<{ items: AgentRunEvent[] }>(
        `/api/agent/runs/${runId}/events?after_seq=${after}&page_size=200`,
        signal ? { signal } : {},
      );
      all.push(...result.items);
      if (result.items.length === 0) break;
      after = result.items[result.items.length - 1].seq;
    }
    return all;
  },
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/lib/agent-api.test.ts -v
```

Expected: 5 tests pass (4 existing + 1 new).

- [ ] **Step 6: Run full frontend suite**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
```

Expected: No new failures (13 pre-existing unchanged).

- [ ] **Step 7: Build check**

```bash
cd C:\01_agent_loop_pro\frontend && npx next build
```

Expected: Compiled successfully.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/agent-api.ts frontend/src/lib/agent-api.test.ts
git commit -m "fix: paginate run events fetch to retrieve full event history"
```
