import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: mockApi,
    adminPointsAll: () => mockApi("/api/admin/points/all"),
    adminGrantPoints: (userId: string, points: number, description: string) =>
      mockApi("/api/admin/points/grant", {
        method: "POST",
        body: JSON.stringify({ user_id: userId, points, description }),
        csrf: true,
      }),
    adminCreateRedeemCodes: (points: number, count: number) =>
      mockApi("/api/admin/redeem-codes", {
        method: "POST",
        body: JSON.stringify({ points, count }),
        csrf: true,
      }),
    adminListRedeemCodes: (page = 1, pageSize = 20) =>
      mockApi(`/api/admin/redeem-codes?page=${page}&page_size=${pageSize}`),
  };
});

import UserManagement from "@/components/users/user-management";
import type { CurrentUser } from "@/types/auth";

function pageButtons() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
}

function findPageButton(label: RegExp) {
  return pageButtons().find((b) => label.test(b.textContent || ""));
}

const mockUsers = {
  items: [
    {
      id: "1",
      username: "alice",
      display_name: "Alice",
      email: "alice@example.com",
      phone: "123456789",
      roles: [{ id: "r1", code: "admin", name: "Admin" }],
      status: "active",
      is_builtin: false,
      created_at: "2024-01-01T00:00:00Z",
    },
    {
      id: "2",
      username: "bob",
      display_name: "Bob",
      email: "bob@example.com",
      phone: "987654321",
      roles: [{ id: "r2", code: "user", name: "User" }],
      status: "disabled",
      is_builtin: false,
      created_at: "2024-01-02T00:00:00Z",
    },
  ],
  page: 1,
  page_size: 10,
  total: 2,
};

const readerUser: CurrentUser = {
  id: "1",
  username: "reader",
  display_name: "Reader",
  roles: [],
  permissions: ["user:read"],
  menu_permissions: [],
};

const adminUser: CurrentUser = {
  id: "2",
  username: "admin",
  display_name: "Admin",
  roles: [],
  permissions: [
    "user:read",
    "user:create",
    "user:update",
    "user:delete",
    "user:status",
    "user:reset_password",
  ],
  menu_permissions: [],
};

