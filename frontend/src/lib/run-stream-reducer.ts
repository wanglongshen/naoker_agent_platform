import type { AgentRun, AgentRunEvent, AgentRunStatus } from "@/types/agent";

type StreamEventType =
  | "run_queued"
  | "run_started"
  | "plan_created"
  | "step_completed"
  | "run_retry_scheduled"
  | "run_retry_resumed"
  | "run_failed"
  | "run_cancelled"
  | "run_retried"
  | "run_completed"
  | "run_succeeded"
  | "run_cancel_requested"
  | "visible_thought_started"
  | "visible_thought_delta"
  | "visible_thought_completed"
  | "visible_thought_failed"
  | "visible_thought_paused"
  | "plan_started"
  | "plan_delta"
  | "plan_completed"
  | "tool_started"
  | "tool_completed"
  | "answer_started"
  | "answer_delta"
  | "answer_checkpoint"
  | "answer_completed"
  | "answer_failed";

type StreamEvent = {
  seq: number;
  type: StreamEventType;
  run_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
};

export type RunStreamConnection = "connecting" | "open" | "reconnecting" | "failed" | "closed";

type VisibleThoughtStreamState = {
  stepIndex: number;
  text: string;
};

export type RunStreamState = {
  run: AgentRun | null;
  events: AgentRunEvent[];
  narrativeEvents: AgentRunEvent[];
  lastSeq: number;
  connection: RunStreamConnection;
  answerText: string;
  answerStreamId: string | null;
  visibleThoughtByStep: Record<number, string>;
  visibleThoughtStreamIds: Record<number, string>;
  liveStreamed: boolean;
};

type InitialStateOptions = {
  initialEvents?: AgentRunEvent[];
  initialRun?: AgentRun;
  disabled?: boolean;
};

const TERMINAL_STATUSES = new Set<AgentRunStatus>(["succeeded", "failed", "cancelled"]);

export function shouldResetRunStreamState(previousRunId: string | null, nextRunId: string): boolean {
  return previousRunId !== nextRunId;
}

function normalizeRunEventToStreamEvent(event: AgentRunEvent): StreamEvent {
  return {
    seq: event.seq,
    type: (event.type ?? event.event_type) as StreamEventType,
    run_id: event.run_id,
    timestamp: event.timestamp ?? event.created_at,
    payload: event.payload,
  };
}

function streamEventToRunEvent(event: StreamEvent): AgentRunEvent {
  return {
    id: `${event.run_id}:${event.seq}`,
    run_id: event.run_id,
    attempt_id: null,
    seq: event.seq,
    event_type: event.type,
    type: event.type,
    payload: event.payload,
    created_at: event.timestamp,
    timestamp: event.timestamp,
  };
}

export function createInitialRunStreamState(options: InitialStateOptions = {}): RunStreamState {
  const persistedFinalAnswer =
    options.initialRun?.status !== "running" && options.initialRun?.result?.final_answer?.trim()
      ? options.initialRun.result.final_answer
      : null;
  const baseState: RunStreamState = {
    run: options.initialRun ?? null,
    events: [],
    narrativeEvents: [],
    lastSeq: 0,
    connection:
      options.disabled ? "closed" :
      options.initialRun && TERMINAL_STATUSES.has(options.initialRun.status) ? "closed" : "connecting",
    answerText: options.initialRun?.result?.final_answer ?? "",
    answerStreamId: null,
    visibleThoughtByStep: {},
    visibleThoughtStreamIds: {},
    liveStreamed: false,
  };

  const sortedEvents = [...(options.initialEvents ?? [])].sort((a, b) => a.seq - b.seq);
  return sortedEvents.reduce(
    (state, event) => {
      const streamEvent = normalizeRunEventToStreamEvent(event);
      const nextState = reduceRunStream(state, streamEvent);
      if (!persistedFinalAnswer || !streamEvent.type.startsWith("answer_")) {
        return nextState;
      }
      return {
        ...nextState,
        answerText: persistedFinalAnswer,
        run: setRunFinalAnswer(nextState.run, persistedFinalAnswer),
      };
    },
    baseState
  );
}

function appendEvent(events: AgentRunEvent[], event: StreamEvent): AgentRunEvent[] {
  const nextEvent = streamEventToRunEvent(event);
  if (events.some((item) => item.seq === nextEvent.seq)) {
    return events;
  }
  return [...events, nextEvent];
}

export function isNarrativeEvent(event: StreamEvent): boolean {
  return !event.type.startsWith("answer_");
}

function maybeNarrativeAppend(state: RunStreamState, event: StreamEvent): AgentRunEvent[] {
  return isNarrativeEvent(event)
    ? appendEvent(state.narrativeEvents, event)
    : state.narrativeEvents;
}

function readText(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" ? value : null;
}

