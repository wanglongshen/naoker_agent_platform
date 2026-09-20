import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";
import { PRODUCT_NAME, PRODUCT_SUBTITLE } from "./lib/copy";

const visibleComponentFiles = [
  "components/auth/login-form.tsx",
  "components/auth/protected-page.tsx",
  "components/layout/app-sidebar.tsx",
  "components/layout/app-header.tsx",
  "components/layout/dashboard-shell.tsx",
  "components/users/user-filters.tsx",
  "components/users/user-table.tsx",
  "components/users/user-drawer.tsx",
  "components/users/password-reset-dialog.tsx",
  "components/users/confirm-dialog.tsx",
  "components/roles/role-filters.tsx",
  "components/roles/role-table.tsx",
  "components/roles/role-drawer.tsx",
  "components/roles/permission-tree.tsx",
];

describe("脑壳工作台 brand identity", () => {
  test("PRODUCT_NAME is the correct Chinese brand name", () => {
    expect(PRODUCT_NAME).toBe("脑壳工作台");
  });

  test("PRODUCT_SUBTITLE conveys private / intelligent / organizational positioning", () => {
    expect(PRODUCT_SUBTITLE).toMatch(/私有|智能|组织/);
  });
});

describe("管理员界面中文化", () => {
  test("用户可见组件不保留已知英文界面文案", () => {
    const forbidden = [
      "Sign in",
      "Loading...",
      "No permission",
      "Cancel",
      "Create User",
      "Role Management",
      "User Management",
      "Navigation",
      "Dashboard",
      "Active",
      "Disabled",
    ];
    const source = visibleComponentFiles
      .map((file) => readFileSync(resolve(process.cwd(), "src", file), "utf8"))
      .join("\n");

    for (const text of forbidden) {
      expect(source).not.toContain(`>${text}<`);
      expect(source).not.toContain(`"${text}"`);
    }
  });
});
