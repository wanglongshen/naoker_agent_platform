# Ant Design Warm Executive Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the RBAC frontend presentation with a responsive, branded Ant Design Warm Executive interface while preserving every current route, API operation, authorization rule, and localization-owned string.

**Architecture:** Add one client-side Ant Design provider at the root to own theme tokens and feedback context. Keep domain data fetching and mutations in the existing user and role management components, while replacing their custom presentation primitives with Ant Design composition. The dashboard shell remains the only owner of responsive navigation placement; table/form/dialog children preserve their current callback contracts.

**Tech Stack:** Next.js 16.2.10, React 19.2.4, TypeScript, Ant Design, @ant-design/icons, Vitest, React Testing Library.

## Global Constraints

- Do not modify user-visible wording, the centralized copy values, browser metadata, or localization behavior; those are owned by concurrent work.
- Preserve `/login`, `/users`, `/roles`, API paths, request JSON, response types, route protection, and permission checks.
- Add exactly the `antd` and `@ant-design/icons` runtime dependencies; merge them with existing uncommitted `frontend/package.json` edits instead of replacing that file.
- Use `#E87516` as the primary action color, `#281B16` for the desktop navigation surface, and `#FFFCF8` for the workspace.
- Use Ant Design controls for layout, navigation, buttons, inputs, selects, forms, tables, tags, drawers, dialogs, loading, empty, and feedback states; do not leave duplicate custom primitives for the same interactions.
- Retain all unrelated concurrent edits when touching shared files. Read the current file immediately before every edit.
- Test via semantic roles, labels, and retained copy, not CSS implementation classes.
- Do not add fabricated dashboard metrics, new APIs, or backend/database changes.

---

## File Structure

- Create: `frontend/src/components/ui/ant-design-provider.tsx` - client-only `ConfigProvider` and Ant Design `App` with Warm Executive tokens.
- Modify: `frontend/package.json`, `frontend/package-lock.json` - Ant Design runtime dependencies.
- Modify: `frontend/src/app/layout.tsx` - retain localization metadata and place children in the theme provider.
- Modify: `frontend/src/app/globals.css` - replace legacy primitive styles with Warm Executive layout refinements, Ant Design component overrides, and responsive rules.
- Modify: `frontend/src/app/(auth)/login/page.tsx`, `frontend/src/components/auth/login-form.tsx` - branded login composition and Ant Design form feedback.
- Modify: `frontend/src/components/layout/app-sidebar.tsx`, `app-header.tsx`, `dashboard-shell.tsx` - Ant Design desktop shell and shared responsive drawer navigation.
- Modify: `frontend/src/components/users/user-management.tsx`, `user-filters.tsx`, `user-table.tsx`, `user-drawer.tsx`, `password-reset-dialog.tsx`, `confirm-dialog.tsx` - Ant Design user list, actions, forms, and confirmation flows.
- Modify: `frontend/src/components/roles/role-management.tsx`, `role-filters.tsx`, `role-table.tsx`, `role-drawer.tsx`, `permission-tree.tsx` - Ant Design role list, forms, deletion flow, and permission tree.
- Delete after consumers are migrated: `frontend/src/components/ui/button.tsx`, `input.tsx`, `select.tsx`, `drawer.tsx`, `empty-state.tsx`, `skeleton.tsx`, `status-tag.tsx` - obsolete duplicate primitive controls.
- Modify tests: `frontend/src/components/auth/login-form.test.tsx`, `layout/dashboard-shell.test.tsx`, `users/user-management.test.tsx`, `users/user-drawer.test.tsx`, `users/user-dialogs.test.tsx`, `roles/role-management.test.tsx`, `roles/permission-tree.test.tsx` - semantic assertions for the redesigned controls.

### Task 1: Install and Configure the Warm Executive Ant Design Foundation

**Files:**
- Create: `frontend/src/components/ui/ant-design-provider.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/src/app/layout.tsx`
- Modify: `frontend/src/app/globals.css`
- Create: `frontend/src/components/ui/ant-design-provider.test.tsx`

**Interfaces:**
- Produces: `AntDesignProvider({ children }: { children: ReactNode }): ReactElement`, the mandatory root wrapper for all routes.
- Produces: CSS classes `.warm-executive-layout`, `.warm-executive-sider`, `.warm-executive-content`, `.data-surface`, `.page-intro`, and `.mobile-only` used by later layout and domain tasks.

