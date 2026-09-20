import { describe, expect, test, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PermissionTree from "./permission-tree";
import type { PermissionSummary } from "@/types/role";

const permissions: PermissionSummary[] = [
  { id: "p1", code: "user:read", name: "Read users", module: "user", description: "View user list" },
  { id: "p2", code: "user:create", name: "Create user", module: "user", description: "Add new users" },
  { id: "p3", code: "role:read", name: "Read roles", module: "role", description: null },
  { id: "p4", code: "role:delete", name: "Delete role", module: "role", description: "Remove roles" },
  { id: "p5", code: "system:config", name: "System config", module: "system", description: null },
];

test("checks and unchecks every child in a module", async () => {
  const onChange = vi.fn();
  render(<PermissionTree permissions={permissions} selectedIds={[]} onChange={onChange} readOnly={false} />);
  expect(screen.getByRole("tree")).toBeVisible();

  const userTreeItem = screen.getByRole("treeitem", { name: /用户管理/ });
  expect(within(userTreeItem).getByRole("checkbox")).toBeEnabled();

  await userEvent.click(within(userTreeItem).getByRole("checkbox"));
  expect(onChange).toHaveBeenCalledWith(["p2", "p1"]);
});

test("shows a read-only super admin permission tree", () => {
  const onChange = vi.fn();
  render(<PermissionTree permissions={permissions} selectedIds={["p1", "p2"]} onChange={onChange} readOnly />);
  expect(screen.getByRole("tree")).toBeVisible();

  const userTreeItem = screen.getByRole("treeitem", { name: /用户管理/ });
  expect(within(userTreeItem).getByRole("checkbox")).toHaveAttribute("aria-disabled", "true");
});
