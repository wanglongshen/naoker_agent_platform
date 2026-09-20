interface ApiEnvelope<T> {
  data: T;
  message: string;
  request_id: string;
}

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;
  requestId?: string;

  constructor(status: number, code: string, message: string, details: unknown, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

type ApiInit = RequestInit & { csrf?: boolean };

export async function api<T>(path: string, init?: ApiInit): Promise<T> {
  const headers: Record<string, string> = {};

  if (init?.body && !(init.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  if (init?.csrf) {
    try {
      const csrfResp = await fetch(`${BASE_URL}/api/auth/csrf`, { credentials: "include" });
      if (csrfResp.ok) {
        const csrfBody = await csrfResp.json();
        const token = csrfBody?.data?.token ?? csrfBody?.token;
        if (token) {
          headers["X-CSRF-Token"] = token;
        }
      }
    } catch {
      // proceed without CSRF token
    }
  }

  const { csrf: _, ...fetchInit } = init ?? ({} as ApiInit);

  const response = await fetch(`${BASE_URL}${path}`, {
    ...fetchInit,
    credentials: "include",
    cache: "no-store",
    headers: {
      ...headers,
      ...(fetchInit?.headers as Record<string, string> | undefined),
    },
  });

  if (!response.ok) {
    let body: { code?: string; message?: string; details?: unknown; request_id?: string } = {};
    try {
      body = await response.json();
    } catch {
      // response may not be JSON
    }
    throw new ApiError(
      response.status,
      body.code ?? "UNKNOWN_ERROR",
      body.message ?? response.statusText,
      body.details ?? null,
      body.request_id ?? response.headers.get("X-Request-ID") ?? undefined
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const body = await response.json();

  if (body && typeof body === "object" && "data" in body) {
    return body.data as T;
  }

  return body as T;
}

export async function submitLoginPhone(sessionId: string, phone: string) {
  return api<{ status: string }>(`/api/agent/login-sessions/${sessionId}/phone`, {
    method: "POST",
    body: JSON.stringify({ phone }),
    csrf: true,
  });
}

export async function submitLoginCode(sessionId: string, code: string) {
  return api<{ status: string }>(`/api/agent/login-sessions/${sessionId}/verify`, {
    method: "POST",
    body: JSON.stringify({ code }),
    csrf: true,
  });
}

export interface FeishuConfigItem {
  id: string;
  name: string;
  app_id_mask: string;
  is_default: boolean;
}

export async function listFeishuConfigs() {
  return api<{ configs: FeishuConfigItem[] }>("/api/feishu/configs");
}

export async function createFeishuConfig(data: { name: string; app_id: string; app_secret: string }) {
  return api<FeishuConfigItem>("/api/feishu/configs", {
    method: "POST",
    body: JSON.stringify(data),
    csrf: true,
  });
}

export async function updateFeishuConfig(
  id: string,
  data: { name?: string; app_id?: string; app_secret?: string },
) {
  return api<FeishuConfigItem>(`/api/feishu/configs/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
    csrf: true,
  });
}

export async function deleteFeishuConfig(id: string) {
  return api<{ deleted: boolean }>(`/api/feishu/configs/${id}`, {
    method: "DELETE",
    csrf: true,
  });
}

export async function activateFeishuConfig(id: string) {
  return api<{ activated: boolean }>(`/api/feishu/configs/${id}/activate`, {
    method: "POST",
    csrf: true,
  });
}

export async function getFeishuConfigStatus() {
  return api<{ configured: boolean; app_id: string | null }>("/api/feishu/configs/status");
}

export interface GenerationLog {
  id: string;
  folder_id: string | null;
  folder_name: string;
  user_id: string;
  session_id: string;
  run_id: string;
  input_text: string;
  final_md_file_id: string | null;
  final_answer: string;
  feishu_doc_url: string;
  status: string;
  error: string;
  created_at: string;
}

export async function createGeneration(sessionId: string, runId: string) {
  return api<{ log: GenerationLog }>("/api/generations", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, run_id: runId }),
    csrf: true,
  });
}

export interface GenerationTimelineStep {
  type: "thought" | "tool" | "answer" | "terminal";
  step_index?: number;
  content?: string;
  action_type?: string;
  input?: Record<string, unknown>;
  observation?: string;
  duration_seconds?: number;
  status?: "succeeded" | "failed";
  error?: string;
  created_at: string;
}

export async function getGenerationTimeline(logId: string) {
  return api<{ steps: GenerationTimelineStep[] }>(`/api/generations/${logId}/timeline`);
}

export async function listGenerations(params: { folderId?: string | null; page?: number; pageSize?: number }) {
  const q = new URLSearchParams();
  if (params.folderId) q.set("folder_id", params.folderId);
  if (params.page) q.set("page", String(params.page));
  if (params.pageSize) q.set("page_size", String(params.pageSize));
  return api<{ logs: GenerationLog[]; total: number }>(`/api/generations?${q.toString()}`);
}

export async function updateSyncFeishu(enabled: boolean) {
  return api<{ sync_feishu_enabled: boolean }>("/api/me/sync-feishu", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
    csrf: true,
  });
}

export interface PointTxn {
  id: string;
  amount: number;
  type: string;
  ref: string;
  tokens: number | null;
  created_at: string;
}

export interface MyPoints {
  balance: number;
  total_granted: number;
  total_consumed: number;
  recent: PointTxn[];
}

export function getMyPoints() {
  return api<MyPoints>("/api/points/me");
}

export function getPointsUsage() {
  return api<{ days: { date: string; tokens: number; points: number }[] }>("/api/points/usage");
}

export function redeemPoints(code: string) {
  return api<{ points: number }>("/api/points/redeem", {
    method: "POST",
    body: JSON.stringify({ code }),
    csrf: true,
  });
}

export function adminGrantPoints(userId: string, points: number, description: string) {
  return api<{ balance: number }>("/api/admin/points/grant", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, points, description }),
    csrf: true,
  });
}

export function adminPointsAll() {
  return api<{ users: { user_id: string; balance: number }[] }>("/api/admin/points/all");
}

export function adminCreateRedeemCodes(points: number, count: number) {
  return api<{ codes: string[] }>("/api/admin/redeem-codes", {
    method: "POST",
    body: JSON.stringify({ points, count }),
    csrf: true,
  });
}

export function adminListRedeemCodes(page = 1, pageSize = 20) {
  return api<{ codes: { code: string; points: number; used_by: string | null; used_at: string | null; created_at: string }[]; total: number }>(
    `/api/admin/redeem-codes?page=${page}&page_size=${pageSize}`
  );
}
