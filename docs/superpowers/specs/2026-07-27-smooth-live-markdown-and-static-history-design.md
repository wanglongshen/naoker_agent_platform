# Smooth Live Markdown And Static History Design

## Status

Approved design. This document defines implementation behavior only; no production code is changed by this design phase.

## Objective

Deliver a professional answer experience with two explicit modes:

1. Every Run whose normalized status is exactly `running` displays a smooth, progressively revealed Markdown answer.
2. Every non-running Run, including restored history and completed answers, displays its complete Markdown immediately with no typing replay.

The design preserves character-level Markdown animation for active Runs while removing transport batching, timer contention, terminal page reloads, and accidental historical animation.

## Scope

Implementation target: `C:\01_agent_loop`.

Reference-only source: `X:\01_agent_loop`.

In scope:

- Answer streaming transport and replay behavior.
- Active versus historical animation policy.
- Character-level animation scheduling and catch-up.
- Terminal-state reconciliation without full-page loading.
- Markdown rendering, URL safety, responsive presentation, and accessibility.
- Focused observability and automated/real-browser verification.

Out of scope:

- Sidebar and session-list visual layout.
- Authentication, RBAC rules, model/provider selection, tool execution, and prompt behavior.
- Removing character-level Markdown animation.
- Rendering raw HTML from model output.

## Current Findings

### Historical Animation Risk

Each session turn reconstructs stream metadata by replaying its events. Replayed `answer_started`, `answer_delta`, `answer_checkpoint`, and `answer_completed` events can reconstruct both answer text and an `answerStreamId`. The current display predicate is based on being nonterminal rather than requiring status exactly `running`. This allows queued, retrying, unknown, legacy, or stale states to look like an active stream.

The current terminal vocabulary uses `succeeded`, while reference and historical data may also contain `completed`. Status normalization must occur before deciding whether to animate.

### Live Stutter

The current path has three independent sources of stutter:

1. The SSE endpoint drains process-local queue notifications and then queries persisted events, with a database poll interval up to 250 ms. Multiple model chunks can arrive in visible bursts.
2. Visual typing uses repeated 20 ms timers. Network updates and timer callbacks contend and can build a backlog.
3. Every visible character reparses and reconciles the complete accumulated Markdown document.

### Terminal Interruption

`answer_completed` currently produces a succeeded run in frontend state. The terminal callback reloads all session data with page-level `loading=true`, unmounting the conversation and showing a spinner before the final terminal flow settles. This interrupts animation and creates a visible jump.

### Markdown Baseline

The current Markdown presentation is already structurally close to the reference: `react-markdown`, `remark-gfm`, long-form typography, headings, lists, quotes, code, tables, rules, and responsive handling. The design retains that visual language and strengthens rendering cadence, status behavior, URL policy, accessibility, and test coverage.

## Behavioral Contract

### Status Normalization

Normalize runtime statuses before rendering decisions:

| Runtime value | Canonical category | Animation |
|---|---|---|
| `running` | active | enabled |
| `succeeded` | terminal success | disabled |
| `completed` | terminal success, legacy compatible | disabled |
| `failed` | terminal failure | disabled |
| `cancelled` | terminal cancellation | disabled |
| `queued` | pending | disabled |
| `retry_wait` | pending retry | disabled |
| `cancel_requested` | pending cancellation | disabled |
| unknown value | non-active fail-safe | disabled |

Every Run is evaluated independently. If multiple Runs are genuinely `running`, each may display active streaming. No latest-turn restriction is applied.

### Historical And Restored Answers

A non-running Run must render its full answer immediately on first paint. Replayed stream IDs or answer events never enable animation for a non-running Run.

Answer recovery priority:

1. `run.result.final_answer`.
2. `run_succeeded.payload.final_answer`.
3. `answer_completed.payload.text`.
4. Latest complete `answer_checkpoint.payload.text` for recovery only.

Recovered history never starts from an empty visible string and never replays typing after navigation, page reload, reconnect, or background refresh.

### Active Answers

An active answer uses two separate values:

- `targetText`: complete network text received and validated so far.
- `displayedText`: visible prefix advanced by the presentation scheduler.

Invariants:

- `displayedText` is always a prefix of `targetText`.
- `displayedText` never moves backward during the same stream generation.
- Checkpoints repair target gaps but do not reset displayed text.
- Reconnect and duplicate events do not reset animation.
- A confirmed new stream generation resets once.
- Terminal text is visible in full no later than 250 ms after the final network event.

## Architecture

### Reducer Boundary

`frontend/src/lib/run-stream-reducer.ts` owns transport state only:

