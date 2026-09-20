# Conversation Stream Reliability And Speed Design

## Goal

Eliminate duplicate visible thoughts, endless active-run SSE reconnects,
historical typing replay, slow live Markdown presentation, and tool timeline
misalignment. Preserve durable event replay, safe visible-thought content,
cross-process SSE correctness, and live Markdown rendering.

## Scope

This design covers six focused changes:

1. Prevent tool-resume visible thoughts from repeating pre-tool thought text.
2. Reconcile terminal server state when the browser receives an answer but
   misses the terminal run event.
3. Render historical and non-live conversations statically.
4. Reduce live Markdown presentation latency without reparsing completed
   blocks.
5. Avoid a database event read for ordinary same-process post-commit SSE
   delivery while retaining database-authoritative cross-process recovery.
6. Align tool call markers with reasoning markers on the same timeline axis.

The design does not change the provider chunk protocol, remove durable agent
events, introduce Redis, move the worker into FastAPI, or weaken Markdown URL
and HTML safety.

## Problem Evidence

### Duplicate visible thoughts

The worker generates a visible thought before a tool call with stream ID:

```text
visible-thought-{run_id}-{step_index}
```

After the tool completes, it intentionally generates a second visible thought
with stream ID:

```text
visible-thought-{run_id}-{step_index}-resume
```

The resume prompt does not prohibit the model from repeating the prior
thought. The frontend correctly displays both distinct stream IDs, so repeated
sentence prefixes appear in two adjacent reasoning blocks.

### Endless thinking and SSE reconnects

`answer_completed` updates visible answer text but does not make the local run
terminal. Only `run_succeeded`, `run_failed`, or `run_cancelled` ends local
streaming state. If the server has a terminal run state but the browser cursor
does not receive the terminal event, the server closes the SSE response and
native EventSource reconnects indefinitely with the same cursor. The UI keeps
counting thinking time even though it already displays a final answer.

### Historical animation

Final answers animate only for `running` runs, but thought narrative code
treats `queued` as thinking and can mount typing hooks for restored visible
thought blocks. A historical run with replayed events can therefore appear to
type even though it is not the current live stream.

### Slow live Markdown

Completed Markdown blocks are memoized, but the active tail is published on a
fixed 80 ms timer. A user sees this as extra latency after the RAF text
scheduler exposes text. Long unsealed tails also grow more expensive to parse.

### Same-process SSE event read

After a worker commits an event, the local event bus currently only publishes
`{run_id, seq}`. The local SSE generator then queries the database to read the
same event before encoding it. The database query is necessary for replay and
cross-process notifications, but not for a same-process event object already
committed by the worker.

### Tool marker alignment

The reasoning rail marker and tool record icon use different horizontal
coordinate systems. The tool icon center is offset from the reasoning marker
center instead of sharing the timeline axis.

## Design

### 1. Visible Thought Resume Deduplication

Keep pre-tool and post-tool thought phases separate because they carry distinct
user-facing meaning. The resume prompt must include the finalized pre-tool
thought and require only new progress after tool execution.

The resume prompt adds this constraint:

```text
Do not repeat, paraphrase, extend, or include any complete sentence or
continuous phrase from the previous visible explanation. Describe only the new
progress revealed by the tool result and the next action that will use it.
```

Prompt constraints alone are insufficient. Before persisting resume deltas and
completion, apply a deterministic overlap guard:

```python
def remove_visible_thought_overlap(previous_text: str, resumed_text: str) -> str
```

Rules:

- Normalize repeated whitespace for comparison without changing the final
  non-overlapping visible suffix.
- Find the longest suffix of `previous_text` that equals a prefix of
  `resumed_text`.
- Remove an overlap only when it is at least 12 characters and comprises at
  least 25 percent of the resumed text.
- Preserve unrelated text and short shared phrases.
- If removal leaves no displayable content, use the existing safe visible
  thought fallback for the action type.
- Never include raw tool output, provider errors, prompt content, secrets, or
  credentials in visible thoughts.

### 2. Terminal State Reconciliation

The browser must explicitly reconcile a run after an SSE response ends while
the local state remains non-terminal.

`useRunEventStream` adds a single-flight terminal reconciliation operation:

```ts
async function reconcileTerminalRun(runId: string): Promise<AgentRun | null>
```

On an SSE error or clean closure where local state is still `running`:

1. Prevent duplicate reconciliation requests for the same stream generation.
2. Fetch the canonical run detail.
3. If status is `succeeded`, `failed`, or `cancelled`, merge it into local
   state, retain the richer local answer text, close EventSource, cancel the
   reconnect timer, and invoke the existing terminal callback once.
4. If status remains non-terminal, use the existing bounded reconnect policy.
5. If reconciliation fails, preserve local text and continue the bounded
   reconnect policy.

The backend SSE generator continues final cursor catch-up before closing. It
also detects and logs terminal-state/event mismatch: a terminal run that has
no corresponding terminal event after final catch-up. It must not fabricate an
event. Browser reconciliation provides the safe recovery path.

### 3. Shared Live Animation Eligibility

Create a shared animation predicate:

```ts
export function isActivelyStreamingRun(status: string, isLiveRun: boolean): boolean {
  return isLiveRun && status === "running";
}
```

`isLiveRun` means the latest run currently attached to EventSource on this
session page. It is not inferred from historical status alone.

Apply this predicate to FinalAnswerPanel, ThoughtNarrative, and typing hooks.
Only the current active and unfinished thought block may use `useTypingText`:

```ts
const shouldAnimateThought = isActivelyStreamingRun(run.status, isLiveRun)
  && block.id === activeReasoningId
  && !block.completed;
```

The following always render fully and statically on first paint:

