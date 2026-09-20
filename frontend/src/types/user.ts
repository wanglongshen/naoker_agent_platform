import type { RoleReference } from "./role";

export interface UserListItem {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  phone: string | null;
  avatar_url?: string | null;
  roles: RoleReference[];
  status: "active" | "disabled";
  is_builtin: boolean;
  created_at: string | null;
}

export interface UserListResponse {
  items: UserListItem[];
  page: number;
  page_size: number;
  total: number;
}

