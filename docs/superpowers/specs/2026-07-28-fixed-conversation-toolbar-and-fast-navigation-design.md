# Fixed Conversation Toolbar And Fast Navigation Design

## Status

Approved design awaiting written-spec review.

## Scope

- Keep the right-workspace top bar fixed and visibly branded `企业智助` on the landing and session pages.
- Prevent session titles or user prompts from replacing the top-bar product title.
- Present terminal-answer actions as a compact, professional linear icon toolbar.
- Implement regenerate, local feedback, and share actions with accessible feedback and safe fallbacks.
- Improve perceived and actual session-navigation performance without changing the backend API contract.

## Out Of Scope

- Changes to sidebar visual structure, RBAC, audit data retention, or backend agent execution semantics.
- Persistent server-side answer feedback.
- Public sharing links or exposing a session to another user.

## Layout

- `ConversationTopBar` is rendered once by the agent workspace layout, above the route content scroll region.
- Its 56px header always renders `企业智助` and the account menu.
- Landing and session pages render below the fixed header; session content cannot mount its own top bar.
- Session transcript scrolls independently below the header. The continuation composer remains docked in the session content area.
- Mobile retains the existing sidebar Drawer. The top bar remains visible and accommodates the mobile navigation trigger.

## Answer Actions

Terminal answers with non-empty text render a 20-24px outlined icon toolbar in this order: copy, read aloud, regenerate, like, dislike, share.

- Icons use one professional rounded-line visual system, muted gray-blue default color, subtle hover/focus surface, tooltips, and complete accessible names.
- Copy writes the answer text to the clipboard and announces success or a meaningful failure.
- Read aloud retains the existing browser-speech ownership model and presents as a matching icon action.
- Regenerate creates a new run for the same session and original goal, with fixed `mode: "quick"`; it disables while its request is pending, leaves existing turns intact, and refreshes the session after success.
- Like and dislike are mutually exclusive. Their state is stored in `localStorage` by run ID, restored after reload, and never sent to the backend.
- Share uses `navigator.share` with the answer and current session URL when supported. Otherwise it copies the current session URL. Both paths announce completion or failure. No share action exposes data outside what the user explicitly shares from their browser.

## Performance And Data Flow

- The authenticated workspace shell remains mounted while client-side navigation switches child route content.
- Sidebar session links prefetch their destinations on visibility, hover, and keyboard focus using Next navigation prefetching.
- A session-view cache retains the most recent successful session view by session ID. Navigation may render cached content immediately, then performs a background revalidation.
- Cache entries are invalidated after creating a run or when the relevant session data changes. Failed refreshes never replace previously rendered cached content.
- Session, runs, and current-user requests begin concurrently where their results are independent.
- Per-run events and steps remain independently fault-tolerant, but are fetched through a bounded-concurrency queue to prevent unbounded browser and backend requests for long session histories.
- Route changes abort obsolete pending loads. Only the active request generation can update React state.
- A content skeleton is rendered while no cached session exists. Cached session content stays visible during background refresh.

## Failure Handling

- Auth, session, runs, events, and steps preserve existing permission and partial-data warnings.
- Clipboard, Web Share, browser speech, storage access, malformed URLs, and aborted requests fail without crashing the conversation view.
- Storage access is guarded for unavailable or quota-restricted browser environments.
- Regenerate failures leave the existing answer and input usable, and expose an inline error.

## Testing

- Landing and session pages render exactly one top-bar product heading, never a session title or prompt.
- Answer toolbar exposes the six action names, renders only for terminal non-empty answers, and preserves speech behavior.
- Copy, share fallback, feedback exclusivity/persistence, and regenerate pending/success/failure behavior are tested.
- Session-view cache returns cached data for immediate display, revalidates correctly, and never overwrites richer current data after a failed or aborted refresh.
- Loader concurrency never exceeds its configured limit; a failure in one run's steps/events remains a warning rather than failing the session.
- Sidebar session links invoke prefetch on hover/focus/visibility.
- Existing frontend tests and production build pass.
