# 企业智助 Frontend

Next.js 16 (Turbopack) + Ant Design 6 frontend for 企业智助, the enterprise private AI workspace.

## Prerequisites

- Node.js 20+
- Backend running at `http://localhost:8000`

## Quick Start

```powershell
cd X:\01_RBAC\frontend
npm install
npm run dev
```

`npm run dev` uses Next 16's default Turbopack development server and Fast Refresh.

Open `http://localhost:3000` in your browser. Login with `admin` / `ChangeMe-Strong1` (development only).

## VS Code / IDE Setup

1. Open `X:\01_RBAC\frontend` as your workspace
2. Install recommended extensions: ESLint, Tailwind CSS IntelliSense, Prettier
3. The `settings.json` in `.vscode/` configures format-on-save and Tailwind class sorting

## Project Structure

```
src/
  app/
    (auth)/login/       # Login page
    (dashboard)/
      layout.tsx         # Dashboard shell with sidebar + header
      users/page.tsx     # User management
      roles/page.tsx     # Role management
  components/
    auth/               # Login form, protected page wrapper
    layout/             # App sidebar, app header, dashboard shell
    roles/              # Role table, drawer, permission tree, filters
    users/              # User table, drawer, form dialog, password reset
    ui/                 # Shared primitives (drawer, select, status-tag, etc.)
  lib/                  # API client, auth helpers, permission utilities
  types/                # TypeScript interfaces for User, Role, Auth
```

## Routes

| Route | Permission Required | Description |
|-------|-------------------|-------------|
| `/login` | None | Credential login form |
| `/users` | `user:read` | User list with create, edit, delete, status, password reset |
| `/roles` | `role:read` | Role list with create, edit, delete, status, permission assignment |

The sidebar hides `/roles` when the user lacks `role:read`. Direct navigation is blocked by `ProtectedPage`.

## Key Behaviors

### super_admin Protection

- The `super_admin` role card shows only name/description as editable
- Status toggle and permission tree are read-only
- Delete action is absent
- The last super admin cannot have the role removed or be disabled

### Permission-aware UI

UI controls are conditionally rendered based on the user's permission set from `/api/auth/me`:

- **Create buttons** require `user:create` / `role:create`
- **Edit/delete/status/password actions** check their respective permissions
- **Role assignment** on user forms requires `user:assign_role`
- **Permission assignment** on role forms requires `role:assign_permission`

### Responsive Layout

- Dark sidebar with light content area
- Collapsible sidebar for mobile (toggle via header hamburger button)
- Tables scroll horizontally on narrow viewports
- Drawers and dialogs fit within the viewport at all widths

## API Proxy

The dev server proxies `/api` requests to `http://localhost:8000` (config in `next.config.ts`). The production build expects a reverse proxy or the same-origin backend.

## Testing

```powershell
npm test -- --run       # Run all tests once
npm test -- --watch     # Watch mode
npm test -- --ui        # Vitest UI
```

Tests use Vitest + React Testing Library + MSW for API mocking. Test files are co-located with their components (`*.test.tsx`).

## Build

```powershell
npm run build
```

Output goes to `.next/`. The build is a static export of the three routes: `/login`, `/users`, `/roles`.

## Production Preview

```powershell
npm run preview
```
