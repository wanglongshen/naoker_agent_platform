import { api } from "@/lib/api";
import type { PaginatedResponse } from "@/types/agent";

export interface TaskChainStage {
  id: string;
  stage: string;
  seq: number;
  status: string;
  attempt: number;
  output_payload: Record<string, unknown> | null;
  error: string;
  tokens: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface TaskChain {
  id: string;
  goal: string;
  status: string;
  current_stage: string;
  input_payload: Record<string, unknown>;
  result_file_id: string | null;
  feishu_doc_url: string;
  final_answer: string;
  error: string;
  total_tokens: number;
  points_cost: number;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  stages?: TaskChainStage[];
  duration_seconds?: number;
}

export interface TaskChainCreateInput {
  goal: string;
  input_payload: Record<string, unknown>;
}

export const taskChainApi = {
  create: (input: TaskChainCreateInput) =>
    api<TaskChain>("/api/task-chains", {
      method: "POST",
      body: JSON.stringify(input),
      csrf: true,
    }),

  list: (page = 1, pageSize = 20) =>
    api<PaginatedResponse<TaskChain>>(`/api/task-chains?page=${page}&page_size=${pageSize}`),

  get: (id: string) => api<TaskChain>(`/api/task-chains/${id}`),

  cancel: (id: string) =>
    api<TaskChain>(`/api/task-chains/${id}/cancel`, {
      method: "POST",
      csrf: true,
    }),
};
