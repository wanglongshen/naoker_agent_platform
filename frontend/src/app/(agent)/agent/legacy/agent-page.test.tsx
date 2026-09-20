import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfigProvider } from "antd";

const mockAgentApi = vi.hoisted(() => ({
  createSession: vi.fn().mockResolvedValue({ id: "session-1", owner_user_id: "u1", title: "test", last_run_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }),
  createRun: vi.fn().mockResolvedValue({ id: "run-1", session_id: "session-1", goal: "test", status: "queued", mode: "quick", network_enabled: true, owner_user_id: "u1", current_attempt_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }),
  uploadAttachment: vi.fn().mockResolvedValue({ id: "attachment-1", filename: "report.txt", media_type: "text/plain", size_bytes: 100, extraction_status: "done", created_at: "2026-01-01T00:00:00Z" }),
  listSessions: vi.fn().mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 }),
  getSessionRuns: vi.fn().mockResolvedValue([]),
  getRunEvents: vi.fn().mockResolvedValue([]),
  getRunSteps: vi.fn().mockResolvedValue([]),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/agent",
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/agent-api", () => ({ agentApi: mockAgentApi }));
vi.mock("@/lib/agent-session-store", () => ({ invalidateAgentSessions: vi.fn() }));
vi.mock("@/hooks/use-typing-text", () => ({ useTypingText: () => "mock" }));
vi.mock("@/lib/auth", () => ({ fetchCurrentUser: vi.fn().mockResolvedValue(null) }));
vi.mock("@/lib/api", () => ({ api: vi.fn().mockResolvedValue([]) }));

import AgentPage from "./page";

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider>{children}</ConfigProvider>;
}

describe("Agent page chat composer", () => {
  it("renders top bar and landing copy", () => {
    render(<Wrapper><AgentPage /></Wrapper>);
    expect(screen.getByRole("heading", { level: 1, name: "脑壳工作台" })).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: "今天有什么想一起完成？" })).toBeVisible();
    expect(screen.getByText("在脑壳工作台中提问、写作、分析与协作")).toBeVisible();
  });

  it("creates session and run via ChatComposer", async () => {
    const user = userEvent.setup();
    render(<Wrapper><AgentPage /></Wrapper>);

    const textarea = screen.getByPlaceholderText("问问题、分析材料或开始创作…");
    await user.type(textarea, "请帮我分析数据");
    await user.click(screen.getByRole("button", { name: "发送消息" }));

    await waitFor(() => {
      expect(mockAgentApi.createSession).toHaveBeenCalledOnce();
      expect(mockAgentApi.createRun).toHaveBeenCalledWith("session-1", expect.objectContaining({
        goal: "请帮我分析数据",
      }));
    });
  });

  it("renders the project selector capsule on the landing page", async () => {
    render(<Wrapper><AgentPage /></Wrapper>);
    await waitFor(() => {
      expect(document.querySelector(".composer-project-capsule")).toBeTruthy();
    });
  });

  it("shows the attachment button on the landing page", () => {
    render(<Wrapper><AgentPage /></Wrapper>);
    expect(screen.getByLabelText("添加附件")).toBeInTheDocument();
  });
});
