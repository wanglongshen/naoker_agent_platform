# GPT-Style Right Workspace And Browser Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade only the right-side chat workspace into a focused ChatGPT-style interface, remove visible mode selection while retaining API compatibility, and add accessible browser speech input and completed-answer narration.

**Architecture:** Keep the existing sidebar, routes, RBAC, run APIs, and session history untouched. Refactor `ChatComposer` into a controlled text surface with a fixed internal `quick` mode and add a generation-guarded `useSpeechRecognition` hook. Add a module-level speech synthesis coordinator so only one completed answer can be read at a time without stale controls.

**Tech Stack:** Next.js 16, React 19, TypeScript, Vitest, React Testing Library, browser Web Speech Recognition, browser SpeechSynthesis.

## Global Constraints

- Modify only right-workspace, composer, answer-action, and their directly related test/style/type files; do not modify any sidebar component, sidebar CSS, route, account control, session history, governance, RBAC, audit, or backend Agent execution file.
- The existing left navigation remains functionally and visually unchanged.
- Right top bar displays `企业智助` only; render no empty chevron, menu, or `组织私有空间` pill.
- Landing copy is exactly `今天有什么想一起完成？` and `在企业智助中提问、写作、分析与协作`.
- Ordinary chat must not visibly or accessibly expose `快速模式`, `专家模式`, `深度思考`, or `智能搜索`.
- All ordinary create/continue chat paths submit fixed `mode: "quick"`; preserve backend API and persisted historical-mode compatibility.
- Speech recognition is browser/OS service based. 企业智助 backend must not receive, save, forward, or persist audio.
- Speech input is manual, editable, non-auto-send, and never background listening.
- Completed answers support browser/OS Chinese narration and stop; active streaming answers do not render speech controls.
- Raw Markdown HTML remains disabled; do not add `rehype-raw`.
- Preserve existing Enter/Shift+Enter/IME, attachment, streaming, reconnect, historical-answer, RBAC, and Markdown behavior.
- Use Microsoft Edge for browser acceptance, synthetic non-private content only, and do not use Quark.
- `C:\01_agent_loop` has no Git metadata. Do not run commit commands; write RED/GREEN evidence to `.superpowers/sdd/gpt-workspace-voice-task-N-report.md`.

---

## File Structure And Responsibilities

- Create `frontend/src/types/web-speech.d.ts`: local type declarations for `SpeechRecognition`, its event results, and `Window.SpeechRecognition` / `Window.webkitSpeechRecognition`.
- Create `frontend/src/hooks/use-speech-recognition.ts`: browser capability, generation-safe recognition lifecycle, interim/final state, dedupe, errors, and cleanup.
- Create `frontend/src/hooks/use-speech-recognition.test.ts`: hook lifecycle/race tests using a fake recognition instance.
- Create `frontend/src/lib/browser-speech.ts`: module-level answer narration coordinator with owner identity and stale callback guards.
- Create `frontend/src/lib/browser-speech.test.ts`: coordinator ownership, replacement, stop, stale callback, and availability tests.
- Create `frontend/src/components/agent/answer-speech-button.tsx`: answer-level browser narration UI.
- Create `frontend/src/components/agent/answer-speech-button.test.tsx`: narration control tests.
- Modify `frontend/src/components/agent/chat-composer.tsx`: fixed quick submission, controlled text, speech input, no visible modes.
- Modify `frontend/src/components/agent/chat-composer.test.tsx`: remove mode-choice expectations and add mode/speech tests.
- Modify `frontend/src/components/layout/conversation-top-bar.tsx`: semantic right workspace top bar with no chevron/menu placeholder.
- Modify `frontend/src/app/(agent)/agent/page.tsx`: right-side landing copy/top bar layout only.
- Modify `frontend/src/app/(agent)/agent/sessions/[sessionId]/page.tsx`: conversation top bar only; no sidebar changes.
- Modify `frontend/src/components/agent/answer-actions.tsx`: compose copy and answer speech controls.
- Modify `frontend/src/components/agent/final-answer-panel.tsx`: pass completed sanitized visible answer source to actions only when not streaming.
- Modify `frontend/src/components/agent/agent-streaming.test.tsx`: top bar, no mode terminology, and speech-control rendering tests.
- Modify `frontend/src/app/agent-globals.css`: right-workspace top bar, landing, composer voice states, interim/error, and answer speech styles only.

