import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mocks } = vi.hoisted(() => ({
  mocks: {
    getMyPoints: vi.fn(),
    getPointsUsage: vi.fn(),
    redeemPoints: vi.fn(),
    fetchCurrentUser: vi.fn(),
  },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getMyPoints: mocks.getMyPoints,
    getPointsUsage: mocks.getPointsUsage,
    redeemPoints: mocks.redeemPoints,
  };
});

vi.mock("@/lib/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/auth")>();
  return {
    ...actual,
    fetchCurrentUser: mocks.fetchCurrentUser,
  };
});

import PointsPage from "./page";

function pageButtons() {
  return Array.from(document.querySelectorAll<HTMLButtonElement>("button"));
}

function findPageButton(label: RegExp) {
  return pageButtons().find((b) => label.test(b.textContent || ""));
}

function mockData() {
  return {
    balance: 12345,
    total_granted: 13345,
    total_consumed: 1000,
    recent: [
      {
        id: "t1",
        amount: -500,
        type: "consume",
        ref: "run-1",
        tokens: 5000000,
        created_at: "2026-01-05T10:00:00Z",
      },
      {
        id: "t2",
        amount: 300,
        type: "redeem",
        ref: "ABCD-EFGH-IJKL",
        tokens: null,
        created_at: "2026-01-03T09:00:00Z",
      },
    ],
  };
}

function wrapper() {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <PointsPage />
    </ConfigProvider>
  );
}

