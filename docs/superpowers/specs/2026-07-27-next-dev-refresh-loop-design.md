# Next Development Refresh Loop Design

## Scope

Fix the continuous full-page refresh in `C:\01_agent_loop\frontend` without changing application behavior.

## Root Cause

The copied project still starts Next with `next dev --webpack --no-server-fast-refresh`. The same approximately one-second browser remount loop occurs from the local `C:` path, so the mapped drive is not the cause. The shared trigger is the explicit disabling of server Fast Refresh, combined with forcing Webpack instead of using the Next 16 default development configuration.

## Change

Set `npm run dev` to `next dev`, which uses Next 16's default Turbopack development server and normal Fast Refresh. Keep `npm run preview` as `npm run build && next start` for production-mode validation.

Update the package-script contract test and frontend README to match. Stop the current development process and remove only the generated `frontend/.next` directory before starting the corrected development server.

## Constraints

- Do not change login, authentication, Agent SSE, typing animation, or backend code.
- Do not delete `node_modules`; the installed dependencies match the lock file unless verification proves otherwise.
- Do not modify `X:\01_RBAC` as part of this fix.
- Preserve `preview`, `build`, `start`, `lint`, and `test` scripts.

## Verification

- The package-script test requires `dev` to equal `next dev` and `preview` to remain `npm run build && next start`.
- Run the focused script test, all frontend tests, and the production build.
- Start `npm run dev`, request `/login`, and inspect `.next/dev/logs/next-development.log` for at least 15 seconds. The browser must not remount continuously when no source file changes.
- Modify and restore a harmless source file timestamp/content during manual verification only if needed to confirm a single Fast Refresh event.
