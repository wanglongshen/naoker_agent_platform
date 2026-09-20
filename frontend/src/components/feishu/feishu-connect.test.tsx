import { beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { mockApi } = vi.hoisted(() => ({ mockApi: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  const viaApi = (path: string, opts?: unknown) => mockApi(path, opts);
  return {
    ...actual,
    api: mockApi,
    listFeishuConfigs: () => viaApi("/api/feishu/configs"),
    createFeishuConfig: (data: { name: string; app_id: string; app_secret: string }) =>
      viaApi("/api/feishu/configs", { method: "POST", body: JSON.stringify(data), csrf: true }),
    activateFeishuConfig: (id: string) =>
      viaApi(`/api/feishu/configs/${id}/activate`, { method: "POST", csrf: true }),
    deleteFeishuConfig: (id: string) =>
      viaApi(`/api/feishu/configs/${id}`, { method: "DELETE", csrf: true }),
    updateSyncFeishu: (enabled: boolean) =>
      viaApi("/api/me/sync-feishu", { method: "PUT", body: JSON.stringify({ enabled }), csrf: true }),
  };
});

import FeishuConnectModal from "@/components/feishu/feishu-connect";
import { App } from "antd";

function renderWithApp(ui: React.ReactElement) {
  return render(<App>{ui}</App>);
}

const ADMIN_USER = { roles: [{ code: "super_admin" }], sync_feishu_enabled: false };
const EMPLOYEE_USER = { roles: [], sync_feishu_enabled: false };

function mockEndpoints(overrides: Record<string, unknown> = {}) {
  mockApi.mockImplementation((path: string) => {
    if (overrides[path] !== undefined) return Promise.resolve(overrides[path]);
    if (path === "/api/feishu/status") return Promise.resolve({ connected: false });
    if (path === "/api/feishu/configs/status") return Promise.resolve({ configured: true });
    if (path === "/api/auth/me") return Promise.resolve(EMPLOYEE_USER);
    if (path === "/api/feishu/configs") return Promise.resolve({ configs: [] });
    return Promise.resolve(undefined);
  });
}

function pageButtons() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
}

function findPageButton(label: RegExp) {
  return pageButtons().find((b) => label.test(b.textContent || ""));
}

const onClose = vi.fn();
const onConnectedChange = vi.fn();

function renderModal(connected = false) {
  return renderWithApp(
    <FeishuConnectModal
      open
      onClose={onClose}
      connected={connected}
      onConnectedChange={onConnectedChange}
    />
  );
}

describe("FeishuConnectModal", () => {
  beforeEach(() => {
    mockApi.mockReset();
    onClose.mockReset();
    onConnectedChange.mockReset();
  });

  test("shows disconnected state when not connected", async () => {
    mockEndpoints();
    renderModal(false);
    expect(await screen.findByText("未连接")).toBeTruthy();
    expect(await screen.findByText("登录飞书账号")).toBeTruthy();
  });

  test("shows connected state when connected", async () => {
    mockEndpoints();
    renderModal(true);
    expect(await screen.findByText("已连接")).toBeTruthy();
    expect(await screen.findByText(/已登录（退出）/)).toBeTruthy();
  });

  test("modal opens with login section", async () => {
    mockEndpoints();
    renderModal();
    expect(await screen.findByText("登录飞书账号")).toBeTruthy();
    expect(await screen.findByText("方案生成后同步到飞书")).toBeTruthy();
  });

  test("disconnect calls DELETE and notifies parent", async () => {
    mockEndpoints();
    renderModal(true);
    await screen.findByText(/已登录（退出）/);
    const btn = findPageButton(/已登录（退出）/);
    expect(btn).not.toBeNull();
    const user = userEvent.setup();
    await user.click(btn!);
    const confirmBtn = document.querySelector(".ant-popconfirm-buttons .ant-btn-primary") as HTMLButtonElement;
    expect(confirmBtn).not.toBeNull();
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/feishu/connection",
        expect.objectContaining({ method: "DELETE" })
      );
    });
    expect(onConnectedChange).toHaveBeenCalledWith(false);
  });

  test("super admin sees config section with config list in modal", async () => {
    mockEndpoints({
      "/api/auth/me": ADMIN_USER,
      "/api/feishu/configs": {
        configs: [{ id: "1", name: "公司A", app_id_mask: "cli_ab", is_default: true }],
      },
    });
    renderModal();
    expect(await screen.findByText("填写 API Key（企业飞书应用配置）")).toBeTruthy();
    expect(await screen.findByText(/公司A/)).toBeTruthy();
    expect(screen.getByText("默认")).toBeTruthy();
  });

  test("employee sees login entry even when not configured", async () => {
    mockEndpoints({ "/api/feishu/configs/status": { configured: false } });
    renderModal();
    expect(await screen.findByText("登录飞书账号")).toBeTruthy();
  });

  test("super admin sees config section even when not configured", async () => {
    mockEndpoints({
      "/api/auth/me": ADMIN_USER,
      "/api/feishu/configs/status": { configured: false },
    });
    renderModal();
    expect(await screen.findByText("填写 API Key（企业飞书应用配置）")).toBeTruthy();
  });

  test("employee does not see API key section", async () => {
    mockEndpoints();
    renderModal();
    expect(await screen.findByText("登录飞书账号")).toBeTruthy();
    expect(screen.queryByText("填写 API Key（企业飞书应用配置）")).toBeNull();
  });

  test("sync switch loads initial value from /api/auth/me", async () => {
    mockEndpoints({ "/api/auth/me": { ...EMPLOYEE_USER, sync_feishu_enabled: true } });
    renderModal();
    await screen.findByText("方案生成后同步到飞书");
    const sw = document.querySelector(".ant-switch") as HTMLButtonElement;
    expect(sw).not.toBeNull();
    expect(sw.getAttribute("aria-checked")).toBe("true");
  });

  test("sync switch toggle calls updateSyncFeishu", async () => {
    const user = userEvent.setup();
    mockEndpoints();
    renderModal();
    await screen.findByText("方案生成后同步到飞书");
    const sw = document.querySelector(".ant-switch") as HTMLButtonElement;
    expect(sw).not.toBeNull();

    await user.click(sw);

    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(
        "/api/me/sync-feishu",
        expect.objectContaining({ method: "PUT" })
      );
    });
  });

  test("clears feishu query param after oauth callback", async () => {
    mockEndpoints();
    window.history.pushState({}, "", "/agent?feishu=connected=true");
    renderModal();
    // jsdom 的 location 是快照（replaceState 后不更新），用 history.state 验证清理
    await waitFor(() => {
      expect(window.history.state).not.toContain("feishu");
    });
  });

  test("renders without crashing when feishu=error", async () => {
    mockEndpoints();
    window.history.pushState({}, "", "/agent?feishu=error=exchange_failed");
    renderModal();
    expect(await screen.findByText("登录飞书账号")).toBeTruthy();
  });
});
