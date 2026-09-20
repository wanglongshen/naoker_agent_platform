import { describe, expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import FileList from "@/components/files/file-list";
import type { FileListItem } from "@/types/file";
import type { CurrentUser } from "@/types/auth";

const superAdmin: CurrentUser = {
  id: "user-admin",
  username: "admin",
  display_name: "Admin",
  roles: [{ id: "r1", code: "super_admin", name: "超级管理员" }],
  permissions: ["file:read", "file:delete"],
  menu_permissions: [],
};

function makeFile(id: string, owner: string): FileListItem {
  return {
    id,
    owner_user_id: owner,
    filename: `${id}.txt`,
    original_filename: `${id}.txt`,
    media_type: "text/plain",
    size_bytes: 10,
    folder_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function renderAdminFileList(files: FileListItem[]) {
  render(
    <FileList
      files={files}
      loading={false}
      onRefresh={() => {}}
      folderId=""
      onPreview={() => {}}
      onMove={() => {}}
      onRename={() => {}}
      onDelete={() => {}}
      onBatchDelete={() => {}}
      currentUser={superAdmin}
      adminView
    />,
  );
}

describe("FileList admin view delete visibility", () => {
  test("hides delete button for another user's file", () => {
    renderAdminFileList([makeFile("file-other", "user-bob")]);
    expect(screen.getByText("file-other.txt")).toBeVisible();
    expect(screen.queryByRole("button", { name: /删除/ })).not.toBeInTheDocument();
  });

  test("shows delete button for own file", () => {
    renderAdminFileList([makeFile("file-own", "user-admin")]);
    expect(screen.getByText("file-own.txt")).toBeVisible();
    expect(screen.getByRole("button", { name: /删除/ })).toBeVisible();
  });
});