---

### Task 1: Fixed-Mode Right Workspace And ChatGPT-Style Top Bar

**Files:**
- Modify: `C:\01_agent_loop\frontend\src\components\agent\chat-composer.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\chat-composer.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\layout\conversation-top-bar.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\sessions\[sessionId]\page.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\agent-page.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\(agent)\agent\sessions\[sessionId]\page.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\agent-streaming.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\agent-globals.css`

**Interfaces:**
- `ChatComposerProps.onSubmit` remains `(input: { goal: string; mode: AgentMode; attachmentIds: string[] }) => Promise<void> | void`.
- ChatComposer always calls `onSubmit({ goal, mode: "quick", attachmentIds })`.
- `ConversationTopBar({ title }: { title: string })` renders one `<header>` containing `<h1>{title}</h1>` and no chevron/menu.

- [ ] **Step 1: Replace mode-choice tests with fixed-mode contract tests**

In `chat-composer.test.tsx`, remove selected-mode and mode-control assertions. Add:

```tsx
it("submits fixed quick mode without exposing a mode control", async () => {
  const user = userEvent.setup();
  renderComposer();

  expect(screen.queryByText(/快速模式|专家模式|深度思考|智能搜索/)).not.toBeInTheDocument();
  expect(screen.queryByRole("group", { name: /模式/ })).not.toBeInTheDocument();

  await user.type(screen.getByPlaceholderText("输入消息"), "整理会议纪要{enter}");
  expect(mockOnSubmit).toHaveBeenCalledWith({
    goal: "整理会议纪要",
    mode: "quick",
    attachmentIds: [],
  });
});
```

In landing/session tests add:

```tsx
expect(screen.getByRole("heading", { level: 1, name: "企业智助" })).toBeVisible();
expect(screen.getByRole("heading", { level: 1, name: "今天有什么想一起完成？" })).toBeVisible();
expect(screen.getByText("在企业智助中提问、写作、分析与协作")).toBeVisible();
expect(screen.queryByText("组织私有空间")).not.toBeInTheDocument();
expect(screen.queryByText(/快速模式|专家模式|深度思考|智能搜索/)).not.toBeInTheDocument();
```

- [ ] **Step 2: Run selected tests and verify RED**

Run from `C:\01_agent_loop\frontend`:

```powershell
npm test -- --run src/components/agent/chat-composer.test.tsx "src/app/(agent)/agent/agent-page.test.tsx" "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx" src/components/agent/agent-streaming.test.tsx
```

Expected: tests fail because `AgentModeControls` still renders, landing top bar does not exist, and current text/layout differs.

- [ ] **Step 3: Remove visible mode selection while preserving fixed API compatibility**

In `chat-composer.tsx`, remove imports and state for `AgentModeControls` and `useState<AgentMode>`. Replace submission payload with:

```tsx
await onSubmit({
  goal,
  mode: "quick",
  attachmentIds,
});
```

Remove the toolbar mode control completely. Do not add a hidden input for `mode`; the component passes the fixed value in JavaScript.

Update page callback parameter types only as needed to retain the current API payload contract. Do not change `AgentMode` in persisted types or backend schemas.

- [ ] **Step 4: Implement the right-only top bar and landing copy**

Replace the stub top bar with:

```tsx
export default function ConversationTopBar({ title }: { title: string }) {
  return (
    <header className="conversation-top-bar">
      <h1>{title}</h1>
    </header>
  );
}
```

On landing, render this top bar with `title="企业智助"`, then render exactly:

```tsx
<section className="right-workspace-landing" aria-labelledby="landing-heading">
  <div className="right-workspace-welcome">
    <h2 id="landing-heading">今天有什么想一起完成？</h2>
    <p>在企业智助中提问、写作、分析与协作</p>
  </div>
  <ChatComposer placeholder="问问题、分析材料或开始创作…" submitLabel="发送消息" onSubmit={handleSubmit} autoFocus />
</section>
```

