# Enterprise AI Workspace Visual Redesign

## Status

Approved product and visual design for `C:\01_agent_loop`. This document defines the unified private ChatGPT and governance experience. It does not modify production code.

## Product Positioning

The product name is **企业智助**.

企业智助 is a private organizational AI workspace with two integrated capabilities:

1. A ChatGPT-quality personal conversation experience for every authenticated user.
2. Role-based governance for members, permissions, and organization-wide conversation oversight.

Chat is the primary product, not an add-on to an RBAC dashboard. Governance is a distinct secondary layer inside the same visual system.

## Product Principles

- Beautiful and restrained: warm, refined, and readable rather than decorative.
- Chat first: all users, including super administrators, land in the AI workspace after login.
- Private by default: ordinary users can access only their own sessions.
- Governable by design: the highest administrator can directly inspect all users' conversations.
- Quiet administration: governance features do not visually dominate the daily chat experience.
- Human-readable oversight: administrators see people and conversations before technical run diagnostics.
- Consistent interaction: landing composer, continuation composer, status, loading, error, and empty states use shared components.
- Accessible and responsive: keyboard, reduced motion, zoom, mobile keyboard, and narrow viewport behavior are first-class requirements.

## Confirmed Decisions

- Scope: full-system visual and information-architecture redesign.
- Visual direction: **Warm Intelligence**, using deep coffee, warm white, and restrained amber.
- Product name: **企业智助**.
- Highest administrator conversation access: direct access, no confirmation modal and no required reason field.
- Governance top bar must not display `特权访问 · 自动留痕` or equivalent wording.
- Conversation-view audit activity may still be recorded in backend logs without a visible interruption.
- Default post-login destination for all roles: `/agent`.
- Thought, search, and tool execution details remain expanded by default.
- Composer keyboard behavior: Enter sends; Shift+Enter inserts a newline; IME composition never sends.
- Completed answer actions: copy only.
- Theme: light theme only in this iteration.

## Information Architecture

### Primary Workspace

```text
企业智助
├─ 新建对话
├─ 我的会话
│  └─ 会话详情
└─ 账户
```

Every authenticated user enters the chat workspace. Conversation history and new chat are the highest-frequency actions.

### Governance

The sidebar footer contains a distinct governance group. Items are permission-gated.

```text
治理中心
├─ 对话审计
│  ├─ 人员
│  ├─ 会话
│  ├─ 对话全文
│  └─ 运行诊断
├─ 用户管理
└─ 角色与权限
```

Highest administrators navigate directly into any user's conversations. No visible privileged-access banner is shown. Backend view logging may run silently.

### Audit Reading Order

Governance defaults to human-readable context:

1. Person: display name, username, department/role where available.
2. Conversation: title, date, status, mode, and searchable summary.
3. Transcript: user messages, AI answers, expanded thought/tool timeline.
4. Diagnostics: attempt, step, event, worker, sequence, timing, and retry details.

Raw IDs are secondary copyable metadata. Raw JSON is never the default presentation.

## Unified Visual Language

### Palette

| Token | Value | Usage |
|---|---|---|
| `--color-bg-app` | `#FAF7F3` | Application canvas |
| `--color-bg-surface` | `#FFFFFF` | Panels, composer, drawers |
| `--color-bg-subtle` | `#F7F2EE` | Secondary surfaces |
| `--color-sidebar` | `#2A1812` | Desktop and mobile navigation |
| `--color-sidebar-elevated` | `#3B271F` | Sidebar controls and selection |
| `--color-primary` | `#D96313` | Brand mark and primary action |
| `--color-primary-hover` | `#B94F0C` | Primary hover |
| `--color-primary-soft` | `#FFF0E4` | User bubbles and selected warm states |
| `--color-text-primary` | `#2B2521` | Main text |
| `--color-text-secondary` | `#71645C` | Secondary text |
| `--color-text-muted` | `#8E7F76` | Readable metadata |
| `--color-border` | `#E6DDD6` | Default borders |
| `--color-border-strong` | `#D5C8BE` | Emphasized boundaries |
| `--color-info` | `#4F64DC` | Running/information state |
| `--color-success` | `#21804C` | Completed state |
| `--color-warning` | `#A66300` | Retry/warning state |
| `--color-danger` | `#C24141` | Failure/destructive action |

Amber is not a universal status color. Semantic states retain distinct blue, green, yellow, and red.

### Typography

Use the existing system Chinese font stack. Do not add a remote font dependency.

UI scale:

- 12px metadata.
- 13px compact controls.
- 14px standard UI.
- 16px body and form text.
- 18px section title.
- 22px page title.
- 28px feature heading.
- 36px landing heading.

