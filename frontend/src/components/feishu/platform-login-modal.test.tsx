import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: mockApi };
});

import PlatformLoginModal from "@/components/feishu/platform-login-modal";

function pageButtons() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
}

function findPageButton(label: RegExp) {
  return pageButtons().find((b) => label.test(b.textContent || ""));
}

describe("PlatformLoginModal", () => {
  beforeEach(() => {
    mockApi.mockReset();
  });

  test("shows logout button for logged-in platform", async () => {
    mockApi.mockResolvedValue({
      items: [{ domain: "www.douyin.com", cookie_string: "x" }],
    });
    render(<PlatformLoginModal open onClose={() => {}} />);
    expect(await screen.findByText("已登录")).toBeTruthy();
    expect(findPageButton(/退出登录/)).toBeTruthy();
  });

  test("logout calls DELETE cookie endpoint and refreshes state", async () => {
    const user = userEvent.setup();
    mockApi
      .mockResolvedValueOnce({
        items: [{ domain: "www.douyin.com", cookie_string: "x" }],
      })
      .mockResolvedValueOnce({ deleted: true })
      .mockResolvedValueOnce({ items: [] });

    render(<PlatformLoginModal open onClose={() => {}} />);
    await screen.findByText("已登录");

    await user.click(findPageButton(/退出登录/)!);
    const confirmBtn = document.querySelector(".ant-popconfirm-buttons .ant-btn-primary") as HTMLButtonElement;
    expect(confirmBtn).not.toBeNull();
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/agent/cookies/www.douyin.com",
        expect.objectContaining({ method: "DELETE" })
      );
    });
    const unlogged = await screen.findAllByText("未登录");
    expect(unlogged.length).toBeGreaterThan(0);
  });

  test("import cookie posts JSON to import endpoint", async () => {
    const user = userEvent.setup();
    mockApi
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ saved: { douyin: 2 } });
    render(<PlatformLoginModal open onClose={() => {}} />);
    expect(await screen.findAllByText("未登录")).not.toHaveLength(0);
    await user.click(findPageButton(/导入 Cookie/)!);
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();
    fireEvent.change(textarea, {
      target: { value: JSON.stringify([{ name: "sessionid", value: "abc", domain: ".douyin.com" }]) },
    });
    await user.click(findPageButton(/保\s*存/)!);
    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/agent/cookies/import",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            cookies: [{ name: "sessionid", value: "abc", domain: ".douyin.com" }],
          }),
        })
      );
    });
  });

  test("scan mode shows window-open hint instead of QR image", async () => {
    mockApi
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ session_id: "s1", status: "waiting_scan" })
      .mockResolvedValue({ status: "waiting_scan", detail: "" });
    render(<PlatformLoginModal open onClose={() => {}} />);
    expect(await screen.findAllByText("未登录")).not.toHaveLength(0);
    const loginBtn = pageButtons().find((b) => /登录/.test(b.textContent || ""));
    await userEvent.setup().click(loginBtn!);
    expect(await screen.findByText(/浏览器窗口已弹出/)).toBeTruthy();
  });
});
