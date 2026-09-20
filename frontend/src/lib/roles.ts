import type { CurrentUser } from "@/types/auth";

export function isSuperAdmin(user: CurrentUser): boolean {
  return user.roles.some((role) => role.code === "super_admin");
}
