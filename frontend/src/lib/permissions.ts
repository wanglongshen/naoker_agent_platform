import type { CurrentUser } from "@/types/auth";

export const USER_READ = "user:read";
export const USER_CREATE = "user:create";
export const USER_UPDATE = "user:update";
export const USER_DELETE = "user:delete";
export const USER_STATUS = "user:status";
export const USER_RESET_PASSWORD = "user:reset_password";
export const USER_ASSIGN_ROLE = "user:assign_role";

export const ROLE_READ = "role:read";
export const ROLE_CREATE = "role:create";
export const ROLE_UPDATE = "role:update";
export const ROLE_DELETE = "role:delete";
export const ROLE_STATUS = "role:status";
export const ROLE_ASSIGN_PERMISSION = "role:assign_permission";

export const FILE_READ = "file:read";
export const FILE_UPLOAD = "file:upload";
export const FILE_DELETE = "file:delete";
export const FILE_MANAGE_FOLDERS = "file:manage_folders";
export const FILE_ADMIN_VIEW = "file:admin_view";

export function hasPermission(user: CurrentUser | null | undefined, permission: string): boolean {
  if (!user) {
    return false;
  }
  return user.permissions.includes(permission);
}
