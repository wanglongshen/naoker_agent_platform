# Orange Command Center Visual Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the current RBAC frontend into the approved high-fidelity orange command center while preserving all existing frontend behavior and showing only real summary data.

**Architecture:** Keep Ant Design as the interaction layer and expand the existing provider tokens plus `globals.css` into a cohesive brand system. Shell components own branded navigation and responsive placement; user and role pages keep their existing fetching/mutation state while a small reusable summary-card component renders values derived from existing response state.

**Tech Stack:** Next.js 16.2.10, React 19.2.4, TypeScript, Ant Design 6, @ant-design/icons, Vitest, React Testing Library.

## Global Constraints

- Do not modify localization-owned copy in `frontend/src/lib/copy.ts`, metadata, API contracts, permission logic, routes, backend data, or database schema. The approved visual-only labels are `ACCESS GOVERNANCE`, `IDENTITY DIRECTORY`, `ROLE GOVERNANCE`, and the specified real-data summary labels.
- Do not add APIs, charts, trends, percentages, security events, or any fabricated metric.
- Use only loaded values: user/role API response `total`, `users.length`, `roles.length`, `permissions.length`, and active filter state.
- Use `#E87516` primary orange, `#21130E` through `#322019` navigation, `#FFFCF8` workspace, `#EDE1D5` borders, and `#2A211D` text.
- Keep current CRUD, filters, pagination, role/permission assignment, status, password reset, deletion, logout, and responsive navigation behavior unchanged.
- Prefer Ant Design component APIs; never emulate Ant Design controls through copied internal class names.
- Test through accessible roles/labels and retained visible copy, not CSS implementation selectors.

---

## File Structure

- Create: `frontend/src/components/layout/page-summary.tsx` - visual-only real-value summary card grid.
- Modify: `frontend/src/components/ui/ant-design-provider.tsx` - refined global and component theme tokens.
- Modify: `frontend/src/app/globals.css` - brand composition, shell, page, table, login, responsive, and overlay refinements.
- Modify: `frontend/src/components/layout/app-sidebar.tsx`, `app-header.tsx`, `dashboard-shell.tsx`, `page-header.tsx` - command-center shell and page-header extension.
- Modify: `frontend/src/app/(auth)/login/page.tsx`, `frontend/src/components/auth/login-form.tsx` - refined branded login composition.
- Modify: `frontend/src/components/users/user-management.tsx`, `user-table.tsx`, `user-filters.tsx`, `user-drawer.tsx` - real summary data and enclosed user workspace.
- Modify: `frontend/src/components/roles/role-management.tsx`, `role-table.tsx`, `role-filters.tsx`, `role-drawer.tsx`, `permission-tree.tsx` - matching role workspace and editor composition.
- Modify tests: `frontend/src/components/layout/dashboard-shell.test.tsx`, `users/user-management.test.tsx`, `roles/role-management.test.tsx`, and new `layout/page-summary.test.tsx`.

### Task 1: Establish the Brand Tokens, Global Surfaces, and Summary Component

**Files:**
- Create: `frontend/src/components/layout/page-summary.tsx`
- Create: `frontend/src/components/layout/page-summary.test.tsx`
- Modify: `frontend/src/components/ui/ant-design-provider.tsx`
- Modify: `frontend/src/app/globals.css`

**Interfaces:**
- Produces `PageSummary({ items }: { items: Array<{ label: string; value: number }> }): ReactElement`.
- Each `items` value is already derived by its parent; `PageSummary` must not fetch, calculate trends, or synthesize status text.

- [ ] **Step 1: Write the failing summary-card test.**

```tsx
import { render, screen } from "@testing-library/react";
import PageSummary from "./page-summary";

test("renders supplied real values without trends or fabricated metrics", () => {
  render(<PageSummary items={[{ label: "组织成员", value: 24 }, { label: "当前页", value: 10 }]} />);
  expect(screen.getByText("组织成员")).toBeVisible();
  expect(screen.getByText("24")).toBeVisible();
  expect(screen.queryByText(/较上期|安全事件|%/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the new test and confirm it fails.**

Run from `X:\01_RBAC\frontend`:

```powershell
npm test -- --run src/components/layout/page-summary.test.tsx
```

Expected: FAIL because `./page-summary` does not exist.

- [ ] **Step 3: Create the purely presentational summary grid.**

```tsx
import { Card, Statistic } from "antd";

