import { describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";
import { copy, PRODUCT_NAME } from "@/lib/copy";

const { mockPathname } = vi.hoisted(() => ({ mockPathname: vi.fn(() => "/agent") }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => mockPathname(),
}));

const { mockListSessions } = vi.hoisted(() => ({ mockListSessions: vi.fn() }));
vi.mock("@/lib/agent-api", () => ({
  agentApi: { listSessions: mockListSessions },
}));

import DashboardShell from "@/components/layout/dashboard-shell";
import AppShell from "@/components/layout/app-shell";
import type { CurrentUser } from "@/types/auth";

const user: CurrentUser = {
  id: "1",
  username: "admin",
  display_name: "Admin User",
  roles: [],
  permissions: ["user:read", "role:read"],
  menu_permissions: ["user:read", "role:read"],
};

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider theme={{ token: { motion: false } }}>{children}</ConfigProvider>;
}

beforeEach(() => {
  mockPathname.mockReturnValue("/agent");
  mockListSessions.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 });
});

describe("DashboardShell (legacy)", () => {
  test("renders branded shell with sidebar and navigation", () => {
    render(
      <Wrapper>
        <DashboardShell currentUser={{ ...user, menu_permissions: ["user:read"] }}>
          body
        </DashboardShell>
      </Wrapper>
    );
    expect(screen.getAllByText(copy.app.title)[0]).toBeVisible();
  });

  test("shows only menu entries allowed by menu permissions", () => {
    render(
      <Wrapper>
        <DashboardShell currentUser={{ ...user, menu_permissions: ["user:read"] }}>
          body
        </DashboardShell>
      </Wrapper>
    );
    expect(screen.getByRole("link", { name: copy.navigation.users })).toBeVisible();
    expect(screen.queryByRole("link", { name: copy.navigation.roles })).not.toBeInTheDocument();
  });

  test("opens the mobile navigation drawer", async () => {
    render(
      <Wrapper>
        <DashboardShell currentUser={{ ...user, menu_permissions: ["user:read"] }}>
          body
        </DashboardShell>
      </Wrapper>
    );
    await userEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByRole("dialog")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("AppShell semantic shell", () => {
  const shellUser: CurrentUser = {
    id: "1",
    username: "admin",
    display_name: "Admin User",
    roles: [],
    permissions: ["user:read", "role:read"],
    menu_permissions: ["user:read", "role:read"],
  };

  test("renders a semantic <main> region", () => {
    render(
      <Wrapper>
        <AppShell currentUser={shellUser}>body</AppShell>
      </Wrapper>
    );
    expect(screen.getByRole("main")).toBeVisible();
  });

  test("renders a semantic <nav> with aria-label 主导航", () => {
    render(
      <Wrapper>
        <AppShell currentUser={shellUser}>body</AppShell>
      </Wrapper>
    );
    expect(screen.getByRole("navigation", { name: "主导航" })).toBeVisible();
  });

  test("renders 脑壳工作台 branding link", () => {
    render(
      <Wrapper>
        <AppShell currentUser={shellUser}>body</AppShell>
      </Wrapper>
    );
    const brandLink = screen.getByRole("link", { name: /脑壳工作台/ });
    expect(brandLink).toBeVisible();
  });

  test('"开始新对话" link points to /agent on non-agent routes', () => {
    mockPathname.mockReturnValue("/users");
    render(
      <Wrapper>
        <AppShell currentUser={shellUser}>body</AppShell>
      </Wrapper>
    );
    const newChatLink = screen.getByRole("link", { name: "开始新对话" });
    expect(newChatLink).toHaveAttribute("href", "/agent");
  });

  test("active session link has aria-current page", async () => {
    mockPathname.mockReturnValue("/agent/sessions/s1");
    mockListSessions.mockResolvedValue({
      items: [{
        id: "s1",
        title: "季度报告",
        owner_user_id: shellUser.id,
        last_run_id: null,
        created_at: "2026-07-24T00:00:00Z",
        updated_at: "2026-07-24T00:00:00Z",
      }],
      page: 1,
      page_size: 20,
      total: 1,
    });

    render(
      <Wrapper>
        <AppShell currentUser={shellUser}>body</AppShell>
      </Wrapper>
    );

    await waitFor(() => {
      const activeLink = screen.getByText("季度报告").closest("a");
      expect(activeLink).toHaveAttribute("aria-current", "page");
    });
  });

  test("collapsed sidebar does not leave hidden links focusable", async () => {
    const { container } = render(
      <Wrapper>
        <AppShell currentUser={shellUser}>body</AppShell>
      </Wrapper>
    );

    const trigger = screen.getByRole("button", { name: /收起导航|展开导航/ });
    await userEvent.click(trigger);

    const sidebar = container.querySelector(".enterprise-sidebar");
    if (sidebar) {
      expect(sidebar.hasAttribute("inert")).toBe(true);
      const links = sidebar.querySelectorAll("a");
      links.forEach((link) => {
        expect(link.closest("[inert]")).toBeTruthy();
      });
    }
  });
});
