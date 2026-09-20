import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import FileManagement from "./file-management";
import { api, listGenerations, getGenerationTimeline } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: vi.fn(),
  listGenerations: vi.fn(),
  getGenerationTimeline: vi.fn(),
}));

const mockedApi = vi.mocked(api);
const mockedListGenerations = vi.mocked(listGenerations);
const mockedGetGenerationTimeline = vi.mocked(getGenerationTimeline);

const currentUser = {
  id: "u-admin",
  username: "admin",
  display_name: "管理员",
  roles: [],
  permissions: ["file:upload", "file:manage_folders", "file:admin_view"],
} as any;

const groups = [
  { user_id: "u-admin", username: "admin", display_name: "管理员", folders: [] },
  {
    user_id: "u-other",
    username: "other",
    display_name: "其他用户",
    folders: [{ id: "f1", parent_folder_id: null, name: "文件夹A", child_file_count: 1 } as any],
  },
];

function makeFile(id: string, originalFilename: string) {
  return {
    id,
    owner_user_id: "u-admin",
    filename: id,
    original_filename: originalFilename,
    media_type: "text/plain",
    size_bytes: 10,
    folder_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

beforeEach(() => {
  mockedApi.mockReset();
  mockedListGenerations.mockReset();
  mockedListGenerations.mockResolvedValue({ logs: [], total: 0 });
  mockedGetGenerationTimeline.mockReset();
  mockedGetGenerationTimeline.mockResolvedValue({ steps: [] });
  mockedApi.mockImplementation(async (url: string, init?: any) => {
    if (url.startsWith("/api/files/folders/admin")) return groups;
    if (url.startsWith("/api/files/admin")) {
      return { items: [makeFile("file1", "x.txt")], page: 1, page_size: 20, total: 1 };
    }
    return { items: [], page: 1, page_size: 20, total: 0 };
  });
});

describe("FileManagement admin view", () => {
  it("renders user-grouped tree and loads admin list on mount", async () => {
    render(<FileManagement currentUser={currentUser} adminView />);
    await waitFor(() => expect(screen.getByText("其他用户")).toBeTruthy());
    expect(mockedApi).toHaveBeenCalledWith(
      expect.stringContaining("/api/files/admin?user_id=u-admin")
    );
    expect(mockedApi).toHaveBeenCalledWith("/api/files/folders/admin");
  });

  it("shows upload buttons only for own files (ownView)", async () => {
    render(<FileManagement currentUser={currentUser} adminView />);
    await waitFor(() => expect(screen.getByText("上传文件")).toBeTruthy());
  });

  it("hides upload buttons when another user is selected", async () => {
    render(<FileManagement currentUser={currentUser} adminView />);
    await waitFor(() => expect(screen.getByText("其他用户")).toBeTruthy());
    await waitFor(() => expect(screen.getByText("上传文件")).toBeTruthy());

    fireEvent.click(screen.getByText("其他用户"));

    await waitFor(() => expect(screen.queryByText("上传文件")).not.toBeInTheDocument());
    expect(mockedApi).toHaveBeenCalledWith(
      expect.stringContaining("/api/files/admin?user_id=u-other")
    );
  });

  it("opens generation records modal and lists records without folder filter", async () => {
    mockedListGenerations.mockResolvedValue({
      logs: [
        {
          id: "g1",
          folder_id: null,
          folder_name: "全部",
          user_id: "u-admin",
          session_id: "s1",
          run_id: "r1",
          input_text: "帮我生成一份方案",
          final_md_file_id: null,
          final_answer: "这是最终生成的方案内容",
          feishu_doc_url: "https://feishu.cn/doc/1",
          status: "succeeded",
          error: "",
          created_at: "2026-01-01T00:00:00Z",
        },
        {
          id: "g2",
          folder_id: null,
          folder_name: "全部",
          user_id: "u-admin",
          session_id: "s2",
          run_id: "r2",
          input_text: "这次失败了",
          final_md_file_id: null,
          final_answer: "",
          feishu_doc_url: "",
          status: "failed",
          error: "worker_unhandled_error",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 2,
    });

    render(<FileManagement currentUser={currentUser} adminView />);
    await waitFor(() => expect(screen.getByText("上传文件")).toBeTruthy());

    fireEvent.click(screen.getByText("生成记录"));

    await waitFor(() => {
      expect(screen.getByText("帮我生成一份方案")).toBeTruthy();
    });
    expect(screen.getByText("已同步飞书")).toBeTruthy();
    expect(screen.getByText("失败")).toBeTruthy();
    expect(mockedListGenerations).toHaveBeenCalledWith(
      expect.objectContaining({ folderId: null, pageSize: 10 })
    );
  });

  it("generation record detail modal shows input, answer and feishu link", async () => {
    mockedListGenerations.mockResolvedValue({
      logs: [
        {
          id: "g1",
          folder_id: null,
          folder_name: "全部",
          user_id: "u-admin",
          session_id: "s1",
          run_id: "r1",
          input_text: "帮我生成一份方案",
          final_md_file_id: null,
          final_answer: "这是最终生成的方案内容",
          feishu_doc_url: "https://feishu.cn/doc/1",
          status: "succeeded",
          error: "",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
    });

    render(<FileManagement currentUser={currentUser} adminView />);
    await waitFor(() => expect(screen.getByText("上传文件")).toBeTruthy());

    fireEvent.click(screen.getByText("生成记录"));
    await waitFor(() => expect(screen.getByText("帮我生成一份方案")).toBeTruthy());

    const detailBtn = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find((b) =>
      /详\s*情/.test(b.textContent || "")
    );
    expect(detailBtn).toBeTruthy();
    fireEvent.click(detailBtn!);

    await waitFor(() => {
      expect(screen.getByText("打开飞书文档")).toBeTruthy();
    });
    expect(screen.getByText("这是最终生成的方案内容")).toBeTruthy();
    const link = document.querySelector<HTMLAnchorElement>('a[href="https://feishu.cn/doc/1"]');
    expect(link).not.toBeNull();
    expect(link?.getAttribute("target")).toBe("_blank");
  });
});
