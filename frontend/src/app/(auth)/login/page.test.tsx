import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const { mockFetchCurrentUser } = vi.hoisted(() => ({ mockFetchCurrentUser: vi.fn() }));
vi.mock("@/lib/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth")>();
  return { ...actual, fetchCurrentUser: mockFetchCurrentUser };
});

const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: vi.fn() }),
}));

import LoginPage from "@/app/(auth)/login/page";

describe("LoginPage", () => {
  beforeEach(() => {
    mockFetchCurrentUser.mockReset();
    mockReplace.mockReset();
  });

  test("redirects to /agent when already authenticated", async () => {
    mockFetchCurrentUser.mockResolvedValue({ id: "u1", username: "admin" });
    render(<LoginPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/agent");
    });
  });

  test("renders login form when not authenticated", async () => {
    mockFetchCurrentUser.mockResolvedValue(null);
    render(<LoginPage />);
    expect(await screen.findByText("登录")).toBeTruthy();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  test("displays 脑壳工作台 brand name", async () => {
    mockFetchCurrentUser.mockResolvedValue(null);
    render(<LoginPage />);
    expect(await screen.findByText("脑壳工作台")).toBeTruthy();
  });

  test("displays the blueprint-driven solution positioning subtitle", async () => {
    mockFetchCurrentUser.mockResolvedValue(null);
    render(<LoginPage />);
    expect(await screen.findByText(/严格遵循企业蓝图/)).toBeTruthy();
    expect(screen.getByText("AI SOLUTION WORKSPACE")).toBeTruthy();
    expect(screen.getByText("BRAIN SHELL · AGENT PLATFORM")).toBeTruthy();
  });

  test("does not reference the old management system description", async () => {
    mockFetchCurrentUser.mockResolvedValue(null);
    render(<LoginPage />);
    await screen.findByText("脑壳工作台");
    expect(screen.queryByText(/统一管理用户/)).toBeNull();
  });

  test("renders neural brain theme decorations", async () => {
    mockFetchCurrentUser.mockResolvedValue(null);
    const { container } = render(<LoginPage />);
    await screen.findByText("脑壳工作台");
    expect(container.querySelector(".login-brain")).toBeTruthy();
    expect(container.querySelectorAll(".login-node").length).toBe(8);
    expect(container.querySelector(".login-ai-chip")).toBeTruthy();
    expect(screen.getByText("AI")).toBeTruthy();
    expect(container.querySelector(".login-brand-mark")?.textContent).toBe("脑");
  });

  test("renders enhanced form card with icons and footer", async () => {
    mockFetchCurrentUser.mockResolvedValue(null);
    const { container } = render(<LoginPage />);
    await screen.findByText("脑壳工作台");
    expect(container.querySelector(".ant-input-prefix")).toBeTruthy();
    expect(screen.getByText("忘记密码？")).toBeTruthy();
    expect(screen.getByText("V1.0")).toBeTruthy();
    expect(screen.getByText("欢迎登录")).toBeTruthy();
  });
});