export default function PageSummary({ items }: { items: Array<{ label: string; value: number }> }) {
  return (
    <div className="page-summary" aria-label="页面统计">
      {items.map((item) => (
        <Card key={item.label} className="summary-card" bordered={false}>
          <Statistic title={item.label} value={item.value} />
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Refine provider tokens and global CSS.**

Keep the existing colors, then set component refinements for 14px cards, 72px-class header/sider surfaces, compact warm table headers, rounded drawer/modal elevations, and orange primary buttons. Replace the current minimal `globals.css` with semantic rules for:

```css
.warm-executive-layout { min-height: 100vh; background: radial-gradient(circle at 78% 0, #fff1e3 0, transparent 28%), #fffcf8; }
.warm-executive-content { min-width: 0; padding: 38px; }
.page-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 28px 0 20px; }
.summary-card { border: 1px solid #f0dfd1; border-radius: 14px !important; box-shadow: 0 12px 28px rgba(67, 42, 25, .05); }
.data-surface { overflow: hidden; border: 1px solid #efe0d4; border-radius: 14px; background: #fff; box-shadow: 0 12px 28px rgba(67, 42, 25, .04); }
@media (max-width: 767px) { .warm-executive-content { padding: 20px 16px; } .page-summary { grid-template-columns: 1fr; } }
```

Add matching login, table, tags, pagination, Drawer, Modal, and action-trigger rules using semantic class names. Do not recreate Ant Design internals.

- [ ] **Step 5: Run the focused test and build.**

```powershell
npm test -- --run src/components/layout/page-summary.test.tsx
npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit.**

```powershell
git add frontend/src/components/layout/page-summary.tsx frontend/src/components/layout/page-summary.test.tsx frontend/src/components/ui/ant-design-provider.tsx frontend/src/app/globals.css
git commit -m "feat: establish orange command center visual system"
```

### Task 2: Recompose the Branded Shell and Responsive Navigation

**Files:**
- Modify: `frontend/src/components/layout/app-sidebar.tsx`
- Modify: `frontend/src/components/layout/app-header.tsx`
- Modify: `frontend/src/components/layout/dashboard-shell.tsx`
- Modify: `frontend/src/components/layout/page-header.tsx`
- Modify: `frontend/src/components/layout/dashboard-shell.test.tsx`

**Interfaces:**
- Extends `PageHeaderProps` with optional `eyebrow?: string` and `description?: string`; keeps `title` and `actions` unchanged.
- Preserves `AppSidebar({ user, onNavigate? })` and `DashboardShell({ currentUser, children })` interfaces.

- [ ] **Step 1: Add failing semantic shell assertions.**

```tsx
expect(screen.getByText("ACCESS GOVERNANCE")).toBeVisible();
expect(screen.getByRole("navigation")).toBeVisible();
await user.click(screen.getByRole("button", { name: "Open navigation" }));
expect(screen.getByRole("dialog")).toBeVisible();
```

- [ ] **Step 2: Run shell tests before implementation.**

```powershell
npm test -- --run src/components/layout/dashboard-shell.test.tsx
```

Expected: FAIL on the new visual brand descriptor assertion.

- [ ] **Step 3: Build the command-center shell without changing destinations or permissions.**

In `app-sidebar.tsx`, retain the existing `hasPermission` item construction and links. Add a brand-mark element, the existing `copy.app.title`, static non-user-facing descriptor `ACCESS GOVERNANCE`, contextual menu section labels, and a bottom account block using the supplied `user.display_name`.

In `dashboard-shell.tsx`, change desktop `Sider` width from `232` to `258`, retain `breakpoint="md"`, and update mobile Drawer to Ant Design 6 `size="large"` rather than deprecated `width`. Keep `onNavigate={() => setDrawerOpen(false)}`.

In `app-header.tsx`, replace all inline style objects with `.app-header`, `.header-context`, and `.header-account` classes. Keep the logout POST and `router.push("/login")` exactly as written.

In `page-header.tsx`, render optional eyebrow/description without altering existing callers:

```tsx
<div className="page-header-copy">
  {eyebrow ? <span className="page-eyebrow">{eyebrow}</span> : null}
  <h1>{title}</h1>
  {description ? <p>{description}</p> : null}
</div>
```

- [ ] **Step 4: Run shell tests and build.**

```powershell
npm test -- --run src/components/layout/dashboard-shell.test.tsx
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/components/layout/app-sidebar.tsx frontend/src/components/layout/app-header.tsx frontend/src/components/layout/dashboard-shell.tsx frontend/src/components/layout/page-header.tsx frontend/src/components/layout/dashboard-shell.test.tsx frontend/src/app/globals.css
git commit -m "feat: recompose orange command center shell"
```

### Task 3: Polish Login and User Management With Real Summaries

**Files:**
- Modify: `frontend/src/app/(auth)/login/page.tsx`
- Modify: `frontend/src/components/auth/login-form.tsx`
- Modify: `frontend/src/components/users/user-management.tsx`
- Modify: `frontend/src/components/users/user-table.tsx`
- Modify: `frontend/src/components/users/user-filters.tsx`
- Modify: `frontend/src/components/users/user-drawer.tsx`
- Modify: `frontend/src/components/users/user-management.test.tsx`
- Modify: `frontend/src/components/auth/login-form.test.tsx`

**Interfaces:**
- Consumes `PageSummary` from Task 1.
- Preserves all current `UserManagement` state, `doFetch`, filter params, `DialogState`, mutation endpoints, `UserDrawer` props, and login credentials payload.

- [ ] **Step 1: Add failing user-summary tests.**

```tsx
expect(await screen.findByText("24")).toBeVisible(); // API response total
expect(screen.getByText("10")).toBeVisible(); // current page items length
expect(screen.queryByText(/较上期|安全事件|%/)).not.toBeInTheDocument();
```

Use mock list data with `total: 24` and ten items so the two values are unambiguous.

- [ ] **Step 2: Run focused user tests and confirm new assertions fail.**

```powershell
npm test -- --run src/components/users/user-management.test.tsx
```

- [ ] **Step 3: Add the user command-center page structure.**

Render `PageHeader` with visual-only eyebrow `IDENTITY DIRECTORY` and no new translated business copy. Directly after it render:

```tsx
<PageSummary items={[
  { label: "组织成员", value: total },
  { label: "当前页成员", value: users.length },
  { label: "筛选结果", value: keyword || status || roleId ? total : total },
]} />
```

The third value intentionally stays `total`; it identifies the active result set without inventing a second data source. For loading, render the same heading and three `Skeleton` card silhouettes before the data-surface skeleton. For errors and empty results, retain existing retry/create behavior but keep it inside `.data-surface`.

- [ ] **Step 4: Refine presentation-only user components.**

- `user-table.tsx`: retain columns and callbacks; add table `scroll={{ x: 980 }}`, user/contact hierarchy classes, warm tags/status pills, and a square semantic `Button` trigger for the existing Dropdown.
- `user-filters.tsx`: retain exact callback payload and search/reset behavior; wrap the existing controls in a responsive Ant Design `Space` and apply dedicated class names.
- `user-drawer.tsx`: retain validation and POST/PUT payloads; add a footer class and Ant Design Drawer `styles={{ body: { paddingBottom: 88 } }}`.
- `login/page.tsx` and `login-form.tsx`: do not change copy or submit logic; add only class names/Ant Design props needed for the two-column deep-brown/amber composition and full-width gradient primary button.

- [ ] **Step 5: Run login and user tests plus build.**

```powershell
npm test -- --run src/components/auth/login-form.test.tsx src/components/users
npm run build
```

Expected: PASS; tests still prove login POST/redirect, user query construction, permission gates, and mutations.

- [ ] **Step 6: Commit.**

```powershell
git add frontend/src/app/(auth)/login/page.tsx frontend/src/components/auth/login-form.tsx frontend/src/components/users frontend/src/components/layout/page-summary.tsx frontend/src/app/globals.css
git commit -m "feat: polish orange user management workspace"
```

### Task 4: Apply the Matching Role Governance Workspace

**Files:**
- Modify: `frontend/src/components/roles/role-management.tsx`
- Modify: `frontend/src/components/roles/role-table.tsx`
- Modify: `frontend/src/components/roles/role-filters.tsx`
- Modify: `frontend/src/components/roles/role-drawer.tsx`
- Modify: `frontend/src/components/roles/permission-tree.tsx`
- Modify: `frontend/src/components/roles/role-management.test.tsx`

**Interfaces:**
- Consumes `PageSummary` from Task 1 and current `RoleManagement` state.
- Preserves `RoleDrawerProps`, `PermissionTreeProps`, all role endpoints, system-role protection, and permission tree `onChange(ids: string[])` behavior.

- [ ] **Step 1: Add failing role-summary assertions.**

```tsx
expect(await screen.findByText("16")).toBeVisible(); // roles response total
expect(screen.getByText("10")).toBeVisible(); // roles.length
expect(screen.getByText("13")).toBeVisible(); // permissions.length
```

Use mock response values that differ from all table row values.

- [ ] **Step 2: Run focused role tests and confirm failure.**

```powershell
npm test -- --run src/components/roles/role-management.test.tsx
```

- [ ] **Step 3: Add role summaries and unified workspace composition.**

Use `PageHeader` eyebrow `ROLE GOVERNANCE` and render:

```tsx
<PageSummary items={[
  { label: "角色总数", value: total },
  { label: "当前页角色", value: roles.length },
  { label: "权限总数", value: permissions.length },
]} />
```

Move filters, action Alert, `RoleTable`, and Pagination into one `.data-surface` structure. Preserve conditional pagination behavior (`totalPages > 1`), query parameters, and retry behavior. Loading uses three summary skeletons plus a data-surface skeleton; empty and error states remain inside the same surface.

- [ ] **Step 4: Refine table, editor drawer, and tree framing.**

- `role-table.tsx`: retain permission gates and callbacks; use warm system-role `Tag`, semantic status tag, horizontal table scroll, and a square Ant Design Button action trigger with `aria-label="More actions"`.
- `role-filters.tsx`: preserve exact callbacks while assigning data-workspace filter classes.
- `role-drawer.tsx`: retain role-detail fetch, immutable-system behavior, payloads, and selected count calculation; add drawer body/footer classes and a visible selected-permission summary container.
- `permission-tree.tsx`: preserve `TreeDataNode[]` mapping and read-only behavior; add grouped tree container/title classes only.

- [ ] **Step 5: Run role tests and build.**

```powershell
npm test -- --run src/components/roles
npm run build
```

Expected: PASS, including system-role protection and delete impact request behavior.

- [ ] **Step 6: Commit.**

```powershell
git add frontend/src/components/roles frontend/src/app/globals.css
git commit -m "feat: polish orange role governance workspace"
```

### Task 5: Verify Desktop/Mobile Visual Integrity and Behavioral Preservation

**Files:**
- Modify only files with verified defects discovered by these steps.
- Test: all frontend tests.

**Interfaces:**
- Consumes the completed shell, page summaries, login, user, and role workspaces.
- Produces verified routes without API, permission, or copy regressions.

- [ ] **Step 1: Scan for illegal fabricated metrics and duplicate primitive implementations.**

```powershell
git grep -n -E "较上期|安全事件|%" -- src
git grep -n -E "components/ui/(button|input|select|drawer|empty-state|skeleton|status-tag)" -- src
```

Expected: no presentation metric text in product components and no imports of deleted custom primitives.

- [ ] **Step 2: Run the complete frontend suite.**

```powershell
npm test -- --run
```

Expected: every test passes.

- [ ] **Step 3: Run the production build.**

```powershell
npm run build
```

Expected: PASS with `/login`, `/users`, and `/roles` generated.

- [ ] **Step 4: Perform visual acceptance at desktop and 375px mobile widths.**

Run `npm run dev` and verify:

```text
1. Login has a deep-brown brand narrative and warm-white focused form on desktop, and no clipped controls on mobile.
2. Desktop sidebar is 258px-class, branded, grouped, and permission-filtered; mobile navigation opens/closes a branded Drawer.
3. User and role pages show only real summary values and a single enclosed data workspace.
4. Tables scroll horizontally on mobile without clipped required columns.
5. Filters wrap, create actions remain reachable, and drawer/modal footers remain visible.
6. Existing create, edit, delete, status, reset-password, role, and permission operations still complete correctly.
```

- [ ] **Step 5: Check localization and contract safety.**

```powershell
git diff --check
git diff -- frontend/src/lib/copy.ts frontend/src/app/layout.tsx
```

Expected: no whitespace errors; no changes to `copy.ts`; any `layout.tsx` change is limited to visual composition imports.

- [ ] **Step 6: Commit only verified polish fixes if needed.**

```powershell
git add frontend/src
git commit -m "fix: refine orange command center responsiveness"
```

Skip when no changes were needed.
