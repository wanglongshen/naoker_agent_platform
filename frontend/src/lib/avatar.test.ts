import { afterEach, describe, expect, test } from "vitest";
import { resolveAvatarUrl } from "@/lib/avatar";

afterEach(() => {
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
});

describe("resolveAvatarUrl", () => {
  test("prepends API base URL to relative avatar paths", () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";
    expect(resolveAvatarUrl("/api/avatars/1?v=123")).toBe("http://localhost:8000/api/avatars/1?v=123");
  });

  test("returns undefined for null/undefined/empty", () => {
    expect(resolveAvatarUrl(null)).toBeUndefined();
    expect(resolveAvatarUrl(undefined)).toBeUndefined();
    expect(resolveAvatarUrl("")).toBeUndefined();
  });

  test("keeps absolute URLs unchanged", () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000";
    expect(resolveAvatarUrl("https://cdn.example.com/a.png")).toBe("https://cdn.example.com/a.png");
  });

  test("returns relative path unchanged when no base configured", () => {
    expect(resolveAvatarUrl("/api/avatars/1?v=1")).toBe("/api/avatars/1?v=1");
  });
});
