import { api, ApiError } from "@/lib/api";
import type { CurrentUser } from "@/types/auth";

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  try {
    return await api<CurrentUser>("/api/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}

export function redirectToLogin(router?: { push: (href: string) => void }): void {
  if (router) {
    router.push("/login");
    return;
  }
  window.location.href = "/login";
}