Weights are limited to 400, 500, 600, and 700. Reading content uses a 1.75 line height.

### Spacing

Use a 4px base scale:

```text
4, 8, 12, 16, 20, 24, 32, 40, 48, 64
```

Avoid arbitrary one-off spacing unless needed for optical alignment.

### Radius

- 6px: compact rows, tags, small controls.
- 10px: buttons, inputs, selection surfaces.
- 14px: composer, drawers, major surfaces.
- 999px: tags and circular/pill controls only.

Do not use 24-30px radius on general cards or panels.

### Elevation

Use only three shadow levels:

- Small: controls and subtle floating actions.
- Medium: composer and cards requiring separation.
- Large: modal and drawer only.

Data surfaces and chat content primarily use border and whitespace, not shadow stacking.

## Application Shell

### Desktop

- Sidebar width: approximately 248px.
- Sidebar uses deep coffee on every route.
- Main canvas uses warm white.
- Sidebar remains independently scrollable only in the conversation-history region.
- Brand, new chat, governance group, and account remain fixed.
- The current global dashboard header is removed from chat routes.
- Management routes use a compact page header inside the content area rather than a redundant global identity header.

### Sidebar Structure

```text
Brand: 企业智助
Primary action: 开始新对话
Conversation history
Governance group
Account block
```

The account block displays:

- Avatar or initial.
- Display name.
- Username.
- Role badge such as `超级管理员`.
- Logout action.

Account identity is not duplicated in a global header.

### Collapsed Desktop Sidebar

- Hidden descendants must be removed from keyboard focus using conditional rendering or `inert` plus `aria-hidden`.
- Collapse trigger communicates expanded state.
- Focus moves to the collapse/expand trigger when necessary.

### Main Landmark

The shell renders application content inside a semantic `<main>` landmark.

## Chat Landing Page

- Product heading focuses on assistance, not internal Agent terminology.
- Suggested copy: `今天想完成什么？`
- Supporting copy may reference secure organizational knowledge and tools.
- Initial composer is visually consistent with the continuation composer.
- Remove duplicate large mode selector plus capability tags.
- Mode appears as one compact segmented control, select, or pill inside the composer toolbar.
- The page should feel immediately usable, not like a workflow-launch dashboard.
- Suggested prompt cards are optional but limited to three restrained text actions; no colorful dashboard grid.

## Conversation Page

### Top Bar

The compact top bar contains:

- Mobile/desktop sidebar control.
- Session title as an `h1`.
- Current mode.
- Private workspace indicator.
- Optional compact overflow menu only if it has real actions.

Remove the nonfunctional `↗` glyph.

### Conversation Stream

- Reading width: 720-780px.
- User messages are right-aligned warm-soft bubbles.
- AI answers are unboxed, long-form Markdown on the canvas.
- Completed metadata is subdued.
- Running/retry/failure states remain visible.
- Status is not redundantly repeated in both top bar and every completed turn.

### Thought And Tool Timeline

Thought, search, and tool details remain expanded by default, as selected.

Visual treatment:

- Fine vertical timeline.
- Small semantic icons.
- Low-saturation status markers.
- Clear step title and secondary detail.
- No nested large cards.
- Completed steps render static content.
- Active steps retain smooth streaming animation.

Users may manually collapse the timeline. The disclosure control uses `aria-expanded` and `aria-controls`.

### Final Answer

- Retain safe GFM Markdown.
- Keep headings, lists, blockquotes, code, tables, and links polished.
- Wide code/table regions remain keyboard-focusable and horizontally scrollable.
- Completed historical answers render immediately.
- Active answers stream smoothly.
- Only one completed-answer action is provided: `复制`.
- Copy action is low-emphasis and appears below the answer; it remains keyboard discoverable and has clear copied feedback.

## Composer

Create one reusable `ChatComposer` for landing and session detail.

### Layout

- Warm white surface.
- 1px warm border.
- 14px radius.
- Medium subtle shadow.
- Text area grows to a bounded maximum height and then scrolls.
- Toolbar contains attachments, mode, keyboard hint, and send.
- Send uses amber only when enabled.

### Keyboard Behavior

- Enter sends.
- Shift+Enter inserts newline.
- IME composition never sends.
- Empty or whitespace-only text does not send.
- Attachment upload state disables conflicting submission where required.

### Attachments

- Trigger is keyboard operable and named.
- Selected files render as compact inline chips inside the composer.
- Chips include removal controls.
- Upload/progress/error states do not use absolute-position overlays.
- Errors use `role="alert"`.

### Mobile Composer

- Uses 12-16px horizontal spacing.
- Respects bottom safe area.
- Remains visible above the virtual keyboard.
- Toolbar wraps or simplifies instead of overflowing.

