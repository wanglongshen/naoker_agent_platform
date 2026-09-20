"use client";

import React, { useEffect, useRef, useState } from "react";

import { useTypingText } from "@/hooks/use-typing-text";
import useThoughtNarrativeBlocks from "@/hooks/use-thought-narrative-blocks";
import { isActivelyStreamingRun } from "@/lib/animation-eligibility";
import {
  getThoughtDurationSeconds,
  getToolStatusCopy,
  type ThoughtReasoningBlock,
  type ThoughtToolBlock,
} from "@/lib/thought-narrative";
import type { AgentRun, AgentRunEvent } from "@/types/agent";

type Props = {
  run: AgentRun;
  steps: { id: string; step_number: number; thought_summary: string | null; action_type: string | null; status: string }[];
  events: AgentRunEvent[];
  isLiveRun?: boolean;
  answerStartedAt?: string | null;
};

function isTerminal(status: string): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

function ThoughtText({ text }: { text: string }) {
  return (
    <div className="thought-narrative-text">
      {text.split("\n").map((line, index) => (
        <div key={index} className="thought-narrative-line">{line}</div>
      ))}
    </div>
  );
}

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

export const ToolRecord = React.memo(
  function ToolRecord({ block, runStatus }: { block: ThoughtToolBlock; runStatus?: string }) {
    const icon =
      block.toolType === "web_search" ? "search"
      : block.toolType === "calculator" ? "calculator"
      : block.toolType === "http_request" || block.toolType === "extract_web_content" ? "globe"
      : block.toolType === "read_file" ? "file"
      : block.toolType === "write_file" ? "pen"
      : block.toolType === "edit_file" ? "pencil"
      : block.toolType === "list_files" ? "folder"
      : "page";
    const statusLabel = block.status === "running" && runStatus === "retry_wait"
      ? (block.toolType === "web_search" ? "搜索失败，等待重试" : "执行失败，等待重试")
      : getToolStatusCopy(block.toolType, block.status, block.resultSummary);
    return (
      <div className={`thought-tool-record thought-tool-record-${block.status}`}>
        <span className="thought-tool-record-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" data-tool-icon={icon}>
            {icon === "search" ? <><circle cx="10.5" cy="10.5" r="5.5" stroke="currentColor" strokeWidth="1.8" /><path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></> : null}
            {icon === "page" ? <><path d="M7 3h7l4 4v14H7z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><path d="M14 3v5h4M10 12h5M10 16h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></> : null}
            {icon === "calculator" ? <><rect x="5" y="3" width="14" height="18" rx="2" stroke="currentColor" strokeWidth="1.8" /><path d="M8 7h8M9 12h.01M12 12h.01M15 12h.01M9 16h.01M12 16h.01M15 16h.01" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /></> : null}
            {icon === "globe" ? <><circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" /><path d="M3 12h18M12 3c2.5 2.6 4 5.6 4 9s-1.5 6.4-4 9c-2.5-2.6-4-5.6-4-9s1.5-6.4 4-9Z" stroke="currentColor" strokeWidth="1.8" /></> : null}
            {icon === "file" ? <><path d="M7 3h7l4 4v14H7z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><path d="M14 3v5h4" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><path d="M10 12h5M10 15h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></> : null}
            {icon === "pen" ? <><path d="m4 20 1-4L16 5l3 3L8 19l-4 1Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><path d="m13 8 3 3" stroke="currentColor" strokeWidth="1.8" /></> : null}
            {icon === "pencil" ? <><path d="M4 20h4L19 9l-4-4L4 16v4Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /><path d="m13 7 4 4" stroke="currentColor" strokeWidth="1.8" /></> : null}
            {icon === "folder" ? <><path d="M3 7a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></> : null}
          </svg>
        </span>
        <div className="thought-tool-record-main">
          <span className="thought-tool-record-label">{block.label}</span>
          <span className="thought-tool-record-meta">
            {statusLabel}
          </span>
          {block.url ? (
            <a className="thought-tool-record-link" href={block.url} target="_blank" rel="noopener noreferrer">
              {block.url}
              <span aria-hidden="true">↗</span>
            </a>
          ) : null}
        </div>
      </div>
    );
  },
  (prev, next) => areToolBlocksEqual(prev.block, next.block) && prev.runStatus === next.runStatus,
);

export function ThoughtDuration({ isThinking, durationSeconds, subLabel }: {
  isThinking: boolean;
  durationSeconds: number | null;
  subLabel: string | null;
}) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!isThinking) return;
    const timer = window.setInterval(() => {
      setTick((value) => value + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isThinking]);

  return (
    <span className="thought-narrative-duration">
      {durationSeconds === null
        ? (subLabel ?? "正在整理信息与判断下一步")
        : `（用时 ${durationSeconds} 秒）`}
    </span>
  );
}

const ThoughtNarrative = React.memo(function ThoughtNarrativeImpl({
  run,
  steps: _steps,
  events,
  isLiveRun = false,
  answerStartedAt = null,
}: Props) {
  const [expanded, setExpanded] = useState(true);
  const terminal = isTerminal(run.status);
  const isThinking = isActivelyStreamingRun(run.status, isLiveRun);
  const thinkingStartedAtRef = useRef<number | null>(null);

  useEffect(() => {
    if (isThinking && thinkingStartedAtRef.current === null) {
      thinkingStartedAtRef.current = Date.now();
    }
    if (!isThinking) {
      thinkingStartedAtRef.current = null;
    }
  }, [isThinking]);

  const blocks = useThoughtNarrativeBlocks(events);
  const activeReasoningId = isThinking
    ? [...blocks].reverse().find((block) => block.kind === "reasoning" && !block.isComplete)?.id ?? null
    : null;
  const boundedFinishedAt = run.updated_at;
  const thinkingStartedAt = thinkingStartedAtRef.current
    ? new Date(thinkingStartedAtRef.current).toISOString()
    : null;
  const thoughtDurationSeconds = getThoughtDurationSeconds(events, thinkingStartedAt, terminal ? boundedFinishedAt : null, Date.now(), answerStartedAt);

  const regionId = `thought-region-${run.id}`;

  const titleLabel = isThinking ? "正在思考" : run.status === "retry_wait" ? "已思考" : "已思考";
  const subLabel = isThinking
    ? "正在整理信息与判断下一步"
    : run.status === "retry_wait"
      ? "系统将在数秒后自动重试"
      : run.status === "cancelled"
        ? "任务已取消"
        : null;

  return (
    <section className="thought-narrative-block">
      <button
        type="button"
        className="thought-narrative-header"
        aria-expanded={expanded}
        aria-controls={regionId}
        onClick={() => setExpanded((value) => !value)}
      >
        <div className="thought-narrative-header-left">
          <span className="thought-narrative-glyph" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M8.5 5.5a5.5 5.5 0 0 1 7 8.5c-.7.58-1.12 1.23-1.18 2H9.68c-.06-.77-.48-1.42-1.18-2a5.5 5.5 0 0 1 0-8.5Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
              <path d="M9.5 19h5M10.5 21h3M9.5 10.5h5M12 8v5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </span>
          <span className="thought-narrative-title">{titleLabel}</span>
          <ThoughtDuration
            isThinking={isThinking}
            durationSeconds={thoughtDurationSeconds}
            subLabel={subLabel}
          />
          {run.status === "retry_wait" && thoughtDurationSeconds !== null ? (
            <span className="thought-narrative-duration"> · 系统将自动重试</span>
          ) : null}
        </div>
        <span className="thought-narrative-toggle">{expanded ? "收起思考过程" : "展开思考过程"}</span>
      </button>

      {expanded ? (
        <div id={regionId} role="region" aria-label="思考与工具过程" className="thought-narrative-list">
          {blocks.length === 0 ? (
            <div className="empty-card">{isThinking ? "正在分析你的需求…" : "这轮回答不需要额外的思考步骤。"}</div>
          ) : (
            blocks.map((block) => block.kind === "reasoning" ? (
              block.id === activeReasoningId ? (
                <StreamingReasoningBlock key={block.id} block={block} isActive={block.id === activeReasoningId} />
              ) : (
                <StaticReasoningBlock key={block.id} block={block} />
              )
            ) : (
              <ToolRecord key={block.id} block={block} runStatus={run.status} />
            ))
          )}
        </div>
      ) : null}
    </section>
  );
}, (prevProps, nextProps) => {
  return prevProps.run === nextProps.run &&
    prevProps.steps === nextProps.steps &&
    prevProps.events === nextProps.events &&
    prevProps.isLiveRun === nextProps.isLiveRun;
});

export default ThoughtNarrative;
