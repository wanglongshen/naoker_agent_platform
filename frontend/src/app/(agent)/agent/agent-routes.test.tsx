import { describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ConfigProvider } from "antd";

const { mockPathname } = vi.hoisted(() => ({ mockPathname: vi.fn(() => "/agent") }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => mockPathname(),
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams(),
}));

const { mockFetchCurrentUser } = vi.hoisted(() => ({ mockFetchCurrentUser: vi.fn() }));
vi.mock("@/lib/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth")>();
  return { ...actual, fetchCurrentUser: mockFetchCurrentUser };
});

const { mockListSessions } = vi.hoisted(() => ({ mockListSessions: vi.fn() }));
vi.mock("@/lib/agent-api", () => ({
  agentApi: { listSessions: mockListSessions },
}));

import AppSidebar from "@/components/layout/app-sidebar";
import { dshInstanceStore } from "@/lib/dsh-bridge-store";
import type { CurrentUser } from "@/types/auth";
import { copy, PRODUCT_NAME } from "@/lib/copy";

const ordinaryUser: CurrentUser = {
  id: "1",
  username: "user",
  display_name: "普通用户",
  roles: [],
  permissions: [],
  menu_permissions: [],
};

const superAdmin: CurrentUser = {
  id: "2",
  username: "admin",
  display_name: "管理员",
  roles: [{ id: "r1", code: "super_admin", name: "超级管理员" }],
  permissions: ["user:read", "role:read"],
  menu_permissions: ["user:read", "role:read"],
};

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider theme={{ token: { motion: false } }}>{children}</ConfigProvider>;
}

describe("Agent routes", () => {
  beforeEach(() => {
    mockPathname.mockReturnValue("/agent");
    mockFetchCurrentUser.mockReset();
    mockListSessions.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 });
    dshInstanceStore.reset();
    dshInstanceStore.publish("running");
  });

  test("renders Agent navigation for any authenticated user", () => {
    render(
      <Wrapper>
        <AppSidebar user={ordinaryUser} />
      </Wrapper>
    );
    expect(screen.getByText("+ 新会话")).toBeDefined();
  });

  test("hides audit navigation for ordinary user", () => {
    render(
      <Wrapper>
        <AppSidebar user={ordinaryUser} />
      </Wrapper>
    );
    expect(screen.queryByText(copy.navigation.agentAudit)).not.toBeInTheDocument();
  });

  test("shows audit navigation for super_admin", () => {
    render(
      <Wrapper>
        <AppSidebar user={superAdmin} />
      </Wrapper>
    );
    expect(screen.getByText(copy.navigation.agentAudit)).toBeDefined();
  });

  test("shows both Agent and Audit for super_admin", () => {
    render(
      <Wrapper>
        <AppSidebar user={superAdmin} />
      </Wrapper>
    );
    expect(screen.getByText("+ 新会话")).toBeDefined();
    expect(screen.getByText(copy.navigation.agentAudit)).toBeDefined();
  });

  test("preserves /users and /roles for user with permissions", () => {
    render(
      <Wrapper>
        <AppSidebar user={superAdmin} />
      </Wrapper>
    );
    expect(screen.getByText(copy.navigation.users)).toBeDefined();
    expect(screen.getByText(copy.navigation.roles)).toBeDefined();
  });

  test("hides /users and /roles for user without permissions", () => {
    render(
      <Wrapper>
        <AppSidebar user={ordinaryUser} />
      </Wrapper>
    );
    expect(screen.queryByText(copy.navigation.users)).not.toBeInTheDocument();
    expect(screen.queryByText(copy.navigation.roles)).not.toBeInTheDocument();
  });

  test("highlights /agent when pathname starts with /agent", () => {
    render(
      <Wrapper>
        <AppSidebar user={superAdmin} />
      </Wrapper>
    );
    expect(screen.getByText("+ 新会话")).toBeDefined();
  });

  test("highlights /agent/audit when pathname starts with /agent/audit", () => {
    mockPathname.mockReturnValue("/agent/audit");
    render(
      <Wrapper>
        <AppSidebar user={superAdmin} />
      </Wrapper>
    );
    expect(screen.getByText(copy.navigation.agentAudit)).toBeDefined();
  });

  test("renders owned sessions in the sidebar session list on the legacy route", async () => {
    mockPathname.mockReturnValue("/agent/legacy");
    mockListSessions.mockResolvedValue({
      items: [{
        id: "session-1",
        owner_user_id: ordinaryUser.id,
        title: "季度报告分析",
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
        <AppSidebar user={ordinaryUser} />
      </Wrapper>
    );

    expect(screen.getByText("开始新对话")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("季度报告分析")).toBeInTheDocument());
  });

  test("keeps management navigation above the account footer when Agent sessions are present", async () => {
    mockPathname.mockReturnValue("/agent/legacy");
    mockListSessions.mockResolvedValue({ items: [{ id: "s1", title: "test", owner_user_id: superAdmin.id, last_run_id: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }], page: 1, page_size: 20, total: 1 });
    render(<Wrapper><AppSidebar user={superAdmin} /></Wrapper>);
    await waitFor(() => expect(screen.getByText("test")).toBeInTheDocument());
    expect(screen.getByText("test")).toBeInTheDocument();
  });
});

describe("AppSidebar semantics", () => {
  beforeEach(() => {
    mockPathname.mockReturnValue("/agent");
    mockFetchCurrentUser.mockReset();
    mockListSessions.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 });
  });

  test("renders nav with aria-label 主导航", () => {
    render(
      <Wrapper>
        <AppSidebar user={superAdmin} />
      </Wrapper>
    );
    expect(screen.getByRole("navigation", { name: "主导航" })).toBeVisible();
  });

  test("renders 脑壳工作台 product name link", () => {
    render(
      <Wrapper>
        <AppSidebar user={superAdmin} />
      </Wrapper>
    );
    const brandLink = screen.getByRole("link", { name: /脑壳工作台/ });
    expect(brandLink).toBeVisible();
  });

  test('"开始新对话" link points to /agent on non-agent routes', () => {
    mockPathname.mockReturnValue("/users");
    render(
      <Wrapper>
        <AppSidebar user={superAdmin} />
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
        owner_user_id: superAdmin.id,
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
        <AppSidebar user={superAdmin} />
      </Wrapper>
    );

    await waitFor(() => {
      const activeLink = screen.getByText("季度报告").closest("a");
      expect(activeLink).toHaveAttribute("aria-current", "page");
    });
  });
});
