import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import SessionSidebarList from "./session-sidebar-list";

const mockPrefetch = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ prefetch: mockPrefetch, push: vi.fn() }),
  usePathname: () => "/agent",
  Link: ({ href, children, ...props }: any) => <a href={href} {...props}>{children}</a>,
}));

const sessions = [
  { id: "s1", title: "最新会话", updated_at: "2026-07-25T00:00:00Z", created_at: "2026-07-25T00:00:00Z", owner_user_id: "u1", owner_display_name: "Test User", last_run_id: null },
  { id: "s2", title: "旧会话", updated_at: "2026-06-15T00:00:00Z", created_at: "2026-06-15T00:00:00Z", owner_user_id: "u1", owner_display_name: "Test User", last_run_id: null },
];

describe("SessionSidebarList", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("groups sessions by update month and highlights the active session", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-20T12:00:00Z"));
    render(<SessionSidebarList sessions={sessions} activeSessionId="s1" onNavigate={vi.fn()} />);
    expect(screen.getByText("30 天内")).toBeInTheDocument();
    expect(screen.getByText("2026-06")).toBeInTheDocument();
  });

  it("shows empty state when no sessions", () => {
    render(<SessionSidebarList sessions={[]} activeSessionId={null} onNavigate={vi.fn()} />);
    expect(screen.getByText("还没有会话，先开始一段新对话。")).toBeInTheDocument();
  });

  it("prefetches a session route on pointer enter and keyboard focus", async () => {
    const user = userEvent.setup();
    render(<SessionSidebarList sessions={sessions} activeSessionId={null} />);
    const link = screen.getByRole("link", { name: "最新会话" });
    await user.hover(link);
    expect(mockPrefetch).toHaveBeenCalledWith("/agent/sessions/s1");
  });
});
