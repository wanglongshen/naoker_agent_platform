import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: mockApi,
    ApiError: actual.ApiError,
  };
});

import UserTable from "@/components/users/user-table";
import UserDrawer from "@/components/users/user-drawer";
import type { UserListItem } from "@/types/user";
import type { CurrentUser } from "@/types/auth";
import type { RoleReference } from "@/types/role";

const baseUser: UserListItem = {
  id: "1",
  username: "testuser",
  display_name: "Test User",
  email: null,
  phone: null,
  roles: [],
  status: "active" as const,
  is_builtin: false,
  created_at: null,
};

const admin: CurrentUser = {
  id: "admin-1",
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
    "user:assign_role",
  ],
  menu_permissions: [],
};

const handlers = {
  onEdit: vi.fn(),
  onToggleStatus: vi.fn(),
  onResetPassword: vi.fn(),
  onDelete: vi.fn(),
};

const assignableRoles: RoleReference[] = [
  { id: "r1", code: "user_manager", name: "User Manager" },
  { id: "r2", code: "admin", name: "Admin" },
];

function apiError(status: number, message: string, code = "ERROR") {
  return new ApiError(status, code, message, null);
}

describe("Role Tag Display in UserTable", () => {
  test("renders role names rather than role identifiers", () => {
    render(
      <UserTable
        users={[
          {
            ...baseUser,
            roles: [{ id: "r1", code: "user_manager", name: "User Manager" }],
          },
        ]}
        currentUser={admin}
        {...handlers}
      />
    );
    expect(screen.getByText("User Manager")).toBeVisible();
    expect(screen.queryByText("r1")).not.toBeInTheDocument();
  });

  test("shows only two role tags and an overflow count", () => {
    const threeRoles: RoleReference[] = [
      { id: "r1", code: "role_one", name: "Role One" },
      { id: "r2", code: "role_two", name: "Role Two" },
      { id: "r3", code: "role_three", name: "Role Three" },
    ];
    render(
      <UserTable
        users={[{ ...baseUser, roles: threeRoles }]}
        currentUser={admin}
        {...handlers}
      />
    );
    const overflow = screen.getByText("+1");
    expect(overflow).toBeVisible();
    expect(overflow).toHaveAttribute("title", "Role One, Role Two, Role Three");
  });
});