- [ ] **Step 1: Install only the approved dependencies without discarding concurrent package changes.**

Run from `X:\01_RBAC\frontend`:

```powershell
npm install antd @ant-design/icons
```

Expected: `package.json` and `package-lock.json` contain both packages; all existing scripts and unrelated package entries remain present.

- [ ] **Step 2: Write the failing provider test.**

Create `frontend/src/components/ui/ant-design-provider.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { Button } from "antd";
import AntDesignProvider from "./ant-design-provider";

test("renders children inside the Warm Executive Ant Design provider", () => {
  render(
    <AntDesignProvider>
      <Button type="primary">Primary action</Button>
    </AntDesignProvider>
  );

  expect(screen.getByRole("button", { name: "Primary action" })).toBeVisible();
});
```

- [ ] **Step 3: Run the focused test and verify it fails because the provider does not exist.**

Run from `X:\01_RBAC\frontend`:

```powershell
npm test -- --run src/components/ui/ant-design-provider.test.tsx
```

Expected: FAIL with a module resolution error for `./ant-design-provider`.

- [ ] **Step 4: Create the provider with explicit brand tokens and Ant Design feedback context.**

Create `frontend/src/components/ui/ant-design-provider.tsx`:

```tsx
"use client";

import type { ReactNode } from "react";
import { App, ConfigProvider, theme } from "antd";

export default function AntDesignProvider({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#E87516",
          colorInfo: "#E87516",
          colorBgLayout: "#FFFCF8",
          colorBgContainer: "#FFFFFF",
          colorBorder: "#EDE1D5",
          colorText: "#2A211D",
          colorTextSecondary: "#826F64",
          borderRadius: 10,
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
          boxShadowSecondary: "0 16px 40px rgba(67, 42, 25, 0.12)",
        },
        components: {
          Button: { borderRadius: 8, controlHeight: 38 },
          Card: { borderRadiusLG: 12 },
          Drawer: { colorBgElevated: "#FFFCF8" },
          Layout: { bodyBg: "#FFFCF8", siderBg: "#281B16", headerBg: "#FFFFFF" },
          Menu: { darkItemBg: "#281B16", darkItemSelectedBg: "rgba(232, 117, 22, 0.20)", darkItemSelectedColor: "#FFFFFF" },
          Table: { headerBg: "#FFF9F3", headerColor: "#826F64" },
        },
      }}
    >
      <App>{children}</App>
    </ConfigProvider>
  );
}
```

- [ ] **Step 5: Wrap the existing root content without changing its metadata or language attributes.**

In `frontend/src/app/layout.tsx`, preserve `metadata` and `<html lang="zh-CN">`; add the reset import and wrapper:

```tsx
import "antd/dist/reset.css";
import AntDesignProvider from "@/components/ui/ant-design-provider";
import "./globals.css";

// Keep the existing metadata object unchanged.
// ...
<body>
  <AntDesignProvider>{children}</AntDesignProvider>
</body>
```

- [ ] **Step 6: Replace legacy global styling with focused theme refinements and responsive foundations.**

Keep only styles that define the approved brand details rather than reimplementing Ant Design controls. `frontend/src/app/globals.css` must include this foundation, then add component refinements required by later tasks:

```css
:root {
  --warm-workspace: #fffcf8;
  --warm-sider: #281b16;
  --warm-primary: #e87516;
  --warm-border: #ede1d5;
  --warm-muted: #826f64;
}

html, body { min-height: 100%; }
body { margin: 0; background: var(--warm-workspace); color: #2a211d; }
.warm-executive-layout { min-height: 100vh; background: var(--warm-workspace); }
.warm-executive-sider { background: var(--warm-sider) !important; }
.warm-executive-content { min-width: 0; padding: 32px; background: var(--warm-workspace); }
.data-surface { border: 1px solid var(--warm-border); border-radius: 12px; background: #fff; box-shadow: 0 10px 28px rgba(67, 42, 25, .05); }
.page-intro { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 24px; }
.mobile-only { display: none; }
@media (max-width: 767px) {
  .warm-executive-content { padding: 20px 16px; }
  .mobile-only { display: inline-flex; }
  .page-intro { align-items: stretch; flex-direction: column; }
}
```

