import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mockPathname, mockPush } = vi.hoisted(() => ({
  mockPathname: vi.fn(() => "/agent"),
  mockPush: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => mockPathname(),
}));

const { mockListSessions } = vi.hoisted(() => ({ mockListSessions: vi.fn() }));
vi.mock("@/lib/agent-api", () => ({
  agentApi: { listSessions: mockListSessions },
}));

import AppSidebar from "./app-sidebar";
import { dshBridgeStore, dshInstanceStore } from "@/lib/dsh-bridge-store";
import type { CurrentUser } from "@/types/auth";

const USER: CurrentUser = {
  id: "u1",
  username: "admin",
  display_name: "管理员",
  roles: [],
  permissions: [],
  menu_permissions: [],
};

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider theme={{ token: { motion: false } }}>{children}</ConfigProvider>;
}

function renderSidebar(overrides: Partial<CurrentUser> = {}) {
  const user: CurrentUser = { ...USER, ...overrides };
  if (overrides.permissions && overrides.menu_permissions === undefined) {
    user.menu_permissions = overrides.permissions;
  }
  return render(
    <Wrapper>
      <AppSidebar user={user} />
    </Wrapper>
  );
}

describe("AppSidebar route split", () => {
  beforeEach(() => {
    mockPathname.mockReturnValue("/agent");
    mockListSessions.mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0 });
    dshBridgeStore.reset();
    dshInstanceStore.reset();
    dshInstanceStore.publish("running");
  });

  it("renders the DSH nav section on /agent and not the legacy list", () => {
    render(
      <Wrapper>
        <AppSidebar user={USER} />
      </Wrapper>
    );
    expect(screen.getByText("+ 新会话")).toBeTruthy();
    expect(screen.queryByText("还没有会话，先开始一段新对话。")).toBeNull();
  });

  it("renders the legacy session list on /agent/legacy and not the DSH nav", () => {
    mockPathname.mockReturnValue("/agent/legacy");
    render(
      <Wrapper>
        <AppSidebar user={USER} />
      </Wrapper>
    );
    expect(screen.getByText("还没有会话，先开始一段新对话。")).toBeTruthy();
    expect(screen.queryByText("+ 新会话")).toBeNull();
  });

  it("renders the legacy session list on legacy session detail routes", () => {
    mockPathname.mockReturnValue("/agent/sessions/abc");
    render(
      <Wrapper>
        <AppSidebar user={USER} />
      </Wrapper>
    );
    expect(screen.getByText("还没有会话，先开始一段新对话。")).toBeTruthy();
    expect(screen.queryByText("+ 新会话")).toBeNull();
  });

  it("keeps the DSH session area on non-root agent subroutes", () => {
    mockPathname.mockReturnValue("/agent/audit");
    render(
      <Wrapper>
        <AppSidebar user={USER} />
      </Wrapper>
    );
    expect(screen.getByText("+ 新会话")).toBeTruthy();
    expect(screen.queryByText("还没有会话，先开始一段新对话。")).toBeNull();
  });

  it("keeps the DSH session area outside agent routes and navigates on session click", async () => {
    mockPathname.mockReturnValue("/account/points");
    dshBridgeStore.publishNav({
      currentSessionId: "s1",
      groups: [
        {
          key: "w1",
          label: "默认工作区",
          sessions: [{ id: "s9", title: "历史方案", blank: false, running: false, updatedAt: 1 }],
        },
      ],
    });
    render(
      <Wrapper>
        <AppSidebar user={USER} />
      </Wrapper>
    );
    expect(screen.getByText("+ 新会话")).toBeTruthy();
    await userEvent.click(screen.getByText("历史方案"));
    expect(mockPush).toHaveBeenCalledWith("/agent?session=s9");
  });

  it("shows the instance startup state from the instance store on /agent", () => {
    dshInstanceStore.reset();
    render(
      <Wrapper>
        <AppSidebar user={USER} />
      </Wrapper>
    );
    expect(screen.getByText(/正在启动 DSH 实例/)).toBeTruthy();
  });

  it("routes DSH nav commands through the bridge store sender", async () => {
    const sender = vi.fn();
    dshBridgeStore.setSender(sender);
    render(
      <Wrapper>
        <AppSidebar user={USER} />
      </Wrapper>
    );
    await userEvent.click(screen.getByRole("button", { name: "+ 新会话" }));
    expect(sender).toHaveBeenCalledWith({ v: 1, type: "cmd", action: "new-session" });
  });

  it("shows the DSH settings entry while the instance is running", () => {
    render(
      <Wrapper>
        <AppSidebar user={USER} />
      </Wrapper>
    );
    expect(screen.getByText("DSH 设置")).toBeTruthy();
  });

  it("keeps the DSH settings entry when the instance is not running", () => {
    dshInstanceStore.reset();
    dshInstanceStore.publish("stopped");
    render(
      <Wrapper>
        <AppSidebar user={USER} />
      </Wrapper>
    );
    expect(screen.getByText("DSH 设置")).toBeTruthy();
  });

  it("keeps the DSH settings entry outside the agent workspace", () => {
    mockPathname.mockReturnValue("/account/points");
    render(
      <Wrapper>
        <AppSidebar user={USER} />
      </Wrapper>
    );
    expect(screen.getByText("DSH 设置")).toBeTruthy();
  });

  it("知识库管理紧跟在文件管理之后", async () => {
    renderSidebar({
      roles: [{ code: "super_admin", name: "超级管理员" }],
      permissions: ["user:read", "role:read", "file:admin_view"],
    });
    await screen.findByText("文件管理");
    const items = Array.from(document.querySelectorAll(".sidebar-management .ant-menu-item"));
    const labels = items.map((item) => item.textContent ?? "");
    const filesIndex = labels.findIndex((text) => text.includes("文件管理"));
    const knowledgeIndex = labels.findIndex((text) => text.includes("知识库管理"));
    expect(knowledgeIndex).toBe(filesIndex + 1);
  });

  it("不再渲染方案中心菜单项", () => {
    renderSidebar({
      roles: [{ code: "super_admin", name: "超级管理员" }],
      permissions: ["user:read", "role:read", "file:admin_view"],
    });
    expect(screen.queryByText("方案中心")).toBeNull();
  });

  it("实例未运行时也显示 DSH 设置，点击跳转 /agent?settings=1", async () => {
    mockPush.mockClear();
    dshInstanceStore.reset();
    dshInstanceStore.publish("stopped");
    renderSidebar({ roles: [{ code: "super_admin", name: "超级管理员" }], permissions: [] });
    const button = await screen.findByRole("button", { name: "DSH 设置" });
    button.click();
    expect(mockPush).toHaveBeenCalledWith("/agent?settings=1");
  });
});
