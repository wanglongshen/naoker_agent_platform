# GPT-Style Right Workspace And Browser Voice

## Status

Approved incremental design for `C:\01_agent_loop`. This supersedes only the right-side chat workspace portions of the prior enterprise visual specification. It does not redesign the existing left navigation.

## Scope

### In Scope

- Right-side chat landing workspace.
- Right-side conversation workspace.
- Lightweight ChatGPT-style top navigation bar.
- Central welcome and composer presentation.
- Removing visible quick/expert mode distinction.
- Browser speech-to-text input.
- Browser speech synthesis for completed answers.
- Desktop/mobile/reduced-motion/accessibility behavior for the above.

### Explicitly Out Of Scope

- Any structural, visual, routing, permission, or behavior change to the existing left sidebar.
- Changing session history, governance navigation, user/role links, account controls, or sidebar permission gates.
- Audio recording upload, backend speech storage, external STT/TTS provider integration, real-time voice conversation, automatic send on recognition, or background microphone use.
- Governance, RBAC, audit, user management, role management, login, and backend Agent execution changes.

## Confirmed Product Decisions

- The existing left navigation remains exactly as it is in the running system.
- Only the right workspace changes.
- Right top bar displays `企业智助` only. Do not render a chevron until there is a real product menu.
- Remove the `组织私有空间` pill from the right top bar.
- Welcome headline: `今天有什么想一起完成？`.
- Welcome supporting text: `在企业智助中提问、写作、分析与协作`.
- Remove all visible `快速模式`, `专家模式`, `深度思考`, and `智能搜索` choices from landing and conversation composers.
- API compatibility is retained by submitting the existing fixed default `mode: "quick"`; the user cannot select it.
- Composer contains attachment, speech input, optional more-input control only if it has a real behavior, and send.
- Speech input is manual click-to-start, live transcribes into the composer, and never auto-sends.
- 企业智助后端不接收、保存、转发或持久化音频。浏览器或操作系统可能使用其配置的语音服务处理麦克风音频；该处理不由企业智助控制。
- Completed answers expose browser text-to-speech playback and stop control, in addition to existing copy action.
- Speech playback never appears in the landing welcome area without a real answer.

## Right Workspace Layout

### Top Bar

Desktop right workspace top bar:

```text
企业智助
```

- Height: 56px.
- White surface with a restrained bottom border.
- Aligns to the right workspace, never overlays or changes the sidebar.
- `企业智助` is a non-interactive heading. No empty button, chevron, or placeholder menu is rendered.
- On mobile, the existing mobile navigation trigger remains at the left of this top bar. The sidebar Drawer behavior is unchanged.

### Landing Workspace

- White main canvas, centered welcome group, and a maximum content width of 720px.
- The welcome group is vertically optically centered above the composer, but must remain reachable on short screens.
- No oversized brand mark, mode chips, feature cards, suggested prompt cards, or simulated answer content.
- Composer begins approximately 32-40px below supporting text.
- Keyboard hint below Composer: `Enter 发送 · Shift + Enter 换行`.
- Existing error alert remains directly below Composer and does not shift the sidebar.

### Conversation Workspace

- Same 56px top bar, showing the session title instead of `企业智助` when a conversation is open.
- Conversation transcript remains in current right-side scroll boundary.
- Composer remains docked at bottom of the right workspace.
- No visible quick/expert mode status in conversation header or composer.
- Persisted historical run mode may remain in diagnostics/audit only; it is not shown in ordinary user chat.

## Composer Design

### Visual Structure

```text
┌─────────────────────────────────────────────────────┐
│ 问问题、分析材料或开始创作…                           │
│                                                     │
│ [附件] [语音输入 / 正在聆听…]              [发送 ↑] │
└─────────────────────────────────────────────────────┘
Enter 发送 · Shift + Enter 换行
```

- Maximum width: 720px.
- Warm white surface, 1px subtle warm border, 18-22px radius, subtle shadow.
- No visible mode control or hidden mode form input exposed to users.
- Attachment control retains current upload behavior and inline chips.
- Send is disabled when text is blank, submission is running, or an upload state blocks submission.
- The existing `mode` internal state and `AgentModeControls` are removed from ChatComposer.
- ChatComposer always sends `mode: "quick"` for backward-compatible API contracts.
- Every ordinary-chat create-run and continuation-run path submits fixed `mode: "quick"`, including a conversation created after browser reload. Existing persisted Runs retain their historical mode for audit/diagnostics only.
- No ordinary-chat visible, accessible, tooltip, empty-state, error, loading, retry, or status surface may display `快速模式`, `专家模式`, `深度思考`, or `智能搜索`.

## Speech-To-Text Input

### Browser APIs

Use the browser Web Speech Recognition API only:

```ts
type SpeechRecognitionConstructor = new () => SpeechRecognition;
const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
```

Add local TypeScript declarations rather than adding a dependency. The declaration contains the complete event contract used by the implementation:

