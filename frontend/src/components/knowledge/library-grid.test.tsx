import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mockListLibraries, mockCreateLibrary, mockDeleteLibrary, mockUpdateLibrary } = vi.hoisted(() => ({
  mockListLibraries: vi.fn(),
  mockCreateLibrary: vi.fn(),
  mockDeleteLibrary: vi.fn(),
  mockUpdateLibrary: vi.fn(),
}));

vi.mock("@/lib/rag-api", () => ({
  ragApi: {
    listLibraries: mockListLibraries,
    createLibrary: mockCreateLibrary,
    deleteLibrary: mockDeleteLibrary,
    updateLibrary: mockUpdateLibrary,
  },
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mockPush }) }));

import { ApiError } from "@/lib/api";
import LibraryGrid from "./library-grid";

const LIB = {
  id: "lib-1",
  name: "行业知识库",
  description: "抖音电商官方方法论",
  kind: "industry",
  visibility: "admins_only",
  retrieval_enabled: true,
  created_at: "2026-09-15T07:00:00Z",
  updated_at: "2026-09-15T07:52:00Z",
  stats: { doc_count: 192, chunk_count: 1501, ready_count: 192, failed_count: 0, last_updated_at: "2026-09-15T07:52:00Z" },
};

function renderGrid() {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <LibraryGrid />
    </ConfigProvider>
  );
}

async function openDeleteConfirm() {
  await userEvent.click(screen.getByRole("button", { name: "更多操作" }));
  await userEvent.click(await screen.findByText("删除"));
  await userEvent.click(screen.getByRole("button", { name: "删除" }));
}