- [ ] **Step 7: Run the provider test and baseline suite.**

Run from `X:\01_RBAC\frontend`:

```powershell
npm test -- --run src/components/ui/ant-design-provider.test.tsx
npm test -- --run
```

Expected: provider test PASS. Existing tests may fail only where they assert obsolete custom primitive markup; record each failure for the task that owns the affected component.

- [ ] **Step 8: Commit the isolated foundation.**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/src/app/layout.tsx frontend/src/app/globals.css frontend/src/components/ui/ant-design-provider.tsx frontend/src/components/ui/ant-design-provider.test.tsx
git commit -m "feat: add warm executive ant design theme"
```

### Task 2: Rebuild the Login Experience with Ant Design Form Controls

**Files:**
- Modify: `frontend/src/app/(auth)/login/page.tsx`
- Modify: `frontend/src/components/auth/login-form.tsx`
- Modify: `frontend/src/components/auth/login-form.test.tsx`

**Interfaces:**
- Consumes: `AntDesignProvider` from Task 1 and the existing `copy`, `api`, `ApiError`, and `useRouter` interfaces.
- Produces: `LoginForm(): ReactElement` with unchanged POST payload `{ username, password }`, `router.push("/users")` success behavior, and semantic Ant Design validation/error feedback.

- [ ] **Step 1: Adjust the failing login test to assert roles instead of custom input wrappers.**

Keep the existing behavioral tests and add this style-independent assertion in `login-form.test.tsx`:

```tsx
test("exposes an accessible form and primary submit control", () => {
  render(<LoginForm />);

  expect(screen.getByRole("textbox", { name: "用户名" })).toBeVisible();
  expect(screen.getByLabelText("密码")).toHaveAttribute("type", "password");
  expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
});
```

- [ ] **Step 2: Run the focused login test before migrating the component.**

Run:

```powershell
npm test -- --run src/components/auth/login-form.test.tsx
```

Expected: PASS before migration, establishing existing validation and request behavior.

- [ ] **Step 3: Replace custom primitives with Ant Design Form, Input, Button, and Alert without changing request logic.**

In `login-form.tsx`, keep `handleSubmit` validation and API call semantics. Replace the JSX imports and return structure with the following shape:

```tsx
import { Alert, Button, Form, Input } from "antd";

return (
  <Form layout="vertical" onFinish={handleSubmit} requiredMark={false}>
    {error ? <Alert type="error" showIcon message={error} role="alert" /> : null}
    <Form.Item label={copy.user.username}>
      <Input
        id="username"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
        disabled={loading}
        placeholder={copy.auth.usernamePlaceholder}
        autoComplete="username"
      />
    </Form.Item>
    <Form.Item label={copy.auth.password}>
      <Input.Password
        id="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        disabled={loading}
        placeholder={copy.auth.passwordPlaceholder}
        autoComplete="current-password"
      />
    </Form.Item>
    <Button type="primary" htmlType="submit" loading={loading} block>
      {loading ? copy.auth.signingIn : copy.auth.signIn}
    </Button>
  </Form>
);
```

Change `handleSubmit` to receive no browser event because `Form.onFinish` handles prevention:

```tsx
async function handleSubmit() {
  setError("");
  if (!username.trim()) {
    setError(copy.auth.usernameRequired);
    return;
  }
  if (!password) {
    setError(copy.auth.passwordRequired);
    return;
  }
  setLoading(true);
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: username.trim(), password }),
    });
    router.push("/users");
  } catch (err) {
    setError(err instanceof ApiError ? err.message || copy.auth.invalidCredentials : copy.auth.invalidCredentials);
  } finally {
    setLoading(false);
  }
}
```

- [ ] **Step 4: Compose the existing login copy into the approved large-screen brand panel without replacing text.**

In `app/(auth)/login/page.tsx`, retain all existing `copy`/text nodes and add only structural classes and a non-text brand mark:

```tsx
<main className="login-page">
  <section className="login-brand" aria-hidden="true">
    <div className="login-brand-mark" />
    <div className="login-brand-copy">
      <h1 className="login-brand-title">{copy.app.title}</h1>
      <p className="login-brand-desc">{copy.app.description}</p>
    </div>
  </section>
  <section className="login-panel">
    <div className="login-card"><LoginForm /></div>
  </section>
