import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mockList, mockDisable, mockEnable, mockDelete, mockReingest } = vi.hoisted(() => ({
  mockList: vi.fn(), mockDisable: vi.fn(), mockEnable: vi.fn(), mockDelete: vi.fn(), mockReingest: vi.fn(),
}));
vi.mock("@/lib/rag-api", () => ({
  ragApi: {
    listLibraryDocuments: mockList, disable: mockDisable, enable: mockEnable,
    deleteDocument: mockDelete, reingestDocument: mockReingest,
  },
}));

import DatasetTable from "./dataset-table";

const DOC = {
  id: "d1", title: "千川手册", doc_type: "industry_methodology", source_url: null,
  publisher: "抖音电商官方学习中心", status: "ready", chunk_count: 52,
  created_at: "2026-09-15T07:49:00Z", updated_at: "2026-09-15T07:52:00Z",
};

describe("DatasetTable", () => {
  beforeEach(() => {
    mockList.mockReset(); mockDisable.mockReset(); mockEnable.mockReset();
    mockDelete.mockReset(); mockReingest.mockReset();
  });

  it("renders documents and toggles enabled state", async () => {
    mockList.mockResolvedValue({ items: [DOC], page: 1, page_size: 20, total: 1 });
    mockDisable.mockResolvedValue({ ...DOC, status: "disabled" });
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <DatasetTable libraryId="lib-1" />
      </ConfigProvider>
    );
    await waitFor(() => expect(screen.getByText("千川手册")).toBeTruthy());
    expect(screen.getByText("52")).toBeTruthy();
    await userEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(mockDisable).toHaveBeenCalledWith("d1"));
  });

  it("requeues a document for re-chunking", async () => {
    mockList.mockResolvedValue({ items: [DOC], page: 1, page_size: 20, total: 1 });
    mockReingest.mockResolvedValue({ doc_id: "d1", job_id: "j1" });
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <DatasetTable libraryId="lib-1" />
      </ConfigProvider>
    );
    await waitFor(() => expect(screen.getByText("千川手册")).toBeTruthy());
    await userEvent.click(screen.getByLabelText("更多操作"));
    await userEvent.click(await screen.findByText("重新切分"));
    await waitFor(() => expect(mockReingest).toHaveBeenCalledWith("d1"));
    await waitFor(() => expect(mockList.mock.calls.length).toBeGreaterThan(1));
  });

  it("shows failure reason for failed documents", async () => {
    mockList.mockResolvedValue({
      items: [{ ...DOC, id: "d2", status: "failed", error_message: "未提取到正文", chunk_count: 0 }],
      page: 1, page_size: 20, total: 1,
    });
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <DatasetTable libraryId="lib-1" />
      </ConfigProvider>
    );
    await waitFor(() => expect(screen.getByText("失败")).toBeTruthy());
    expect(screen.getByTitle("未提取到正文")).toBeTruthy();
  });

  it("renders the partial import status label", async () => {
    mockList.mockResolvedValue({
      items: [{ ...DOC, id: "d3", status: "partial", chunk_count: 2 }],
      page: 1, page_size: 20, total: 1,
    });
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <DatasetTable libraryId="lib-1" />
      </ConfigProvider>
    );
    await waitFor(() => expect(screen.getByText("部分成功")).toBeTruthy());
  });
});