## Governance Center

### Governance Home

The first viewport uses a compact summary row:

- Organization members.
- Today's conversations.
- Running conversations.
- Abnormal runs.

Avoid oversized colored statistic cards. Use white surfaces, warm borders, clear numeric emphasis, and semantic status color only where needed.

### Filters

Conversation audit supports:

- Person.
- Username.
- Conversation keyword.
- Date range.
- Status.
- Mode.
- Network enabled state.

Use one compact filter bar with responsive wrapping or mobile filter drawer.

### People And Conversation Browser

Desktop:

- People list or filter column.
- Conversation list/summary.
- Transcript content.

Smaller screens:

- Progressive navigation rather than squeezed three-column layout.

Show human identity first. UUID is secondary.

### Conversation Transcript

Audit transcript visually matches the ordinary conversation page:

- User messages.
- Expanded thought/tool timeline.
- AI Markdown answers.
- Status and timing.
- Copy action if permitted.

The governance top bar must not display `特权访问 · 自动留痕` or equivalent privileged-access wording.

### Run Diagnostics

Attempts, steps, events, worker information, sequence IDs, and raw event details are placed in a secondary collapsible diagnostics region or drawer.

The default view is the conversation, not infrastructure JSON.

### Required Audit Contract Fixes

- Add frontend `getAuditRun()` using `/api/agent/audit/runs/{runId}`.
- Audit run detail must not call owner-scoped `getRun()`.
- Build an audit-session transcript loader equivalent to the owner session-view loader, using audit endpoints.
- Expose the existing backend `user_id` audit filter in the interface.
- Join or enrich audit sessions with human-readable user identity.

## User Management

- Page header contains title, one-line description, and `新建用户` primary action.
- Summary uses restrained inline metrics, not decorative cards.
- Filters use one compact toolbar.
- Table sits inside one `DataSurface`.
- Actions remain permission-gated.
- Horizontal table scrolling is keyboard-focusable.
- Loading uses structured skeleton rows.
- Empty/error states use shared components.
- User drawer is responsive and uses full viewport width on mobile.
- Editing must initialize existing role assignments correctly to avoid accidental role removal.

## Roles And Permissions

- Page structure matches user management.
- Role drawer includes identity, description, status, and permission tree with clear grouping.
- Permission selection maintains readable hierarchy without excessive bordered cards.
- Status editing contract must align with backend behavior; do not show an editable field that is not submitted.
- The shared dashboard layout must not require `user:read` for the `/roles` page. Page-level permissions remain authoritative.
- System/super-admin protections remain intact.

## Login Experience

- Brand changes to 企业智助.
- Retain warm split layout but simplify decorative content.
- Left side communicates private organizational AI, knowledge, and governance.
- Right side uses a restrained login form with clear focus and validation.
- All successful users redirect to `/agent` unless a safe validated callback exists.
- Super administrators no longer default to `/users`.

## Navigation And Permissions

- Ordinary users see chat and their sessions only.
- Governance links appear only when authorized.
- User and role routes retain granular permissions.
- Audit UI should migrate from hard-coded `super_admin` display logic toward explicit audit permissions when backend contracts support it.
- Backend authorization remains authoritative.
- Highest administrator may directly view all conversation content.

## Responsive System

Use four breakpoints only:

- `sm`: 640px.
- `md`: 768px.
- `lg`: 960px.
- `xl`: 1200px.

### Below 768px

- Sidebar becomes a Drawer with the same deep-coffee background.
- Drawer does not use a light default background behind inverse text.
- Main horizontal padding becomes 12-16px.
- Conversation top bar becomes compact.
- Composer remains bottom-accessible.
- Governance uses progressive pages instead of multi-column compression.
- Management drawers use viewport width.

### Scroll Boundaries

- Application shell owns viewport height.
- Sidebar history is independently scrollable.
- Chat transcript is independently scrollable.
- Composer remains docked.
- Management content owns its own vertical scrolling; it must not be clipped by shell overflow.
- Tables and code own local horizontal scrolling.

### Target Verification

- 320x568.
- 375x667.
- 390x844.
- 768x1024.
- 1366x768.
- 1440x900.
- 1920x1080.
- 200% and 400% browser zoom.

## Accessibility

- Restore universal visible `:focus-visible`; do not globally suppress outlines without replacement.
- Shell uses `<main>` and sidebar uses `<nav>`.
- Active navigation/session links use `aria-current="page"`.
- Sidebar collapse removes hidden controls from focus order.
- Icon-only buttons have accessible names and at least 40px touch targets where practical.
- Thought disclosure uses `aria-expanded` and `aria-controls`.
- Attachment trigger is keyboard operable.
- Upload/validation errors use live alert semantics.
- Session title uses `h1`.
- Table/code scroll containers are keyboard accessible.
- Reduced-motion disables typing, pulse, sidebar, tooltip, and decorative transitions.
- Text, borders, controls, and focus rings meet WCAG AA contrast.
- Live streaming announcements are throttled; screen readers do not announce every character.