</main>
```

Add responsive `.login-*` rules to `globals.css`: deep-brown brand panel with restrained amber radial light at `min-width: 960px`; warm-white panel, 12px card radius, and no brand panel below that width.

- [ ] **Step 5: Run all login tests and verify the payload and redirect remain unchanged.**

Run:

```powershell
npm test -- --run src/components/auth/login-form.test.tsx
```

Expected: PASS, including the POST assertion for `/api/auth/login` and redirect to `/users`.

- [ ] **Step 6: Commit the login migration.**

```powershell
git add frontend/src/app/(auth)/login/page.tsx frontend/src/components/auth/login-form.tsx frontend/src/components/auth/login-form.test.tsx frontend/src/app/globals.css
git commit -m "feat: redesign login with ant design"
```

### Task 3: Rebuild the Responsive Application Shell and Permission-Aware Navigation

**Files:**
- Modify: `frontend/src/components/layout/app-sidebar.tsx`
- Modify: `frontend/src/components/layout/app-header.tsx`
- Modify: `frontend/src/components/layout/dashboard-shell.tsx`
- Modify: `frontend/src/components/layout/dashboard-shell.test.tsx`
- Delete: `frontend/src/components/ui/drawer.tsx`

**Interfaces:**
- Consumes: `CurrentUser`, `hasPermission`, `USER_READ`, `ROLE_READ`, and the classes from Task 1.
- Produces: `AppSidebar({ user, onNavigate? })`, a Menu-based navigation list that displays only authorized routes; `DashboardShell({ currentUser, children })` with desktop Sider and mobile Drawer.

- [ ] **Step 1: Extend the shell tests before changing navigation markup.**

Replace text-specific English assertions with centralized copy and add a Drawer close assertion in `dashboard-shell.test.tsx`:

```tsx
import { copy } from "@/lib/copy";

expect(screen.getByRole("link", { name: copy.navigation.users })).toBeVisible();
expect(screen.queryByRole("link", { name: copy.navigation.roles })).not.toBeInTheDocument();

await userEvent.click(screen.getByRole("button", { name: "Open navigation" }));
expect(screen.getByRole("dialog")).toBeVisible();
await userEvent.click(screen.getByRole("button", { name: "Close" }));
expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
```

- [ ] **Step 2: Run the shell tests and establish the current permission baseline.**

Run:

```powershell
npm test -- --run src/components/layout/dashboard-shell.test.tsx
```

Expected: PASS before migration.

- [ ] **Step 3: Implement a single Menu item source in `app-sidebar.tsx`.**

Build menu items from permissions, using `Link` labels so the existing route semantics remain testable:

```tsx
const items = [
  hasPermission({ ...user, permissions: menuPerms }, USER_READ) && {
    key: "/users",
    icon: <TeamOutlined />,
    label: <Link href="/users" onClick={onNavigate}>{copy.navigation.users}</Link>,
  },
  hasPermission({ ...user, permissions: menuPerms }, ROLE_READ) && {
    key: "/roles",
    icon: <SafetyCertificateOutlined />,
    label: <Link href="/roles" onClick={onNavigate}>{copy.navigation.roles}</Link>,
  },
].filter(Boolean);

return <Menu theme="dark" mode="inline" selectedKeys={[pathname]} items={items} />;
```

Use a `DatabaseOutlined`/custom CSS brand mark above the Menu. Do not change menu labels.

- [ ] **Step 4: Replace the custom shell Drawer and header controls with Ant Design Layout, Drawer, Button, Breadcrumb, and Dropdown.**

In `dashboard-shell.tsx`, render the same `AppSidebar` both in desktop Sider and mobile Drawer:

```tsx
<Layout className="warm-executive-layout">
  <Layout.Sider className="warm-executive-sider" width={232} breakpoint="md" collapsedWidth={0}>
    <AppSidebar user={currentUser} />
  </Layout.Sider>
  <Layout>
    <AppHeader user={currentUser} onMenuToggle={() => setDrawerOpen(true)} />
    <Layout.Content className="warm-executive-content">{children}</Layout.Content>
  </Layout>
  <Drawer placement="left" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={280}>
    <AppSidebar user={currentUser} onNavigate={() => setDrawerOpen(false)} />
  </Drawer>
