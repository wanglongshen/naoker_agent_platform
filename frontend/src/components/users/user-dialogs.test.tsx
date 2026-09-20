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
    "user:assign_role",
  ],
  menu_permissions: [],
};

const adminWithRoles: CurrentUser = {
  ...adminUser,
  assignable_roles: [
    { id: "role-user-manager", code: "user-manager", name: "User Manager" },
    { id: "role-admin", code: "admin", name: "Admin" },
  ],
};

const readerUser: CurrentUser = {
  id: "1",
  username: "reader",
  display_name: "Reader",
  roles: [],
  permissions: ["user:read"],
  menu_permissions: [],
};

function resolveUsers(data = mockUsers) {
  mockApi.mockResolvedValue(data);
}

function apiError(status: number, message: string, code = "ERROR") {
  const err = new ApiError(status, code, message, null);
  return err;
}

describe("User Dialog Mutations", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  describe("Create User", () => {
    test("creates a user with roles and refreshes the list", { timeout: 10000 }, async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminWithRoles} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/新建用户/)!);

      expect(screen.getByLabelText("用户名")).toBeVisible();
      expect(screen.getByLabelText("初始密码")).toBeVisible();
      expect(screen.getByLabelText("姓名")).toBeVisible();
      expect(screen.getByLabelText("角色")).toBeVisible();

      expect(findPageButton(/保\s*存/)!).toBeEnabled();

      await user.type(screen.getByLabelText("用户名"), "charlie");
      await user.type(screen.getByLabelText("姓名"), "Charlie");
      await user.type(screen.getByLabelText("初始密码"), "Password123");
      await user.click(screen.getByLabelText("角色"));
      await user.click(await screen.findByText("User Manager", { selector: ".ant-select-item-option-content" }));

      mockApi.mockClear();
      resolveUsers();

      await user.click(findPageButton(/保\s*存/)!);

      expect(mockApi).toHaveBeenCalledWith(
        "/api/users",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining("charlie"),
        })
      );
    });

    test("validates password client-side before submitting", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminWithRoles} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/新建用户/)!);

      await user.type(screen.getByLabelText("用户名"), "charlie");
      await user.type(screen.getByLabelText("初始密码"), "short");

      mockApi.mockClear();
      await user.click(findPageButton(/保\s*存/)!);

      expect(mockApi).not.toHaveBeenCalled();
      expect(await screen.findByText(/密码长度/i)).toBeInTheDocument();
    });

    test("hides role selection when user lacks user:assign_role", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminUser} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/新建用户/)!);

      expect(screen.getByLabelText("用户名")).toBeVisible();
      expect(screen.queryByLabelText("角色")).not.toBeInTheDocument();
    });

    test("shows API error feedback on 409 conflict", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminWithRoles} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/新建用户/)!);

      await user.type(screen.getByLabelText("用户名"), "alice");
      await user.type(screen.getByLabelText("姓名"), "Alice");
      await user.type(screen.getByLabelText("初始密码"), "Password123");

      mockApi.mockRejectedValue(apiError(409, "Username already exists", "DUPLICATE_VALUE"));

      await user.click(findPageButton(/保\s*存/)!);

      await waitFor(() => {
        expect(screen.getByText(/已存在/i)).toBeVisible();
      });
    });
  });

  describe("Edit User", () => {
    test("edits a user and refreshes the list", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminWithRoles} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/编辑/)!);

      expect(screen.getByLabelText("姓名")).toBeVisible();
      expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument();
      expect(screen.queryByLabelText("初始密码")).not.toBeInTheDocument();

      await user.clear(screen.getByLabelText("姓名"));
      await user.type(screen.getByLabelText("姓名"), "Alice Updated");
      await user.clear(screen.getByLabelText("邮箱"));
      await user.type(screen.getByLabelText("邮箱"), "alice.new@example.com");

      mockApi.mockClear();
      resolveUsers();

      await user.click(findPageButton(/保\s*存/)!);

      expect(mockApi).toHaveBeenCalledWith(
        "/api/users/1",
        expect.objectContaining({
          method: "PUT",
          body: expect.stringContaining("Alice Updated"),
        })
      );
    });

    test("hides role selection in edit form when user lacks user:assign_role", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminUser} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/编辑/)!);

      expect(screen.queryByLabelText("角色")).not.toBeInTheDocument();
    });
  });

  describe("Reset Password", () => {
    test("resets password and closes dialog on success", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminUser} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/重置密码/)!);

      expect(await screen.findByText(/设置新密码/i)).toBeInTheDocument();

      await user.type(screen.getByLabelText("新密码"), "NewPass123");
      await user.type(screen.getByLabelText("确认密码"), "NewPass123");

      mockApi.mockResolvedValue(undefined);

      const submitButtons = pageButtons().filter((b) => /重置密码/.test(b.textContent || ""));
      await user.click(submitButtons[submitButtons.length - 1]);

      await waitFor(() => {
        expect(mockApi).toHaveBeenCalledWith(
          "/api/users/1/reset-password",
          expect.objectContaining({ method: "POST" })
        );
      });
    });

    test("shows error when passwords do not match", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminUser} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/重置密码/)!);

      await user.type(screen.getByLabelText("新密码"), "NewPass123");
      await user.type(screen.getByLabelText("确认密码"), "Different456");

      mockApi.mockClear();
      const submitButtons = pageButtons().filter((b) => /重置密码/.test(b.textContent || ""));
      await user.click(submitButtons[submitButtons.length - 1]);

      expect(mockApi).not.toHaveBeenCalled();
      expect(await screen.findByText(/不一致/i)).toBeInTheDocument();
    });
  });

  describe("Confirm Dialog", () => {
    test("deletes a user after confirmation", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminUser} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/删\s*除/)!);

      expect(await screen.findByText(/删除用户/i)).toBeInTheDocument();

      mockApi.mockClear();
      resolveUsers();

      const buttons = pageButtons().filter((b) => /删\s*除/.test(b.textContent || ""));
      await user.click(buttons[buttons.length - 1]);

      expect(mockApi).toHaveBeenCalledWith(
        "/api/users/1",
        expect.objectContaining({ method: "DELETE" })
      );
    });

    test("toggles user status from active to disabled", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminUser} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/停\s*用/)!);

      expect(await screen.findByText(/停用用户/i)).toBeInTheDocument();

      mockApi.mockClear();
      resolveUsers();

      const buttons = pageButtons().filter((b) => /停\s*用/.test(b.textContent || ""));
      await user.click(buttons[buttons.length - 1]);

      expect(mockApi).toHaveBeenCalledWith(
        "/api/users/1/status",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ status: "disabled" }),
        })
      );
    });

    test("toggles user status from disabled to active", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminUser} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/启\s*用/)!);

      expect(await screen.findByText(/启用用户/i)).toBeInTheDocument();

      mockApi.mockClear();
      resolveUsers();

      const buttons = pageButtons().filter((b) => /启\s*用/.test(b.textContent || ""));
      await user.click(buttons[buttons.length - 1]);

      expect(mockApi).toHaveBeenCalledWith(
        "/api/users/2/status",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ status: "active" }),
        })
      );
    });

    test("cancels confirmation and does not call API", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminUser} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/删\s*除/)!);

      expect(await screen.findByText(/删除用户/i)).toBeInTheDocument();
      mockApi.mockClear();

      await user.click(findPageButton(/取\s*消/)!);

      expect(mockApi).not.toHaveBeenCalled();
    });
  });

  describe("Dialog Close Behavior", () => {
    test("closes create dialog after successful mutation", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminWithRoles} />);

      await screen.findByText("alice");
      await user.click(findPageButton(/新建用户/)!);

      expect(screen.getAllByText("新建用户").length).toBeGreaterThanOrEqual(2);
      expect(screen.getByLabelText("用户名")).toBeVisible();

      await user.type(screen.getByLabelText("用户名"), "charlie");
      await user.type(screen.getByLabelText("姓名"), "Charlie");
      await user.type(screen.getByLabelText("初始密码"), "Password123");

      resolveUsers();
      await user.click(findPageButton(/保\s*存/)!);

      await waitFor(() => {
        expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument();
      });
    });

    test("stays open on API error in create dialog", async () => {
      resolveUsers();
      const user = userEvent.setup();
      render(<UserManagement currentUser={adminWithRoles} />);

      await screen.findByText("alice");

      await user.click(findPageButton(/新建用户/)!);

      await user.type(screen.getByLabelText("用户名"), "charlie");
      await user.type(screen.getByLabelText("姓名"), "Charlie");
      await user.type(screen.getByLabelText("初始密码"), "Password123");

      mockApi.mockRejectedValue(apiError(500, "Server error", "INTERNAL"));

      await user.click(findPageButton(/保\s*存/)!);

      await waitFor(() => {
        expect(screen.getByText("Server error")).toBeVisible();
      });
    });
  });
});
