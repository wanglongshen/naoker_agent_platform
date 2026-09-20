import { describe, expect, test, vi } from "vitest";
import { api, ApiError } from "@/lib/api";

function mockResponse(body: unknown, init?: ResponseInit): Response {
  if (init?.status === 204) {
    return new Response(null, { ...init, status: 204 });
  }
  return new Response(JSON.stringify(body), init);
}

describe("api", () => {
  test("sends cookies and turns error envelope into ApiError", async () => {
    const response = mockResponse(
      { code: "PERMISSION_DENIED", message: "Permission denied", details: null },
      { status: 403, headers: { "Content-Type": "application/json" } }
    );
    global.fetch = vi.fn().mockResolvedValue(response);

    const err = await api("/api/users").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 403, code: "PERMISSION_DENIED" });

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/users"),
      expect.objectContaining({ credentials: "include" })
    );
  });

  test("returns parsed JSON on success", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      mockResponse({ id: 1, name: "Alice" }, { status: 200 })
    );

    const result = await api<{ id: number; name: string }>("/api/users/1");
    expect(result).toEqual({ id: 1, name: "Alice" });
  });

  test("sets JSON Content-Type when body is provided", async () => {
    global.fetch = vi.fn().mockResolvedValue(mockResponse(null, { status: 204 }));

    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({ name: "Bob" }),
    });

    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      })
    );
  });

  test("includes cache: no-store by default", async () => {
    global.fetch = vi.fn().mockResolvedValue(mockResponse(null, { status: 204 }));

    await api("/api/users");
    expect(fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ cache: "no-store" })
    );
  });

  test("unwraps a successful api envelope", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ data: { username: "admin" }, message: "OK", request_id: "request-1" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    await expect(api<{ username: string }>("/api/auth/me")).resolves.toEqual({ username: "admin" });
  });

  test("keeps request id on api errors", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ code: "PERMISSION_DENIED", message: "Denied", details: null, request_id: "request-2" }),
      { status: 403, headers: { "Content-Type": "application/json" } },
    ));
    await expect(api("/api/roles")).rejects.toMatchObject({ requestId: "request-2" });
  });
});