</Layout>
```

In `app-header.tsx`, retain logout behavior but replace the text menu glyph with a labeled `Button` and an account `Dropdown`; use `MenuOutlined`, `LogoutOutlined`, `Breadcrumb`, `Avatar`, and `Tooltip`. Keep the existing logout POST and `router.push("/login")` behavior.

- [ ] **Step 5: Add narrow-width CSS behavior and remove the obsolete custom Drawer.**

Ensure `.warm-executive-sider` is hidden by Ant Design's `breakpoint="md"` behavior and the menu trigger only appears under `768px`. Delete `components/ui/drawer.tsx` after no imports remain:

```powershell
rg 'components/ui/drawer' frontend/src
```

Expected: no matches before deletion.

- [ ] **Step 6: Run shell tests and the TypeScript build.**

Run:

```powershell
npm test -- --run src/components/layout/dashboard-shell.test.tsx
npm run build
```

Expected: PASS. Build completes without server/client component boundary errors.

- [ ] **Step 7: Commit the shell migration.**

```powershell
git add frontend/src/components/layout/app-sidebar.tsx frontend/src/components/layout/app-header.tsx frontend/src/components/layout/dashboard-shell.tsx frontend/src/components/layout/dashboard-shell.test.tsx frontend/src/app/globals.css
git rm frontend/src/components/ui/drawer.tsx
git commit -m "feat: redesign responsive dashboard shell"
```

### Task 4: Migrate User Management to Ant Design Data, Form, and Confirmation Components

**Files:**
- Modify: `frontend/src/components/users/user-management.tsx`
- Modify: `frontend/src/components/users/user-filters.tsx`
- Modify: `frontend/src/components/users/user-table.tsx`
- Modify: `frontend/src/components/users/user-drawer.tsx`
- Modify: `frontend/src/components/users/password-reset-dialog.tsx`
- Modify: `frontend/src/components/users/confirm-dialog.tsx`
- Modify: `frontend/src/components/users/user-management.test.tsx`
- Modify: `frontend/src/components/users/user-drawer.test.tsx`
- Modify: `frontend/src/components/users/user-dialogs.test.tsx`
- Delete: `frontend/src/components/ui/button.tsx`, `input.tsx`, `select.tsx`, `empty-state.tsx`, `skeleton.tsx`, `status-tag.tsx`

**Interfaces:**
- Consumes: `UserListItem`, `UserListResponse`, `CurrentUser`, current mutation endpoints, and permission constants unchanged.
- Produces: `UserFilters` with unchanged filter callback shape; `UserTable` with unchanged action callbacks; `UserDrawer` with unchanged `open`, `user`, `currentUser`, `assignableRoles`, `onClose`, and `onSuccess` props.

- [ ] **Step 1: Update user tests to locate Ant Design controls semantically before implementation.**

In `user-dialogs.test.tsx`, retain API assertions and update role selection to work with Ant Design Select:

```tsx
await user.click(screen.getByLabelText("角色"));
await user.click(await screen.findByText("User Manager", { selector: ".ant-select-item-option-content" }));

expect(screen.getByRole("dialog", { name: "新建用户" })).toBeVisible();
expect(screen.getByRole("button", { name: "保存" })).toBeEnabled();
```

Add table-menu coverage in `user-management.test.tsx`:

```tsx
await user.click(screen.getAllByRole("button", { name: "More actions" })[0]);
expect(screen.getByRole("menuitem", { name: "编辑" })).toBeVisible();
```

- [ ] **Step 2: Run all user tests and verify the current API behavior.**

Run:

```powershell
npm test -- --run src/components/users
```

Expected: current suite passes before the migration or fails only for assertions intentionally updated in Step 1.

- [ ] **Step 3: Convert filters and the management state views to Ant Design surfaces.**

Use `Input.Search`, `Select`, `Button`, `Alert`, `Empty`, `Pagination`, `Skeleton`, `Card`, and `Space`. Preserve `doFetch`, the exact query parameter construction, and all `DialogState` variants. The list body must follow this shape:

```tsx
<section className="data-surface">
  <div className="data-surface-toolbar">
    <UserFilters {...filterProps} />
  </div>
  {actionError ? <Alert type="error" showIcon message={actionError} /> : null}
  <UserTable {...tableProps} />
  <Pagination current={page} pageSize={PAGE_SIZE} total={total} onChange={handlePageChange} />
