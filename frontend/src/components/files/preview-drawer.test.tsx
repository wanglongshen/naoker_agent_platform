import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import PreviewDrawer from "@/components/files/preview-drawer";
import type { FileListItem } from "@/types/file";

function makeFile(overrides: Partial<FileListItem> = {}): FileListItem {
  return {
    id: "f1",
    owner_user_id: "u1",
    filename: "a.md",
    original_filename: "a.md",
    media_type: "text/markdown",
    size_bytes: 10,
    folder_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const jsonResponse = (data: unknown) => ({ json: async () => data });

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PreviewDrawer", () => {
  test("renders markdown file as rendered markdown", async () => {
    const md = "# 标题\n\n| 列A | 列B |\n| --- | --- |\n| 1 | 2 |";
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ data: { content: md } }));

    render(<PreviewDrawer open file={makeFile()} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1, name: "标题" })).toBeTruthy();
    });
    expect(document.querySelector("table")).toBeTruthy();
  });

  test("renders docx file as extracted text", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ data: { content: "这是文档提取的文字" } }),
    );

    render(
      <PreviewDrawer
        open
        file={makeFile({
          media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          original_filename: "报告.docx",
        })}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("这是文档提取的文字")).toBeTruthy();
    });
  });

  test("text categories fetch the preview endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ data: { content: "hello" } }));
    vi.stubGlobal("fetch", fetchMock);

    render(<PreviewDrawer open file={makeFile({ media_type: "text/plain" })} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("hello")).toBeTruthy();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/files/f1/preview"),
      expect.objectContaining({ credentials: "include" }),
    );
  });

  test("image category does not fetch text content", () => {
    render(<PreviewDrawer open file={makeFile({ media_type: "image/png", original_filename: "pic.png" })} onClose={() => {}} />);

    expect(fetch).not.toHaveBeenCalled();
  });

  test("pdf preview uses inline download url", () => {
    render(
      <PreviewDrawer
        open
        file={makeFile({ media_type: "application/pdf", original_filename: "doc.pdf" })}
        onClose={() => {}}
      />,
    );
    const iframe = document.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("src")).toContain("/api/files/f1/download");
    expect(iframe?.getAttribute("src")).not.toContain("download=1");
  });

  test.each([
    ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "报表.xlsx"],
    ["application/vnd.openxmlformats-officedocument.presentationml.presentation", "演示.pptx"],
  ])("office document %s fetches the preview endpoint", async (mediaType, filename) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ data: { content: "提取的文字" } }));
    vi.stubGlobal("fetch", fetchMock);

    render(<PreviewDrawer open file={makeFile({ media_type: mediaType, original_filename: filename })} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("提取的文字")).toBeTruthy();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/files/f1/preview"),
      expect.objectContaining({ credentials: "include" }),
    );
  });
});
