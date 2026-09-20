# Zero-Jitter Streaming Markdown & Thought Narrative Rewrite

## Goal

1. **Zero-jitter streaming Markdown**: current `ProgressiveMarkdown` shows the active
   tail as plain text with a blinking cursor. Unclosed inline markers (`**`, `` ` ``,
   `[`) are visible as raw characters until the block is completed. This spec
   defines an enterprise-grade incremental renderer where the active tail
   partitions at the last *balanced marker position* — the balanced prefix
   renders as stable Markdown, the remainder as plain text.

2. **Thought narrative de-duplication**: `useThoughtNarrativeBlocks` currently
   mixes event-delivered `visible_thought_*` events with `visibleThoughtByStep`
   snapshots from `run-stream-reducer`. This dual-source design causes duplicate
   reasoning blocks. The hook is rewritten as a pure `useMemo` that derives
   blocks solely from events, eliminating the internal `stateRef` accumulator.

## Motivation — Why Not Just Render Everything as Markdown?

The naive fix — "just pass the active tail to `ReactMarkdown`" — fails on two
classes of input:

| Input | Naive output | Correct output |
|-------|-------------|---------------|
| `Hello **wor` | `**wor` interpreted as literal (asterisks consumed) | `wor` shown as plain text (`**` is unclosed) |
| `` `const x` `` | ``` `const x` ``` shown as inline code | `const` shown as inline code, trailing backtick as plain text |
| `### 标题内容` | First `#` turns into heading (massive font jump) | `### ` shown as plain text (heading not at block start) |

These artifacts cause **layout jitter** — the page height/cursor position shifts
when an unclosed marker is consumed by the parser. The zero-jitter invariants are:

1. **Completed blocks never re-layout.** Each completed block is `React.memo`-wrapped
   and rendered exactly once.
2. **The active block's height changes only by character advance, never by style
   transitions.** This means no marker that would change font size/weight/color
   becomes active until it is provably closed.
3. **Cursor position is monotonic.** When a balanced region is promoted from
   active-tail to stable-Markdown, the rendered character count including invisible
   gaps is preserved exactly.

## Architecture

### Layer Model

```
  ┌──────────── raw text stream ────────────┐
  │                                         │
  ▼                                         │
SplitBlocks (by \n\n)                       │
  │                                         │
  ├─ completedBlock[0] ── memo ──▶ rendered │
  ├─ completedBlock[1] ── memo ──▶ rendered │
  ├─ ...                                    │
  │                                         │
  └─ activeBlock ──▶ MarkerPartition ───────┤
        │                 │                 │
        ▼                 ▼                 │
    stablePrefix     activeTail             │
        │                 │                 │
        ▼                 ▼                 │
   ReactMarkdown     plain text + cursor   ◀┘
   (memo by prefix)
```

### Data Flow

```
SSE answer_delta events
    │
    ▼
run-stream-reducer.answerText ( accumulates raw text )
    │
    ▼
ProgressiveMarkdown({ text, terminal })
    │
    ├─ terminal=true  → single ReactMarkdown ( full content, no partitioning )
    │
    └─ terminal=false →
           splitBlocks(text) → { completed, active }
               │
               ├─ completed.map(block => <CompletedBlock key={hash} content={block} />)
               │
               └─ active → partitionInline(active) → { stable, tail }
                       │
                       ├─ stable → <ReactMarkdown content={stable} />  (memo by hash)
                       └─ tail   → <span className="streaming-tail">{tail}</span>
```

### Key Modules

| Module | Responsibility |
|--------|---------------|
| `lib/markdown-split.ts` | `splitBlocks(text)`, `partitionInline(text)`, `hashBlock(text)` |
| `components/agent/progressive-markdown.tsx` | Renderer: orchestrates block/inline split, memoization |
| `hooks/use-thought-narrative-blocks.ts` | Rewrite: pure `useMemo`, events-only input |
| `lib/thought-narrative.ts` | Remove `mergeAdjacentReasoningBlocks`, snapshots merge logic |

## Block Splitting Algorithm

### splitBlocks(rawText: string): { completed: string[]; active: string }

```
Let BLOCK_DELIMITER = "\n\n"   (two consecutive newlines)
Let fences = "```" or "~~~" count

Scan rawText character by character:
  - Track fence state: inside_fence bool, fence_char string
  - When !inside_fence:
      - If delimiter "\n\n" found → emit completed block, advance, reset delimiter pointer
      - If "```" or "~~~" at start of delimiter position → enter fence, set fence_char
  - When inside_fence:
      - If matching closing fence found → exit fence, mark block as completed
      - Text accumulates in current block

After scan:
  - If !inside_fence && no active delimiter in progress:
      → all blocks are completed, active = ""
  - Else:
      → last accumulated segment is the active block
```

Invariant: a fenced code block is treated as a single atomic segment. The
delimiter `\n\n` inside fences is NOT a block separator.

### partitionInline(source: string): { stable: string; tail: string }

```
Define marker states:
  bold   = { open: false, char: '' }   // ** or __
  italic = { open: false, char: '' }   // * or _
  inlineCode = { open: false }
  link   = { depth: 0 }                // [text](url) nesting  
  escape = { active: false }           // backslash escape

let lastBalanced = 0

Scan source character by character (i = 0 .. len-1):

  if escape.active:
    escape.active = false; continue

  if char == '\':
    escape.active = true; continue

  if inlineCode.open:
    if char == '`' and notLookaheadDouble:
      inlineCode.open = false
      if allMarkersClosed(): lastBalanced = i + 1
    continue

  if char == '`':
    inlineCode.open = true
    continue

  // Bold: ** or __
  if char == '*' and lookahead(1) == '*' and !italic.open:
    bold.open = !bold.open
    i++ // skip second *
    if allMarkersClosed(): lastBalanced = i + 1
    continue

  if char == '_' and lookahead(1) == '_' and !italic.open:
    bold.open = !bold.open
    i++
    if allMarkersClosed(): lastBalanced = i + 1
    continue

  // Italic: * or _ (not part of bold)
  if char == '*' and !bold.open and !lookahead(1, '*'):
    italic.open = !italic.open
    if allMarkersClosed(): lastBalanced = i + 1
    continue

  if char == '_' and !bold.open and !lookahead(1, '_'):
    italic.open = !italic.open
    if allMarkersClosed(): lastBalanced = i + 1
    continue

  // Link: [text](url)
  if char == '[' and !bold.open and !italic.open:
    link.depth++
    continue

  if char == ']' and link.depth > 0:
    // Looking for '(' after ']' — handled by next iteration
    continue

  if char == '(' and link.depth > 0:
    // Enter URL portion. Scan for matching ')'
    // Note: this is simplified — real impl tracks link state more carefully
    link.depth--
    if allMarkersClosed(): lastBalanced = i + 1
    continue

  // Strikethrough: ~~
  if char == '~' and lookahead(1) == '~':
    // toggle, similar to bold
    i++
    if allMarkersClosed(): lastBalanced = i + 1
    continue

  // Default: literal character
  if allMarkersClosed(): lastBalanced = i + 1

Return:
  stable = source.slice(0, lastBalanced)
  tail   = source.slice(lastBalanced)
```

### Example Walkthrough

```
Input: "Hello **world** and `code` chan"

i=0-5   : "Hello "              → literal, balanced at 6
i=6-7   : "**"                  → bold.open = true
i=8-11  : "worl"                → bold.open = true
i=12-13 : "d*"                  → bold.open = false (12: d, 13: * + lookahead *), balanced at 14
i=14-17 : " and "               → literal, balanced at 18
i=18    : "`"                   → inlineCode.open = true
i=19-21 : "cod"                 → inlineCode.open = true
i=22-23 : "e`"                  → inlineCode.open = false (22+e, 23+`), balanced at 24
i=24-27 : " cha"                → literal, balanced at 28
i=28-30 : "n"                   → literal, balanced at 29

{"stable": "Hello **world** and `code` cha", "tail": "n"}
```

### Edge Cases

| Input | stable | tail | Rationale |
|-------|--------|------|-----------|
| `**a*b**` (invalid nesting) | `**a*b**` at nest | varies by impl | Per CommonMark, `*` inside `**` is literal `*`. We treat as non-italic. |
| `### heading` | `### heading` (none) | `### heading` (all) | `#` is handled at block level, not inline. If this is the active block, treat as plain text. |
| `` ``` `` inside text | (inside fence) | — | Fenced code blocks are atomic at the block level. |
| `[link](https://` | `[link](https://` | none (pending) | URL portion not yet closed; not ink at `(` |
| Empty string | `""` | `""` | Trivial. |

## Component Architecture

### ProgressiveMarkdown (rewrite)

```typescript
interface ProgressiveMarkdownProps {
  text: string;
  terminal: boolean;
}

// Internal:
//   splitBlocks(text) → { completed: string[], active: string }
//
// For each completed block:
//   key = fastHash(block)  (FNV-1a, 32-bit)
//   render = <CompletedBlock key={key} content={block} />
//
// For active block (if terminal=false):
//   { stable, tail } = partitionInline(active)
//   renderStable = stable ? <StableInline key={fastHash(stable)} content={stable} /> : null
//   renderTail   = tail   ? <StreamingTail text={tail} /> : null

const CompletedBlock = React.memo(
  function ({ content }) {
    return <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
  },
  (prev, next) => prev.content === next.content
);

const StableInline = React.memo(
  function ({ content }) {
    return <ReactMarkdown remarkPlugins={[remarkGfm]} disallowedElements={['p','div']}>
      {content}
    </ReactMarkdown>
  },
  (prev, next) => prev.content === next.content
);

function StreamingTail({ text }: { text: string }) {
  return <span className="streaming-tail">{text}<span className="streaming-cursor">|</span></span>;
}
```

### Thought Narrative Hook (rewrite)

```typescript
function useThoughtNarrativeBlocks(
  events: AgentRunEvent[],
): ThoughtNarrativeBlock[] {
  return useMemo(() => buildThoughtNarrativeBlocks(events), [events]);
}
```

`buildThoughtNarrativeBlocks` processes events in seq order:

1. `visible_thought_started` → create empty reasoning block (if streamId not seen)
2. `visible_thought_delta` → accumulate text (offset-validated), toggle `isComplete: false`
3. `visible_thought_paused` → set `isComplete: true`
4. `visible_thought_completed` → set `isComplete: true`, set `text = payload.text` (authoritative)
5. `tool_started` → mark previous reasoning block complete, create tool block
6. `tool_completed` → update tool block to `status: "completed"`

No snapshots. No `stateRef`. No internal mutation. Single source of truth: events array.

## Performance

| Metric | Before | After |
|--------|--------|-------|
| `partitionInline` time for 1000-char block | N/A | ~0.05 ms (single pass, O(n)) |
| `splitBlocks` time for 5000-char text | ~0.02 ms (split by `\n\n`) | ~0.05 ms (added fence tracking) |
| Completed block re-renders | 0 (memo) | 0 (memo) |
| Active tail re-renders per frame | 1 | 1 (same) |
| Memory | O(n) text only | O(n) text + 2 × hash overhead (32 bits each) |

## Files Changed

| File | Change |
|------|--------|
| `frontend/src/lib/markdown-split.ts` | **New.** `splitBlocks()`, `partitionInline()`, `fastHash()` |
| `frontend/src/components/agent/progressive-markdown.tsx` | **Rewrite.** Two-layer partition, StableInline, StreamingTail |
| `frontend/src/hooks/use-thought-narrative-blocks.ts` | **Rewrite.** Pure `useMemo`, single data source |
| `frontend/src/lib/thought-narrative.ts` | **Edit.** Remove `mergeAdjacentReasoningBlocks`, snapshot merge in `buildThoughtNarrativeBlocks` |
| `frontend/src/components/agent/thought-narrative.tsx` | **Edit.** Remove `visibleThoughtByStep`/`visibleThoughtStreamIds` props (no longer needed) |
| `frontend/src/components/agent/session-conversation-stream.tsx` | **Edit.** Remove snapshot props passthrough |
| `frontend/src/lib/markdown-split.test.ts` | **New.** Unit tests for split and partition |
| `frontend/src/components/agent/progressive-markdown.test.tsx` | **New.** Render tests for edge cases |

## Testing Strategy

### Unit Tests — `markdown-split.test.ts`

| Test | Input | Expected |
|------|-------|----------|
| Splits by `\n\n` | `"a\n\nb"` | completed: `["a"]`, active: `"b"` |
| Single block (no delimiter) | `"hello"` | completed: `[]`, active: `"hello"` |
| Fenced code preserves block | `"```\n\nx\n```\n\nafter"` | completed: `["```\n\nx\n```"]`, active: `"after"` |
| Multiple completed | `"a\n\nb\n\nc"` | completed: `["a","b"]`, active: `"c"` |
| Active inline balanced | `"Hello **world**"` | stable: `"Hello **world**"`, tail: `""` |
| Active inline unbalanced | `"Hello **wor"` | stable: `"Hello "`, tail: `"**wor"` |
| Nested bold-italic balanced | `"**a*b***"` (not valid) | stable: `""`, tail: full |
| Inline code balanced | `` "`code` text" `` | stable: `"`code` text"`, tail: `""` |
| Empty | `""` | stable: `""`, tail: `""` |

### Integration Tests

| Test | Description |
|------|-------------|
| ProgressiveMarkdown renders without crash | Smoketest with 10 random streaming inputs |
| Thought narrative dedup | Simulate duplicate delta events, verify single reasoning block |
| Completed blocks don't re-render | Mock `ReactMarkdown`, verify render count |

## Migration & Rollback

All changes are additive (new files) or self-contained rewrites of existing files.
No backend changes required. Rollback is a single revert commit.