</section>
```

For initial loading render heading plus `Skeleton active paragraph={{ rows: 8 }}`. For empty unfiltered results, use `Empty` and retain the existing create action only if `USER_CREATE` is granted. For fetch errors, use `Alert` with a retry `Button` that calls `doFetch(1)`.

- [ ] **Step 4: Replace native table controls with a typed Ant Design Table and compact overflow actions.**

In `user-table.tsx`, define `ColumnsType<UserListItem>` with stable renderers and keep every permission gate:

```tsx
const columns: ColumnsType<UserListItem> = [
  { title: copy.user.username, dataIndex: "username", key: "username", render: (value) => <Typography.Text strong>{value}</Typography.Text> },
  { title: copy.user.displayName, dataIndex: "display_name", key: "display_name" },
  { title: copy.user.roles, key: "roles", render: (_, user) => <RoleTags roles={user.roles} /> },
  { title: copy.user.status, dataIndex: "status", key: "status", render: (status) => <Tag color={status === "active" ? "success" : "default"}>{status === "active" ? copy.status.active : copy.status.disabled}</Tag> },
  { title: "", key: "actions", align: "right", render: (_, user) => <UserActionMenu user={user} {...callbacks} /> },
];

return <Table rowKey="id" columns={columns} dataSource={users} pagination={false} scroll={{ x: 900 }} />;
```

`UserActionMenu` uses an accessible `Button` with `aria-label="More actions"`, `MoreOutlined`, and `Dropdown` menu items. Include only actions permitted by `USER_UPDATE`, `USER_STATUS`, `USER_RESET_PASSWORD`, and `USER_DELETE`; set deletion item `danger: true`.

- [ ] **Step 5: Convert create/edit, password reset, and confirmations while retaining endpoint payloads.**

Use `Drawer` plus `Form` in `user-drawer.tsx`; drawer `width={560}`, `placement="right"`, and `styles={{ body: { paddingBottom: 88 } }}`. On screens under 768px, CSS must make the drawer full width. Map initial values from `user`, keep `validatePassword`, and submit the same body fields to the same POST/PUT endpoints.

Use `Select mode="multiple"` for `role_ids` only when `USER_ASSIGN_ROLE` is granted. Keep the label and role options from `assignableRoles` unchanged.

Convert `password-reset-dialog.tsx` and `confirm-dialog.tsx` to controlled Ant Design `Modal` components. Their public prop interfaces and `onConfirm` promises stay unchanged. Use `okButtonProps={{ danger: isDestructive }}` for destructive confirmation and preserve every current request endpoint.

- [ ] **Step 6: Remove obsolete primitives only after confirming all user and layout imports are gone.**

Run:

```powershell
rg 'components/ui/(button|input|select|empty-state|skeleton|status-tag)' frontend/src
```

Expected: no matches. Then delete the six listed primitive files.

- [ ] **Step 7: Run the user test suite and build.**

Run:

```powershell
npm test -- --run src/components/users
npm run build
```

Expected: PASS. In particular, tests continue to verify create/edit requests, password reset, status PATCH, delete request, role-assignment permission visibility, and API error presentation.

- [ ] **Step 8: Commit the user management migration.**

```powershell
git add frontend/src/components/users frontend/src/app/globals.css
git rm frontend/src/components/ui/button.tsx frontend/src/components/ui/input.tsx frontend/src/components/ui/select.tsx frontend/src/components/ui/empty-state.tsx frontend/src/components/ui/skeleton.tsx frontend/src/components/ui/status-tag.tsx
git commit -m "feat: redesign user management with ant design"
```

### Task 5: Migrate Role Management and Permission Assignment to Ant Design

**Files:**
- Modify: `frontend/src/components/roles/role-management.tsx`
- Modify: `frontend/src/components/roles/role-filters.tsx`
- Modify: `frontend/src/components/roles/role-table.tsx`
- Modify: `frontend/src/components/roles/role-drawer.tsx`
- Modify: `frontend/src/components/roles/permission-tree.tsx`
- Modify: `frontend/src/components/roles/role-management.test.tsx`
- Modify: `frontend/src/components/roles/permission-tree.test.tsx`

**Interfaces:**
- Consumes: unchanged `RoleListItem`, `RoleListResponse`, `RoleDetail`, `PermissionSummary`, `CurrentUser`, permission constants, and API endpoints.
- Produces: Ant Design Table/Drawer/Form/Tree presentation while preserving `RoleDrawerProps`, `RoleTableProps`, and `PermissionTreeProps` public callback interfaces.

- [ ] **Step 1: Write semantic role tests for the new role table, drawer, and Tree.**

In `role-management.test.tsx`, retain request assertions and add:

```tsx
expect(await screen.findByRole("table")).toBeVisible();
await user.click(screen.getAllByRole("button", { name: "More actions" })[0]);
expect(screen.getByRole("menuitem", { name: "编辑" })).toBeVisible();
```

In `permission-tree.test.tsx`, assert Ant Design tree checkbox semantics rather than native CSS:

```tsx
expect(screen.getByRole("tree")).toBeVisible();
expect(screen.getByRole("checkbox", { name: "用户管理" })).toBeEnabled();
```

- [ ] **Step 2: Run the focused role tests before migration.**

Run:

```powershell
npm test -- --run src/components/roles
```

Expected: existing behavior passes, or only Step 1's future-markup assertions fail.

- [ ] **Step 3: Use Ant Design filter, surface, feedback, table, and pagination controls in role management.**

Preserve `doFetch`, its parallel `/api/roles` and `/api/permissions` requests, pagination query parameters, and existing `DialogState`. Replace the render-only parts with the same `data-surface` pattern used by Task 4. Use `Skeleton` for loading, `Alert` plus retry for fetch failures, `Empty` for unfiltered empty results, and `Pagination` with `current={page}`, `pageSize={PAGE_SIZE}`, `total={total}`, and `onChange={handlePageChange}`.

- [ ] **Step 4: Render role rows as an Ant Design Table with semantic tags and a permission-gated action menu.**

In `role-table.tsx`, render columns for code, name, `permission_count`, status, system role, and right-aligned actions:

```tsx
{ title: copy.role.code, dataIndex: "code", key: "code", render: (code) => <Typography.Text code>{code}</Typography.Text> },
{ title: copy.user.status, dataIndex: "status", key: "status", render: (status) => <Tag color={status === "active" ? "success" : "default"}>{status === "active" ? copy.status.active : copy.status.disabled}</Tag> },
{ title: "系统角色", dataIndex: "is_system", key: "is_system", render: (isSystem) => isSystem ? <Tag color="gold">系统角色</Tag> : "—" },
```

Render the actions column with an Ant Design `Dropdown` whose trigger is a `Button` containing `MoreOutlined` and `aria-label="More actions"`. Its `menu.items` array includes an edit item only when `hasPermission(currentUser, ROLE_UPDATE)`; it includes status and dangerous delete items only when `!role.is_system` and their respective `ROLE_STATUS` or `ROLE_DELETE` permission is present. Each item calls the existing `onEdit`, `onToggleStatus`, or `onDelete` callback for that row.

- [ ] **Step 5: Convert the role editor and permission selection to Drawer, Form, and Tree.**

In `role-drawer.tsx`, replace the custom modal with `Drawer` and `Form`. Preserve the existing role-detail fetch on open, immutable-system-role behavior, `permissionChanges` calculation, and request bodies. Render `Input`, `Input.TextArea`, and `Select` for existing fields; disabled fields remain disabled for system roles.

In `permission-tree.tsx`, transform grouped `PermissionSummary` data to Ant Design `TreeDataNode[]`:

```tsx
const treeData: TreeDataNode[] = groups.map((group) => ({
  key: group.module,
  title: group.label,
  children: group.permissions.map((permission) => ({
    key: permission.id,
    title: <Space direction="vertical" size={0}><span>{permission.name}</span>{permission.description ? <Typography.Text type="secondary">{permission.description}</Typography.Text> : null}</Space>,
  })),
}));

