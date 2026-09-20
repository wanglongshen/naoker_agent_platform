import type { AgentRunStatus } from "@/types/agent";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8010";

export const STREAM_EVENT_TYPES = [
  "run_queued",
  "run_started",
  "plan_created",
  "step_completed",
  "run_retry_scheduled",
  "run_retry_resumed",
  "run_failed",
  "run_cancelled",
  "run_retried",
  "run_completed",
  "run_succeeded",
  "run_cancel_requested",
  "visible_thought_started",
  "visible_thought_delta",
  "visible_thought_completed",
  "visible_thought_failed",
  "visible_thought_paused",
  "tool_started",
  "tool_completed",
  "answer_started",
  "answer_delta",
  "answer_checkpoint",
  "answer_completed",
  "answer_failed",
] as const;

const TERMINAL_STATUSES = ["succeeded", "failed", "cancelled", "completed"] as const;

export function isTerminalAgentRunStatus(status: AgentRunStatus | "completed"): boolean {
  return TERMINAL_STATUSES.includes(status as (typeof TERMINAL_STATUSES)[number]);
}

export function streamUrlWithSeq(runId: string, afterSeq: number): string {
  const params = afterSeq > 0 ? `?after_seq=${afterSeq}` : "";
  return `${API_BASE_URL}/api/agent/runs/${runId}/stream${params}`;
}

export type StreamEventType = (typeof STREAM_EVENT_TYPES)[number];

export type StreamEvent = {
  seq: number;
  type: StreamEventType;
  run_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
};

export function parseStreamEvent(data: string): StreamEvent {
  const raw = JSON.parse(data) as Record<string, unknown>;
  return {
    seq: raw.seq as number,
    type: (raw.type ?? raw.event_type) as StreamEventType,
    run_id: raw.run_id as string,
    timestamp: (raw.timestamp ?? raw.created_at) as string,
    payload: (raw.payload ?? {}) as Record<string, unknown>,
  };
}

const FATAL_SSE_STATUSES = new Set([401, 403, 404, 410]);

export function isFatalSseStatus(status: number): boolean {
  return FATAL_SSE_STATUSES.has(status);
}