- Ordered sequence consumption and duplicate rejection.
- Stream generation identity.
- Target answer text.
- Checkpoint recovery.
- Run status and persisted result projection.
- Terminal answer precedence.

It does not own visible animation timing.

Required terminal behavior:

- `answer_completed` stores complete text and marks answer streaming complete, but must not initiate page-level reload.
- `run_succeeded` reads non-empty `payload.final_answer`, updates target text and `run.result.final_answer`, then transitions to terminal success.
- Empty terminal payload never overwrites a non-empty target.
- `run_failed` and `run_cancelled` preserve received text and end active animation.

### EventSource Hook Boundary

`frontend/src/hooks/use-run-event-stream.ts` owns:

- Connection and credentials.
- Replay cursor and reconnect.
- Parsing and reducer dispatch.
- Old-connection suppression after Run changes.
- Terminal callback only after the terminal event is fully reduced.

Stale events from closed EventSource instances must be ignored. Parse failures enter a recoverable failed connection state rather than fabricating successful completion.

### Presentation Scheduler

Replace independent character timers with a requestAnimationFrame-driven scheduler in `use-typing-text.ts` and `typing-animation.ts`.

Inputs:

- `targetText: string`.
- `enabled: boolean`.
- `resetKey: stream generation identifier`.
- reduced-motion preference.

Scheduling contract:

- At most one visible-state update per animation frame.
- Small backlog: advance one character per frame.
- Medium backlog: advance two to four characters per frame.
- Large backlog: advance a proportional chunk while retaining character-level transitions.
- Punctuation pauses may be retained only when backlog is small.
- Terminal state enters bounded catch-up and reaches complete text within 250 ms.
- Reduced-motion mode displays `targetText` immediately.

The scheduler must not create multiple concurrent RAF loops for one answer.

### Final Answer Panel

`frontend/src/components/agent/final-answer-panel.tsx` computes:

```text
isActivelyStreaming = normalizeStatus(run.status) === "running"
```

Behavior:

- Active: render RAF-driven `displayedText` through Markdown.
- Non-active: render complete target/persisted answer immediately.
- Running with no received answer: do not show a false completed placeholder.
- Succeeded with no recoverable answer: show an explicit abnormal-empty-result state.
- Failed/cancelled: preserve any received partial answer and render the status separately.

### Session Conversation Stream

`frontend/src/components/agent/session-conversation-stream.tsx` continues to isolate state per Run. It passes normalized active state explicitly to answer and reasoning presentation. All `running` Runs may animate independently.

Completed thought/reasoning blocks should be static. Only currently growing blocks should run presentation animation.

### Session Page Reconciliation

`frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx` must separate initial loading from background terminal reconciliation.

- Initial navigation may use page-level loading.
- Terminal reconciliation must not set page-level `loading=true`.
- Existing turns remain mounted.
- A stale or empty HTTP snapshot cannot replace a more complete local target/result.
- Reconciliation failures preserve local data and produce a scoped warning.
- Reconciliation is triggered by the actual terminal Run event, not by an answer-complete snapshot alone.

## SSE Delivery Design

### Immediate Notification Path

For events published in the API process, the event-bus queue acts as a wake-up signal. On notification, the SSE generator immediately queries and yields all events with `seq > last_seen_seq`. It must not discard queue signals before fetching.

### Cross-Process Compensation

Worker and API may be separate processes, so database polling remains necessary. Active streams poll persisted events every 100 ms as a compensation path.

The event bus is an optimization, not the sole correctness mechanism. Database replay remains authoritative.

### Ordering And Deduplication

Initial replay, event-bus wake-up, compensation polling, reconnect replay, and terminal catch-up share one cursor:

```text
emit event only when event.seq > last_seen_seq
after emit: last_seen_seq = event.seq
```

All queried batches are ordered ascending. Duplicate wake-ups are harmless. The terminal generator completes only after a final persisted-event catch-up.

### Response Contract

Retain:

- `Content-Type: text/event-stream`.
- `Cache-Control: no-store, no-transform` or deployment-equivalent no-cache contract.
- `X-Accel-Buffering: no`.
- Ownership, authentication, origin, and cursor validation.
- Heartbeats no slower than 15 seconds.

Do not enable response compression or proxy buffering for this route.

## Markdown Rendering Contract

### Active Streaming

Active streaming continues to render character-level Markdown. Rendering is bounded to at most one parse/reconciliation per animation frame.

Incomplete syntax is provisional and may reflow as it becomes valid, but it must never throw or blank the answer. The implementation must preserve the visible prefix across ordinary target growth.

### Completed And Historical

Complete answers render once from the full recovered text. No animation, empty-to-full transition, or repeated parser churn is permitted.

