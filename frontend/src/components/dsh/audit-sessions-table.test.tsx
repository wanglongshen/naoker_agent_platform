import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { ConfigProvider } from "antd";
import AuditSessionsTable from "./audit-sessions-table";

const ENVELOPE = {
  data: {
    items: [
      {
        dsh_session_id: "dsess-1",
        title: "季度财报分析",
        turn_count: 3,
        last_activity_at: "2026-09-01T04:12:00Z",
        synced_at: "2026-09-01T04:12:05Z",
        user_id: "4c40bada-b2e6-45ea-b1b2-a2e43e663072",
      },
    ],
    page: 1,
    page_size: 20,
    total: 1,
  },
  message: "OK",
  request_id: "req-1",
};

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function stubFetch(response: unknown) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => response });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider theme={{ token: { motion: false } }}>{children}</ConfigProvider>;
}

describe("AuditSessionsTable", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests the dsh sessions audit endpoint with page_size 20", async () => {
    const fetchMock = stubFetch(ENVELOPE);
    render(
      <Wrapper>
        <AuditSessionsTable />
      </Wrapper>
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/dsh/sessions/audit?page=1&page_size=20");
  });

  it("renders headers and first row from the envelope", async () => {
    stubFetch(ENVELOPE);
    const { container } = render(
      <Wrapper>
        <AuditSessionsTable />
      </Wrapper>
    );
    await waitFor(() => {
      expect(container.querySelector(".ant-table-row")).not.toBeNull();
    });
    const thead = container.querySelector(".ant-table-thead");
    const headerText = Array.from(thead?.querySelectorAll("th") ?? [])
      .map((th) => th.textContent ?? "")
      .join(" ");
    for (const h of ["用户", "标题", "轮次", "最近活动", "同步时间"]) {
      expect(headerText).toContain(h);
    }
    const row = container.querySelector(".ant-table-tbody .ant-table-row");
    const rowText = row?.textContent ?? "";
    expect(rowText).toContain("季度财报分析");
    expect(rowText).toContain("3");
    expect(rowText).toContain("4c40bada-b2e");
    expect(rowText).toContain(formatTime("2026-09-01T04:12:00Z"));
    expect(rowText).toContain(formatTime("2026-09-01T04:12:05Z"));
  });

  it("shows fallbacks for missing title and timestamps", async () => {
    stubFetch({
      data: {
        items: [
          {
            dsh_session_id: "dsess-2",
            title: null,
            turn_count: 0,
            last_activity_at: null,
            synced_at: null,
            user_id: "5a31633d-b03d-4fd6-b707-5dcd194f7c77",
          },
        ],
        page: 1,
        page_size: 20,
        total: 1,
      },
      message: "OK",
      request_id: "req-2",
    });
    const { container } = render(
      <Wrapper>
        <AuditSessionsTable />
      </Wrapper>
    );
    await waitFor(() => {
      expect(container.querySelector(".ant-table-row")).not.toBeNull();
    });
    const rowText = container.querySelector(".ant-table-tbody .ant-table-row")?.textContent ?? "";
    expect(rowText).toContain("未命名会话");
    expect(rowText).toContain("—");
  });

  it("shows the owner display name in the user column when present", async () => {
    stubFetch({
      data: {
        items: [
          {
            dsh_session_id: "dsess-3",
            title: "有中文名",
            turn_count: 1,
            last_activity_at: "2026-09-03T04:12:00Z",
            synced_at: "2026-09-03T04:12:05Z",
            user_id: "7b1e0f4a-9c2d-4e8f-a1b2-c3d4e5f60718",
            username: "zhangsan",
            display_name: "张三",
          },
        ],
        page: 1,
        page_size: 20,
        total: 1,
      },
      message: "OK",
      request_id: "req-3",
    });
    const { container } = render(
      <Wrapper>
        <AuditSessionsTable />
      </Wrapper>
    );
    await waitFor(() => {
      expect(container.querySelector(".ant-table-row")).not.toBeNull();
    });
    const rowText = container.querySelector(".ant-table-tbody .ant-table-row")?.textContent ?? "";
    expect(rowText).toContain("张三");
    expect(rowText).not.toContain("7b1e0f4a-9c2");
  });

  it("falls back to the username when display_name is empty", async () => {
    stubFetch({
      data: {
        items: [
          {
            dsh_session_id: "dsess-4",
            title: "只有用户名",
            turn_count: 1,
            last_activity_at: "2026-09-04T04:12:00Z",
            synced_at: "2026-09-04T04:12:05Z",
            user_id: "8c2f1a5b-0d3e-4f90-b2c3-d4e5f6071829",
            username: "lisi",
            display_name: "",
          },
        ],
        page: 1,
        page_size: 20,
        total: 1,
      },
      message: "OK",
      request_id: "req-4",
    });
    const { container } = render(
      <Wrapper>
        <AuditSessionsTable />
      </Wrapper>
    );
    await waitFor(() => {
      expect(container.querySelector(".ant-table-row")).not.toBeNull();
    });
    const rowText = container.querySelector(".ant-table-tbody .ant-table-row")?.textContent ?? "";
    expect(rowText).toContain("lisi");
    expect(rowText).not.toContain("8c2f1a5b-0d3");
  });

  it("falls back to a short user id when no owner names are available", async () => {
    stubFetch({
      data: {
        items: [
          {
            dsh_session_id: "dsess-5",
            title: "无用户名",
            turn_count: 1,
            last_activity_at: "2026-09-05T04:12:00Z",
            synced_at: "2026-09-05T04:12:05Z",
            user_id: "9d3a2b6c-1e4f-4a01-c3d4-e5f60718293a",
            username: "",
            display_name: "",
          },
        ],
        page: 1,
        page_size: 20,
        total: 1,
      },
      message: "OK",
      request_id: "req-5",
    });
    const { container } = render(
      <Wrapper>
        <AuditSessionsTable />
      </Wrapper>
    );
    await waitFor(() => {
      expect(container.querySelector(".ant-table-row")).not.toBeNull();
    });
    const rowText = container.querySelector(".ant-table-tbody .ant-table-row")?.textContent ?? "";
    expect(rowText).toContain("9d3a2b6c-1e4");
  });

  it("loads page 2 when the pager is clicked", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ...ENVELOPE, data: { ...ENVELOPE.data, total: 25 } }),
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        data: {
          items: [
            {
              dsh_session_id: "dsess-2",
              title: "第二页会话",
              turn_count: 5,
              last_activity_at: "2026-09-02T04:12:00Z",
              synced_at: "2026-09-02T04:12:05Z",
              user_id: "5a31633d-b03d-4fd6-b707-5dcd194f7c77",
            },
          ],
          page: 2,
          page_size: 20,
          total: 25,
        },
        message: "OK",
        request_id: "req-2",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(
      <Wrapper>
        <AuditSessionsTable />
      </Wrapper>
    );
    await waitFor(() => {
      expect(container.querySelector(".ant-table-row")).not.toBeNull();
    });
    const page2 = container.querySelector<HTMLElement>(
      ".ant-pagination .ant-pagination-item-2, .ant-pagination li[title='2']"
    );
    expect(page2).not.toBeNull();
    await act(async () => {
      fireEvent.click(page2 as HTMLElement);
    });
    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c) => String(c[0]));
      expect(calls.some((u) => u.includes("page=2&page_size=20"))).toBe(true);
    });
    await waitFor(() => {
      const rowText = container.querySelector(".ant-table-tbody .ant-table-row")?.textContent ?? "";
      expect(rowText).toContain("第二页会话");
    });
  });

  it("renders an error alert when the request fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ code: "FORBIDDEN", message: "无权限", request_id: "req-403" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <Wrapper>
        <AuditSessionsTable />
      </Wrapper>
    );
    expect(await screen.findByText("加载 DSH 会话审计数据失败")).toBeDefined();
  });
});
