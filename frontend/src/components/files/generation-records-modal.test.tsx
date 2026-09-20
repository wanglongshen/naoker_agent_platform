import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: mockApi,
    listGenerations: () => mockApi("/api/generations"),
    getGenerationTimeline: (logId: string) => mockApi(`/api/generations/${logId}/timeline`),
  };
});

import GenerationRecordsModal from "@/components/files/generation-records-modal";

const LOG = {
  id: "log-1",
  folder_id: null,
  folder_name: "",
  user_id: "u1",
  session_id: "s1",
  run_id: "r1",
  input_text: "写一个方案",
  final_md_file_id: null,
  final_answer: "最终方案内容",
  feishu_doc_url: "",
  status: "succeeded",
  error: "",
  created_at: "2026-08-06T10:00:00Z",
};

const STEPS = [
  { type: "thought", step_index: 0, content: "先查资料再写", created_at: "2026-08-06T10:00:01Z" },
  {
    type: "tool",
    step_index: 0,
    action_type: "read_file",
    input: { path: "docs/a.md" },
    observation: "file_id: x; filename: a.md",
    duration_seconds: 1.5,
    created_at: "2026-08-06T10:00:02Z",
  },
  { type: "answer", content: "最终方案内容", created_at: "2026-08-06T10:00:03Z" },
  { type: "terminal", status: "succeeded", created_at: "2026-08-06T10:00:04Z" },
];

function mockEndpoints(overrides: Record<string, unknown> = {}) {
  mockApi.mockImplementation((path: string) => {
    if (overrides[path] !== undefined) return Promise.resolve(overrides[path]);
    if (path === "/api/generations") return Promise.resolve({ logs: [LOG], total: 1 });
    if (path === "/api/generations/log-1/timeline") return Promise.resolve({ steps: STEPS });
    return Promise.resolve(undefined);
  });
}

describe("GenerationRecordsModal timeline", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  test("detail loads and renders timeline steps", async () => {
    const user = userEvent.setup();
    mockEndpoints();
    render(<GenerationRecordsModal open folderId={null} onClose={() => {}} />);
    await screen.findByText("写一个方案");
    const detailBtn = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find((b) =>
      /详\s*情/.test(b.textContent || "")
    );
    expect(detailBtn).not.toBeNull();
    await user.click(detailBtn!);

    expect(await screen.findByText("过程稿")).toBeTruthy();
    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith("/api/generations/log-1/timeline");
    });
    expect(await screen.findByText(/思考（步骤 1）/)).toBeTruthy();
    expect(await screen.findByText(/工具 · read_file（步骤 1）/)).toBeTruthy();
    expect(await screen.findByText(/答案/)).toBeTruthy();
  });

  test("failed terminal shows error and auto-expands", async () => {
    const user = userEvent.setup();
    mockEndpoints({
      "/api/generations/log-1/timeline": {
        steps: [
          {
            type: "terminal",
            status: "failed",
            error: "max_steps_exceeded",
            created_at: "2026-08-06T10:00:04Z",
          },
        ],
      },
    });
    render(<GenerationRecordsModal open folderId={null} onClose={() => {}} />);
    await screen.findByText("写一个方案");
    const detailBtn = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find((b) =>
      /详\s*情/.test(b.textContent || "")
    );
    await user.click(detailBtn!);

    expect(await screen.findByText("失败")).toBeTruthy();
    expect(await screen.findByText("max_steps_exceeded")).toBeTruthy();
  });

  test("empty timeline shows placeholder", async () => {
    const user = userEvent.setup();
    mockEndpoints({ "/api/generations/log-1/timeline": { steps: [] } });
    render(<GenerationRecordsModal open folderId={null} onClose={() => {}} />);
    await screen.findByText("写一个方案");
    const detailBtn = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find((b) =>
      /详\s*情/.test(b.textContent || "")
    );
    await user.click(detailBtn!);
    expect(await screen.findByText("暂无过程记录")).toBeTruthy();
  });
});