return <Tree checkable selectable={false} disabled={readOnly} checkedKeys={selectedIds} onCheck={(keys) => onChange(keys as string[])} treeData={treeData} />;
```

Keep group ordering and module labels from the existing `groupPermissions` logic. Below the Tree, keep the existing selected/removed permission count message when editing is allowed.

- [ ] **Step 6: Convert role deletion to a controlled danger Modal with assignment-impact loading.**

Keep the `GET /api/roles/{id}` request that retrieves `assigned_user_count`. Render `Modal` with `confirmLoading={loading}`, disable the destructive action until count resolution, retain the exact deletion request `DELETE /api/roles/{id}`, and retain current immutable-role error handling.

- [ ] **Step 7: Run role tests and full production build.**

Run:

```powershell
npm test -- --run src/components/roles
npm run build
```

Expected: PASS, including permission tree selection, role creation/update, system role protection, status updates, and deletion impact behavior.

- [ ] **Step 8: Commit the role management migration.**

```powershell
git add frontend/src/components/roles frontend/src/app/globals.css
git commit -m "feat: redesign role management with ant design"
```

### Task 6: Verify the Complete Visual Redesign and Remove Legacy Style Debt

**Files:**
- Modify: `frontend/src/app/globals.css` only if verification reveals component-specific responsive/style defects.
- Modify: the exact test file associated with any failed semantic assertion; do not change tests to conceal behavioral regressions.

**Interfaces:**
- Consumes: all tasks above.
- Produces: validated desktop/mobile workflows and a clean set of imports with no obsolete custom control dependencies.

- [ ] **Step 1: Run a static scan for deleted primitive imports and legacy custom control classes.**

Run from `X:\01_RBAC\frontend`:

```powershell
rg 'components/ui/(button|input|select|drawer|empty-state|skeleton|status-tag)' src
rg 'className="(btn|drawer|modal|table-container|filters|pagination)' src
```

Expected: no imports of deleted primitives. Remaining semantic layout classes are acceptable only if defined by the Warm Executive stylesheet and not recreating Ant Design controls.

- [ ] **Step 2: Run the complete frontend test suite.**

```powershell
npm test -- --run
```

Expected: PASS with all existing behavioral suites plus the provider test.

- [ ] **Step 3: Run the production build.**

```powershell
npm run build
```

Expected: PASS with production routes for `/login`, `/users`, and `/roles` generated successfully.

- [ ] **Step 4: Perform manual desktop verification.**

Run:

```powershell
npm run dev
```

Verify at a desktop viewport:

```text
1. /login displays the deep-brown/amber brand panel and warm-white Ant Design form.
2. Invalid login shows an in-form error; valid login reaches /users.
3. /users and /roles show deep-brown desktop navigation, warm workspace, branded primary buttons, filters, table tags, and compact action menus.
4. Create/edit drawers, password reset, status controls, and destructive confirmations retain successful and failing API feedback.
5. Unauthorized navigation/actions remain absent, and system role restrictions remain visible/enforced.
```

- [ ] **Step 5: Perform manual narrow mobile verification at 375px width.**

Verify:

```text
1. The persistent sider is absent and the labeled menu trigger opens/closes the navigation Drawer.
2. Navigation remains permission-filtered and closing a destination closes the Drawer.
3. Login is a focused single-column form with no clipped controls.
4. Page headings, filters, and primary actions wrap cleanly.
5. User and role tables scroll horizontally inside their data surfaces; no essential column overlaps.
6. Create/edit drawers occupy a usable full-width mobile surface and dialogs remain operable.
```

- [ ] **Step 6: Inspect the final diff for concurrent-localization safety.**

Run from `X:\01_RBAC`:

```powershell
git diff --check
git diff -- frontend/src/lib/copy.ts frontend/src/app/layout.tsx
git status --short
```

Expected: no whitespace errors. `copy.ts` has no visual-redesign wording changes. `layout.tsx` differs only by Ant Design imports/provider composition while retaining the localization metadata and `lang` attribute.

- [ ] **Step 7: Commit only verification fixes, if any.**

```powershell
git add frontend/src/app/globals.css frontend/src/components frontend/src/app
git commit -m "fix: polish warm executive responsive ui"
```

Skip this commit when no verification fixes were necessary.
