import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockApi, mockFetchCurrentUser, mockRedirectToLogin } = vi.hoisted(() => ({
  mockApi: vi.fn(),
  mockFetchCurrentUser: vi.fn(),
  mockRedirectToLogin: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: mockApi,
  };
});
vi.mock("@/lib/auth", () => ({
  fetchCurrentUser: mockFetchCurrentUser,
  redirectToLogin: mockRedirectToLogin,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/roles",
}));

import RoleManagement from "@/components/roles/role-management";
import RoleDrawer from "@/components/roles/role-drawer";
import DashboardLayout from "@/app/(dashboard)/layout";
import RolesPage from "@/app/(dashboard)/roles/page";
import type { CurrentUser } from "@/types/auth";
import type { RoleListItem } from "@/types/role";

function pageButtons() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
}

function findPageButton(label: RegExp) {
  return pageButtons().find((b) => label.test(b.textContent || ""));
}

const mockRoles = {
  items: [
    {
      id: "r1",
      code: "Super Admin",
      name: "Super Admin",
      description: "Full access",
      status: "active",
      is_system: true,
      permission_count: 13,
    },
    {
      id: "r2",
      code: "user_manager",
      name: "User Manager",
      description: "Manage users",
      status: "active",
      is_system: true,
      permission_count: 7,
    },
    {
      id: "r3",
      code: "viewer",
      name: "Viewer",
      description: null,
      status: "disabled",
      is_system: false,
      permission_count: 2,
    },
  ],
  page: 1,
  page_size: 10,
  total: 3,
};

const mockPermissions = [
  { id: "p1", code: "user:read", name: "Read users", module: "user", description: null },
  { id: "p2", code: "role:read", name: "Read roles", module: "role", description: null },
];

const readerUser: CurrentUser = {
  id: "1",
  username: "reader",
  display_name: "Reader",
  roles: [],
  permissions: ["role:read"],
  menu_permissions: [],
};

const adminUser: CurrentUser = {
  id: "2",
  username: "admin",
  display_name: "Admin",
  roles: [],
  permissions: [
    "role:read",
    "role:create",
    "role:update",
    "role:delete",
    "role:status",
    "role:assign_permission",
  ],
  menu_permissions: [],
};