### Supported Presentation

Retain and verify:

- Paragraphs and Chinese/English long-form text.
- Headings `h1` through `h6`.
- Ordered, unordered, and nested lists.
- GFM strikethrough and task lists.
- Blockquotes.
- Inline and fenced code.
- GFM tables with mobile horizontal overflow.
- Horizontal rules.
- Safe internal and external links.

### URL And HTML Safety

Raw HTML remains disabled. Do not add `rehype-raw`.

Allowed links:

- `http:`.
- `https:`.
- `mailto:`.
- Safe relative application paths.
- Safe fragment anchors.

Reject or neutralize:

- `javascript:`.
- `data:`.
- Encoded or mixed-case dangerous schemes.
- Unapproved protocol-relative URLs.

External links use a new tab with `noopener noreferrer` and an accessible new-tab indication. Internal and fragment links remain in the current tab.

### Accessibility

- Final answer section has an accessible label or heading relationship.
- Streaming announcements are throttled through `aria-live="polite"`; every character is not announced.
- Links have visible `:focus-visible` styling.
- Code and table overflow regions are keyboard accessible.
- Task-list controls are noninteractive unless backed by state.
- Reduced-motion preference bypasses character animation.

## Error Handling

| Failure | Required behavior |
|---|---|
| Offset mismatch | Reconnect and repair from replay/checkpoint; preserve displayed prefix. |
| Stream generation mismatch | Reset only after confirming a new generation. |
| Malformed SSE JSON | Close that connection, mark recoverable failure, retain local text. |
| Connection interruption | Reconnect from last sequence; no duplicate visible text. |
| Background reconciliation failure | Keep local final answer; show scoped warning. |
| Empty terminal answer | Preserve non-empty accumulated text; otherwise show explicit abnormal state and structured diagnostic. |
| Incomplete Markdown | Render safely without raw HTML or runtime exception. |
| Dangerous URL | Remove navigation capability or render safe text. |

Diagnostics may include run ID, stream ID, sequence, event type, answer length, first-delta latency, delta count, reconnect count, and terminal status. Never log answer bodies, prompts, cookies, JWTs, or API keys.

## File-Level Change Map

### Frontend

- `frontend/src/lib/run-stream-reducer.ts`: target text, normalized terminal merging, generation and sequence invariants.
- `frontend/src/lib/run-stream-reducer.test.ts`: replay, terminal precedence, status compatibility, and no-overwrite tests.
- `frontend/src/hooks/use-run-event-stream.ts`: connection lifecycle, stale-source suppression, terminal notification timing.
- `frontend/src/hooks/use-run-event-stream.test.ts`: reconnect, Run switch, terminal sequencing, and stale-event tests.
- `frontend/src/lib/typing-animation.ts`: pure RAF advancement policy and bounded catch-up calculations.
- `frontend/src/lib/typing-animation.test.ts`: backlog tiers, monotonic prefix, terminal deadline, reduced motion.
- `frontend/src/hooks/use-typing-text.ts`: one RAF loop, enabled state, reset generation, reduced-motion handling.
- `frontend/src/hooks/use-typing-text.test.ts`: active progression, target growth, stop/catch-up, cancellation.
- `frontend/src/components/agent/final-answer-panel.tsx`: strict running-only policy, complete historical path, Markdown security/accessibility.
- `frontend/src/components/agent/agent-streaming.test.tsx`: historical no-animation, all-running policy, Markdown structure and safety.
- `frontend/src/components/agent/session-conversation-stream.tsx`: explicit per-Run active-state wiring.
- `frontend/src/components/agent/thought-narrative.tsx`: animate only growing reasoning blocks.
- `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`: background reconciliation without full-page loading.
- `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx`: no spinner/remount and stale-snapshot protection.
- `frontend/src/app/agent-globals.css`: `h4-h6`, focus-visible, table/code overflow, task list, responsive prose.

### Backend

- `backend/app/api/agent_stream.py`: immediate event-bus wake-up, 100 ms cross-process polling, unified cursor, terminal catch-up.
- `backend/tests/test_agent_stream.py`: immediate wake-up latency, cross-process compensation, ordering, deduplication, reconnect, terminal catch-up.

No provider, worker chunk-generation, authentication, RBAC, or prompt changes are required unless diagnostics during implementation contradict this design.

## Test-Driven Implementation Order

### Stage 1: Historical Versus Active Policy

Write failing tests first:

- `succeeded` history with persisted and replayed events renders complete immediately.
- legacy `completed` renders complete immediately.
- queued, retrying, cancellation-pending, failed, cancelled, and unknown statuses do not animate.
- every Run with exact status `running` may animate, including multiple simultaneous running Runs.
- terminal transition reveals complete text without reset.

