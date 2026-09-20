# Run Terminal Consistency Design

## Goal

Prevent historical conversations from displaying a complete final answer while
still showing "thinking". A successful answer must have consistent durable run,
attempt, result, and terminal-event state; historical turns must never open
live SSE connections.

## Problem

Final answer generation currently commits `answer_completed` before a later
transaction commits the step, attempt status, run status, result projection,
and `run_succeeded`. A worker shutdown or failure between these transactions
can leave a durable complete answer paired with a `running` run.

The API projects a final answer from `answer_completed` events at read time
without changing the raw run status. The frontend then renders the answer and
also renders the stale status as "thinking", attaches SSE to historical turns,
and increments the thinking timer.

## Invariants

For a successful completed answer, one transaction must commit:

```text
answer_completed
step_completed
attempt.status = succeeded
run.status = succeeded
run.result.final_answer
run_succeeded
```

If the guarded attempt or run transition fails, the transaction must roll back
and must not append `run_succeeded` or persist the final result.

Historical turns are static and must not create `EventSource`. A session has at
most one live stream: its latest running turn that lacks terminal evidence.

## Backend Design

Move terminal answer completion into the existing terminal persistence method.
The streaming method may collect answer text and emit nonterminal deltas, but
does not commit a terminal completion event separately. The final answer,
completed step, run status, attempt status, result, and `run_succeeded` are
written in one short event session transaction, then a post-commit notification
is published.

`source_event_sequence` stores `event.seq`, never the event primary-key UUID.

Worker lease recovery writes durable retry/failure events and publishes
notifications. A new idempotent repair command detects legacy runs with a
completed-answer event, no `run_succeeded`, and an expired/non-owned attempt.
It supports `--dry-run` by default and `--apply` to reconcile eligible records
to succeeded with a terminal event.

## API And Frontend Design

API responses retain raw status and include a safe terminal-evidence field:

```text
persisted_terminal
run_succeeded_event
answer_completed_event
none
```

For a non-live historical turn, `answer_completed_event` is sufficient display
evidence to show a completed answer without presenting "thinking". It does not
rewrite backend status. A live running turn with only `answer_completed` keeps
active semantics until the existing canonical terminal reconciliation confirms
the run status.

Only the latest session turn satisfying `status === "running"` and no terminal
evidence enables `useRunEventStream`. All other turns render the REST snapshot
and persisted events statically.

## Tests

- Simulated success commits all terminal records and events atomically.
- Guarded transition failure writes no final result or terminal event.
- Running + answer_completed + expired attempt is repaired idempotently.
- Historical answer-completed turn is displayed completed, has no timer, and
  creates no EventSource.
- Latest running turn creates one EventSource; older turns do not.
- A live answer-completed run remains active until canonical reconciliation.

## Out Of Scope

- Changing provider protocol or answer Markdown rendering.
- Inferring successful completion for active live runs without canonical server
  evidence.
- Exposing repair diagnostics in the ordinary user transcript.