describe("UserManagement", () => {
  vi.setConfig({ testTimeout: 15000 });

  beforeEach(() => {
    mockApi.mockReset();
  });

  test("loads users and hides actions without their permissions", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={readerUser} />);

    expect(await screen.findByText("alice")).toBeVisible();
    expect(screen.queryByRole("button", { name: "新建用户" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除" })).not.toBeInTheDocument();
  });

  test("shows action buttons for user with all permissions", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={adminUser} />);

    expect(await screen.findByText("alice")).toBeVisible();
    expect(findPageButton(/新建用户/)).toBeVisible();
    expect(pageButtons().filter((b) => /编辑/.test(b.textContent || ""))).toHaveLength(2);
  });

  test("renders filter controls for keyword, status, and role", async () => {
    const adminWithRoles: CurrentUser = {
      ...adminUser,
      assignable_roles: [
        { id: "r1", code: "admin", name: "Admin" },
        { id: "r2", code: "user", name: "User" },
      ],
    };
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={adminWithRoles} />);

    await screen.findByText("alice");

    expect(screen.getByPlaceholderText("搜索用户")).toBeVisible();
    expect(pageButtons().filter((b) => /查/.test(b.textContent || "")).length).toBeGreaterThan(0);
    expect(findPageButton(/重\s*置/)).toBeVisible();
    expect(screen.getByText("全部状态")).toBeVisible();
    expect(screen.getByText("全部角色")).toBeVisible();
  });

  test("hides role filter when assignable_roles is absent", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");

    expect(screen.getByText("全部状态")).toBeVisible();
    expect(screen.queryByText("全部角色")).not.toBeInTheDocument();
  });

  test("displays loading state while fetching", () => {
    let resolvePromise: (value: unknown) => void;
    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
    });
    mockApi.mockReturnValue(promise);
    render(<UserManagement currentUser={adminUser} />);

    const skeletons = document.querySelectorAll(".ant-skeleton");
    expect(skeletons.length).toBeGreaterThan(0);
    resolvePromise!(mockUsers);
  });

  test("displays empty state when no users returned", async () => {
    mockApi.mockResolvedValue({ items: [], page: 1, page_size: 10, total: 0 });
    render(<UserManagement currentUser={adminUser} />);

    expect(await screen.findByText(/请新建用户/i)).toBeVisible();
  });

  test("displays error state on fetch failure", async () => {
    mockApi.mockRejectedValue(new Error("Network error"));
    render(<UserManagement currentUser={adminUser} />);

    expect(await screen.findByText(/Network error/i)).toBeVisible();
  });

  test("rebuilds request with filter and page parameters on search", async () => {
    mockApi.mockResolvedValue(mockUsers);
    const user = userEvent.setup();
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");
    mockApi.mockClear();

    mockApi.mockResolvedValue({ items: [], page: 1, page_size: 10, total: 0 });

    await user.type(screen.getByPlaceholderText("搜索用户"), "test");
    await user.click(pageButtons().filter((b) => /查/.test(b.textContent || ""))[0]);

    expect(mockApi).toHaveBeenCalledWith(
      expect.stringContaining("keyword=test")
    );
  });

  test("permission-gates create button for user:create", () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={readerUser} />);

    expect(screen.queryByRole("button", { name: "新建用户" })).not.toBeInTheDocument();
  });

  test("permission-gates edit button for user:update", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={readerUser} />);

    await screen.findByText("alice");
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
  });

  test("permission-gates status toggle for user:status", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={readerUser} />);

    await screen.findByText("alice");
    expect(screen.queryByRole("button", { name: "停用" })).not.toBeInTheDocument();
  });

  test("permission-gates reset password for user:reset_password", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={readerUser} />);

    await screen.findByText("alice");
    expect(screen.queryByRole("button", { name: /重置密码/ })).not.toBeInTheDocument();
  });

  test("permission-gates delete button for user:delete", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={readerUser} />);

    await screen.findByText("alice");
    expect(screen.queryByRole("button", { name: "删除" })).not.toBeInTheDocument();
  });

  test("shows all action buttons for fully-privileged user", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");

    expect(findPageButton(/新建用户/)).toBeVisible();
    expect(pageButtons().filter((b) => /编辑/.test(b.textContent || ""))).toHaveLength(2);
  });

  test("shows pagination when more pages exist", async () => {
    mockApi.mockResolvedValue({
      ...mockUsers,
      total: 25,
      page: 1,
      page_size: 10,
    });
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");
    expect(screen.getByText("共 25 条")).toBeVisible();
    expect(screen.getByTitle("Next Page")).toBeVisible();
  });

  test("fetches next page when Next button clicked", async () => {
    mockApi.mockResolvedValue({
      ...mockUsers,
      total: 25,
      page: 1,
      page_size: 10,
    });
    const user = userEvent.setup();
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");
    mockApi.mockClear();
    mockApi.mockResolvedValue({
      items: [],
      total: 25,
      page: 2,
      page_size: 10,
    });

    await user.click(screen.getByTitle("Next Page"));

    expect(mockApi).toHaveBeenCalledWith(
      expect.stringContaining("page=2")
    );
  });

  test("以中文显示用户管理操作和状态", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={adminUser} />);
    expect(await screen.findByText("用户管理", { selector: "h1" })).toBeVisible();
    expect(findPageButton(/新建用户/)).toBeVisible();
    expect(findPageButton(/启\s*用/)).toBeInTheDocument();
    expect(screen.queryByText("超级管理员")).not.toBeInTheDocument();
  });

  test("shows flat action buttons per row", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");

    const labels = pageButtons().map((b) => b.textContent || "");
    expect(labels.filter((t) => /编辑/.test(t))).toHaveLength(2);
    expect(labels.filter((t) => /停\s*用/.test(t))).toHaveLength(1);
    expect(labels.filter((t) => /启\s*用/.test(t))).toHaveLength(1);
    expect(labels.filter((t) => /重置密码/.test(t))).toHaveLength(2);
    expect(labels.filter((t) => /删\s*除/.test(t))).toHaveLength(2);
  });

  test("shows summary cards with real API totals and page item count", async () => {
    const tenUsers = {
      items: Array.from({ length: 10 }, (_, i) => ({
        id: String(i + 1),
        username: `user${i + 1}`,
        display_name: `User ${i + 1}`,
        email: `user${i + 1}@example.com`,
        phone: null,
        roles: [],
        status: "active" as const,
        created_at: "2024-01-01T00:00:00Z",
      })),
      page: 1,
      page_size: 10,
      total: 24,
    };
    mockApi.mockResolvedValue(tenUsers);
    render(<UserManagement currentUser={adminUser} />);

    const all24 = await screen.findAllByText(/24/);
    expect(all24.length).toBeGreaterThan(0);
    expect(all24[0]).toBeVisible();

    const all10 = screen.getAllByText(/10/);
    expect(all10.length).toBeGreaterThan(0);
    expect(all10[0]).toBeVisible();

    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  test("management table scroll region is keyboard focusable", () => {
    const { container } = render(<UserManagement currentUser={adminUser} />);
    expect(container.querySelector(".data-surface-scroll")).toHaveAttribute("tabindex", "0");
  });

  test("disables status toggle for builtin users", async () => {
    mockApi.mockResolvedValue({
      ...mockUsers,
      items: [{ ...mockUsers.items[0], is_builtin: true }],
    });
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");
    expect(findPageButton(/停\s*用/)).toBeDisabled();
  });

  test("disables delete for builtin users", async () => {
    mockApi.mockResolvedValue({
      ...mockUsers,
      items: [{ ...mockUsers.items[0], is_builtin: true }],
    });
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");
    expect(findPageButton(/删\s*除/)).toBeDisabled();
  });

  test("renders avatar column with src when avatar_url present", async () => {
    mockApi.mockResolvedValue({
      ...mockUsers,
      items: [{ ...mockUsers.items[0], avatar_url: "/api/avatars/1?v=1" }],
    });
    render(<UserManagement currentUser={adminUser} />);
    await screen.findByText("alice");
    const avatar = document.querySelector(".ant-table-row .ant-avatar img");
    expect(avatar).not.toBeNull();
    expect(avatar?.getAttribute("src")?.endsWith("/api/avatars/1?v=1")).toBe(true);
  });

  test("shows balance column merged from admin points data", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path.includes("/api/admin/points/all")) {
        return Promise.resolve({
          users: [
            { user_id: "1", balance: 1234 },
            { user_id: "2", balance: 50 },
          ],
        });
      }
      return Promise.resolve(mockUsers);
    });
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");

    expect(screen.getByText("1,234")).toBeVisible();
    expect(screen.getByText("50")).toBeVisible();
  });

  test("renders recharge buttons per row", async () => {
    mockApi.mockResolvedValue(mockUsers);
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");

    expect(pageButtons().filter((b) => /充值积点/.test(b.textContent || ""))).toHaveLength(2);
  });

  test("recharges points through the modal", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path.includes("/api/admin/points/all")) {
        return Promise.resolve({ users: [{ user_id: "1", balance: 100 }] });
      }
      return Promise.resolve(mockUsers);
    });
    const user = userEvent.setup();
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");
    mockApi.mockClear();

    await user.click(findPageButton(/充值积点/)!);

    const pointsInput = document.querySelector<HTMLInputElement>('input[placeholder="请输入积点数量"]');
    expect(pointsInput).not.toBeNull();
    await user.type(pointsInput!, "200");

    const descInput = document.querySelector<HTMLInputElement>('input[placeholder="选填，例如：运营补偿"]');
    expect(descInput).not.toBeNull();
    await user.type(descInput!, "测试充值");

    await user.click(findPageButton(/确\s*认/)!);

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/admin/points/grant",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ user_id: "1", points: 200, description: "测试充值" }),
          csrf: true,
        })
      );
    });
  });

  test("lists redeem codes from the management modal", async () => {
    mockApi.mockImplementation((path: string) => {
      if (path.includes("/api/admin/redeem-codes")) {
        return Promise.resolve({
          codes: [
            {
              code: "ABCD-EFGH-IJKL",
              points: 500,
              used_by: null,
              used_at: null,
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        });
      }
      if (path.includes("/api/admin/points/all")) {
        return Promise.resolve({ users: [] });
      }
      return Promise.resolve(mockUsers);
    });
    const user = userEvent.setup();
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");

    await user.click(findPageButton(/兑换码管理/)!);

    expect(await screen.findByText("ABCD-EFGH-IJKL")).toBeInTheDocument();
    expect(screen.getByText("未使用")).toBeInTheDocument();
    expect(findPageButton(/生\s*成/)).toBeInTheDocument();
  });

  test("generates redeem codes from the modal", async () => {
    mockApi.mockImplementation((path: string, init?: RequestInit) => {
      if (path.includes("/api/admin/redeem-codes") && init?.method === "POST") {
        return Promise.resolve({ codes: ["NEW1-AAAA-BBBB", "NEW2-CCCC-DDDD"] });
      }
      if (path.includes("/api/admin/redeem-codes")) {
        return Promise.resolve({ codes: [], total: 0 });
      }
      if (path.includes("/api/admin/points/all")) {
        return Promise.resolve({ users: [] });
      }
      return Promise.resolve(mockUsers);
    });
    const user = userEvent.setup();
    render(<UserManagement currentUser={adminUser} />);

    await screen.findByText("alice");

    await user.click(findPageButton(/兑换码管理/)!);
    await screen.findByText("历史兑换码");

    await user.click(findPageButton(/生\s*成/)!);

    expect(await screen.findByText("NEW1-AAAA-BBBB")).toBeInTheDocument();
    expect(screen.getByText("NEW2-CCCC-DDDD")).toBeInTheDocument();
  });
});
