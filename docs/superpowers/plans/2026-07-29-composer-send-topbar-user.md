# Composer Send, Top Bar User, And Voice-Prune Plan

## Status

Approved incremental development plan. No code is modified by this document.

## Scope

Three constrained right-workspace changes plus one top-bar addition. The existing left sidebar and all governance/RBAC paths are not modified.

1. Remove the visible long voice-privacy paragraph from the Composer.
2. Redesign the send button as a warm-amber 40px circle with a white upward arrow only.
3. Move all tool controls (attachment → voice → send) to the right side of the Composer toolbar.
4. Add current user avatar and account dropdown to the rightmost position of the right workspace top bar.

## Target Files

| File | Change |
|---|---|
| `frontend/src/components/agent/chat-composer.tsx` | Remove speech-input-help sr-only span and speech-input-help unsupported visible paragraph; keep aria-describedby pointing to speech-input-status only; reorder toolbar to float-right: attachment → voice → send; replace current send button with circle-arrow. |
| `frontend/src/components/agent/chat-composer.test.tsx` | Update assertions: no speech-input-help id; send button has accessible name "发送消息" but no visible text `发送消息`; toolbar control order verified by DOM position. |
| `frontend/src/components/layout/conversation-top-bar.tsx` | Accept `currentUser: CurrentUser` prop; render avatar + display-name button with Ant Dropdown (username, logout) at right. |
| `frontend/src/app/(agent)/agent/page.tsx` | Pass `currentUser` to `ConversationTopBar`. |
| `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx` | Pass `currentUser` to `ConversationTopBar`. |
| `frontend/src/app/(agent)/agent/agent-page.test.tsx` | Assert top bar has avatar + display name. |
| `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx` | Assert session top bar has avatar + display name. |
| `frontend/src/app/agent-globals.css` | Replace `.composer-submit` blue gradient with circle-amber; add `.chat-composer-toolbar-right`, `.composer-send-circle`, `.top-bar-user-btn`, `.top-bar-avatar`, `.top-bar-user-name`; narrow-screen avatar-only behavior. |

## Detail

### 1. Voice-privacy paragraph removal

- Delete the `sr-only` `<span id="speech-input-help">` block entirely (lines 138-140). The mic button `aria-describedby` attribute changes from `"speech-input-help speech-input-status"` to `"speech-input-status"` only.
- Change the visible unsupported fallback paragraph: delete the second `语音由当前浏览器或系统语音服务实时转写…` sentence; keep only `语音输入需要浏览器语音支持。`. The `#speech-input-help` id stays on this reduced visible text.
- The `speech-input-status` live region and all error `role="alert"` messages remain unchanged.

### 2. Send button redesign

Visual contract:

- 40px × 40px warm-amber `#D96313` circle.
- Centered white up-arrow (Unicode `↑` or inline SVG).
- Disabled: `#E6DDD6` background, `#B8AFA8` arrow.
- Hover: `#B94F0C` background, subtle `box-shadow`.
- Focus: visible focus ring using existing `:focus-visible` provision.
- Loading/uploading: same size, amber background, arrow replaced by a small Ant `LoadingOutlined` spinner in white.

Implementation:

```tsx
<button
  type="submit"
  className="composer-send-circle"
  aria-label="发送消息"
  disabled={disabled || uploading || !value.trim()}
>
  {uploading ? <LoadingOutlined /> : <SendArrow />}
</button>
```

`SendArrow` is a simple inline SVG or the `↑` character. No `submitLabel` text is rendered inside the visual button — only in `aria-label`.

### 3. Toolbar right-side layout

Current state places all controls in one `chat-composer-actions` div. The refreshed layout uses a simpler structure:

```tsx
<div className="chat-composer-toolbar">
  {/* empty left side for future growth or keyboard hint */}
  <div className="chat-composer-toolbar-right">
    <AttachmentInput ... />
    {/* voice button */}
    <button className="composer-send-circle" ... />
  </div>
</div>
```

CSS:

```css
.chat-composer-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.chat-composer-toolbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}
```

### 4. Top-bar user area

The `ConversationTopBar` currently renders a single `<h1>`. It will now render:

```tsx
<header className="conversation-top-bar">
  <h1>{title}</h1>
  {currentUser && (
    <Dropdown menu={{ items: [{ key: 'account', label: `@${username}`, disabled: true }, { key: 'logout', label: '退出登录', onClick: handleLogout, icon: <LogoutOutlined /> }] }} trigger={['click']}>
      <button className="top-bar-user-btn">
        <Avatar size={28} icon={<UserOutlined />}>{displayName?.[0]}</Avatar>
        <span className="top-bar-user-name">{displayName}</span>
      </button>
    </Dropdown>
  )}
</header>
```

The display name hides at `max-width: 480px`, leaving only the avatar. The accessible label remains `{displayName} 账户菜单`.

CSS:

```css
.top-bar-user-btn {
  display: flex; align-items: center; gap: 8px; background: none; border: none;
  cursor: pointer; padding: 4px 8px; border-radius: 8px;
  margin-left: auto; margin-right: 4px;
}
.top-bar-user-btn:hover { background: var(--color-bg-subtle); }
.top-bar-user-name { font-size: 13px; color: var(--color-text-secondary); }
@media (max-width: 480px) { .top-bar-user-name { display: none; } }
```

Logout calls `api('/api/auth/logout', { method: 'POST' })` then `router.push('/login')`.

### 5. Composer send circle CSS

```css
.composer-send-circle {
  width: 40px; height: 40px;
  border-radius: 50%;
  border: none;
  display: grid; place-items: center;
  background: var(--color-primary); /* #D96313 */
  color: #fff;
  cursor: pointer;
  transition: background .15s;
}
.composer-send-circle:hover { background: var(--color-primary-hover); box-shadow: 0 4px 14px rgba(217,99,19,.35); }
.composer-send-circle:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }
.composer-send-circle:disabled { background: #E6DDD6; color: #B8AFA8; cursor: not-allowed; box-shadow: none; }
```

Remove the existing `.composer-submit` blue gradient blocks.

## Verification

- Full frontend test suite pass.
- Production build pass.
- Composer and top bar regression tests updated.
- No sidebar or governance file modifications.
