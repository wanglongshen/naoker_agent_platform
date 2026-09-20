# Real-Time Answer Priority Design

## Goal

Make final-answer streaming visibly track received model output without a
synthetic typewriter backlog, preserve safe real-time Markdown rendering, and
align final-answer list markers with the neutral DeepSeek-like visual style.

Every visible final-answer update must be Markdown-rendered before browser
paint. The UI must never show a plain-text streaming fallback that later
changes into formatted Markdown.

## Current Behavior

The current final-answer path has two intentional queues after the provider
emits content:

```text
provider chunk
-> backend answer delta coalescing: 24 characters or 50 ms
-> persisted event and SSE
-> browser reducer target answer text
-> RAF typing scheduler: 2 to 48 characters per frame
-> incremental Markdown partitioner and active-tail render
```

The second queue makes the visual answer lag behind text that has already
arrived in the browser. It is useful for a typewriter effect but conflicts with
the product requirement that final answers feel as immediate as DeepSeek.

The first screenshot's blue bullets and ordered-list numbers are intentional
styling from:

```css
.final-answer-prose li::marker {
  color: #657cf4;
  font-weight: 700;
}
```

They are not emitted by Markdown or the model. DeepSeek-like answer styling
uses neutral inherited marker color.

## Design

### Final Answer Presentation Policy

Final answers use real-time streaming priority rather than typewriter replay.

```text
SSE answer_delta arrives
-> reducer appends target answer text
-> one pending requestAnimationFrame is scheduled
-> next frame exposes the newest complete target answer text
-> incremental Markdown renderer receives only the newest displayed prefix
```

Rules:

- There is at most one pending RAF for final-answer presentation.
- A burst of many `answer_delta` events before the next frame produces one
  visible update containing the latest accumulated answer text.
- The displayed final answer must not retain a character backlog after a frame
  runs; it catches up to the reducer target atomically.
- The final answer is never animated for historical, non-live, terminal, or
  reduced-motion content.
- The separate visible-thought animation may retain its controlled pacing.
- A reset occurs only when `answerStreamId` changes. A growing target with the
  same stream ID never clears or replays prior visible text.

The existing `useTypingText` remains available for visible thoughts. Add a
separate final-answer presentation hook instead of adding a mode flag that
mixes two different scheduling policies.

Suggested interface:

```ts
export function useLiveAnswerText(
  targetText: string,
  options: { enabled: boolean; resetKey: string | null },
): string;
```

Behavior:

```ts
if (!enabled || prefersReducedMotion) {
  return targetText;
}

// On each target update, retain the latest target in a ref.
// If no RAF is pending, schedule one.
// RAF callback performs exactly one setDisplayedText(latestTarget).
```

This maintains browser-paint coalescing while removing synthetic answer delay.

### Real-Time Markdown Rendering

Keep the existing append-only Markdown architecture:

```text
sealed Markdown block -> memoized SafeMarkdown -> stable DOM
active Markdown tail  -> bounded SafeMarkdown parse
terminal answer       -> canonical full-document SafeMarkdown render
```

The streaming answer always renders through `SafeMarkdown`. A provider prefix
such as `## 食材\n\n- 鸡蛋` becomes a rendered heading and list immediately;
raw Markdown markers are not shown as an interim presentation mode. The active
tail may be syntactically incomplete, but it is still passed through the safe
Markdown renderer using the newest available prefix.

The final-answer hook can produce larger displayed-text jumps. The incremental
partitioner must receive the complete newest prefix and seal all safe blocks
available in that prefix in one state transition. It must not iterate
character-by-character.

A text update may be painted only after the corresponding completed blocks and
active tail have been passed to `SafeMarkdown`; there is no plain-text final
answer branch during active generation.

The active-tail scheduler remains frame-coalesced and reads the newest snapshot
when a frame executes. It must preserve adaptive parse intervals:

| Active tail size | Minimum publish interval |
| --- | --- |
| 0-2,000 characters | 16 ms |
| 2,001-8,000 characters | 32 ms |
| More than 8,000 characters | 64 ms |

During a burst, intermediate tail states are intentionally discarded; only the
latest tail is rendered. This is correct because answer text is append-only and
the next frame contains the full latest prefix.

### Backend Answer Delta Cadence

The backend remains durable and event-sourced. It continues to persist answer
deltas before notification and retains checkpoints and `answer_completed`.

