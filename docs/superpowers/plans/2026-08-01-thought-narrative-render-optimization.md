# 思考区渲染优化（消除高频整体重渲染）— Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 停止思考区在流式期间的高频整体重渲染——计时器与 SSE delta 只影响对应的小范围 UI。

**Architecture:** (1) 把"用时 X 秒"计时器抽成独立 `ThoughtDuration` 组件（自带 interval），父组件不再持有 `setNowMs`。 (2) 三个块渲染器（`StaticReasoningBlock`/`StreamingReasoningBlock`/`ToolRecord`）用 `React.memo` + 字段级比较器包裹，内容未变的块跳过重渲染。

**Tech Stack:** TypeScript, React

## Global Constraints

- `thought-narrative.tsx` 是唯一改动文件（+测试文件）
- 行为不变：时长文本仍每秒更新；块渲染内容不变
- 现有 63 个 agent-streaming 测试必须通过
- 比较器作为导出函数（可单测、可复用）

---

### Task 1: 计时器抽离为 ThoughtDuration 组件

**Files:**
- Modify: `frontend/src/components/agent/thought-narrative.tsx`
- Test: `frontend/src/components/agent/thought-narrative.test.tsx`（如不存在则新建，或复用 agent-streaming.test.tsx 中 ThoughtNarrative 相关用例）

**Interfaces:**
- Consumes: `isThinking: boolean`, `durationSeconds: number | null`, `subLabel: string | null`
- Produces: `ThoughtDuration` 组件自管每秒 tick；父组件移除 `nowMs` state 与 interval

- [ ] **Step 1: Write the failing test**

新建/追加到 `frontend/src/components/agent/thought-narrative.test.tsx`（先用 `glob` 确认是否存在该文件；若 agent-streaming.test.tsx 已有 ThoughtNarrative 描述块，追加到那里）：

```tsx
describe("ThoughtDuration", () => {
  test("renders duration or sublabel from props", () => {
    const { container, rerender } = render(
      <ThoughtDuration isThinking durationSeconds={null} subLabel="正在整理信息与判断下一步" />,
    );
    expect(container.textContent).toContain("正在整理信息与判断下一步");

    rerender(<ThoughtDuration isThinking durationSeconds={5} subLabel={null} />);
    expect(container.textContent).toContain("用时 5 秒");
  });

  test("starts interval only while thinking", () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    const clearIntervalSpy = vi.spyOn(window, "clearInterval");
    const { rerender } = render(
      <ThoughtDuration isThinking durationSeconds={null} subLabel="整理中" />,
    );
    expect(setIntervalSpy).toHaveBeenCalled();

    rerender(<ThoughtDuration isThinking={false} durationSeconds={null} subLabel="已思考" />);
    expect(clearIntervalSpy).toHaveBeenCalled();
    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -t "ThoughtDuration" -v
```

Expected: FAIL（组件不存在，ImportError）。

- [ ] **Step 3: Implement**

在 `frontend/src/components/agent/thought-narrative.tsx`：

新增组件（放在 `ThoughtNarrative` 之前）：

```tsx
function ThoughtDuration({ isThinking, durationSeconds, subLabel }: {
  isThinking: boolean;
  durationSeconds: number | null;
  subLabel: string | null;
}) {
  useEffect(() => {
    if (!isThinking) return;
    const timer = window.setInterval(() => {
      // Local tick keeps this component's lifecycle alive; the displayed
      // text is driven by the durationSeconds prop from the parent.
      setTick((value) => value + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isThinking]);
  const [, setTick] = useState(0);

  return (
    <span className="thought-narrative-duration">
      {durationSeconds === null
        ? (subLabel ?? "正在整理信息与判断下一步")
        : `（用时 ${durationSeconds} 秒）`}
    </span>
  );
}
```

在 `ThoughtNarrativeImpl` 中：
- 删除 `const [nowMs, setNowMs] = useState(() => Date.now());`（line 102）
- 删除 `useEffect` interval（lines 114-121）
- 删除 `nowMs` 在 `getThoughtDurationSeconds` 调用中的传参（line 131 改为传 `null` 或去掉该参数——保持函数签名不变，传 `Date.now()` 亦可，因为只读一次）

替换 header 中的时长 span（lines 161-165）：

```tsx
          <ThoughtDuration
            isThinking={isThinking}
            durationSeconds={thoughtDurationSeconds}
            subLabel={subLabel}
          />
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -t "ThoughtDuration" -v
```

Expected: PASS。