describe("UserDrawer", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  test("renders create form when no user is provided", () => {
    render(
      <UserDrawer
        open
        user={null}
        currentUser={admin}
        assignableRoles={assignableRoles}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    expect(screen.getByLabelText("用户名")).toBeVisible();
    expect(screen.getByLabelText("初始密码")).toBeVisible();
    expect(screen.getByLabelText("姓名")).toBeVisible();
    expect(screen.getByLabelText("角色")).toBeVisible();
    expect(screen.getByLabelText("状态")).toBeVisible();
  });

  test("renders edit form when user is provided", () => {
    render(
      <UserDrawer
        open
        user={baseUser}
        currentUser={admin}
        assignableRoles={assignableRoles}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("初始密码")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("状态")).not.toBeInTheDocument();
    expect(screen.getByLabelText("姓名")).toBeVisible();
    expect(screen.getByLabelText("角色")).toBeVisible();
  });

  test("hides role selection when user lacks user:assign_role", () => {
    const noRoleUser: CurrentUser = {
      ...admin,
      permissions: ["user:read", "user:create"],
    };

    render(
      <UserDrawer
        open
        user={null}
        currentUser={noRoleUser}
        assignableRoles={assignableRoles}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    expect(screen.getByLabelText("用户名")).toBeVisible();
    expect(screen.queryByLabelText("角色")).not.toBeInTheDocument();
  });

  test("validates password must be 8+ characters with letter and digit", async () => {
    render(
      <UserDrawer
        open
        user={null}
        currentUser={admin}
        assignableRoles={assignableRoles}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    const pw = screen.getByLabelText("初始密码");
    await userEvent.setup().type(pw, "short");

    mockApi.mockClear();
    await userEvent.setup().click(screen.getByRole("button", { name: "保 存" }));

    expect(mockApi).not.toHaveBeenCalled();
    expect(await screen.findByText(/密码长度/i)).toBeInTheDocument();
  });

  test("shows 409 conflict error in drawer", async () => {
    render(
      <UserDrawer
        open
        user={null}
        currentUser={admin}
        assignableRoles={assignableRoles}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    const ue = userEvent.setup();
    await ue.type(screen.getByLabelText("用户名"), "dupe");
    await ue.type(screen.getByLabelText("姓名"), "Dupe");
    await ue.type(screen.getByLabelText("初始密码"), "Password123");

    mockApi.mockRejectedValue(apiError(409, "Username already exists", "DUPLICATE_VALUE"));

    await ue.click(screen.getByRole("button", { name: "保 存" }));

    await waitFor(() => {
      expect(screen.getByText(/已存在/i)).toBeVisible();
    });
  });

  test("creates user and calls onSuccess", async () => {
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    mockApi.mockResolvedValue({});

    render(
      <UserDrawer
        open
        user={null}
        currentUser={admin}
        assignableRoles={assignableRoles}
        onClose={onClose}
        onSuccess={onSuccess}
      />
    );

    const ue = userEvent.setup();
    await ue.type(screen.getByLabelText("用户名"), "newuser");
    await ue.type(screen.getByLabelText("姓名"), "New User");
    await ue.type(screen.getByLabelText("初始密码"), "Password123");

    mockApi.mockClear();
    await ue.click(screen.getByRole("button", { name: "保 存" }));

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/users",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("newuser"),
        })
      );
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  test("edits user with PUT and calls onSuccess", async () => {
    const onSuccess = vi.fn();
    mockApi.mockResolvedValue({});

    render(
      <UserDrawer
        open
        user={baseUser}
        currentUser={admin}
        assignableRoles={assignableRoles}
        onClose={vi.fn()}
        onSuccess={onSuccess}
      />
    );

    const ue = userEvent.setup();
    await ue.clear(screen.getByLabelText("姓名"));
    await ue.type(screen.getByLabelText("姓名"), "Updated");

    mockApi.mockClear();
    await ue.click(screen.getByRole("button", { name: "保 存" }));

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/users/1",
        expect.objectContaining({
          method: "PUT",
          body: expect.stringContaining("Updated"),
        })
      );
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  test("stays open on API error", async () => {
    render(
      <UserDrawer
        open
        user={null}
        currentUser={admin}
        assignableRoles={assignableRoles}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    const ue = userEvent.setup();
    await ue.type(screen.getByLabelText("用户名"), "failuser");
    await ue.type(screen.getByLabelText("姓名"), "Fail");
    await ue.type(screen.getByLabelText("初始密码"), "Password123");

    mockApi.mockRejectedValue(apiError(500, "Server error", "INTERNAL"));

    await ue.click(screen.getByRole("button", { name: "保 存" }));

    await waitFor(() => {
      expect(screen.getByText("Server error")).toBeVisible();
      expect(screen.getByLabelText("用户名")).toBeVisible();
    });
  });

  test("editing a user initializes existing role ids", async () => {
    const userWithRoles: UserListItem = {
      ...baseUser,
      roles: [
        { id: "r1", code: "role_one", name: "Role One" },
        { id: "r2", code: "role_two", name: "Role Two" },
      ],
    };

    render(
      <UserDrawer
        open
        user={userWithRoles}
        currentUser={admin}
        assignableRoles={assignableRoles}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    mockApi.mockClear();
    mockApi.mockResolvedValue({});

    const ue = userEvent.setup();
    await ue.clear(screen.getByLabelText("姓名"));
    await ue.type(screen.getByLabelText("姓名"), "Updated User");

    await ue.click(screen.getByRole("button", { name: "保 存" }));

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/users/1",
        expect.objectContaining({
          method: "PUT",
          body: expect.stringContaining('"r1"'),
        }),
      );
      expect(mockApi).toHaveBeenCalledWith(
        "/api/users/1",
        expect.objectContaining({
          method: "PUT",
          body: expect.stringContaining('"r2"'),
        }),
      );
    });
  });
});
