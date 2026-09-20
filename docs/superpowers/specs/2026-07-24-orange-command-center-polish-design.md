# Orange Command Center Visual Polish Design

## Goal

Elevate the existing Ant Design RBAC frontend from a functional component migration into a high-fidelity orange enterprise identity-governance console. The redesign applies one coherent visual system to login, dashboard navigation, user management, role management, drawers, dialogs, tables, and responsive mobile behavior.

## Scope

### In scope

- Refine the current Ant Design theme tokens and add the Warm Executive visual details absent from the first implementation.
- Rebuild desktop and mobile dashboard composition: branded deep-brown sidebar, lightweight header, constrained warm-white workspace, and responsive navigation drawer.
- Give user and role pages a common information hierarchy: eyebrow, title/description, primary action, real-data summary cards, and one enclosed data workspace.
- Restyle login, tables, filters, tags, pagination, empty/loading/error states, drawers, modals, and action menus.
- Add only real summary data derived from already-loaded frontend data.

### Out of scope

- User-visible copy, translations, metadata, API contracts, permission logic, routes, backend data, or database changes.
- New APIs, analytics, charts, trend calculations, or fabricated security metrics.
- Changes to the existing CRUD, filtering, pagination, role assignment, permission assignment, status, password reset, deletion, and logout behavior.

## Visual Direction

The reference direction is the approved high-fidelity orange command center preview: deep brown tonal navigation framing a warm-white administrative workspace, with amber orange reserved for brand recognition and high-value interaction.

### Palette

- Primary orange: `#E87516`.
- Primary button gradient: amber-orange through `#E87516` to a deeper orange action shade.
- Sidebar range: `#21130E` through `#322019`.
- Workspace: `#FFFCF8` with restrained cream/amber background gradients.
- Borders: warm neutral around `#EDE1D5`.
- Main text: warm near-black around `#2A211D`.
- Secondary text: muted warm brown around `#826F64`.

Orange is limited to the brand mark, active navigation, primary action buttons, selected emphasis, and selected semantic markers. Success, disabled, warning, and destructive states retain distinct semantic colors.

### Surfaces and spacing

- Desktop content remains inside a controlled workspace rather than expanding as an unbounded table canvas.
- The desktop sider is approximately 258px wide; main page gutters are 36-40px and reduce to 16px on mobile.
- Data workspaces use white 14px-radius surfaces, a warm hairline border, low-elevation shadow, and a single continuous boundary around filters, table, alerts, and pagination.
- Page headings and data workspaces have intentionally separated vertical rhythm. Buttons do not appear disconnected from their page context.

## App Shell

### Sidebar

- Use a deep-brown gradient surface with a geometric amber brand mark, existing product name, and a small English product descriptor.
- Group navigation into contextual sections without changing menu destinations or permission gates.
- Give the active menu a translucent amber gradient, a leading orange accent, and an emphasized icon background.
- Place the current account identity at the bottom of the desktop sidebar.
- Reuse the same branded menu content in the mobile `Drawer`; the drawer closes after a navigation selection.

### Header and workspace

- Use a 72px lightweight white header with a compact breadcrumb on the left and account menu/avatar on the right.
- Remove ad hoc inline styling in favor of semantic shell CSS classes.
- The main workspace has a warm-white base and a barely visible cream/amber atmospheric gradient. It must not compete with page data.

## Pages

### Login

- Desktop is a two-column composition: roughly 42% deep-brown brand narrative and 58% warm-white form panel.
- The brand side contains the existing title/description, geometric mark, and a soft amber radial glow. No new marketing copy is introduced.
- The form side uses a narrow, high-quality card with disciplined field rhythm, clear focus state, warm border, and full-width amber gradient submit button.
- Mobile removes the large narrative panel and shows a focused form with a compact brand mark.

### User management

- Add the `IDENTITY DIRECTORY` eyebrow above the existing title/description and primary create action.
- Render three summary cards from real values only:
  - total users from the list response `total`;
  - visible users from `users.length`;
  - filtered result count from the same `total` when any active filter is present, otherwise the unfiltered total.
- Do not render trends, percentages, security events, or other data without an existing data source.
- Place filters, action errors, the existing user table, and pagination inside one data workspace.
- Preserve the existing table fields and responsive horizontal scrolling. Present usernames with stronger hierarchy, contact information as secondary text, low-saturation role tags, semantic status pills, and one square ellipsis action trigger per row.

### Role management

- Mirror the user-page hierarchy so the system reads as one product.
- Render three summary cards from real values only:
  - total roles from the roles list response `total`;
  - visible roles from `roles.length`;
  - loaded permission count from `permissions.length`.
- Keep system-role protection logic unchanged, but present system roles with an amber/gold protected tag.
- Use the same enclosed filter/table/pagination workspace structure as users.
- Keep the existing permission tree data and mutation behavior, but provide grouped tree framing and a selected-permission count summary in the role editor drawer.

## Shared States and Responsiveness

- Loading preserves the page title and page structure, then shows summary-card and data-workspace skeletons instead of a disconnected blank skeleton.
- Errors appear inside the data workspace using Ant Design `Alert` and retain the current retry behavior.
- Empty states sit within the data workspace and keep authorized primary creation actions reachable.
- At 767px and below, summary cards stack to one column, title/actions stack vertically, filter controls wrap, tables scroll horizontally inside their own surface, and create/edit drawers fill the usable screen width.
- All icon-only actions retain accessible labels and tooltips.

## Component Boundaries

- The root Ant Design provider remains the single owner of global tokens.
- `globals.css` owns only brand composition and component refinements, not reimplementations of Ant Design controls.
- Shell components own sidebar/header/mobile-drawer placement.
- User and role management components continue to own their existing API requests, state, permissions, dialogs, and callbacks; page composition and summary-card presentation are added around that behavior.
- Domain table, filter, drawer, modal, and permission-tree components retain their current public interfaces unless a visual-only prop is necessary.

## Verification

- Existing frontend tests retain coverage of API requests, permission gates, dialogs, forms, filters, pagination, and responsive navigation.
- Add focused tests for real summary-card values and their no-fabrication rules.
- Run `npm test -- --run` and `npm run build` from `frontend`.
- Manually verify `/login`, `/users`, and `/roles` at desktop and 375px mobile widths, including navigation, filters, action menus, drawers, dialogs, loading, errors, empty states, and horizontal tables.

## Acceptance Criteria

- The application visibly matches the approved orange command center hierarchy rather than a default Ant Design admin layout.
- The brand colors, sidebar, header, cards, data workspaces, and login form are coherent across every route.
- Every summary value is derived from an existing loaded response or collection; no simulated metric is displayed.
- Existing business behavior and localization-owned copy remain unchanged.
- Desktop and mobile layouts remain usable and readable.
- Tests and production build pass.
