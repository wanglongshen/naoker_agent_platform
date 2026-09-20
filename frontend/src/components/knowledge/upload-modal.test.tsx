import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mockUpload, mockJobs, mockImport } = vi.hoisted(() => ({
  mockUpload: vi.fn(), mockJobs: vi.fn(), mockImport: vi.fn(),
}));
vi.mock("@/lib/rag-api", () => ({
  ragApi: { uploadDocument: mockUpload, listJobs: mockJobs, importCollected: mockImport },
}));

import UploadModal from "./upload-modal";

describe("UploadModal", () => {
  beforeEach(() => {
    mockUpload.mockReset();
    mockJobs.mockReset();
    mockImport.mockReset();
  });

  it("uploads a file and shows queued progress", async () => {
    mockUpload.mockResolvedValue({ doc_id: "d9", job_id: "j9" });
    mockJobs.mockResolvedValue([
      { id: "j9", library_id: "lib-1", doc_id: "d9", kind: "upload", status: "running", total: 1, processed: 0, error_message: null },
    ]);
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <UploadModal libraryId="lib-1" open onClose={() => {}} onQueued={() => {}} />
      </ConfigProvider>
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["# t"], "a.md", { type: "text/markdown" }));
    await userEvent.click(screen.getByRole("button", { name: "开始上传" }));
    await waitFor(() => expect(mockUpload).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/处理中/)).toBeTruthy());
  });

  it("imports collected material and shows queued progress", async () => {
    mockImport.mockResolvedValue({ job_id: "j10", queued: 226 });
    mockJobs.mockResolvedValue([
      {
        id: "j10", library_id: "lib-1", doc_id: null, kind: "import", status: "running",
        total: 226, processed: 10, error_message: null,
      },
    ]);
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <UploadModal libraryId="lib-1" open onClose={() => {}} onQueued={() => {}} />
      </ConfigProvider>
    );
    await userEvent.click(screen.getByRole("tab", { name: "从已采集素材导入" }));
    await userEvent.click(screen.getByRole("button", { name: "开始导入" }));
    await waitFor(() => expect(mockImport).toHaveBeenCalledWith("lib-1", { scope: "core" }));
    await waitFor(() => expect(screen.getByText(/处理中/)).toBeTruthy());
  });
});
