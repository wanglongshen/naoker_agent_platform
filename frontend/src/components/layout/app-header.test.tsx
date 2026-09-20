import { render, screen } from "@testing-library/react";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn(() => new Promise(() => {})) }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: mockApi };
});

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import AppHeader from "./app-header";

const USER = {
  id: "u-1",
  username: "admin",
  display_name: "超级管理员",
  avatar_url: null,
  roles: [],
  permissions: [],
} as never;

function renderHeader() {
  return render(
    <App>
      <AppHeader user={USER} />
    </App>
  );
}

describe("AppHeader", () => {
  it("渲染品牌区与用户区", () => {
    renderHeader();
    expect(screen.getByText("脑壳工作台")).toBeTruthy();
    expect(screen.getByText("超级管理员")).toBeTruthy();
  });

  it("用户下拉包含飞书与平台登录入口", async () => {
    renderHeader();
    screen.getByRole("button", { name: /超级管理员/ }).click();
    expect(await screen.findByText(/飞书|连接飞书/)).toBeTruthy();
    expect(await screen.findByText("平台登录")).toBeTruthy();
  });
});