describe("RoleManagement", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  async function mockListAndPerms() {
    mockApi.mockImplementation((path: string) => {
      if (path.includes("/api/permissions")) return Promise.resolve(mockPermissions);
      if (path.startsWith("/api/roles")) return Promise.resolve(mockRoles);
      return Promise.resolve({});
    });
  }

  test("loads roles and hides actions without permissions", async () => {
    await mockListAndPerms();
    render(<RoleManagement currentUser={readerUser} />);

    expect(await screen.findByText("Super Admin")).toBeVisible();
    expect(screen.queryByRole("button", { name: "新建角色" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /编辑/ })).not.toBeInTheDocument();
  });

  test("shows action buttons for user with all permissions", async () => {
    await mockListAndPerms();
    render(<RoleManagement currentUser={adminUser} />);

    expect(await screen.findByText("Super Admin")).toBeVisible();
    expect(findPageButton(/新建角色/)).toBeVisible();
    expect(document.querySelector(".ant-table")).not.toBeNull();
    expect(pageButtons().filter((b) => /编辑/.test(b.textContent || ""))).toHaveLength(3);
  });

  test("hides status/delete for system role", async () => {
    await mockListAndPerms();
    render(<RoleManagement currentUser={adminUser} />);

    expect(await screen.findByText("Super Admin")).toBeVisible();
    const systemElements = screen.getAllByText("系统角色");
    expect(systemElements.length).toBeGreaterThanOrEqual(1);

    const rows = Array.from(document.querySelectorAll(".ant-table-row")) as HTMLElement[];
    const superAdminRow = rows.find((row) => within(row).queryByText("Super Admin"))!;
    const superAdminLabels = Array.from(superAdminRow.querySelectorAll("button")).map((b) => b.textContent || "");
    expect(superAdminLabels.filter((t) => /编辑/.test(t))).toHaveLength(1);
    expect(superAdminLabels.filter((t) => /停\s*用/.test(t))).toHaveLength(0);
    expect(superAdminLabels.filter((t) => /删\s*除/.test(t))).toHaveLength(0);

    const viewerRow = rows.find((row) => within(row).queryByText("Viewer"))!;
    const viewerLabels = Array.from(viewerRow.querySelectorAll("button")).map((b) => b.textContent || "");
    expect(viewerLabels.filter((t) => /启\s*用/.test(t))).toHaveLength(1);
    expect(viewerLabels.filter((t) => /删\s*除/.test(t))).toHaveLength(1);
  });

  test("displays loading state while fetching", async () => {
    let resolvePromise: (value: unknown) => void;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });
    mockApi.mockReturnValue(promise);
    render(<RoleManagement currentUser={adminUser} />);

    expect(document.querySelector(".ant-skeleton")).toBeVisible();
    resolvePromise!(mockRoles);
  });

  test("displays empty state when no roles returned", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path.includes("/api/permissions")) return Promise.resolve([]);
      return Promise.resolve({ items: [], page: 1, page_size: 10, total: 0 });
    });
    render(<RoleManagement currentUser={adminUser} />);

    expect(await screen.findByText(/请新建角色/i)).toBeVisible();
  });

  test("displays error state on fetch failure", async () => {
    mockApi.mockRejectedValue(new Error("Network error"));
    render(<RoleManagement currentUser={adminUser} />);

    expect(await screen.findByText(/Network error/i)).toBeVisible();
  });

  test("rebuilds request with filter parameters on search", async () => {
    await mockListAndPerms();
    const user = userEvent.setup();
    render(<RoleManagement currentUser={adminUser} />);

    await screen.findByText("Super Admin");
    mockApi.mockClear();
    mockApi.mockImplementation((path: string) => {
      if (path.includes("/api/permissions")) return Promise.resolve(mockPermissions);
      return Promise.resolve(mockRoles);
    });

    await user.type(screen.getByPlaceholderText("搜索角色"), "test");
    await user.click(findPageButton(/查/)!);

    expect(mockApi).toHaveBeenCalledWith(
      expect.stringContaining("keyword=test")
    );
  });

  test("shows pagination when multiple pages exist", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path.includes("/api/permissions")) return Promise.resolve(mockPermissions);
      return Promise.resolve({ ...mockRoles, total: 25, page: 1, page_size: 10 });
    });
    render(<RoleManagement currentUser={adminUser} />);

    await screen.findByText("Super Admin");
    expect(screen.getByText("共 25 条")).toBeVisible();
    expect(document.querySelector(".ant-pagination")).toBeVisible();
  });

  test("以中文显示角色管理和系统角色提示", async () => {
    await mockListAndPerms();
    render(<RoleManagement currentUser={adminUser} />);
    expect(await screen.findByRole("heading", { name: "角色管理" })).toBeVisible();
    expect(findPageButton(/新建角色/)).toBeVisible();
  });

  test("displays role governance summary with real totals", async () => {
    const mockItems = Array.from({ length: 10 }, (_, i) => ({
      id: `r${i + 1}`,
      code: `role${i + 1}`,
      name: `Role ${i + 1}`,
      description: null,
      status: "active" as const,
      is_system: i === 0,
      permission_count: i + 20,
    }));
    const mockPerms = Array.from({ length: 13 }, (_, i) => ({
      id: `p${i + 1}`,
      code: `perm:${i + 1}`,
      name: `Perm ${i + 1}`,
      module: i % 2 === 0 ? "user" : "role",
      description: null,
    }));
    mockApi.mockImplementation((path: string) => {
      if (path.includes("/api/permissions")) return Promise.resolve(mockPerms);
      return Promise.resolve({ items: mockItems, page: 1, page_size: 10, total: 16 });
    });
    render(<RoleManagement currentUser={adminUser} />);

    expect(await screen.findByText("16")).toBeVisible();
    expect(screen.getByText("10")).toBeVisible();
    expect(screen.getByText("13")).toBeVisible();
    expect(screen.getAllByText("角色名称")[0]).toBeVisible();
  });

  test("role:read user reaches roles without user:read", async () => {
    mockFetchCurrentUser.mockResolvedValue({
      id: "role-reader",
      username: "role-reader",
      display_name: "Role Reader",
      roles: [],
      permissions: ["role:read"],
      menu_permissions: [],
    });
    mockApi.mockImplementation((path: string) => {
      if (path.includes("/api/permissions")) return Promise.resolve(mockPermissions);
      return Promise.resolve(mockRoles);
    });

    render(<DashboardLayout><RolesPage /></DashboardLayout>);

    expect(await screen.findByRole("heading", { name: "角色管理" })).toBeVisible();
    expect(screen.queryByText("无权访问")).not.toBeInTheDocument();
    mockFetchCurrentUser.mockReset();
  });

  test("role status is changed through the dedicated action, not the edit drawer", async () => {
    const sampleRole: RoleListItem = {
      id: "r1",
      code: "test",
      name: "Test Role",
      description: null,
      status: "active",
      is_system: false,
      permission_count: 3,
    };

    mockApi.mockResolvedValue({
      id: "r1",
      code: "test",
      name: "Test Role",
      description: null,
      status: "active",
      is_system: false,
      permission_count: 3,
      permissions: [],
      assigned_user_count: 0,
    });

    render(
      <RoleDrawer
        open
        role={sampleRole}
        currentUser={adminUser}
        permissions={mockPermissions}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    await screen.findByText("权限分配");
    expect(screen.queryByLabelText("状态")).not.toBeInTheDocument();
  });
});