### Stage 2: Animation Scheduler

Write failing tests first:

- One RAF loop per answer.
- Small backlog advances one character per frame.
- Medium and large backlogs accelerate monotonically.
- Target growth preserves displayed prefix.
- Checkpoint repair does not restart animation.
- Terminal target is reached within 250 ms.
- Reduced motion displays target immediately.

### Stage 3: Session Reconciliation

Write failing tests first:

- `answer_completed` does not trigger page-level spinner.
- `run_succeeded` triggers background reconciliation after reduction.
- Existing conversation remains mounted.
- Empty/older HTTP result does not overwrite fuller local result.
- Reconciliation failure retains answer and produces scoped warning.

### Stage 4: SSE Cadence

Write failing tests first:

- Event-bus notification wakes delivery without waiting for the 100 ms poll timeout.
- Cross-process persisted event arrives within the compensation window.
- Multiple wake-ups do not duplicate events.
- Reconnect after sequence N only emits greater sequences.
- Terminal status performs one final catch-up before close.

### Stage 5: Markdown Contract

Write failing tests first:

- Historical answer renders complete GFM immediately.
- Active answer remains character progressive.
- Headings `h1-h6`, nested lists, task lists, code, quote, table, and rule render semantically.
- Raw HTML is not inserted.
- Dangerous schemes are not navigable.
- Internal/external links use correct navigation policy.
- Reduced motion and accessible answer section behavior.
- Mobile table/code overflow remains contained.

## Verification Matrix

### Automated

- Focused frontend unit/component tests for every stage.
- Full frontend suite: `npm test -- --run`.
- Frontend production build: `npm run build`.
- Focused backend SSE suite.
- Full Agent backend suites covering API, loop, stream, tools, and worker.

### Real Browser

Use Microsoft Edge with a clean development profile; do not use Quark for acceptance because diagnostics proved it creates repeated localhost navigations independently of application code.

Scenarios:

1. Load completed history: full Markdown appears on first paint with zero typing frames.
2. Start a long Run: terminal state is not reached before at least two visible DOM text-growth observations, except for very short answers.
3. Capture SSE arrival timestamps and DOM-growth timestamps.
4. Disconnect after multiple deltas, reconnect, and verify no duplicate/backward/reset text.
5. Complete the Run: no full-page spinner, remount, or blank interval; final text matches persisted result.
6. Reload the completed session: full answer appears immediately with no animation.
7. Run two simultaneous `running` Runs if supported: both animate independently.
8. Exercise Markdown fixtures at desktop and mobile widths.

### Performance

- Worker-persisted chunk to browser-visible text P95 below 500 ms in the normal local environment.
- No fixed 250 ms delivery clustering for in-process notifications.
- Markdown parsing/render updates no more than once per animation frame.
- Target device steady-state goal: 55-60 FPS for a 2,000-character Markdown response.
- No sustained browser main-thread tasks longer than 50 ms during steady streaming.
- Terminal answer catches up within 250 ms.

## Acceptance Criteria

1. Only Runs whose normalized status is exactly `running` animate.
2. Every non-running Run renders its complete answer immediately, including legacy `completed` history.
3. All genuinely running Runs may animate independently.
4. Active answers remain character-level Markdown and progress monotonically.
5. Reconnect, checkpoint, replay, and background refresh never duplicate, erase, or replay visible history.
6. Event-bus notifications deliver without waiting for the database polling interval; cross-process events remain correct through 100 ms compensation polling.
7. Terminal completion never triggers a page-wide spinner or unmount.
8. Final text from stream, terminal event, persisted Run, and page reload is identical.
9. Complete Markdown supports GFM structures, remains responsive, and rejects unsafe HTML/URLs.
10. Focused tests, full frontend tests, backend Agent tests, production build, and real Edge scenarios pass.

## Rollout And Rollback

Implementation should be split into reviewable stages matching the TDD order. Frontend status/animation policy and page reconciliation can be rolled back independently from backend SSE cadence.

Rollout order:

1. Backend immediate wake-up plus compensation tests.
2. Frontend historical/active policy.
3. RAF scheduler.
4. Background reconciliation.
5. Markdown hardening and visual verification.

Rollback:

- If SSE cadence regresses ordering, restore the previous polling implementation while retaining frontend correctness fixes.
- If RAF animation regresses rendering, revert to direct target display for active Runs rather than restoring historical replay.
- If Markdown hardening breaks content, retain raw HTML disabled and roll back only presentation overrides.

No database migration is required by this design.
