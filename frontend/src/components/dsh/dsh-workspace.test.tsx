import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, waitFor, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { ConfigProvider } from "antd";

const { mockFetchCurrentUser } = vi.hoisted(() => ({ mockFetchCurrentUser: vi.fn() }));
vi.mock("@/lib/auth", () => ({ fetchCurrentUser: mockFetchCurrentUser }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/agent",
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams(),
}));

import DshWorkspace from "./dsh-workspace";
import DshInstanceWatcher from "./dsh-instance-watcher";
import { resetFrameKeeper } from "./dsh-frame-keeper";
import { dshInstanceStore } from "@/lib/dsh-bridge-store";

const USER_ID = "u1";

const RUNNING_STATUS = {
  data: { state: "running", port: 3101, pid: 1, last_active_at: null, error_hint: null },
  message: "OK",
  request_id: "req-1",
};

function stubFetch(responses: Record<string, unknown>) {
  const fn = vi.fn().mockImplementation((url: string) => {
    for (const [key, value] of Object.entries(responses)) {
      if (String(url).includes(key)) {
        return Promise.resolve({ ok: true, status: 200, json: async () => value });
      }
    }
    return Promise.resolve({ ok: false, status: 404, json: async () => ({ message: "not found" }) });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return <ConfigProvider theme={{ token: { motion: false } }}>{children}</ConfigProvider>;
}

function renderWorkspace() {
  return render(
    <Wrapper>
      <DshWorkspace />
      <DshInstanceWatcher />
    </Wrapper>
  );
}

function makeMessage(data: unknown, source: Window | null) {
  const event = new MessageEvent("message", { data });
  Object.defineProperty(event, "source", { value: source });
  return event;
}

describe("DshWorkspace", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    mockFetchCurrentUser.mockReset();
    mockFetchCurrentUser.mockResolvedValue({
      id: USER_ID,
      username: "alice",
      display_name: "Alice",
      roles: [],
      permissions: [],
      menu_permissions: [],
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resetFrameKeeper();
    dshInstanceStore.reset();
    window.localStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  it("embeds the dsh-proxy iframe for the current user", async () => {
    stubFetch({ "/api/dsh/instances/me": RUNNING_STATUS });

    renderWorkspace();

    await waitFor(() => expect(document.querySelector("iframe")).toBeTruthy());
    const frame = document.querySelector("iframe");
    await waitFor(() =>
      expect(frame?.getAttribute("src")).toBe("http://127.0.0.1:3101/")
    );
    expect(frame?.src).toContain("127.0.0.1:3101");
  });

  it("shows the instance state and port from GET /api/dsh/instances/me", async () => {
    const fetchMock = stubFetch({ "/api/dsh/instances/me": RUNNING_STATUS });

    renderWorkspace();

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const getCall = fetchMock.mock.calls.find(([url]) => {
      const u = String(url);
      return u.includes("/api/dsh/instances/me") && !u.includes("/restart");
    });
    expect(getCall).toBeTruthy();
    expect(await screen.findByText(/运行中/)).toBeDefined();
    expect(screen.getByText("端口 3101")).toBeDefined();
  });

  it("shows stopped state and error hint", async () => {
    stubFetch({
      "/api/dsh/instances/me": {
        data: { state: "stopped", port: null, pid: null, last_active_at: null, error_hint: "端口冲突" },
        message: "OK",
        request_id: "req-2",
      },
    });

    renderWorkspace();

    expect(await screen.findByText("未运行")).toBeDefined();
    expect(screen.getByText("端口冲突")).toBeDefined();
  });

  it("fires a POST /api/dsh/instances/me/restart with csrf token when 重建 is clicked", async () => {
    const fetchMock = stubFetch({
      "/api/auth/csrf": { data: { token: "tok-123" }, message: "OK", request_id: "req-csrf" },
      "/api/dsh/instances/me/restart": RUNNING_STATUS,
      "/api/dsh/instances/me": RUNNING_STATUS,
    });

    const user = userEvent.setup();
    renderWorkspace();

    const restartButton = [...document.querySelectorAll("button")].find(
      (b) => b.textContent?.replace(/\s+/g, "") === "重建"
    );
    expect(restartButton).toBeTruthy();
    await user.click(restartButton!);

    await waitFor(() => {
      const restartCall = fetchMock.mock.calls.find(([url]) => {
        const u = String(url);
        return u.includes("/api/dsh/instances/me/restart") || (u.includes("restart") && !u.includes("csrf"));
      });
      expect(restartCall).toBeTruthy();
    });

    const restartCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/restart"))!;
    expect(restartCall[1]?.method).toBe("POST");
    const headers = restartCall[1]?.headers as Record<string, string> | undefined;
    expect(headers?.["X-CSRF-Token"]).toBe("tok-123");
  });

  it("restores the ?session= deep link once the bridge reports ready", async () => {
    stubFetch({ "/api/dsh/instances/me": RUNNING_STATUS });
    window.history.replaceState(null, "", "/agent?session=deep-session");

    renderWorkspace();

    await waitFor(() => expect(document.querySelector("iframe")).toBeTruthy());
    const frame = document.querySelector("iframe") as HTMLIFrameElement;
    const post = vi.spyOn(frame.contentWindow as Window, "postMessage");

    act(() => {
      window.dispatchEvent(makeMessage({ v: 1, type: "state", event: "ready", payload: {} }, frame.contentWindow));
    });

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        { v: 1, type: "cmd", action: "select-session", payload: { sessionId: "deep-session" } },
        "*"
      )
    );
  });

  it("re-arms the ?session= deep link after the iframe reloads", async () => {
    stubFetch({ "/api/dsh/instances/me": RUNNING_STATUS });
    window.history.replaceState(null, "", "/agent?session=deep-session");

    renderWorkspace();

    await waitFor(() => expect(document.querySelector("iframe")).toBeTruthy());
    const frame = document.querySelector("iframe") as HTMLIFrameElement;
    const post = vi.spyOn(frame.contentWindow as Window, "postMessage");

    act(() => {
      frame.dispatchEvent(new Event("load"));
    });
    act(() => {
      window.dispatchEvent(makeMessage({ v: 1, type: "state", event: "ready", payload: {} }, frame.contentWindow));
    });

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));

    act(() => {
      frame.dispatchEvent(new Event("load"));
    });
    act(() => {
      window.dispatchEvent(makeMessage({ v: 1, type: "state", event: "ready", payload: {} }, frame.contentWindow));
    });

    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post).toHaveBeenLastCalledWith(
      { v: 1, type: "cmd", action: "select-session", payload: { sessionId: "deep-session" } },
      "*"
    );
  });

  it("re-arms the ?session= deep link after the instance is rebuilt", async () => {
    const REBUILT_STATUS = {
      data: { state: "running", port: 3102, pid: 2, last_active_at: null, error_hint: null },
      message: "OK",
      request_id: "req-2",
    };
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      const u = String(url);
      if (u.includes("/api/dsh/instances/me/restart")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => REBUILT_STATUS });
      }
      if (u.includes("/api/auth/csrf")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: { token: "tok" }, message: "OK", request_id: "req-csrf" }) });
      }
      if (u.includes("/api/dsh/instances/me")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => RUNNING_STATUS });
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({ message: "not found" }) });
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(null, "", "/agent?session=deep-session");

    const user = userEvent.setup();
    renderWorkspace();

    await waitFor(() => expect(document.querySelector("iframe")).toBeTruthy());
    const firstFrame = document.querySelector("iframe") as HTMLIFrameElement;
    const firstPost = vi.spyOn(firstFrame.contentWindow as Window, "postMessage");
    act(() => {
      firstFrame.dispatchEvent(new Event("load"));
    });
    act(() => {
      window.dispatchEvent(makeMessage({ v: 1, type: "state", event: "ready", payload: {} }, firstFrame.contentWindow));
    });
    await waitFor(() => expect(firstPost).toHaveBeenCalledTimes(1));

    const restartButton = [...document.querySelectorAll("button")].find(
      (b) => b.textContent?.replace(/\s+/g, "") === "重建"
    );
    await user.click(restartButton!);

    await waitFor(() => {
      const frame = document.querySelector("iframe");
      expect(frame).toBeTruthy();
      expect(frame).toBe(firstFrame);
      expect(frame?.getAttribute("src")).toContain("rev=");
    });
    const rebuiltFrame = document.querySelector("iframe") as HTMLIFrameElement;
    const rebuiltPost = vi.spyOn(rebuiltFrame.contentWindow as Window, "postMessage");

    act(() => {
      rebuiltFrame.dispatchEvent(new Event("load"));
    });
    act(() => {
      window.dispatchEvent(makeMessage({ v: 1, type: "state", event: "ready", payload: {} }, rebuiltFrame.contentWindow));
    });

    await waitFor(() =>
      expect(rebuiltPost).toHaveBeenCalledWith(
        { v: 1, type: "cmd", action: "select-session", payload: { sessionId: "deep-session" } },
        "*"
      )
    );
  });

  it("?settings=1 在桥就绪后发送 open-settings 并清掉参数", async () => {
    stubFetch({ "/api/dsh/instances/me": RUNNING_STATUS });
    window.history.replaceState(null, "", "/agent?settings=1");

    renderWorkspace();

    await waitFor(() => expect(document.querySelector("iframe")).toBeTruthy());
    const frame = document.querySelector("iframe") as HTMLIFrameElement;
    const post = vi.spyOn(frame.contentWindow as Window, "postMessage");

    act(() => {
      window.dispatchEvent(makeMessage({ v: 1, type: "state", event: "ready", payload: {} }, frame.contentWindow));
    });

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith({ v: 1, type: "cmd", action: "open-settings" }, "*")
    );
    expect(window.location.search).toBe("");
  });

  it("mirrors the current DSH session into the URL via replaceState", async () => {
    stubFetch({ "/api/dsh/instances/me": RUNNING_STATUS });

    renderWorkspace();

    await waitFor(() => expect(document.querySelector("iframe")).toBeTruthy());
    const frame = document.querySelector("iframe") as HTMLIFrameElement;

    act(() => {
      window.dispatchEvent(makeMessage({
        v: 1,
        type: "state",
        event: "nav",
        payload: { currentSessionId: "s-42", groups: [] },
      }, frame.contentWindow));
    });

    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).get("session")).toBe("s-42")
    );
  });

  it("links to the legacy agent page at /agent/legacy", async () => {
    stubFetch({ "/api/dsh/instances/me": RUNNING_STATUS });

    renderWorkspace();

    await waitFor(() => expect(document.querySelector("a[href='/agent/legacy']")).toBeTruthy());
    expect(document.querySelector("a[href='/agent/legacy']")?.textContent).toContain("打开原版");
  });
});