Make delta thresholds named settings:

```env
AGENT_ANSWER_FIRST_DELTA_IMMEDIATE=true
AGENT_ANSWER_DELTA_FLUSH_CHARACTERS=48
AGENT_ANSWER_DELTA_FLUSH_SECONDS=0.025
```

Rules:

- The first non-empty provider chunk of an answer stream flushes immediately.
- Subsequent chunks coalesce until 48 characters or 25 ms, whichever happens
  first.
- A checkpoint, provider completion, provider error, cancellation, and terminal
  event force a pending delta flush before their next event.
- Every delta remains committed before local or cross-process notification.
- The worker must not create one durable event per provider token under a
  high-rate stream.
- Existing cursor replay, direct same-process committed events, PostgreSQL
  notification, and compensation polling semantics remain unchanged.

This reduces initial response latency from the existing 50 ms cap while keeping
event rates bounded.

### Neutral Markdown Markers

Replace the final-answer list marker accent color with inherited text color:

```css
.final-answer-prose li::marker {
  color: currentColor;
  font-weight: 700;
}
```

This changes only bullets and ordered-list numbers. Links, focus rings,
checkbox accent color, quote borders, code blocks, and tables retain their
existing styles.

## Error Handling And Accessibility

- `prefers-reduced-motion` renders all final-answer text immediately with no
  RAF.
- Historical and terminal answer rendering remains static.
- New stream IDs reset answer presentation; same-stream target growth is
  monotonic and never clears visible content.
- Markdown rendering continues `skipHtml`, safe href classification, protected
  external links, focusable code scroll, and focusable table scroll.
- No answer text, prompt text, tool data, credentials, or attachments are
  logged by latency instrumentation.

## Measurements

Add content-free browser performance marks or counters for:

```text
answer_delta_reduced
answer_frame_scheduled
answer_frame_committed
markdown_tail_published
```

Add server-side timing around:

```text
provider_chunk_received
first_answer_delta_committed
answer_delta_committed
sse_frame_emitted
```

Permitted dimensions are run ID, stream ID, sequence number, wake-up source,
and duration. Do not log text content.

## Tests

### Frontend

- Multiple answer target updates before one RAF yield one frame and display the
  newest full target.
- No final-answer character backlog remains after the RAF callback.
- Same stream growth never clears previously displayed text.
- A new stream ID resets the displayed answer before its first live frame.
- Reduced-motion, terminal, historical, and non-live answers render fully with
  no queued RAF.
- A burst containing multiple Markdown block boundaries seals all completed
  blocks and preserves their DOM identity on later tail growth.
- Live headings, lists, tables, and fenced code blocks are visible as rendered
  Markdown before `answer_completed`; no raw `#`, `-`, `|`, or code fence is
  used as an intermediate final-answer display.
- Active-tail parse publishes only the latest snapshot and respects 16/32/64 ms
  cadence.
- List markers inherit neutral answer color.

### Backend

- First non-empty provider chunk emits an answer delta without waiting for the
  normal coalescing timeout.
- Subsequent short chunks flush by the configured 25 ms maximum.
- Subsequent rapid chunks flush at the 48-character threshold.
- Completion and failure flush pending answer content before terminal events.
- Existing checkpoint, offset, replay, and failure behavior remains correct.

## Acceptance Criteria

1. A received final-answer delta becomes visible by the next browser frame,
   rather than after a typewriter catch-up queue.
2. Rapid deltas produce at most one final-answer React state update per frame.
3. The rendered final answer does not visually lag the reducer target by more
   than one pending frame under normal browser load.
4. Real-time Markdown remains visible throughout active generation.
5. Every final-answer update is Markdown-rendered before browser paint; there
   is no plain-text-to-Markdown visual transition.
6. Completed Markdown blocks remain memoized and stable.
7. The first provider answer chunk is not deliberately delayed by the normal
   25 ms or size threshold.
8. Subsequent provider chunks do not create unbounded durable event volume.
9. Final-answer bullets and ordered-list numbers use neutral text color rather
   than blue accent color.
10. Historical, terminal, and reduced-motion behavior remains static and safe.

## Out Of Scope

- Changing thought narrative animation policy.
- Replacing the Markdown renderer or adding a rich-text editor.
- Removing durable answer events or cursor replay.
- Changing user-facing answer wording or model prompts.
