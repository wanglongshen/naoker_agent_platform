import { api } from "@/lib/api";
import type { AgentAttachment, AgentSession, AgentRun, AgentRunEvent, AgentRunAttempt, AgentStep, AgentConversationStep, PaginatedResponse, AuditSessionTranscript } from "@/types/agent";


export const agentApi = {
  createSession: (title?: string, projectFolderId?: string | null) =>
    api<AgentSession>("/api/agent/sessions", {
      method: "POST",
      body: JSON.stringify({ title, project_folder_id: projectFolderId ?? undefined }),
      csrf: true,
    }),

  updateSessionProject: (sessionId: string, projectFolderId: string | null) =>
    api<{ project_folder_id: string | null; project_name: string }>(
      `/api/agent/sessions/${sessionId}/project`,
      { method: "PUT", body: JSON.stringify({ project_folder_id: projectFolderId }), csrf: true }
    ),

  listSessions: (page = 1, pageSize = 20) =>
    api<PaginatedResponse<AgentSession>>(`/api/agent/sessions?page=${page}&page_size=${pageSize}`),

  renameSession: (sessionId: string, title: string) =>
    api<AgentSession>(`/api/agent/sessions/${sessionId}/rename`, {
      method: "PUT",
      body: JSON.stringify({ title }),
      csrf: true,
    }),

  pinSession: (sessionId: string, pinned: boolean) =>
    api<AgentSession>(`/api/agent/sessions/${sessionId}/pin`, {
      method: "PATCH",
      body: JSON.stringify({ pinned }),
      csrf: true,
    }),

  deleteSession: (sessionId: string) =>
    api<void>(`/api/agent/sessions/${sessionId}`, {
      method: "DELETE",
      csrf: true,
    }),

  getSession: (sessionId: string, signal?: AbortSignal) =>
    api<AgentSession>(`/api/agent/sessions/${sessionId}`, { signal }),

  getSessionRuns: (sessionId: string, signal?: AbortSignal) =>
    api<AgentRun[]>(`/api/agent/sessions/${sessionId}/runs`, { signal }),

  createRun: (
    sessionId: string,
    body: { goal: string; network_enabled: boolean; attachment_ids: string[] }
  ) =>
    api<AgentRun>(`/api/agent/sessions/${sessionId}/runs`, {
      method: "POST",
      body: JSON.stringify(body),
      csrf: true,
    }),

  getRun: (runId: string, signal?: AbortSignal) =>
    api<AgentRun>(`/api/agent/runs/${runId}`, signal ? { signal } : {}),

  cancelRun: (runId: string) =>
    api<AgentRun>(`/api/agent/runs/${runId}/cancel`, {
      method: "POST",
      csrf: true,
    }),

  retryRun: (runId: string) =>
    api<AgentRun>(`/api/agent/runs/${runId}/retry`, {
      method: "POST",
      csrf: true,
    }),

  answerPendingQuestions: (runId: string, answers: Record<string, string>) =>
    api<AgentRun>(`/api/agent/runs/${runId}/answer`, {
      method: "POST",
      body: JSON.stringify({ answers }),
      csrf: true,
    }),

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

  getRunSteps: (runId: string, signal?: AbortSignal) =>
    api<AgentConversationStep[]>(`/api/agent/runs/${runId}/steps`, { signal }),

  getRunAttempts: (runId: string, page = 1, pageSize = 20) =>
    api<PaginatedResponse<AgentRunAttempt>>(`/api/agent/runs/${runId}/attempts?page=${page}&page_size=${pageSize}`),

  getAttemptSteps: (runId: string, attemptId: string, page = 1, pageSize = 50) =>
    api<PaginatedResponse<AgentStep>>(`/api/agent/runs/${runId}/attempts/${attemptId}/steps?page=${page}&page_size=${pageSize}`),

  uploadAttachment: (sessionId: string, formData: FormData) =>
    api<AgentAttachment>(`/api/agent/sessions/${sessionId}/attachments`, {
      method: "POST",
      body: formData,
      csrf: true,
    }),

  listAuditSessions: (page = 1, pageSize = 20) =>
    api<PaginatedResponse<AgentSession>>(`/api/agent/audit/sessions?page=${page}&page_size=${pageSize}`),

  getAuditSession: (sessionId: string) =>
    api<AgentSession>(`/api/agent/audit/sessions/${sessionId}`),

  listAuditSessionRuns: (sessionId: string) =>
    api<AgentRun[]>(`/api/agent/audit/sessions/${sessionId}/runs`),

  getAuditRunAttempts: (runId: string, page = 1, pageSize = 20) =>
    api<PaginatedResponse<AgentRunAttempt>>(`/api/agent/audit/runs/${runId}/attempts?page=${page}&page_size=${pageSize}`),

  getAuditAttemptSteps: (runId: string, attemptId: string, page = 1, pageSize = 50) =>
    api<PaginatedResponse<{ id: string; step_number: number }>>(`/api/agent/audit/runs/${runId}/attempts/${attemptId}/steps?page=${page}&page_size=${pageSize}`),

  getAuditRunEvents: (runId: string, cursor?: number | null, pageSize = 50) =>
    api<{ items: AgentRunEvent[]; next_seq: number | null }>(
      `/api/agent/audit/runs/${runId}/events?${new URLSearchParams({ ...(cursor ? { cursor: String(cursor) } : {}), page_size: String(pageSize) }).toString()}`
    ),

  getAuditRun: (runId: string) =>
    api<AgentRun>(`/api/agent/audit/runs/${runId}`),

  getAuditSessionTranscript: (sessionId: string) =>
    api<AuditSessionTranscript>(`/api/agent/audit/sessions/${sessionId}/transcript`),
};
