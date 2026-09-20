import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mockSearch } = vi.hoisted(() => ({ mockSearch: vi.fn() }));
vi.mock("@/lib/rag-api", () => ({ ragApi: { search: mockSearch } }));

import SearchTestPanel from "./search-test-panel";

describe("SearchTestPanel", () => {
  beforeEach(() => mockSearch.mockReset());

  it("runs a library-scoped search and renders hits", async () => {
    mockSearch.mockResolvedValue({
      items: [
        {
          chunk_id: "c1",
          doc_id: "d1",
          title: "千川手册",
          section_path: "出价",
          content: "控成本投放",
          source_url: "https://x",
          publisher: "抖音",
          score: 0.83,
        },
      ],
      elapsed_ms: 12,
    });
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <SearchTestPanel libraryId="lib-1" />
      </ConfigProvider>
    );
    await userEvent.type(screen.getByPlaceholderText("输入问题，验证本库召回效果"), "出价策略");
    await userEvent.click(screen.getByRole("button", { name: "检索" }));
    await waitFor(() => expect(screen.getByText("千川手册")).toBeTruthy());
    expect(mockSearch).toHaveBeenCalledWith("出价策略", 5, "lib-1");
  });
});