function finalAnswerFromPayload(payload: Record<string, unknown>): string | null {
  const answer = readText(payload, "final_answer") ?? readText(payload, "text");
  return answer?.trim() ? answer : null;
}

function readNumber(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readStepIndex(payload: Record<string, unknown>): number | null {
  const stepIndex = readNumber(payload, "step_index");
  return stepIndex === null ? null : stepIndex;
}

function setRunStatus(run: AgentRun | null, status: AgentRunStatus): AgentRun | null {
  return run ? { ...run, status } : run;
}

function setRunFinalAnswer(run: AgentRun | null, answerText: string, status?: AgentRunStatus): AgentRun | null {
  if (!run) {
    return run;
  }
  return {
    ...run,
    ...(status ? { status } : {}),
    result: {
      ...(run.result ?? {}),
      final_answer: answerText,
    },
  };
}

function applyVisibleThoughtSnapshot(
  state: RunStreamState,
  event: StreamEvent,
  streamId: string | null,
  thought: VisibleThoughtStreamState
): RunStreamState {
  return {
    ...state,
    lastSeq: event.seq,
    events: appendEvent(state.events, event),
    narrativeEvents: maybeNarrativeAppend(state, event),
    visibleThoughtByStep: {
      ...state.visibleThoughtByStep,
      [thought.stepIndex]: thought.text,
    },
    visibleThoughtStreamIds: streamId
      ? {
          ...state.visibleThoughtStreamIds,
          [thought.stepIndex]: streamId,
        }
      : state.visibleThoughtStreamIds,
  };
}

const TERMINAL_EVENT_TYPES = ["run_succeeded", "run_completed", "run_failed", "run_cancelled", "answer_completed"];

export function hasTerminalEvidence(events: AgentRunEvent[]): boolean {
  return events.some((event) => TERMINAL_EVENT_TYPES.includes(event.event_type));
}

const AUTHORITATIVE_TERMINAL_STATUSES = new Set<AgentRunStatus>(["succeeded", "failed", "cancelled"]);
const AUTHORITATIVE_TERMINAL_EVENT_TYPES = ["run_succeeded", "run_completed", "run_failed", "run_cancelled"];

export function hasAuthoritativeTerminalEvidence(run: AgentRun | null | undefined, events: AgentRunEvent[]): boolean {
  if (run && AUTHORITATIVE_TERMINAL_STATUSES.has(run.status)) return true;
  return events.some((e) => AUTHORITATIVE_TERMINAL_EVENT_TYPES.includes(e.event_type));
}

export function hasCompletedAnswerEvidence(events: AgentRunEvent[]): boolean {
  return events.some(
    (e) =>
      e.event_type === "answer_completed" &&
      typeof (e.payload as any)?.text === "string" &&
      (e.payload as any).text.trim().length > 0,
  );
}

export function shouldOpenRunStream(run: AgentRun, isLatestTurn: boolean, events: AgentRunEvent[]): boolean {
  return isLatestTurn && !hasAuthoritativeTerminalEvidence(run, events);
}

export function reduceRunStream(state: RunStreamState, event: StreamEvent): RunStreamState {
  if (event.seq <= state.lastSeq) {
    return state;
  }

  switch (event.type) {
    case "run_started":
      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
        run: setRunStatus(state.run, "running"),
      };
    case "run_completed":
      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
        run: setRunStatus(state.run, "succeeded") ? { ...setRunStatus(state.run, "succeeded")!, updated_at: event.timestamp } : null,
      };
    case "run_succeeded": {
      const finalAnswer = finalAnswerFromPayload(event.payload);
      const hasFinalAnswer = finalAnswer !== null;
      const updatedRun = (hasFinalAnswer
        ? setRunFinalAnswer(state.run, finalAnswer, "succeeded")
        : setRunStatus(state.run, "succeeded"));
      const runWithTimestamp = updatedRun ? { ...updatedRun, updated_at: event.timestamp } : null;
      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
        run: runWithTimestamp,
        answerText: hasFinalAnswer && !state.answerText ? finalAnswer : state.answerText,
        connection: "closed",
      };
    }
    case "run_failed": {
      const failed = setRunStatus(state.run, "failed");
      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
        run: failed ? { ...failed, updated_at: event.timestamp } : null,
      };
    }
    case "run_cancelled": {
      const cancelled = setRunStatus(state.run, "cancelled");
      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
        run: cancelled ? { ...cancelled, updated_at: event.timestamp } : null,
      };
    }
    case "answer_started": {
      const streamId = readText(event.payload, "stream_id");
      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
        answerText: "",
        answerStreamId: streamId,
      };
    }
    case "answer_checkpoint": {
      const streamId = readText(event.payload, "stream_id");
      const text = readText(event.payload, "text") ?? state.answerText;
      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
        answerText: text,
        answerStreamId: streamId ?? state.answerStreamId,
      };
    }
    case "answer_delta": {
      const offset = readNumber(event.payload, "offset") ?? 0;
      const delta = readText(event.payload, "delta") ?? "";
      const streamId = readText(event.payload, "stream_id");
      const streamIdMismatch =
        state.answerStreamId !== null && streamId !== null && state.answerStreamId !== streamId;

      if (streamIdMismatch || offset !== state.answerText.length) {
        return { ...state, connection: "reconnecting" };
      }

      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
        answerText: state.answerText + delta,
        answerStreamId: streamId ?? state.answerStreamId,
      };
    }
    case "answer_failed": {
      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
        connection: "reconnecting",
      };
    }
    case "answer_completed": {
      const finalText = finalAnswerFromPayload(event.payload) ?? state.answerText;
      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
        answerText: finalText,
        run: setRunFinalAnswer(state.run, finalText),
      };
    }
    case "visible_thought_started": {
      const streamId = readText(event.payload, "stream_id");
      const stepIndex = readStepIndex(event.payload);
      if (stepIndex === null) {
        return {
          ...state,
          lastSeq: event.seq,
          events: appendEvent(state.events, event),
          narrativeEvents: maybeNarrativeAppend(state, event),
        };
      }

      return applyVisibleThoughtSnapshot(state, event, streamId, {
        stepIndex,
        text: "",
      });
    }
    case "visible_thought_completed": {
      const stepIndex = readStepIndex(event.payload);
      if (stepIndex === null) {
        return {
          ...state,
          lastSeq: event.seq,
          events: appendEvent(state.events, event),
          narrativeEvents: maybeNarrativeAppend(state, event),
        };
      }

      return applyVisibleThoughtSnapshot(state, event, readText(event.payload, "stream_id"), {
        stepIndex,
        text: readText(event.payload, "text") ?? state.visibleThoughtByStep[stepIndex] ?? "",
      });
    }
    case "visible_thought_delta": {
      const stepIndex = readStepIndex(event.payload);
      const offset = readNumber(event.payload, "offset") ?? 0;
      const delta = readText(event.payload, "delta") ?? "";
      const streamId = readText(event.payload, "stream_id");
      if (stepIndex === null) {
        return { ...state, connection: "reconnecting" };
      }

      const currentText = state.visibleThoughtByStep[stepIndex] ?? "";
      const currentStreamId = state.visibleThoughtStreamIds[stepIndex] ?? null;
      const streamIdMismatch =
        currentStreamId !== null && streamId !== null && currentStreamId !== streamId;

      if (streamIdMismatch || offset !== currentText.length) {
        return { ...state, connection: "reconnecting" };
      }

      return applyVisibleThoughtSnapshot(state, event, streamId ?? currentStreamId, {
        stepIndex,
        text: currentText + delta,
      });
    }
    case "plan_started": {
      const streamId = readText(event.payload, "stream_id");
      const stepIndex = readStepIndex(event.payload);
      if (stepIndex === null) {
        return {
          ...state,
          lastSeq: event.seq,
          events: appendEvent(state.events, event),
          narrativeEvents: maybeNarrativeAppend(state, event),
        };
      }
      return applyVisibleThoughtSnapshot(state, event, streamId, {
        stepIndex,
        text: "",
      });
    }
    case "plan_completed": {
      const stepIndex = readStepIndex(event.payload);
      if (stepIndex === null) {
        return {
          ...state,
          lastSeq: event.seq,
          events: appendEvent(state.events, event),
          narrativeEvents: maybeNarrativeAppend(state, event),
        };
      }
      return applyVisibleThoughtSnapshot(state, event, readText(event.payload, "stream_id"), {
        stepIndex,
        text: readText(event.payload, "text") ?? state.visibleThoughtByStep[stepIndex] ?? "",
      });
    }
    case "plan_delta": {
      const stepIndex = readStepIndex(event.payload);
      const offset = readNumber(event.payload, "offset") ?? 0;
      const delta = readText(event.payload, "delta") ?? "";
      const streamId = readText(event.payload, "stream_id");
      if (stepIndex === null) {
        return { ...state, connection: "reconnecting" };
      }
      const currentText = state.visibleThoughtByStep[stepIndex] ?? "";
      const currentStreamId = state.visibleThoughtStreamIds[stepIndex] ?? null;
      const streamIdMismatch =
        currentStreamId !== null && streamId !== null && currentStreamId !== streamId;
      if (streamIdMismatch || offset !== currentText.length) {
        return { ...state, connection: "reconnecting" };
      }
      return applyVisibleThoughtSnapshot(state, event, streamId ?? currentStreamId, {
        stepIndex,
        text: currentText + delta,
      });
    }
    default:
      return {
        ...state,
        lastSeq: event.seq,
        events: appendEvent(state.events, event),
        narrativeEvents: maybeNarrativeAppend(state, event),
      };
  }
}