describe("PointsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.fetchCurrentUser.mockResolvedValue({ roles: [] });
  });

  it("renders kpi cards, rules and redeem button", async () => {
    mocks.getMyPoints.mockResolvedValue(mockData());
    mocks.getPointsUsage.mockResolvedValue({
      days: [{ date: "2026-01-05", tokens: 5000000, points: 500 }],
    });

    render(wrapper());

    expect(await screen.findByText(/12,345/)).toBeVisible();
    expect(screen.getByText("当前余额")).toBeVisible();
    expect(screen.getByText("累计获得")).toBeVisible();
    expect(screen.getByText("累计消耗")).toBeVisible();
    expect(screen.getByText("本月用量")).toBeVisible();
    expect(screen.getByText(/1 积点 = 10,000 token/)).toBeVisible();
    expect(screen.getByText(/新用户赠送 1,000 积点/)).toBeVisible();
    expect(screen.getByText("收支明细")).toBeVisible();
    expect(findPageButton(/兑\s*换/)).toBeVisible();
  });

  it("switches chart range between 7 and 30 days", async () => {
    mocks.getMyPoints.mockResolvedValue(mockData());
    mocks.getPointsUsage.mockResolvedValue({
      days: [
        { date: "2026-01-04", tokens: 10000, points: 1 },
        { date: "2026-01-05", tokens: 50000, points: 5 },
      ],
    });

    const user = userEvent.setup();
    render(wrapper());

    await screen.findByText(/12,345/);

    const bars = Array.from(document.querySelectorAll<HTMLElement>("[data-date]"));
    expect(bars).toHaveLength(2);
    expect(bars[0].dataset.date).toBe("2026-01-04");

    await user.click(screen.getByText("7 天"));
    expect(screen.getByText("7 天")).toBeVisible();
  });

  it("renders continuous 30-day axis with zero-fill ticks and legend", async () => {
    mocks.getMyPoints.mockResolvedValue(mockData());
    const days = Array.from({ length: 30 }, (_, i) => ({
      date: `2026-01-${String(i + 1).padStart(2, "0")}`,
      tokens: 0,
      points: 0,
    }));
    days[10].tokens = 189;
    days[10].points = -1;
    mocks.getPointsUsage.mockResolvedValue({ days });

    const user = userEvent.setup();
    render(wrapper());

    await screen.findByText(/12,345/);

    const ticks = Array.from(document.querySelectorAll<HTMLElement>("[data-date]"));
    expect(ticks).toHaveLength(30);
    expect(screen.getByText("近 30 天用量")).toBeVisible();
    expect(screen.getByText(/每日 token 消耗/)).toBeVisible();
    expect(screen.getByText("今日")).toBeVisible();
    expect(screen.getByText("无消耗")).toBeVisible();

    await user.hover(ticks[10]);
    expect((await screen.findAllByText(/189/)).length).toBeGreaterThan(0);
    expect(screen.getByText("token")).toBeVisible();

    await user.click(screen.getByText("7 天"));
    expect(screen.getByText("近 7 天用量")).toBeVisible();
  });

  it("renders transactions table with typed tags and colored amounts", async () => {
    mocks.getMyPoints.mockResolvedValue(mockData());
    mocks.getPointsUsage.mockResolvedValue({ days: [] });

    render(wrapper());

    await screen.findByText(/12,345/);

    expect(screen.getByText("消耗")).toBeVisible();
    expect(screen.getByText("兑换")).toBeVisible();
    expect(screen.getByText("-500")).toBeVisible();
    expect(screen.getByText("+300")).toBeVisible();
    expect(screen.getByText("ABCD-EFGH-IJKL")).toBeVisible();
  });

  it("redeems a code successfully and refreshes balance", async () => {
    mocks.getMyPoints.mockResolvedValueOnce(mockData()).mockResolvedValueOnce({
      ...mockData(),
      balance: 12745,
    });
    mocks.getPointsUsage.mockResolvedValue({ days: [] });
    mocks.redeemPoints.mockResolvedValue({ points: 400 });

    const user = userEvent.setup();
    render(wrapper());

    await screen.findByText(/12,345/);

    await user.type(screen.getByPlaceholderText("输入兑换码"), "TEST-1234-5678");
    await user.click(findPageButton(/兑\s*换/)!);

    await waitFor(() => expect(mocks.redeemPoints).toHaveBeenCalledWith("TEST-1234-5678"));
    await waitFor(() => expect(screen.getByText(/12,745/)).toBeVisible());
    expect(await screen.findByText(/兑换成功，获得 400 积点/)).toBeInTheDocument();
  });

  it("shows error message when redeem code is invalid", async () => {
    mocks.getMyPoints.mockResolvedValue(mockData());
    mocks.getPointsUsage.mockResolvedValue({ days: [] });
    const { ApiError } = await import("@/lib/api");
    mocks.redeemPoints.mockRejectedValue(new ApiError(400, "INVALID_CODE", "兑换码无效或已被使用", null));

    const user = userEvent.setup();
    render(wrapper());

    await screen.findByText(/12,345/);

    await user.type(screen.getByPlaceholderText("输入兑换码"), "BAD-CODE");
    await user.click(findPageButton(/兑\s*换/)!);

    expect(await screen.findByText("兑换码无效或已被使用")).toBeInTheDocument();
  });

  it("shows empty states when there is no data", async () => {
    mocks.getMyPoints.mockResolvedValue({
      balance: 0,
      total_granted: 0,
      total_consumed: 0,
      recent: [],
    });
    mocks.getPointsUsage.mockResolvedValue({ days: [] });

    render(wrapper());

    expect(await screen.findByText(/0/)).toBeVisible();
    expect(screen.getByText("暂无流水")).toBeVisible();
    expect(screen.getByText("暂无消耗数据")).toBeVisible();
  });

  it("shows loading spinner while fetching", () => {
    mocks.getMyPoints.mockReturnValue(new Promise(() => {}));
    mocks.getPointsUsage.mockReturnValue(new Promise(() => {}));

    render(wrapper());

    expect(document.querySelectorAll(".ant-spin").length).toBeGreaterThan(0);
  });

  it("shows generate-code entry only for super admins", async () => {
    mocks.getMyPoints.mockResolvedValue(mockData());
    mocks.getPointsUsage.mockResolvedValue({ days: [] });
    mocks.fetchCurrentUser.mockResolvedValue({ roles: [{ code: "super_admin" }] });

    const user = userEvent.setup();
    render(wrapper());

    await screen.findByText(/12,345/);
    const genBtn = findPageButton(/生成兑换码/);
    expect(genBtn).toBeTruthy();

    await user.click(genBtn!);
    expect(await screen.findByText("兑换码管理")).toBeInTheDocument();
    expect(screen.getByText("生成兑换码")).toBeInTheDocument();
  });

  it("hides generate-code entry for employees", async () => {
    mocks.getMyPoints.mockResolvedValue(mockData());
    mocks.getPointsUsage.mockResolvedValue({ days: [] });
    mocks.fetchCurrentUser.mockResolvedValue({ roles: [] });

    render(wrapper());

    await screen.findByText(/12,345/);
    expect(findPageButton(/生成兑换码/)).toBeUndefined();
  });
});