On session detail, replace the existing conversation-header title `<h1>` with `ConversationTopBar` using the session title, so each right workspace still has exactly one top-bar `<h1>`. Remove ordinary-chat mode labels from the header. Do not import, edit, or restyle the sidebar.

- [ ] **Step 5: Add right-workspace styles without touching sidebar selectors**

Add only new right-workspace selectors:

```css
.conversation-top-bar {
  min-height: 56px;
  display: flex;
  align-items: center;
  padding: 0 28px;
  background: var(--color-bg-surface);
  border-bottom: 1px solid var(--color-border);
}

.conversation-top-bar h1 {
  margin: 0;
  font-size: 17px;
  font-weight: 650;
  color: var(--color-text-primary);
}

.right-workspace-landing {
  min-height: calc(100dvh - 56px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 16px calc(32px + env(safe-area-inset-bottom));
}

.right-workspace-welcome { text-align: center; }
.right-workspace-welcome h2 { margin: 0; font-size: clamp(26px, 3vw, 34px); }
.right-workspace-welcome p { margin: 10px 0 0; color: var(--color-text-secondary); }
.right-workspace-landing .chat-composer { width: min(720px, 100%); margin-top: 36px; }

@media (max-height: 680px) {
  .right-workspace-landing {
    min-height: auto;
    justify-content: flex-start;
    padding-top: max(48px, env(safe-area-inset-top));
    overflow-y: auto;
  }
}
```

Do not modify `.enterprise-sidebar`, `.app-sidebar`, sidebar Drawer styles, or responsive sidebar rules.

- [ ] **Step 6: Run selected tests and verify GREEN**

Run:

```powershell
npm test -- --run src/components/agent/chat-composer.test.tsx "src/app/(agent)/agent/agent-page.test.tsx" "src/app/(agent)/agent/sessions/[sessionId]/page.test.tsx" src/components/agent/agent-streaming.test.tsx
```

Expected: all selected tests pass.

- [ ] **Step 7: Record Task 1 evidence**

Write exact RED/GREEN commands/output, changed files, and sidebar non-modification proof to `C:\01_agent_loop\.superpowers\sdd\gpt-workspace-voice-task-1-report.md`.

### Task 2: Generation-Safe Browser Speech Recognition

**Files:**
- Create: `C:\01_agent_loop\frontend\src\types\web-speech.d.ts`
- Create: `C:\01_agent_loop\frontend\src\hooks\use-speech-recognition.ts`
- Create: `C:\01_agent_loop\frontend\src\hooks\use-speech-recognition.test.ts`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\chat-composer.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\chat-composer.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\agent-globals.css`

**Interfaces:**

```ts
export type SpeechRecognitionState = "unsupported" | "idle" | "listening" | "error";

export type UseSpeechRecognitionResult = {
  state: SpeechRecognitionState;
  interimText: string;
  message: string | null;
  supported: boolean;
  start: () => void;
  stop: () => void;
  dispose: () => void;
};