describe("LibraryGrid", () => {
  beforeEach(() => {
    mockListLibraries.mockReset();
    mockCreateLibrary.mockReset();
    mockDeleteLibrary.mockReset();
    mockUpdateLibrary.mockReset();
    mockPush.mockReset();
  });

  it("renders library cards with real stats, the aggregate bar, and opens detail on click", async () => {
    mockListLibraries.mockResolvedValue([LIB]);
    renderGrid();
    await waitFor(() => expect(screen.getByText("行业知识库")).toBeTruthy());

    const summary = screen.getByText("文档总数").closest(".page-summary");
    expect(summary).not.toBeNull();
    expect(summary?.textContent).toContain("192");
    expect(summary?.textContent).toContain("1,501");

    const cardStats = screen.getByText(/篇 ·/);
    expect(cardStats.textContent).toContain("192");
    expect(cardStats.textContent).toContain("1,501");

    await userEvent.click(screen.getByText("行业知识库"));
    expect(mockPush).toHaveBeenCalledWith("/knowledge/lib-1");
  });

  it("gives the toolbar and placeholder create buttons distinct accessible names", async () => {
    mockListLibraries.mockResolvedValue([LIB]);
    renderGrid();
    await waitFor(() => expect(screen.getByText("行业知识库")).toBeTruthy());
    expect(screen.getByRole("button", { name: "新建知识库（工具栏）" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "新建知识库（占位卡片）" })).toBeTruthy();
  });

  it("creates a library from the new modal", async () => {
    mockListLibraries.mockResolvedValue([]);
    mockCreateLibrary.mockResolvedValue({ ...LIB, id: "lib-2", name: "新库", stats: { ...LIB.stats, doc_count: 0, chunk_count: 0 } });
    renderGrid();
    await waitFor(() => expect(mockListLibraries).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "新建知识库（工具栏）" }));
    await userEvent.type(screen.getByLabelText("名称"), "新库");
    await userEvent.click(screen.getByRole("button", { name: "创建" }));
    await waitFor(() => expect(mockCreateLibrary).toHaveBeenCalledWith({ name: "新库", description: undefined }));
  });

  it("keeps the grid rendered while refreshing after a change", async () => {
    mockListLibraries.mockResolvedValueOnce([LIB]);
    let resolveRefresh: (items: (typeof LIB)[]) => void = () => {};
    mockListLibraries.mockImplementationOnce(
      () =>
        new Promise<(typeof LIB)[]>((resolve) => {
          resolveRefresh = resolve;
        })
    );
    mockCreateLibrary.mockResolvedValue({ ...LIB, id: "lib-2", name: "新库" });

    renderGrid();
    await waitFor(() => expect(screen.getByText("行业知识库")).toBeTruthy());
    await userEvent.click(screen.getByRole("button", { name: "新建知识库（工具栏）" }));
    await userEvent.type(screen.getByLabelText("名称"), "新库");
    await userEvent.click(screen.getByRole("button", { name: "创建" }));
    await waitFor(() => expect(mockListLibraries).toHaveBeenCalledTimes(2));

    expect(screen.getByText("行业知识库")).toBeTruthy();
    expect(document.querySelector(".page-loading")).toBeNull();

    await act(async () => {
      resolveRefresh([LIB]);
    });
  });

  it("shows the inline name-conflict error for LIBRARY_NAME_EXISTS", async () => {
    mockListLibraries.mockResolvedValue([]);
    mockCreateLibrary.mockRejectedValue(new ApiError(409, "LIBRARY_NAME_EXISTS", "", null));
    renderGrid();
    await waitFor(() => expect(mockListLibraries).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "新建知识库（工具栏）" }));
    await userEvent.type(screen.getByLabelText("名称"), "新库");
    await userEvent.click(screen.getByRole("button", { name: "创建" }));
    expect(await screen.findByText("知识库名称已存在，请换一个名称。")).toBeTruthy();
  });

  it("shows a generic save error for a 409 with an unrelated code", async () => {
    mockListLibraries.mockResolvedValue([]);
    mockCreateLibrary.mockRejectedValue(new ApiError(409, "OTHER_CONFLICT", "", null));
    renderGrid();
    await waitFor(() => expect(mockListLibraries).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "新建知识库（工具栏）" }));
    await userEvent.type(screen.getByLabelText("名称"), "新库");
    await userEvent.click(screen.getByRole("button", { name: "创建" }));
    expect(await screen.findByText("保存失败，请稍后重试。")).toBeTruthy();
    expect(screen.queryByText("知识库名称已存在，请换一个名称。")).toBeNull();
  });

  it("offers force delete for a non-empty library and deletes with force=true", async () => {
    mockListLibraries.mockResolvedValue([LIB]);
    mockDeleteLibrary
      .mockRejectedValueOnce(new ApiError(409, "LIBRARY_NOT_EMPTY", "知识库非空", null))
      .mockResolvedValueOnce({ deleted: true });
    renderGrid();
    await waitFor(() => expect(screen.getByText("行业知识库")).toBeTruthy());

    await openDeleteConfirm();
    await waitFor(() => expect(mockDeleteLibrary).toHaveBeenCalledWith("lib-1", false));
    expect(await screen.findByText("知识库非空")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "强制删除" }));
    await waitFor(() => expect(mockDeleteLibrary).toHaveBeenLastCalledWith("lib-1", true));
  });

  it("库卡片按文档数降序排列", async () => {
    mockListLibraries.mockResolvedValue([
      { ...LIB, id: "lib-small", name: "小库", stats: { ...LIB.stats, doc_count: 3 } },
      { ...LIB, id: "lib-big", name: "大库", stats: { ...LIB.stats, doc_count: 80 } },
    ]);
    const { container } = renderGrid();
    await waitFor(() => expect(screen.getByText("大库")).toBeTruthy());
    const text = container.textContent ?? "";
    expect(text.indexOf("大库")).toBeLessThan(text.indexOf("小库"));
  });

  it("does not offer force delete for a 409 that is not LIBRARY_NOT_EMPTY", async () => {
    mockListLibraries.mockResolvedValue([LIB]);
    mockDeleteLibrary.mockRejectedValue(new ApiError(409, "OTHER_CONFLICT", "删除冲突", null));
    renderGrid();
    await waitFor(() => expect(screen.getByText("行业知识库")).toBeTruthy());

    await openDeleteConfirm();
    await waitFor(() => expect(mockDeleteLibrary).toHaveBeenCalledWith("lib-1", false));
    expect(await screen.findByText("删除冲突")).toBeTruthy();
    expect(screen.queryByText("知识库非空")).toBeNull();
  });
});
