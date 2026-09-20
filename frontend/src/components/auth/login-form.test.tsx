import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockPush } = vi.hoisted(() => ({ mockPush: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: mockApi,
  };
});

import LoginForm from "@/components/auth/login-form";

describe("LoginForm", () => {
  beforeEach(() => {
    mockPush.mockReset();
    mockApi.mockReset();
  });

  test("renders username, password, and submit button", () => {
    render(<LoginForm />);
    expect(screen.getByLabelText("用户名")).toBeDefined();
    expect(screen.getByLabelText("密码")).toBeDefined();
    expect(screen.getByRole("button", { name: "登录" })).toBeDefined();
  });

  test("validates non-empty username", async () => {
    render(<LoginForm />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(screen.getByText("用户名不能为空")).toBeDefined();
    expect(mockApi).not.toHaveBeenCalled();
  });

  test("validates non-empty password", async () => {
    render(<LoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(screen.getByText("密码不能为空")).toBeDefined();
    expect(mockApi).not.toHaveBeenCalled();
  });

  test("submits credentials and navigates to /agent for non-admin after login", async () => {
    mockApi
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({
        id: "1",
        username: "user",
        display_name: "User",
        roles: [],
        permissions: [],
        menu_permissions: [],
      });
    render(<LoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("用户名"), "user");
    await user.type(screen.getByLabelText("密码"), "User1234");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/agent");
    });
  });

  test("submits credentials and navigates to /agent for super_admin after login", async () => {
    mockApi
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({
        id: "1",
        username: "admin",
        display_name: "Admin",
        roles: [{ id: "r1", code: "super_admin", name: "超级管理员" }],
        permissions: [],
        menu_permissions: [],
      });
    render(<LoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.type(screen.getByLabelText("密码"), "ChangeMe-Strong1");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/agent");
    });
  });

  test("displays backend error message on failure", async () => {
    mockApi.mockRejectedValueOnce(new Error("Invalid credentials"));
    render(<LoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.type(screen.getByLabelText("密码"), "wrong");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toBeDefined();
  });

  test("shows generic error when error has no message", async () => {
    mockApi.mockRejectedValueOnce(new Error());
    render(<LoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.type(screen.getByLabelText("密码"), "ChangeMe-Strong1");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toBeDefined();
  });

  test("disables button while submitting", async () => {
    let resolveApi: (value: unknown) => void;
    const apiPromise = new Promise((resolve) => {
      resolveApi = resolve;
    });
    mockApi.mockReturnValueOnce(apiPromise);

    render(<LoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.type(screen.getByLabelText("密码"), "ChangeMe-Strong1");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /正在登录\.\.\./ })).toBeDisabled();
    });

    resolveApi!({ ok: true });
  });

  test("exposes an accessible form and primary submit control", () => {
    render(<LoginForm />);

    expect(screen.getByRole("textbox", { name: "用户名" })).toBeVisible();
    expect(screen.getByLabelText("密码")).toHaveAttribute("type", "password");
    expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
  });
});
