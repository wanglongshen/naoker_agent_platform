# Ant Design Warm Executive Visual Redesign

## 1. Goal

Redesign the entire Next.js RBAC frontend as a polished, responsive enterprise console. The visual direction is **Warm Executive**: a deep brown navigation surface, warm-white workspace, and restrained amber-orange actions and accents.

Ant Design provides the accessible interaction and component foundation. Its default appearance is not the target; global theme tokens and scoped visual refinements produce the approved branded result.

## 2. Scope

### In scope

- Install and use `antd` and `@ant-design/icons`.
- Add a root Ant Design provider with the global Warm Executive theme.
- Redesign the login page, desktop dashboard shell, mobile navigation, user management, role management, and shared feedback/form components.
- Replace custom primitive controls with appropriate Ant Design components where they are currently used: layout, navigation, buttons, form controls, tables, tags, drawers, dialogs, skeletons, empty states, and feedback.
- Preserve all existing routes, API contracts, business flows, permission checks, loading behavior, and mobile functionality.
- Update frontend tests only as necessary to verify the retained behavior through the redesigned controls.

### Out of scope

- User-visible wording, translations, browser metadata, or a copy dictionary. A concurrent localization task owns those changes.
- Backend APIs, database schema, authorization behavior, and seed data.
- New product capabilities, dashboard APIs, or analytics data. Decorative statistic cards shown in brainstorming mockups are not added without real data sources.

## 3. Concurrent Work Boundaries

The localization task may change `app/layout.tsx`, the login page, shared layout components, and UI strings. The visual redesign must not overwrite its wording or metadata work.

- Treat user-visible text as supplied content. Do not translate, remove, or introduce business copy.
- Prefer styling and component composition changes around existing text nodes or the localization module.
- Before editing a concurrently changed file, read its current contents and retain unrelated modifications.
- `package.json` currently has uncommitted changes; dependency changes must be merged carefully with those edits.

## 4. Visual System

### Palette and hierarchy

- Brand/action orange: `#E87516`; hover and active shades are darker, with a soft amber background for selected states.
- Navigation: deep brown-black around `#281B16`, with warm low-contrast inactive text.
- Workspace: warm white around `#FFFCF8`; cards remain white.
- Borders: subtle warm neutral, not cool gray.
- Semantic success, warning, and danger colors retain their recognized meanings and sufficient contrast.

### Tokens

Use `ConfigProvider` at the application root to configure Ant Design tokens for `colorPrimary`, primary hover/active variants, `colorBgLayout`, `colorBgContainer`, `colorBorder`, `colorText`, `borderRadius`, `fontFamily`, and shadows. Add component-specific overrides for Layout/Menu, Button, Table, Drawer, Modal, Input, Select, Tag, and Pagination when global tokens alone cannot achieve the approved hierarchy.

### Surfaces and typography

- Page backgrounds use warm-white space with restrained decorative amber gradients only where they support emphasis.
- Cards have 12px-class radii, warm hairline borders, and low-elevation shadows.
- Preserve the existing system Chinese font stack. Data, codes, and IDs may use a suitable monospace treatment where already useful.
- Orange is reserved for brand identity, current navigation, primary actions, and selective emphasis. It must not become the default color for all controls.

### Icons and feedback

Use `@ant-design/icons` for navigation and action affordances. Remove text glyph substitutions for icons. Use Ant Design `message`, `notification`, `Alert`, `Empty`, and `Skeleton` consistently for transient feedback, errors, empty results, and loading states.

## 5. Page Design

### Application shell

Desktop uses Ant Design `Layout`, with a fixed deep-brown `Sider`, brand mark, icon-led permission-aware menu, and a warm-white header/content workspace. Selected menu entries receive a softly tinted orange background, a strong left/leading accent, and orange icon emphasis.

The header holds the existing contextual breadcrumb/content, account area, and logout control. It remains visually quiet so the page title and primary action lead attention.

### Mobile navigation

At narrow breakpoints, the persistent sider is hidden and the existing menu control opens an Ant Design `Drawer`. The drawer renders the same permission-filtered navigation and preserves the current route behavior. Page actions and filter controls wrap without overlap; tables retain a deliberate horizontal-scroll container rather than compressing essential columns beyond readability.

### Login

Large screens use a two-column composition: a branded warm/dark narrative panel and a light login surface. The form uses Ant Design Form, Input, Button, Alert, and loading states. Small screens remove the narrative panel and prioritize a focused, full-height form presentation. Soft amber light and the brand mark provide visual identity without relying on stock imagery.

### User and role management

Each page has a compact page heading, retained description/content, and a clear primary action. Filter controls sit in the header area of a white data surface rather than floating independently.

- Lists use Ant Design `Table` with a responsive scroll strategy and a coherent pagination treatment.
- Status, roles, permission counts, and system badges use semantic `Tag` variants.
- Row actions use compact icon buttons and/or `Dropdown` menus rather than a dense run of full-size buttons.
- Loading is represented by `Skeleton`; no-result cases use `Empty`; request failures surface as `Alert` without hiding recovery actions.

### Forms and destructive actions

Create/edit flows use Ant Design `Drawer`: a side sheet on desktop and a full-width sheet on small screens. Forms retain existing validation and request semantics while adopting Form field spacing, inline validation, and fixed action areas where appropriate.

Delete, disable, reset-password, and other high-impact operations use `Modal.confirm` or an equivalent branded Ant Design modal. Existing permission and immutable-system-role protections stay enforced by the current logic; the presentation makes the risk and confirmation step clear.

Permission assignment uses the existing data and rules, presented through grouped tree/selection controls and an explicit selected-permission summary so dense permission sets remain readable.

## 6. Component Boundaries

- A root theme/provider component owns Ant Design configuration and style registration.
- The dashboard shell owns responsive layout and navigation placement.
- Existing domain components keep ownership of user/role data fetching, permission gating, and mutations.
- Shared UI primitives are consolidated around Ant Design rather than retaining competing custom implementations for the same interaction.
- Domain components receive data and callbacks through their current interfaces wherever possible, minimizing API changes across the frontend.

## 7. Error Handling and Accessibility

- Preserve existing API error parsing and authorization redirects.
- Keep actionable errors visible near the related form/list and provide retry paths where currently available.
- Ensure icon-only controls have accessible labels/tooltips.
- Preserve keyboard operation, visible focus rings, readable contrast, and modal/drawer focus management supplied by Ant Design.
- Do not use color as the only signal for status or destructive behavior.

## 8. Testing and Verification

- Update affected React Testing Library assertions to query semantic roles, labels, and visible retained copy instead of implementation-specific CSS classes.
- Add focused tests for the Ant Design provider/theme wrapper and responsive navigation behavior if not already covered.
- Preserve existing behavioral coverage for login, shell permissions, user CRUD/filter actions, role management, permissions, confirmations, and error states.
- Run `npm test -- --run` and `npm run build` in `frontend`.
- Manually inspect desktop and narrow mobile widths for login, users, roles, drawers, forms, table scroll, dialogs, loading, empty, and error states.

## 9. Acceptance Criteria

- The login, users, and roles routes share a clearly recognizable Warm Executive visual language rather than default Ant Design styling.
- All existing user and role API operations, permission checks, route protection, and responsive navigation continue to work.
- Desktop navigation and mobile drawer expose only allowed destinations.
- Forms, tables, dialogs, statuses, loading, empty, and error states use a consistent Ant Design-based component system.
- No wording, localization behavior, metadata, or backend contract owned by the concurrent localization work is lost or altered.
- Frontend tests and production build pass.