- [ ] **Step 5: Run full agent-streaming suite**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: 全部通过（时长显示行为不变）。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/agent/thought-narrative.tsx frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "perf: extract thinking duration timer into isolated ThoughtDuration component"
```

---

### Task 2: 块渲染器 memo 化（字段级比较器）

**Files:**
- Modify: `frontend/src/components/agent/thought-narrative.tsx`
- Test: `frontend/src/components/agent/agent-streaming.test.tsx`

**Interfaces:**
- Produces: 导出 `areReasoningBlocksEqual(a, b)` / `areToolBlocksEqual(a, b)` 比较器；三个块组件用 `React.memo(..., comparator)` 包裹

- [ ] **Step 1: Write the failing tests**

追加到 `agent-streaming.test.tsx`：

```tsx
describe("thought block memo comparators", () => {
  test("reasoning comparator skips re-render when content unchanged", () => {
    const { areReasoningBlocksEqual } = require("@/components/agent/thought-narrative");
    const a = { kind: "reasoning", id: "r-1", streamId: "s-1", stepIndex: 0, text: "正在思考", isComplete: false };
    const b = { ...a };
    expect(areReasoningBlocksEqual(a, b)).toBe(true);
  });

  test("reasoning comparator re-renders when text changes", () => {
    const { areReasoningBlocksEqual } = require("@/components/agent/thought-narrative");
    const a = { kind: "reasoning", id: "r-1", streamId: "s-1", stepIndex: 0, text: "正在思考", isComplete: false };
    const b = { ...a, text: "正在思考中" };
    expect(areReasoningBlocksEqual(a, b)).toBe(false);
  });

  test("reasoning comparator re-renders when isComplete flips", () => {
    const { areReasoningBlocksEqual } = require("@/components/agent/thought-narrative");
    const a = { kind: "reasoning", id: "r-1", streamId: "s-1", stepIndex: 0, text: "x", isComplete: false };
    const b = { ...a, isComplete: true };
    expect(areReasoningBlocksEqual(a, b)).toBe(false);
  });

  test("tool comparator re-renders when status changes", () => {
    const { areToolBlocksEqual } = require("@/components/agent/thought-narrative");
    const a = { kind: "tool", id: "t-1", toolType: "web_search", label: "搜索", status: "running", url: null, resultSummary: null };
    const b = { ...a, status: "completed" };
    expect(areToolBlocksEqual(a, b)).toBe(false);
  });
});
```

Note: 若 `require` 在 ESM/vitest 环境报错，改用顶层 `import { areReasoningBlocksEqual, areToolBlocksEqual } from "@/components/agent/thought-narrative";`。块类型字段以 `lib/thought-narrative.ts` 的 `ThoughtReasoningBlock`/`ThoughtToolBlock` 为准（先读该文件确认字段名）。

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -t "memo comparators" -v
```

Expected: FAIL（导出不存在）。

- [ ] **Step 3: Implement**

在 `frontend/src/components/agent/thought-narrative.tsx`：

新增导出比较器（放在组件定义前，字段名以 `lib/thought-narrative.ts` 的类型为准——先读该文件确认）：

```tsx
export function areReasoningBlocksEqual(
  a: ThoughtReasoningBlock,
  b: ThoughtReasoningBlock,
): boolean {
  return a.id === b.id
    && a.streamId === b.streamId
    && a.stepIndex === b.stepIndex
    && a.text === b.text
    && a.isComplete === b.isComplete;
}

export function areToolBlocksEqual(
  a: ThoughtToolBlock,
  b: ThoughtToolBlock,
): boolean {
  return a.id === b.id
    && a.toolType === b.toolType
    && a.label === b.label
    && a.status === b.status
    && a.url === b.url
    && a.resultSummary === b.resultSummary;
}
```

用 memo 包裹三个渲染器：

```tsx
const StaticReasoningBlock = React.memo(
  function StaticReasoningBlock({ block }: { block: ThoughtReasoningBlock }) {
    return (
      <div className="thought-narrative-item thought-narrative-item-static">
        <span className="thought-narrative-rail-marker" aria-hidden="true" />
        <ThoughtText text={block.text} />
      </div>
    );
  },
  (prev, next) => areReasoningBlocksEqual(prev.block, next.block),
);

const StreamingReasoningBlock = React.memo(
  function StreamingReasoningBlock({ block, isActive }: { block: ThoughtReasoningBlock; isActive: boolean }) {
    const animatedText = useTypingText(block.text, { resetKey: block.streamId });
    if (block.isComplete) {
      return <StaticReasoningBlock block={block} />;
    }
    return (
      <div className={isActive ? "thought-narrative-item thought-narrative-item-streaming thought-narrative-item-active" : "thought-narrative-item thought-narrative-item-streaming"}>
        <span className="thought-narrative-rail-marker" aria-hidden="true" />
        <ThoughtText text={animatedText} />
      </div>
    );
  },
  (prev, next) => areReasoningBlocksEqual(prev.block, next.block) && prev.isActive === next.isActive,
);

const ToolRecord = React.memo(
  function ToolRecord({ block, runStatus }: { block: ThoughtToolBlock; runStatus?: string }) {
    // ...原有实现不变...
  },
  (prev, next) => areToolBlocksEqual(prev.block, next.block) && prev.runStatus === next.runStatus,
);
```

关键点：
- `StreamingReasoningBlock` 的 memo 比较包含 `isActive`（活动标记变化要重渲染）
- `ToolRecord` 比较包含 `runStatus`
- 保留原有 JSX 与样式类不变

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run src/components/agent/agent-streaming.test.tsx -v
```

Expected: 全部通过（63 既有 + 4 新比较器测试）。

- [ ] **Step 5: Run full frontend suite + build**

```bash
cd C:\01_agent_loop_pro\frontend && npx vitest run -v
cd C:\01_agent_loop_pro\frontend && npx next build
```

Expected: 无新增失败；构建通过。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/agent/thought-narrative.tsx frontend/src/components/agent/agent-streaming.test.tsx
git commit -m "perf: memoize thought block renderers with field-level comparators"
```
