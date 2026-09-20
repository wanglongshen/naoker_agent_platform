import { api } from "@/lib/api";

export interface RagDocument {
  id: string;
  title: string;
  doc_type: string;
  source_url: string | null;
  publisher: string | null;
  status: string;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface RagDocumentListParams {
  status?: string;
  keyword?: string;
  page?: number;
  pageSize?: number;
}

export interface RagDocumentPage {
  items: RagDocument[];
  page: number;
  page_size: number;
  total: number;
}

export interface RagSearchHit {
  chunk_id: string;
  doc_id: string;
  title: string;
  section_path: string;
  content: string;
  source_url: string | null;
  publisher: string | null;
  score: number;
}

export interface RagSearchResult {
  items: RagSearchHit[];
  elapsed_ms: number;
}

export interface RagLibraryStats {
  doc_count: number;
  chunk_count: number;
  ready_count: number;
  failed_count: number;
  last_updated_at: string | null;
}

export interface RagLibrary {
  id: string;
  name: string;
  description: string | null;
  kind: string;
  visibility: string;
  retrieval_enabled: boolean;
  created_at: string;
  updated_at: string;
  stats: RagLibraryStats;
}

export interface RagJob {
  id: string;
  library_id: string;
  doc_id: string | null;
  kind: string;
  status: string;
  total: number;
  processed: number;
  error_message: string | null;
}

export const ragApi = {
  listLibraries: () => api<{ items: RagLibrary[] }>("/api/rag/libraries").then((r) => r.items),

  createLibrary: (body: { name: string; description?: string; kind?: string }) =>
    api<RagLibrary>("/api/rag/libraries", { method: "POST", csrf: true, body: JSON.stringify(body) }),

  updateLibrary: (id: string, body: Partial<{ name: string; description: string; visibility: string; retrieval_enabled: boolean }>) =>
    api<RagLibrary>(`/api/rag/libraries/${id}`, { method: "PATCH", csrf: true, body: JSON.stringify(body) }),

  deleteLibrary: (id: string, force = false) =>
    api<{ deleted: boolean }>(`/api/rag/libraries/${id}${force ? "?force=true" : ""}`, { method: "DELETE", csrf: true }),

  listLibraryDocuments: (libraryId: string, params: RagDocumentListParams = {}) => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.keyword) q.set("q", params.keyword);
    q.set("page", String(params.page ?? 1));
    q.set("page_size", String(params.pageSize ?? 20));
    return api<RagDocumentPage>(`/api/rag/libraries/${libraryId}/documents?${q.toString()}`);
  },

  deleteDocument: (id: string) =>
    api<{ deleted: boolean }>(`/api/rag/documents/${id}`, { method: "DELETE", csrf: true }),

  reingestDocument: (id: string) =>
    api<{ doc_id: string; job_id: string }>(`/api/rag/documents/${id}/reingest`, {
      method: "POST",
      csrf: true,
    }),

  listChunks: (docId: string, page = 1, pageSize = 20) =>
    api<{ items: { id: string; chunk_index: number; section_path: string | null; content: string }[]; total: number }>(
      `/api/rag/documents/${docId}/chunks?page=${page}&page_size=${pageSize}`
    ),

  uploadDocument: (libraryId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api<{ doc_id: string; job_id: string }>(`/api/rag/libraries/${libraryId}/documents`, {
      method: "POST",
      csrf: true,
      body: form,
    });
  },

  importCollected: (libraryId: string, body: { scope: "core" | "all"; category?: string; limit?: number }) =>
    api<{ job_id: string; queued: number }>(`/api/rag/libraries/${libraryId}/import`, {
      method: "POST",
      csrf: true,
      body: JSON.stringify(body),
    }),

  listJobs: (libraryId: string, active = false) =>
    api<{ items: RagJob[] }>(`/api/rag/jobs?library_id=${libraryId}&active=${active}`).then((r) => r.items),

  listDocuments: (params: RagDocumentListParams = {}) => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.keyword) q.set("keyword", params.keyword);
    q.set("page", String(params.page ?? 1));
    q.set("page_size", String(params.pageSize ?? 20));
    return api<RagDocumentPage>(`/api/rag/documents?${q.toString()}`);
  },

  disable: (id: string) =>
    api<RagDocument>(`/api/rag/documents/${id}/disable`, { method: "POST", csrf: true }),

  enable: (id: string) =>
    api<RagDocument>(`/api/rag/documents/${id}/enable`, { method: "POST", csrf: true }),

  search: (query: string, topK = 5, libraryId?: string) =>
    api<RagSearchResult>("/api/rag/search", {
      method: "POST",
      body: JSON.stringify({ query, top_k: topK, library_id: libraryId }),
    }),
};
