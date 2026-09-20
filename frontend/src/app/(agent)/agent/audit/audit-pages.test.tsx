import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { ConfigProvider } from "antd";

vi.mock("@/lib/agent-api", () => ({
  agentApi: {
    getAuditSession: vi.fn().mockResolvedValue({
      id: "s1",
      owner_user_id: "u1",
      owner_display_name: "张三",
      title: "测试会话",
      last_run_id: null,
      created_at: "2026-07-25T00:00:00Z",
      updated_at: "2026-07-25T00:00:00Z",
    }),
    listAuditSessionRuns: vi.fn().mockResolvedValue([]),
    getRun: vi.fn().mockResolvedValue({
      id: "r1",
      session_id: "s1",
      owner_user_id: "u1",
      goal: "测试目标",
      status: "succeeded",
      mode: "quick",
      network_enabled: false,
      current_attempt_id: null,
      result: null,
      created_at: "2026-07-25T00:00:00Z",
      updated_at: "2026-07-25T00:00:00Z",
    }),
    getAuditRun: vi.fn().mockResolvedValue({
      id: "r1",
      session_id: "s1",
      owner_user_id: "u1",
      goal: "测试目标",
      status: "succeeded",
      mode: "quick",
      network_enabled: false,
      current_attempt_id: null,
      result: { final_answer: "测试回答" },
      created_at: "2026-07-25T00:00:00Z",
      updated_at: "2026-07-25T00:00:00Z",
    }),
    getAuditRunAttempts: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 }),
    getAuditRunEvents: vi.fn().mockResolvedValue({ items: [], next_seq: null }),
    listAuditSessions: vi.fn().mockResolvedValue({
      items: [
        {
          id: "s1",
          owner_user_id: "u1",
          owner_display_name: "张三",
          title: "测试会话",
          last_run_id: null,
          created_at: "2026-07-25T00:00:00Z",
          updated_at: "2026-07-25T00:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    }),
    getAuditSessionTranscript: vi.fn().mockResolvedValue({
      session: {
        id: "s1",
        owner_user_id: "u1",
        owner_display_name: "张三",
        title: "测试会话",
        last_run_id: "r1",
        created_at: "2026-07-25T00:00:00Z",
        updated_at: "2026-07-25T00:00:00Z",
      },
      owner: {
        id: "u1",
        username: "jdoe",
        display_name: "张三",
        roles: ["user"],
      },
      turns: [
        {
          run: {
            id: "r1",
            session_id: "s1",
            owner_user_id: "u1",
            goal: "测试目标",
            status: "succeeded",
            mode: "quick",
            network_enabled: false,
            current_attempt_id: null,
            result: { final_answer: "测试回答" },
            created_at: "2026-07-25T00:00:00Z",
            updated_at: "2026-07-25T00:00:00Z",
          },
          steps: [],
          events: [],
        },
      ],
    }),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({ sessionId: "s1", runId: "r1" }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/auth", () => ({
  fetchCurrentUser: vi.fn().mockResolvedValue({
    id: "2",
    username: "admin",
    display_name: "管理员",
    roles: [{ id: "r1", code: "super_admin", name: "超级管理员" }],
    permissions: [],
    menu_permissions: [],
  }),
}));

import AuditPage from "./page";
import AuditSessionDetailPage from "./sessions/[sessionId]/page";
import AuditRunDetailPage from "./runs/[runId]/page";
import { agentApi } from "@/lib/agent-api";

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider theme={{ token: { motion: false } }}>{children}</ConfigProvider>;
}

describe("Audit pages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(agentApi.getAuditSession).mockResolvedValue({
      id: "s1",
      owner_user_id: "u1",
      owner_display_name: "张三",
      title: "测试会话",
      last_run_id: null,
      created_at: "2026-07-25T00:00:00Z",
      updated_at: "2026-07-25T00:00:00Z",
    });
    vi.mocked(agentApi.listAuditSessionRuns).mockResolvedValue([]);
    vi.mocked(agentApi.getRun).mockResolvedValue({
      id: "r1",
      session_id: "s1",
      owner_user_id: "u1",
      goal: "测试目标",
      status: "succeeded",
      mode: "quick",
      network_enabled: false,
      current_attempt_id: null,
      result: null,
      created_at: "2026-07-25T00:00:00Z",
      updated_at: "2026-07-25T00:00:00Z",
    });
    vi.mocked(agentApi.getAuditRun).mockResolvedValue({
      id: "r1",
      session_id: "s1",
      owner_user_id: "u1",
      goal: "测试目标",
      status: "succeeded",
      mode: "quick",
      network_enabled: false,
      current_attempt_id: null,
      result: { final_answer: "测试回答" },
      created_at: "2026-07-25T00:00:00Z",
      updated_at: "2026-07-25T00:00:00Z",
    });
    vi.mocked(agentApi.getAuditRunAttempts).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
    vi.mocked(agentApi.getAuditRunEvents).mockResolvedValue({ items: [], next_seq: null });
    vi.mocked(agentApi.listAuditSessions).mockResolvedValue({
      items: [
        {
          id: "s1",
          owner_user_id: "u1",
          owner_display_name: "张三",
          title: "测试会话",
          last_run_id: null,
          created_at: "2026-07-25T00:00:00Z",
          updated_at: "2026-07-25T00:00:00Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    });
    vi.mocked(agentApi.getAuditSessionTranscript).mockResolvedValue({
      session: {
        id: "s1",
        owner_user_id: "u1",
        owner_display_name: "张三",
        title: "测试会话",
        last_run_id: "r1",
        created_at: "2026-07-25T00:00:00Z",
        updated_at: "2026-07-25T00:00:00Z",
      },
      owner: {
        id: "u1",
        username: "jdoe",
        display_name: "张三",
        roles: ["user"],
      },
      turns: [
        {
          run: {
            id: "r1",
            session_id: "s1",
            owner_user_id: "u1",
            goal: "测试目标",
            status: "succeeded",
            mode: "quick",
            network_enabled: false,
            current_attempt_id: null,
            result: { final_answer: "测试回答" },
            created_at: "2026-07-25T00:00:00Z",
            updated_at: "2026-07-25T00:00:00Z",
          },
          steps: [],
          events: [],
        },
      ],
    });
  });

  it("loads audit session transcript instead of session runs endpoint", async () => {
    render(
      <Wrapper>
        <AuditSessionDetailPage />
      </Wrapper>
    );
    await waitFor(() =>
      expect(vi.mocked(agentApi).getAuditSessionTranscript).toHaveBeenCalledWith("s1")
    );
  });

  it("audit run detail page loads granular attempts calls", async () => {
    render(
      <Wrapper>
        <AuditRunDetailPage />
      </Wrapper>
    );
    await waitFor(() =>
      expect(vi.mocked(agentApi).getAuditRunAttempts).toHaveBeenCalledWith("r1")
    );
  });

  it("audit events use next_seq cursor for subsequent pages", async () => {
    vi.mocked(agentApi.getAuditRunEvents).mockResolvedValue({
      items: [{ id: "e1", run_id: "r1", attempt_id: null, seq: 37, event_type: "test", payload: {}, created_at: "2026-07-25T00:00:00Z" }],
      next_seq: 37,
    });

    render(
      <Wrapper>
        <AuditRunDetailPage />
      </Wrapper>
    );

    await waitFor(() =>
      expect(vi.mocked(agentApi).getAuditRunEvents).toHaveBeenCalledWith("r1", null, 50)
    );

    const loadMoreBtn = screen.getByRole("button", { name: "加载更多事件" });
    await waitFor(() => expect(loadMoreBtn).toBeDefined());

    loadMoreBtn.click();

    await waitFor(() =>
      expect(vi.mocked(agentApi).getAuditRunEvents).toHaveBeenCalledWith("r1", 37, 50)
    );
  });

  // ---- New Task 6 assertions ----

  it("audit list page shows 治理中心 heading", async () => {
    render(
      <Wrapper>
        <AuditPage />
      </Wrapper>
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "治理中心" })).toBeDefined()
    );
  });

  it("audit list has no privileged-access wording", async () => {
    render(
      <Wrapper>
        <AuditPage />
      </Wrapper>
    );
    await waitFor(() => {
      expect(screen.queryByText(/特权访问/)).toBeNull();
      expect(screen.queryByText(/自动留痕/)).toBeNull();
    });
  });

  it("session detail shows owner display_name and username from transcript", async () => {
    render(
      <Wrapper>
        <AuditSessionDetailPage />
      </Wrapper>
    );
    await waitFor(() => {
      expect(screen.getByText("张三")).toBeDefined();
      expect(screen.getByText("jdoe")).toBeDefined();
    });
  });

  it("session detail shows conversation transcript region", async () => {
    render(
      <Wrapper>
        <AuditSessionDetailPage />
      </Wrapper>
    );
    await waitFor(() => {
      expect(screen.getByRole("region", { name: "对话全文" })).toBeDefined();
    });
  });

  it("session detail has collapsible diagnostics", async () => {
    render(
      <Wrapper>
        <AuditSessionDetailPage />
      </Wrapper>
    );
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /展开运行诊断/ })).toBeDefined();
    });
  });

  it("session detail has no privileged-access wording", async () => {
    render(
      <Wrapper>
        <AuditSessionDetailPage />
      </Wrapper>
    );
    await waitFor(() => {
      expect(screen.queryByText(/特权访问/)).toBeNull();
      expect(screen.queryByText(/自动留痕/)).toBeNull();
    });
  });

  it("run detail uses getAuditRun instead of getRun", async () => {
    render(
      <Wrapper>
        <AuditRunDetailPage />
      </Wrapper>
    );
    await waitFor(() => {
      expect(vi.mocked(agentApi).getAuditRun).toHaveBeenCalledWith("r1");
      expect(vi.mocked(agentApi).getRun).not.toHaveBeenCalled();
    });
  });

  it("run detail has no privileged-access wording", async () => {
    render(
      <Wrapper>
        <AuditRunDetailPage />
      </Wrapper>
    );
    await waitFor(() => {
      expect(screen.queryByText(/特权访问/)).toBeNull();
      expect(screen.queryByText(/自动留痕/)).toBeNull();
    });
  });

  it("audit list calls listAuditSessions", async () => {
    render(
      <Wrapper>
        <AuditPage />
      </Wrapper>
    );
    await waitFor(() => {
      expect(vi.mocked(agentApi).listAuditSessions).toHaveBeenCalled();
    });
  });

  it("run detail page has breadcrumb link back to session page", async () => {
    render(
      <Wrapper>
        <AuditRunDetailPage />
      </Wrapper>
    );
    await waitFor(() => {
      const link = screen.getByRole("link", { name: /返回会话详情|返回会话|会话详情/ });
      expect(link).toBeDefined();
      expect(link).toHaveAttribute("href", "/agent/audit/sessions/s1");
    });
  });

  it("run detail renders quality review section when quality event exists", async () => {
    vi.mocked(agentApi.getAuditRunEvents).mockResolvedValue({
      items: [
        {
          id: "e1",
          run_id: "r1",
          attempt_id: null,
          seq: 10,
          event_type: "quality_review_completed",
          payload: {
            file_id: "f1",
            rounds: 2,
            score: 62,
            pass: true,
            dims: [
              { name: "准确性", pass: true, reason: "数据核对无误" },
              { name: "完整性", pass: false, reason: "缺少费用明细" },
            ],
          },
          created_at: "2026-07-25T00:00:00Z",
        },
      ],
      next_seq: null,
    });

    const { container } = render(
      <Wrapper>
        <AuditRunDetailPage />
      </Wrapper>
    );
    await waitFor(() => {
      const section = container.querySelector(".quality-review-section");
      expect(section).not.toBeNull();
      const text = section?.textContent ?? "";
      expect(text).toContain("质量审校");
      expect(text).toContain("62");
      expect(text).toContain("分");
      expect(text).toContain("准确性");
      expect(text).toContain("数据核对无误");
      expect(text).toContain("完整性");
      expect(text).toContain("缺少费用明细");
      expect(text).toContain("共 2 轮评审");
      expect(text).toContain("✓");
      expect(text).toContain("✗");
    });
  });

  it("run detail hides quality review section when no quality event", async () => {
    vi.mocked(agentApi.getAuditRunEvents).mockResolvedValue({
      items: [
        {
          id: "e1",
          run_id: "r1",
          attempt_id: null,
          seq: 5,
          event_type: "run_succeeded",
          payload: {},
          created_at: "2026-07-25T00:00:00Z",
        },
      ],
      next_seq: null,
    });

    const { container } = render(
      <Wrapper>
        <AuditRunDetailPage />
      </Wrapper>
    );
    await waitFor(() => {
      expect(vi.mocked(agentApi).getAuditRunEvents).toHaveBeenCalledWith("r1", null, 50);
    });
    await waitFor(() => {
      expect(container.querySelector(".quality-review-section")).toBeNull();
    });
  });

  it("audit list offers a DSH sessions tab that loads the audit table", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
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
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(
      <Wrapper>
        <AuditPage />
      </Wrapper>
    );
    await waitFor(() => expect(screen.getByRole("heading", { name: "治理中心" })).toBeDefined());
    const tabs = Array.from(container.querySelectorAll<HTMLElement>(".ant-tabs-tab"));
    const tabText = tabs.map((el) => el.textContent ?? "").join(" ");
    expect(tabText).toContain("DSH 会话");
    const dshTab = tabs.find((el) => (el.textContent ?? "").includes("DSH 会话"));
    expect(dshTab).toBeDefined();
    vi.clearAllMocks();
    await act(async () => {
      fireEvent.click(dshTab as HTMLElement);
    });
    await waitFor(() => {
      const url = String(fetchMock.mock.calls[0][0]);
      expect(url).toContain("/api/dsh/sessions/audit?page=1&page_size=20");
    });
    vi.unstubAllGlobals();
  });
});
