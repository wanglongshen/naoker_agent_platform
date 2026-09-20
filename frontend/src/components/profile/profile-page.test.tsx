import { describe, expect, test, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: mockApi };
});

import ProfilePage from "@/components/profile/profile-page";
import type { CurrentUser } from "@/types/auth";

const currentUser: CurrentUser = {
  id: "1",
  username: "admin",
  display_name: "Admin",
  roles: [],
  permissions: [],
  menu_permissions: [],
  avatar_url: null,
};

function pageButtons() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
}

function findPageButton(label: RegExp) {
  return pageButtons().find((b) => label.test(b.textContent || ""));
}

describe("ProfilePage", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  test("renders profile info form and password block", async () => {
    render(<ProfilePage currentUser={currentUser} />);
    expect(screen.getByLabelText("姓名")).toBeVisible();
    expect(screen.getByLabelText("邮箱")).toBeVisible();
    expect(screen.getByLabelText("手机号")).toBeVisible();
    expect(
      Array.from(document.querySelectorAll(".profile-card-title")).some(
        (el) => el.textContent?.includes("安全设置")
      )
    ).toBe(true);
  });

  test("saves profile changes", async () => {
    const user = userEvent.setup();
    render(<ProfilePage currentUser={currentUser} />);
    mockApi.mockResolvedValue({ display_name: "New Name" });

    await user.clear(screen.getByLabelText("姓名"));
    await user.type(screen.getByLabelText("姓名"), "New Name");
    await user.click(findPageButton(/保\s*存/)!);

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/users/me/profile",
        expect.objectContaining({ method: "PUT" })
      );
    });
  });

  test("blocks password change when confirmation mismatches", async () => {
    const user = userEvent.setup();
    render(<ProfilePage currentUser={currentUser} />);
    mockApi.mockClear();

    await user.type(screen.getByLabelText("旧密码"), "OldPass123");
    await user.type(screen.getByLabelText("新密码"), "NewPass456");
    await user.type(screen.getByLabelText("确认新密码"), "Different789");
    await user.click(findPageButton(/修改密码/)!);

    expect(mockApi).not.toHaveBeenCalledWith(
      "/api/users/me/password",
      expect.anything()
    );
    expect(await screen.findByText(/不一致/i)).toBeTruthy();
  });

  test("uploads avatar via FormData", async () => {
    const user = userEvent.setup();
    render(<ProfilePage currentUser={currentUser} />);
    mockApi.mockResolvedValue({ avatar_url: "/api/avatars/1?v=123" });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array([137, 80, 78, 71])], "a.png", { type: "image/png" });
    await user.upload(input, file);

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/avatars/me",
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  test("renders hero banner with account and role tags", () => {
    const user: CurrentUser = {
      ...currentUser,
      roles: [{ id: "r1", code: "super_admin", name: "超级管理员" }],
    };
    render(<ProfilePage currentUser={user} />);
    expect(screen.getByText("@admin")).toBeTruthy();
    expect(screen.getByText("超级管理员")).toBeTruthy();
  });

  test("renders two cards side by side", () => {
    render(<ProfilePage currentUser={currentUser} />);
    expect(document.querySelectorAll(".profile-card").length).toBe(2);
    expect(document.querySelectorAll(".profile-cards").length).toBe(1);
    const titles = Array.from(document.querySelectorAll(".profile-card-title"));
    expect(titles.some((el) => el.textContent?.includes("基本信息"))).toBe(true);
    expect(titles.some((el) => el.textContent?.includes("安全设置"))).toBe(true);
  });
});
