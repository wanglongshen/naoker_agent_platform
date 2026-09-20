export interface RoleReference {
  id: string;
  code: string;
  name: string;
}

export interface PermissionSummary {
  id: string;
  code: string;
  name: string;
  module: string;
  description: string | null;
}

export interface RoleListItem {
  id: string;
  code: string;
  name: string;
  description: string | null;
  status: "active" | "disabled";
  is_system: boolean;
  permission_count: number;
}

export interface RoleListResponse {
  items: RoleListItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface RoleDetail {
  id: string;
  code: string;
  name: string;
  description: string | null;
  status: "active" | "disabled";
  is_system: boolean;
  permission_count: number;
  permissions: PermissionSummary[];
  assigned_user_count: number;
}
