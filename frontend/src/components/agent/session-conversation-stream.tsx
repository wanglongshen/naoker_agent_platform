"use client";

import React from "react";

import FinalAnswerPanel from "@/components/agent/final-answer-panel";
import ThoughtNarrative from "@/components/agent/thought-narrative";
import { useRunEventStream } from "@/hooks/use-run-event-stream";
import type { AgentConversationStep, AgentRun, AgentRunEvent } from "@/types/agent";
import type { AgentSessionTurn } from "@/lib/agent-session-view";
import { hasAuthoritativeTerminalEvidence, hasCompletedAnswerEvidence, shouldOpenRunStream } from "@/lib/run-stream-reducer";

type Props = {
  turns: AgentSessionTurn[];
  onTerminalState?: (run: AgentRun) => void;
  onRegenerate?: (run: AgentRun) => void;
};

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "等待中",
    running: "思考中",
    retry_wait: "准备重试",
    awaiting_question: "等待回答",
    succeeded: "已完成",
    failed: "未完成",
    cancelled: "已取消",
  };
  return labels[status];
}

export default function SessionConversationStream({ turns, onTerminalState, onRegenerate }: Props) {
  if (turns.length === 0) {
    return <div className="empty-card">当前会话还没有任务记录。</div>;
  }

  const lastTurnIndex = turns.length - 1;

  return (
    <div className="detail-conversation-stack">
      {turns.map(({ run, steps, events: initialEvents }, index) => (
        <SessionTurn key={run.id} run={run} steps={steps} initialEvents={initialEvents} isLiveRun={index === lastTurnIndex} onTerminalState={onTerminalState} onRegenerate={onRegenerate} />
      ))}
    </div>
  );
}

function SessionTurn({
  run,
  steps,
  initialEvents,
  isLiveRun,
  onTerminalState,
  onRegenerate,
}: {
  run: AgentRun;
  steps: AgentConversationStep[];
  initialEvents: AgentRunEvent[];
  isLiveRun: boolean;
  onTerminalState?: (run: AgentRun) => void;
  onRegenerate?: (run: AgentRun) => void;
}) {
  const shouldStream = shouldOpenRunStream(run, isLiveRun, initialEvents);
  const hasAnswer = hasCompletedAnswerEvidence(initialEvents);
  const isAuthoritativeTerminal = hasAuthoritativeTerminalEvidence(run, initialEvents);

  const streamState = useRunEventStream({
    runId: run.id,
    initialEvents,
    initialRun: run,
    onTerminalState,
    disabled: !shouldStream,
  });

  const streamedRun = streamState.run ?? run;

  const displayRun = (!isLiveRun && hasAnswer && !isAuthoritativeTerminal)
    ? { ...streamedRun, status: "succeeded" as const }
    : streamedRun;

  const adaptedSteps = steps.map((s) => ({ ...s, step_index: s.step_number }));
  const answerStartedEvent = streamState.events.find(e => e.event_type === "answer_started");

  return (
    <section className="session-turn-block">
      <div className="message-row message-row-user">
        <div className="message-bubble message-bubble-user">{run.goal}</div>
      </div>

      <div className="session-turn-meta">
        <span>{new Date(run.created_at).toLocaleString("zh-CN")}</span>
        <span className={`status-pill status-inline status-${displayRun.status}`}>{statusLabel(displayRun.status)}</span>
      </div>

      <ThoughtNarrative
        run={displayRun}
        steps={adaptedSteps}
        events={streamState.narrativeEvents}
        isLiveRun={shouldStream}
        answerStartedAt={answerStartedEvent?.created_at ?? null}
      />
      <FinalAnswerPanel
        run={displayRun}
        streamingAnswer={streamState.answerText}
        answerStreamId={streamState.answerStreamId}
        isLiveRun={shouldStream}
        wasLiveStreamed={streamState.liveStreamed}
        onRegenerate={onRegenerate ? () => onRegenerate(run) : undefined}
      />
    </section>
  );
}