```text
queued
retry_wait
cancel_requested
succeeded
completed
failed
cancelled
unknown
running runs that are not the page's live run
```

### 4. Live Markdown Presentation Cadence

Keep the existing append-only Markdown partitioning model:

```text
completed block -> memoized SafeMarkdown -> never reparsed
active tail     -> SafeMarkdown -> bounded live reparsing
terminal answer -> full SafeMarkdown render once
```

Replace the fixed 80 ms active-tail timer with an RAF-coalesced publisher. The
tail parser runs at these bounded cadences:

| Active tail size | Minimum interval |
| --- | --- |
| 0-2,000 characters | 16 ms |
| 2,001-8,000 characters | 32 ms |
| More than 8,000 characters | 64 ms |

Rules:

- At most one active-tail parse is scheduled at a time.
- A scheduled callback reads the latest partition snapshot, not a stale text
  closure.
- Completed blocks publish immediately when a safe block boundary is sealed.
- The display scheduler retains one `slice()` and one state update per RAF.
- Non-terminal text reveal uses adaptive counts: 2, 6, 12, 20, 32, and 48
  characters per frame by backlog band, never more than 48.
- Large unsealed tails remain bounded by the 64 ms parser interval until a
  paragraph, table, list, or code boundary can seal a completed block.
- `prefers-reduced-motion` still exposes all text immediately.

### 5. Same-Process Direct SSE Frames

Retain two post-commit notification forms:

```python
@dataclass(frozen=True)
class PersistedEvent:
    run_id: UUID
    seq: int

@dataclass(frozen=True)
class CommittedEvent:
    run_id: UUID
    seq: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
```

Worker paths create and commit an event before publishing either signal.

Same-process worker-to-SSE delivery publishes `CommittedEvent` after commit.
The SSE generator can emit it directly only when:

```text
event.seq == last_seen_seq + 1
```

For stale, duplicate, or sequence-gap events, SSE uses the existing persisted
cursor query. PostgreSQL LISTEN/NOTIFY remains `{run_id, seq}` only and always
uses the database fetch path. Initial replay, reconnect, cross-process gap
repair, and compensation polling remain database-authoritative.

The SSE generator detects terminal events from emitted direct or persisted
events and closes cleanly after final catch-up. It no longer performs a run
status query on every local wake-up; status reads occur on compensation poll
and terminal reconciliation paths.

### 6. Tool Timeline Alignment

Tool records become relative positioning contexts. Tool icons use absolute
coordinates centered on the same rail as reasoning markers:

```css
.thought-tool-record {
  position: relative;
}

.thought-tool-record-icon {
  position: absolute;
  left: -28px;
  top: 7px;
  margin: 0;
}
```

The icon aligns to the tool label's first text line instead of the center of a
potentially multi-line card. Existing mobile sizing and tool text layout remain
unchanged.

## Error Handling And Observability

Add safe structured logs and metrics without answer text, prompts, tool input,
tool output, cookies, JWTs, attachments, or secrets.

Required fields:

```text
run_id
attempt_id
seq
event_type
stream_generation
wakeup_source
listener_state
latency_ms
```

Required metrics:

- terminal reconciliation requested, succeeded, failed, and deduplicated;
- terminal-state/event mismatch count;
- provider chunk received to durable event commit latency;
- event commit to SSE frame latency;
- SSE frame to visible text latency;
- direct same-process frame count;
- persisted replay fallback count;
- active-tail parse cadence and active-tail size;
- EventSource reconnect count and close reason.

## Tests

### Backend

- Resume prompt includes prior visible thought and explicit non-repetition rule.
- Overlap guard removes a repeated prefix, preserves short shared phrases, and
  uses fallback for fully duplicated resume text.
- Normal and terminal event transactions publish a committed post-commit event.
- Direct event sequence emits without database event query when contiguous.
- Gaps, duplicates, and cross-process persisted notifications use cursor
  recovery.
- Terminal database status with a missing terminal event logs mismatch and
  closes after final catch-up without inventing data.

### Frontend

- Answer completed followed by SSE close and canonical succeeded run detail
  stops timer, closes EventSource, and prevents reconnect.
- Reconciliation that reports still-running retains reconnect behavior.
- Historical queued, retry, terminal, unknown, and non-live running turns do
  not create typing frames.
- Live active reasoning still types; completed reasoning remains static.
- Short tail publishes within a frame; large tail observes the 64 ms cap.
- A completed Markdown block retains DOM identity while the tail grows.
- Per-frame visible text growth never exceeds 48 characters.
- Tool record icon exposes the expected alignment class and relative positioning
  contract.

## Acceptance Criteria

1. Tool-resume visible thoughts do not repeat a meaningful pre-tool prefix.
2. An answer shown without a received terminal event becomes terminal after one
   successful canonical run reconciliation.
3. No repeated SSE requests use the same cursor after terminal reconciliation.
4. Thinking duration stops when the run becomes terminal.
5. Historical conversations never animate their final answers or reasoning.
6. Live Markdown tail update latency is 16-64 ms by size, not a fixed 80 ms.
7. Completed Markdown blocks do not reparse when only the active tail grows.
8. Non-terminal visual reveal is bounded to 48 characters per frame.
9. Same-process contiguous committed events are encoded without an additional
   event-table query.
10. Cross-process replay, duplicate notification, sequence gap, reconnect, and
    compensation polling preserve strict sequence order with no event loss.
11. Tool markers and reasoning markers share a common horizontal timeline axis.

## Out Of Scope

- Provider protocol changes or exposing provider chain-of-thought.
- Persisting raw unhandled exception text in user-visible data.
- Replacing PostgreSQL notifications with Redis.
- Removing PostgreSQL cursor replay or persistent event history.
- Full Markdown AST incremental patching or a rich-text editor framework.
