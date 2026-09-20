export type AgentRunStatus = "queued" | "running" | "retry_wait" | "awaiting_question" | "succeeded" | "failed" | "cancel_requested" | "cancelled";

export type AgentAttemptStatus =
  | "queued"
  | "claimed"
  | "running"
  | "paused"
  | "retryable_failed"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "lease_expired";

export type AgentSession = {
  id: string;
  owner_user_id: string;
  owner_display_name: string;
  title: string | null;
  last_run_id: string | null;
  is_pinned?: boolean;
  created_at: string;
  updated_at: string;
};

export type AgentRun = {
  id: string;
  session_id: string;
  owner_user_id: string;
  goal: string;
  status: AgentRunStatus;
  mode: string;
  network_enabled: boolean;
  current_attempt_id: string | null;
  result: { final_answer?: string } | null;
  pending_questions?: { question: string; affects?: string }[] | null;
  failure_code?: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentRunAttempt = {
  id: string;
  run_id: string;
  attempt_number: number;
  status: AgentAttemptStatus;
  worker_id: string | null;
  retry_of_attempt_id: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type AgentRunEvent = {
  id: string;
  run_id: string;
  attempt_id: string | null;
  seq: number;
  event_type: string;
  type?: string;
  payload: Record<string, unknown>;
  created_at: string;
  timestamp?: string;
};

export type AgentAttachment = {
  id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  extraction_status: string;
  created_at: string;
};

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

export type PaginatedResponse<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

export type AgentConversationStep = {
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

export type AuditOwnerSummary = {
  id: string;
  username: string;
  display_name: string;
  roles: string[];
};

export type AuditTranscriptTurn = {
  run: AgentRun;
  steps: AgentStep[];
  events: AgentRunEvent[];
};

export type AuditSessionTranscript = {
  session: AgentSession;
  owner: AuditOwnerSummary;
  turns: AuditTranscriptTurn[];
};