## Shared Component Boundaries

Create or consolidate these units:

- `AppShell`: viewport, responsive sidebar, semantic main.
- `AppSidebar`: brand, chat history, governance navigation, account.
- `ConversationTopBar`: session title/mode/privacy/sidebar control.
- `ChatComposer`: text, attachments, mode, send, keyboard behavior.
- `ConversationTurn`: prompt, process timeline, answer, copy action.
- `ProcessTimeline`: expanded thought/search/tool timeline.
- `GovernanceTranscript`: administrator-readable conversation view.
- `PageHeader`: management title/description/action.
- `DataSurface`: table/list container.
- `FilterBar`: responsive management/audit filters.
- `PageLoading`, `InlineLoading`, `EmptyState`, `PageError`, `InlineAlert`.

Avoid creating a generic component for every small visual fragment. Shared boundaries must correspond to meaningful reusable behavior.

## Error, Loading, And Empty States

- Initial page loading uses stable skeletons; avoid centered spinners that shift the layout.
- Background reconciliation never replaces the conversation with a page loader.
- Inline warnings preserve available content.
- Empty chat history suggests starting a conversation.
- Empty governance filters explain how to broaden filters.
- Access denial clearly identifies missing permission without exposing protected content.
- Network and streaming failures preserve received text and offer a clear recoverable status.

## Testing And Acceptance

### Automated

- Existing full frontend tests remain green.
- Next production build passes.
- Navigation permissions have explicit matrix tests.
- Composer keyboard tests cover Enter, Shift+Enter, IME, empty input, and attachments.
- Sidebar tests cover collapse focus order, Drawer, active link semantics, and bottom account access.
- Conversation tests cover streaming, historical answers, expanded timeline, copy action, and Markdown.
- Governance tests cover all-session listing, user filter, audit run endpoint, transcript rendering, and ordinary-user denial.
- User/role tests cover permissions, role initialization, status behavior, responsive drawers, and table scroll semantics.

### Real Browser

Use Microsoft Edge with a clean profile for acceptance. Do not use Quark because prior diagnostics showed repeated localhost navigations unrelated to application code.

Validate:

- Login and redirect for ordinary and highest-admin roles.
- Chat landing and multi-turn conversation.
- Streaming, completion, history reload, and copy answer.
- Expanded thought/tool timeline.
- Governance people/conversation/transcript/diagnostics flow.
- Direct highest-admin access to another user's transcript.
- User and role CRUD according to permission matrix.
- Desktop/mobile/zoom layout and keyboard focus.

Use synthetic non-private fixtures. Do not capture private production conversation content in screenshots or logs.

### Visual Regression Pages

- Login.
- Chat landing.
- Conversation detail.
- Governance home.
- Audited conversation.
- User management.
- Role and permission management.

## Rollout Sequence

1. Establish shared tokens and Ant theme alignment.
2. Refactor shell/sidebar/header and responsive scroll boundaries.
3. Consolidate ChatComposer and keyboard/attachment behavior.
4. Restyle landing/conversation/timeline/answer actions.
5. Redesign governance information architecture and fix audit API usage.
6. Align users/roles/loading/error/empty states.
7. Update login branding and redirects.
8. Complete accessibility, responsive, permission, and browser verification.

## Rollback

Each rollout stage should remain independently reversible:

- Tokens/theme may roll back without changing data/API contracts.
- Chat composer refactor retains existing submit contracts.
- Governance visual redesign must preserve old audit endpoints until replacement loaders are verified.
- Login redirect change can roll back independently.
- No database migration is required for the visual redesign itself.

## Acceptance Criteria

1. The product consistently presents as 企业智助, a private organizational ChatGPT, rather than an RBAC dashboard with an Agent feature.
2. All users land in chat after login.
3. Ordinary users access only their own conversations.
4. Highest administrators directly access all user conversations from governance.
5. Governance UI does not show `特权访问 · 自动留痕` wording.
6. Chat, governance, users, roles, login, and mobile Drawer use one Warm Intelligence visual system.
7. Conversation reading, expanded process timeline, composer, and Markdown remain clear and responsive.
8. Answer actions contain copy only.
9. Enter sends, Shift+Enter inserts newline, and IME composition is safe.
10. Desktop, mobile, zoom, keyboard, reduced-motion, permission, frontend tests, and production build gates pass.