```ts
interface SpeechRecognitionAlternative {
  transcript: string;
  confidence: number;
}

interface SpeechRecognitionResult {
  isFinal: boolean;
  length: number;
  [index: number]: SpeechRecognitionAlternative;
}

interface SpeechRecognitionEvent extends Event {
  resultIndex: number;
  results: { length: number; [index: number]: SpeechRecognitionResult };
}

interface SpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
}

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  }
}

```

### States

| State | Button label | Behavior |
|---|---|---|
| Unsupported | `语音输入不可用` | Disabled; tooltip explains browser support is required. |
| Idle | `语音输入` | Click requests/starts browser recognition. |
| Listening | `正在聆听…` | Animated microphone indicator; click stops recognition. |
| Permission denied/error | `语音输入` | Stop state, show inline `role="alert"` message. |
| Final result | `语音输入` | Append final transcript to existing composer text with a space only when both sides are non-empty. |

### Recognition Configuration

- `lang = "zh-CN"`.
- `continuous = false`.
- `interimResults = true`.
- Interim text appears in a visually distinct transient state inside the composer, but is not part of the controlled textarea value, is never submitted, and is cleared on final result, error, stop, or end.
- For each `onresult`, iterate from `event.resultIndex` through `event.results.length - 1`. Concatenate only non-empty final segments from that event. Maintain a `Set<string>` of final segment keys for the active recognition generation. Each key is `${generation}:${resultIndex}:${finalTranscript}`. This ignores repeated callbacks for one result while preserving intentionally repeated identical phrases at different result indexes.
- Append final speech text to the then-current controlled textarea value, never to a stale closure. Preserve user edits made while listening. If both current text and final transcript are non-empty and current text does not end in whitespace, insert one ASCII space before final transcript; otherwise append directly. Ignore empty final text.
- Starting recognition increments a generation ID. Every `onresult`, `onerror`, and `onend` handler verifies its generation still matches; callbacks from a stopped/old recognition instance make no state change.
- Recognition is stopped and detached when the Composer unmounts, disables, submits, or the user clicks stop. `stop()` is used for deliberate end; `abort()` is used on unmount. All handlers are nulled before replacing an instance.
- The recognizer is created only after a user activation click.
- No recognition text is sent until the user presses send.

### Privacy Copy

The speech-input button has `aria-label="语音输入"` in idle state and `aria-label="停止语音输入"` while listening. It uses `aria-pressed="false"` idle and `aria-pressed="true"` listening. A short tooltip or assistive description says:

`语音由当前浏览器或系统语音服务实时转写；企业智助不会接收或保存音频。`

Do not add an always-visible privacy badge to the page.

## Answer Speech Synthesis

### Availability

- Render only for a non-empty final/historical answer.
- Do not render while a final answer is actively character-streaming.
- Use `window.speechSynthesis` and `SpeechSynthesisUtterance`; no backend TTS.
- Use `lang = "zh-CN"`.

### UI States

| State | Control text | Behavior |
|---|---|---|
| Idle | `朗读回答` | Begins speech of the complete rendered answer source text. |
| Speaking | `停止朗读` | Cancels current utterance. |
| End/error | `朗读回答` | Returns to idle. |
| Unsupported | no control | Do not render a broken control. |

- Speech control sits beside the existing copy action beneath a completed answer.
- Use a compact outlined button with an audio icon. Do not show simulated waveform or a playback panel.
- Starting a second answer cancels any currently speaking answer before beginning the new one.
- Speech ownership is centralized in one module-level browser speech controller. It stores `{ ownerId, utterance, onIdle }`; `speak(ownerId, text, onIdle)` first invokes the prior owner callback, then calls `speechSynthesis.cancel()` before assigning the new owner and utterance. This explicitly returns the displaced answer control to `朗读回答`. `stop(ownerId)` cancels only if its owner ID is current and invokes its `onIdle`. `onend`/`onerror` update React state only after verifying owner ID and utterance identity still match, then invoke the current `onIdle`.
- Unmounting an answer component calls `stop(ownerId)`; it cannot cancel a newer answer owned by another mounted control.
- Reduced-motion preference does not disable speech; it only disables decorative microphone animation.

## Accessibility

- Right workspace top bar has one `h1`: landing uses `企业智助`; session page uses session title.
- Composer textarea maintains existing Enter/Shift+Enter/IME semantics.
- Mic button communicates pressed/listening state using `aria-pressed`.
- Recognition status is announced with a short `aria-live="polite"` status node: `正在聆听` / `语音已转写` / meaningful error.
- Interim transcript is not repeatedly announced character by character.
- Speech playback control has accessible names `朗读回答` / `停止朗读`.
- Mic help and error messages are connected through `aria-describedby`; focus remains on the mic after a deliberate stop/error and moves nowhere automatically.
- On narrow icon-only presentation, the mic remains accessible as `语音输入` or `停止语音输入`.
- All controls retain visible keyboard focus.
- Speech features must degrade silently and correctly in browsers without support.

