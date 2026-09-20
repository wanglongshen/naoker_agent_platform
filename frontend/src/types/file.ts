export interface FileListItem {
  id: string;
  owner_user_id: string;
  filename: string;
  original_filename: string;
  media_type: string;
  size_bytes: number;
  folder_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface FolderNode {
  id: string;
  name: string;
  parent_folder_id: string | null;
  child_file_count: number;
  children: FolderNode[];
  created_at: string;
}

export interface FileListResponse {
  items: FileListItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface UserFolderGroup {
  user_id: string;
  username: string;
  display_name: string;
  folders: FolderNode[];
}