export function useSpeechRecognition(options: {
  onFinalTranscript: (append: (currentText: string) => string) => void;
  disabled: boolean;
}): UseSpeechRecognitionResult;
```

- [ ] **Step 1: Write hook tests with a fake recognition constructor**

In `use-speech-recognition.test.ts`, define a fake class with `start`, `stop`, `abort`, and manual event emitters. Add a `Window` mock constructor before each test.

Test unsupported browser:

```tsx
delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
delete (window as Window & { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;
const { result } = renderHook(() => useSpeechRecognition({ onFinalTranscript, disabled: false }));
expect(result.current.state).toBe("unsupported");
expect(result.current.supported).toBe(false);
```

Test start configuration:

```tsx
act(() => result.current.start());
expect(fake.lang).toBe("zh-CN");
expect(fake.continuous).toBe(false);
expect(fake.interimResults).toBe(true);
expect(result.current.state).toBe("listening");
```

Test final appending/deduplication:

```tsx
fake.emitResult({ resultIndex: 0, results: [finalResult("第一句"), finalResult("第一句")] });
expect(append).toHaveBeenCalledTimes(1);
expect(append.mock.calls[0][0]("已有内容")).toBe("已有内容 第一句");

fake.emitResult({ resultIndex: 1, results: [finalResult("第一句"), finalResult("第一句")] });
expect(append).toHaveBeenCalledTimes(2);
```

Test late result after `stop`, after unmount, and after a second `start` makes no state/appender changes. Test error mapping for `not-allowed`, `service-not-allowed`, `audio-capture`, `network`, and `no-speech`, with the message preserved after the following `end` event.

- [ ] **Step 2: Run hook test and verify RED**

Run:

```powershell
npm test -- --run src/hooks/use-speech-recognition.test.ts
```

Expected: module missing and all hook tests fail.

- [ ] **Step 3: Add complete local browser speech types**

Create `web-speech.d.ts` with:

```ts
export {};

declare global {
  interface SpeechRecognitionAlternative { transcript: string; confidence: number; }
  interface SpeechRecognitionResult { isFinal: boolean; length: number; [index: number]: SpeechRecognitionAlternative; }
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
  type SpeechRecognitionConstructor = new () => SpeechRecognition;
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  }
}
```

- [ ] **Step 4: Implement generation-safe `useSpeechRecognition`**

Use refs for recognition instance, generation, and final-key set. The critical cleanup helper is:

```ts
function invalidate(abort: boolean) {
  generationRef.current += 1;
  const recognition = recognitionRef.current;
  recognitionRef.current = null;
  if (recognition) {
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.onend = null;
    if (abort) recognition.abort();
    else recognition.stop();
  }
  finalKeysRef.current.clear();
  setInterimText("");
  setState("idle");
}
```

Each handler captures `const generation = generationRef.current` and begins with:

```ts
if (generation !== generationRef.current || recognitionRef.current !== recognition) return;
```

For a final segment at `index`, compute `const key = `${generation}:${index}:${transcript}`;` and ignore it only when that exact key is already in the active set.

Use these Chinese messages:

```ts
const messages: Record<string, string> = {
  "not-allowed": "浏览器未授予麦克风权限。",
  "service-not-allowed": "浏览器语音服务不可用。",
  "audio-capture": "未检测到可用麦克风。",
  network: "语音服务连接失败，请稍后重试。",
  "no-speech": "未识别到语音，请再试一次。",
};
```

Capability is supported only if `window.isSecureContext !== false` and a constructor exists. Catch synchronous construction/start errors and map them to a recoverable error message. Add `visibilitychange` and `pagehide` listeners that invalidate active recognition using `abort()`.

- [ ] **Step 5: Integrate microphone controls into `ChatComposer`**

Make textarea value controlled:

```tsx
const [value, setValue] = useState("");
const speech = useSpeechRecognition({
  disabled: disabled || uploading,
  onFinalTranscript: (append) => setValue((current) => append(current)),
});
```

Pass `value`/`onChange` to `SubmitTextarea`, include only `value` in `FormData` replacement logic, and call `speech.stop()` before taking submit's value snapshot.

Render:

```tsx
<button
  type="button"
  className="composer-voice-button"
  aria-label={speech.state === "listening" ? "停止语音输入" : "语音输入"}
  aria-pressed={speech.state === "listening"}
  aria-describedby="speech-input-help speech-input-status"
  aria-disabled={!speech.supported}
  disabled={!speech.supported}
  onClick={speech.state === "listening" ? speech.stop : speech.start}
>
  <MicrophoneIcon />
  <span>{speech.state === "listening" ? "正在聆听…" : "语音输入"}</span>
</button>
<span id="speech-input-help" className="sr-only">语音由当前浏览器或系统语音服务实时转写；企业智助不会接收或保存音频。</span>
<span id="speech-input-status" className="sr-only" aria-live="polite">{speech.message ?? (speech.state === "listening" ? "正在聆听" : "")}</span>
{speech.interimText ? <div className="composer-speech-interim" aria-hidden="true">{speech.interimText}</div> : null}
{speech.state === "error" && speech.message ? <div className="composer-speech-error" role="alert">{speech.message}</div> : null}
```

The unsupported explanation must be rendered as visible/assistive text adjacent to the disabled control; do not rely on a disabled-button tooltip.

- [ ] **Step 6: Run hook and composer tests and verify GREEN**

Run:

```powershell
npm test -- --run src/hooks/use-speech-recognition.test.ts src/components/agent/chat-composer.test.tsx
```

Expected: all selected tests pass.

- [ ] **Step 7: Record Task 2 evidence**

Write exact RED/GREEN commands/output and browser-service privacy wording verification to `C:\01_agent_loop\.superpowers\sdd\gpt-workspace-voice-task-2-report.md`.

### Task 3: Coordinated Completed-Answer Speech Synthesis

**Files:**
- Create: `C:\01_agent_loop\frontend\src\lib\browser-speech.ts`
- Create: `C:\01_agent_loop\frontend\src\lib\browser-speech.test.ts`
- Create: `C:\01_agent_loop\frontend\src\components\agent\answer-speech-button.tsx`
- Create: `C:\01_agent_loop\frontend\src\components\agent\answer-speech-button.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\answer-actions.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\answer-actions.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\final-answer-panel.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\agent-streaming.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\app\agent-globals.css`

**Interfaces:**

```ts
export type BrowserSpeechController = {
  supported: () => boolean;
  speak: (ownerId: string, text: string, onIdle: () => void, onFailure: () => void) => boolean;
  stop: (ownerId: string) => void;
};

export const browserSpeech: BrowserSpeechController;
```

`AnswerSpeechButton({ ownerId, text }: { ownerId: string; text: string })` renders nothing when browser speech is unsupported.

- [ ] **Step 1: Write coordinator tests with fake browser speech APIs**

Test availability requires all three APIs:

```ts
expect(browserSpeech.supported()).toBe(false);
window.speechSynthesis = fakeSynthesis;
window.SpeechSynthesisUtterance = FakeUtterance;
expect(browserSpeech.supported()).toBe(true);
```

Test replacement/reset:

```ts
browserSpeech.speak("answer-a", "第一段", idleA, failA);
browserSpeech.speak("answer-b", "第二段", idleB, failB);
expect(fakeSynthesis.cancel).toHaveBeenCalledTimes(1);
expect(idleA).toHaveBeenCalledTimes(1);

firstUtterance.onend?.(new Event("end"));
expect(idleB).not.toHaveBeenCalled();
secondUtterance.onend?.(new Event("end"));
expect(idleB).toHaveBeenCalledTimes(1);
```

Test `stop("answer-a")` does not cancel `answer-b`; test `stop("answer-b")` cancels and idles `answer-b`; test `onerror` calls current failure/idle only.

- [ ] **Step 2: Run coordinator tests and verify RED**

Run:

```powershell
npm test -- --run src/lib/browser-speech.test.ts src/components/agent/answer-speech-button.test.tsx
```

Expected: modules missing and tests fail.

- [ ] **Step 3: Implement `browserSpeech` coordinator**

Use a module-level current record:

```ts
let current: {
  ownerId: string;
  utterance: SpeechSynthesisUtterance;
  onIdle: () => void;
  onFailure: () => void;
} | null = null;
```

`supported()` returns true only when `window`, `window.speechSynthesis`, and `window.SpeechSynthesisUtterance` exist.

`speak()` must:

1. Return false when unsupported or text is blank.
2. Call `current.onIdle()` before cancelling an existing current utterance.
3. Create `new SpeechSynthesisUtterance(text)` and set `lang = "zh-CN"`.
4. Assign `current` before calling `speechSynthesis.speak(utterance)`.
5. In `onend`/`onerror`, verify `current?.ownerId === ownerId && current.utterance === utterance` before changing state.
6. On current `onerror`, clear `current`, call `onFailure()`, then `onIdle()`.
7. Catch synchronous `speak()` errors, clear current, call `onFailure()` and `onIdle()`, and return false.

`stop(ownerId)` only acts on the matching owner, clears current, invokes its idle callback, then calls `speechSynthesis.cancel()`.

- [ ] **Step 4: Implement `AnswerSpeechButton`**

Use a stable owner ID derived from `run.id` in the caller. The button owns state:

```tsx
export default function AnswerSpeechButton({ ownerId, text }: Props) {
  const [speaking, setSpeaking] = useState(false);
  const [failed, setFailed] = useState(false);
  if (!browserSpeech.supported()) return null;

  function toggle() {
    if (speaking) {
      browserSpeech.stop(ownerId);
      return;
    }
    setFailed(false);
    const started = browserSpeech.speak(ownerId, text, () => setSpeaking(false), () => setFailed(true));
    setSpeaking(started);
  }

  useEffect(() => () => browserSpeech.stop(ownerId), [ownerId]);
  return (
    <div className="answer-speech-control">
      <button
        type="button"
        className="answer-speech-button"
        aria-label={speaking ? "停止朗读" : "朗读回答"}
        onClick={toggle}
      >
        <VolumeIcon aria-hidden="true" />
        <span>{speaking ? "停止朗读" : "朗读回答"}</span>
      </button>
      {failed ? <span role="status">朗读不可用，请检查浏览器语音设置。</span> : null}
    </div>
  );
}
```

Render `朗读回答` idle and `停止朗读` speaking. An action failure renders `role="status"` with `朗读不可用，请检查浏览器语音设置。`.

- [ ] **Step 5: Integrate copy plus narration only for complete answers**

Change `AnswerActions`:

```tsx
export default function AnswerActions({ ownerId, text }: { ownerId: string; text: string }) {
  return (
    <div className="answer-actions">
      <CopyAnswerButton text={text} />
      <AnswerSpeechButton ownerId={ownerId} text={text} />
    </div>
  );
}
```

Pass `ownerId={run.id}` from `FinalAnswerPanel` only when `isTerminal && answerText.trim()`. `shouldAnimate` remains the gate that prevents narration controls on active character-streamed answers.

The narration source is exactly `answerText`, which is the sanitized user-visible Markdown source currently passed to `ReactMarkdown`. Do not derive text from DOM, tool events, hidden `.sr-only` elements, links' URLs, or diagnostics. Markdown punctuation/code/table syntax is read as source in this initial browser-native implementation; do not promise semantic Markdown speech transformation.

- [ ] **Step 6: Add rendering tests**

Add tests:

```tsx
it("renders speech only for a completed non-empty answer when supported", () => {
  mockSpeechSupported();
  render(<FinalAnswerPanel run={succeededRunWithAnswer("# 标题\n内容")} />);
  expect(screen.getByRole("button", { name: "朗读回答" })).toBeVisible();
});

it("does not render speech control for active streaming answer", () => {
  mockSpeechSupported();
  render(<FinalAnswerPanel run={runningRun} streamingAnswer="正在生成" answerStreamId="s1" />);
  expect(screen.queryByRole("button", { name: /朗读回答|停止朗读/ })).not.toBeInTheDocument();
});
```

Test that starting answer B resets answer A text to `朗读回答`, and unmounting answer A does not cancel active answer B.

- [ ] **Step 7: Run speech/action tests and verify GREEN**

Run:

```powershell
npm test -- --run src/lib/browser-speech.test.ts src/components/agent/answer-speech-button.test.tsx src/components/agent/answer-actions.test.tsx src/components/agent/agent-streaming.test.tsx
```

Expected: all selected tests pass.

- [ ] **Step 8: Record Task 3 evidence**

Write exact RED/GREEN commands/output, coordinator ownership verification, and unsupported behavior evidence to `C:\01_agent_loop\.superpowers\sdd\gpt-workspace-voice-task-3-report.md`.

### Task 4: Right-Only Regression And Browser Acceptance

**Files:**
- Modify: `C:\01_agent_loop\frontend\src\app\agent-globals.css`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\chat-composer.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\agent\agent-streaming.test.tsx`
- Modify: `C:\01_agent_loop\frontend\src\components\layout\conversation-top-bar.tsx` only if test-driven accessibility corrections are required
- Create: `C:\01_agent_loop\.superpowers\sdd\gpt-workspace-voice-task-4-report.md`

**Interfaces:**
- No sidebar component, sidebar stylesheet selector, route, or permission gate is modified in this task.
- Existing `AppSidebar`, `AppShell`, session history, governance, RBAC, and audit behavior is consumed as-is.

- [ ] **Step 1: Write right-only regression tests**

Add component assertions for right-only behavior. The task reviewer must verify the task changed only files listed in Tasks 1-4 and no sidebar component, sidebar CSS selector, route, account control, session-history, governance, RBAC, audit, or backend file:

```tsx
expect(screen.queryByText("组织私有空间")).not.toBeInTheDocument();
expect(screen.queryByText(/快速模式|专家模式|深度思考|智能搜索/)).not.toBeInTheDocument();
expect(screen.getByRole("button", { name: "语音输入" })).toHaveAttribute("aria-pressed", "false");
```

Add narrow-state tests by rendering the Composer with interim/error state and asserting send, mic, and textarea remain in document order. Add tests for top bar `h1` only, no button/chevron/menu placeholder.

- [ ] **Step 2: Run regression tests and verify RED**

Run:

```powershell
npm test -- --run src/components/agent/chat-composer.test.tsx src/components/agent/agent-streaming.test.tsx
```

Expected: any unimplemented visual/accessibility edge assertions fail before final CSS corrections.

- [ ] **Step 3: Complete responsive and focus CSS**

Add only selectors scoped under `.right-workspace-*`, `.conversation-top-bar`, `.chat-composer`, `.composer-voice-button`, `.composer-speech-*`, `.answer-speech-button`, and `.answer-actions`.

Required behavior:

```css
@media (max-width: 375px) {
  .composer-voice-button span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
}

@media (prefers-reduced-motion: reduce) {
  .composer-voice-button.is-listening svg { animation: none; }
}
```

Use `visualViewport` handling in `ChatComposer` only to call `textareaRef.current?.scrollIntoView({ block: "nearest" })` while focused; do not alter shell/sidebar scroll logic.

- [ ] **Step 4: Run full frontend verification**

Run:

```powershell
npm test -- --run
npm run build
```

Expected: all feature tests pass. If unrelated existing test failures remain, capture full names and stack causes, prove no new feature test is failing, and record them separately.

- [ ] **Step 5: Run Microsoft Edge acceptance with synthetic content**

Launch Edge with a clean profile. Verify and screenshot:

1. Existing sidebar is unchanged at 1440x900: item order, labels, session selection, governance links, account controls.
2. Mobile sidebar Drawer remains unchanged at 390x844: open/close/Escape/focus return.
3. Landing right workspace: top bar `企业智助`, exact welcome text, no private-space pill, no visible modes.
4. Composer at 1440x900, 390x844, 320x568, 200% zoom, and a short-height viewport: input, mic, send, and hint are reachable.
5. Grant microphone: dictate synthetic Chinese text; verify editable transcription and no automatic send.
6. Deny microphone: verify recoverable error, mic focus, and continued typing/send behavior.
7. Complete a synthetic answer: verify copy plus narration, start/stop narration, and answer replacement cancels/resets prior control.
8. Check reduced motion: listening state has no decorative animation while controls remain functional.

Do not capture actual private conversation content, credentials, or audio.

- [ ] **Step 6: Record Task 4 evidence**

Write viewport screenshots, commands/output, accessibility checks, unsupported/permission cases, unchanged-sidebar proof, residual risks, and rollback notes to `C:\01_agent_loop\.superpowers\sdd\gpt-workspace-voice-task-4-report.md`.

---

## Execution Dependencies

- Task 1 must complete and pass review before Task 2 begins.
- Task 2 and Task 3 can run in parallel after Task 1 because they touch separate functional areas except integration tests; Task 3 integration runs after Task 2 implementation is on disk.
- Task 4 begins only after Task 2 and Task 3 both pass task review.
- Every task requires independent specification-compliance and code-quality review. Fix and retest every rejected review finding before dependent work starts.

## Definition Of Done

- Left navigation, routes, permission gates, account controls, history, governance, and sidebar CSS are unchanged.
- Right landing and session workspace use a 56px `企业智助`/session-title top bar with no chevron/menu placeholder or private-space pill.
- Right landing exact supporting copy is present and all visible ordinary chat mode distinctions are absent.
- Ordinary chat still submits fixed `mode: "quick"` with no user selection.
- Speech recognition correctly handles support, browser/OS privacy messaging, permission/error states, recognition generation races, dedupe, manual edits, submit/stop/unmount/visibility cleanup, and no auto-send.
- Completed answers support coordinated Chinese browser/OS narration, replacement/reset, stop, stale callback protection, and unsupported degradation.
- All feature tests, frontend build, Edge synthetic acceptance, responsive, keyboard, IME, and reduced-motion checks pass or document unrelated existing failures with proof they are unrelated.
