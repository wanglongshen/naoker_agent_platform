import type { RoleReference } from "./role";

export interface CurrentUser {
  id: string;
  username: string;
  display_name: string;
  email?: string | null;
  phone?: string | null;
  avatar_url?: string | null;
  roles: RoleReference[];
  permissions: string[];
  menu_permissions: string[];
  assignable_roles?: RoleReference[];
  sync_feishu_enabled?: boolean;
}