## Responsive Behavior

- Desktop: right workspace remains independent of unchanged sidebar.
- Below 768px: existing sidebar Drawer stays unchanged; right top bar includes the existing trigger and title.
- Composer uses 12-16px page padding, full available width, and safe-area bottom inset.
- Mic label may reduce to icon-only at 375px and below, but its accessible label remains complete.
- Voice error and interim transcript wrap without pushing send offscreen.
- At viewport heights below 680px, landing content uses `justify-content: flex-start`, `padding-top: max(48px, env(safe-area-inset-top))`, and the right workspace scrolls vertically. It must not vertically crop welcome text, interim transcription, voice error, Composer, send button, or keyboard hint.
- When a mobile virtual keyboard reduces the visual viewport, the focused Composer uses `scrollIntoView({ block: "nearest" })`; the send button, microphone button, interim text, and inline voice error remain visible and operable.

## Testing

### Unit/Component Tests

- ChatComposer has no `AgentModeControls` and submits exactly `mode: "quick"`.
- ChatComposer has no quick/expert/deep-thinking/search visible text.
- Every ordinary-chat create/continue code path uses fixed `mode: "quick"`, and ordinary-chat headers/retries/errors expose no historical mode terminology.
- Landing renders the exact new headline/supporting copy and right top bar.
- Session renders title inside top-bar `h1` and does not show mode text.
- Speech unsupported state renders disabled mic control and no recognizer instance.
- Speech recognition click sets listening state and configuration (`zh-CN`, non-continuous, interim results).
- Interim result renders transient text without changing submitted source value.
- Multiple final result segments and repeated browser result callbacks append each unique `generation:resultIndex:transcript` segment exactly once, use the specified whitespace behavior, preserve manual edits made while listening, and preserve intentionally repeated phrases emitted at different result indexes.
- Recognition error/end/unmount cancels state and recognizer safely; stale callbacks after replacement do nothing.
- Submit while listening stops recognition and sends only final textarea content.
- Completed answer renders speech control only when `speechSynthesis` is available.
- Speech start configures a `zh-CN` utterance from the complete answer text; stop invokes cancel; end/error restores idle state. Starting another answer must reset the previously speaking control to `朗读回答` before the new control enters `停止朗读`.
- No speech control exists while active answer animation is running.
- Assert `aria-pressed`, live status text, `aria-describedby`, narrow icon-only accessible names, focus after stop/error, speech start/stop labels, and no repeated interim live announcements.

### Browser Acceptance

Use Microsoft Edge with an isolated profile and synthetic content:

1. Verify unchanged sidebar before/after feature at desktop and mobile: width/position, item order/labels, selected session behavior, all links, permission-gated entries, account controls, Drawer open/close/Escape/focus return, and all existing routes. Review must show no sidebar component, sidebar CSS, route, or permission-gate change in this feature.
2. Verify right top bar, landing copy, no visible modes, and centered Composer at 1440x900, 390x844, and 320x568.
3. Allow microphone access; dictate Chinese synthetic text; verify it appears in composer and does not auto-send.
4. Deny microphone access; verify recoverable inline error and composer remains usable.
5. Send synthetic answer; verify completed answer has copy and speech control.
6. Start and stop answer speech; switch answers and verify prior speech cancels.
7. Verify unsupported behavior by disabling/mocking APIs in an automated test.
8. At 320x568, 390x844, 200% zoom, and mobile virtual keyboard: verify focused Composer, send, mic, interim text, and voice error remain visible and operable.
9. Check keyboard focus, Enter/Shift+Enter, IME, reduced motion, and a manual screen-reader checklist for recognition start, stop, denial, final transcription, speech start, answer replacement, and speech failure.

## Rollback

- Remove `SpeechInputButton`/speech hook and `AnswerSpeechButton`/speech hook.
- ChatComposer continues submitting the fixed default `mode: "quick"` without a mode UI.
- Remove right workspace CSS/top bar changes without changing sidebar, session, run, or backend contracts.
- No migration, persisted audio, or backend data requires rollback.

## Acceptance Criteria

1. Existing left navigation remains functionally and visually unchanged.
2. Right chat workspace resembles a professional ChatGPT-style workspace with a lightweight top bar and focused central Composer.
3. `组织私有空间` is absent from the right workspace.
4. Welcome copy exactly says `在企业智助中提问、写作、分析与协作`.
5. No quick/expert/deep-thinking/search mode distinctions are visible in ordinary chat.
6. Existing API remains compatible through fixed `mode: "quick"` submission.
7. Speech input uses browser/OS speech recognition, is manual, editable, non-persistent within enterprise services, and non-auto-send.
8. Completed answers support browser/OS Chinese speech playback and stop; enterprise services do not receive or persist audio.
9. Unsupported speech APIs degrade safely and accessibly.
10. Existing sidebar, streaming, Markdown safety, RBAC, governance, and audit functionality remain unchanged.
